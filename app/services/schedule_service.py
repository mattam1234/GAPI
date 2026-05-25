"""Business logic for the game-night scheduler."""
import datetime
import uuid
from typing import Dict, List, Optional, Tuple

from ..repositories.schedule_repository import ScheduleRepository

_EDITABLE_FIELDS = ('title', 'date', 'time', 'duration_minutes', 'attendees', 'game_name', 'notes',
                     'game_appid', 'attendee_ids', 'discord_event_id', 'discord_guild_id', 'game_image_url',
                     'schedule_id',
                     'timezone_name', 'timezone_offset_minutes', 'rsvp_statuses')
_VALID_RSVP_STATUSES = {'pending', 'accepted', 'maybe', 'declined'}
_SCHEDULES_KEY = '__schedules__'
_EVENTS_KEY = '__events__'


def _clean_schedule_participants(attendees: Optional[List[str]],
                                 attendee_ids: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """Return de-duplicated attendee labels and identifiers in display order."""
    clean_attendees: List[str] = []
    clean_attendee_ids: List[str] = []
    seen_keys = set()
    ids = attendee_ids or []

    for index, raw_name in enumerate(attendees or []):
        name = str(raw_name or '').strip()
        if not name:
            continue
        attendee_id = str(ids[index] if index < len(ids) else name).strip() or name
        dedupe_key = attendee_id.lower() if attendee_id else name.lower()
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        clean_attendees.append(name)
        clean_attendee_ids.append(attendee_id)

    return clean_attendees, clean_attendee_ids


def _normalize_rsvp_statuses(attendees: List[str],
                             attendee_ids: List[str],
                             rsvp_statuses: Optional[Dict[str, str]] = None,
                             existing_statuses: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return an RSVP mapping keyed by attendee identifier."""
    provided = dict(rsvp_statuses or {})
    existing = dict(existing_statuses or {})
    normalized: Dict[str, str] = {}

    for index, attendee_name in enumerate(attendees):
        attendee_id = attendee_ids[index] if index < len(attendee_ids) else attendee_name
        status = (
            provided.get(attendee_id)
            or provided.get(attendee_name)
            or existing.get(attendee_id)
            or existing.get(attendee_name)
            or 'pending'
        )
        safe_status = str(status or 'pending').strip().lower()
        normalized[attendee_id] = safe_status if safe_status in _VALID_RSVP_STATUSES else 'pending'

    return normalized


def _clean_schedule_members(members: Optional[List[str]]) -> List[str]:
    """Normalize and de-duplicate schedule member usernames."""
    clean_members: List[str] = []
    seen = set()
    for raw_member in members or []:
        member = str(raw_member or '').strip()
        if not member:
            continue
        key = member.lower()
        if key in seen:
            continue
        seen.add(key)
        clean_members.append(member)
    return clean_members


class ScheduleService:
    """Creates, updates, and deletes game-night events, delegating persistence
    to :class:`~app.repositories.schedule_repository.ScheduleRepository`.
    """

    def __init__(self, repository: ScheduleRepository) -> None:
        self._repo = repository
        self._ensure_store_shape()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _default_schedule_id(self, username: str) -> str:
        return f'personal:{str(username or "").strip().lower()}'

    def _ensure_store_shape(self) -> None:
        """Normalize repository payload to the v2 schedule+events envelope."""
        changed = False
        root = self._repo.data if isinstance(self._repo.data, dict) else {}
        schedules = root.get(_SCHEDULES_KEY)
        events = root.get(_EVENTS_KEY)

        if not isinstance(schedules, dict):
            schedules = {}
            changed = True

        if not isinstance(events, dict):
            events = {}
            for key, value in root.items():
                if str(key).startswith('__'):
                    continue
                if isinstance(value, dict) and value.get('id'):
                    events[str(key)] = value
            changed = True

        self._repo.data = {
            _SCHEDULES_KEY: schedules,
            _EVENTS_KEY: events,
        }
        if changed:
            self._repo.save()

    def _get_schedules(self) -> Dict[str, Dict]:
        return self._repo.data.setdefault(_SCHEDULES_KEY, {})

    def _get_events(self) -> Dict[str, Dict]:
        return self._repo.data.setdefault(_EVENTS_KEY, {})

    def _can_access_schedule(self, schedule: Dict, username: Optional[str]) -> bool:
        if not username:
            return True
        safe_username = str(username).strip().lower()
        owner = str(schedule.get('owner') or '').strip().lower()
        members = {str(member).strip().lower() for member in (schedule.get('members') or [])}
        return safe_username == owner or safe_username in members

    def ensure_default_schedule(self, username: str) -> Optional[Dict]:
        """Ensure each user has a personal default schedule container."""
        safe_username = str(username or '').strip()
        if not safe_username:
            return None
        schedule_id = self._default_schedule_id(safe_username)
        schedules = self._get_schedules()
        existing = schedules.get(schedule_id)
        if existing:
            return existing
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        default_schedule = {
            'id': schedule_id,
            'name': 'My Schedule',
            'owner': safe_username,
            'members': [safe_username],
            'is_shared': False,
            'created_at': now,
            'updated_at': now,
        }
        schedules[schedule_id] = default_schedule
        self._repo.save()
        return default_schedule

    def list_schedules(self, username: Optional[str] = None) -> List[Dict]:
        """List schedules visible to *username* (or all schedules when omitted)."""
        if username:
            self.ensure_default_schedule(username)
        schedules = list(self._get_schedules().values())
        if username:
            schedules = [schedule for schedule in schedules if self._can_access_schedule(schedule, username)]
        schedules.sort(key=lambda item: (not bool(item.get('is_shared')), str(item.get('name') or '').lower()))
        return schedules

    def resolve_schedule_for_user(self, requested_schedule_id: Optional[str], username: Optional[str]) -> Optional[str]:
        """Resolve a requested schedule ID to one the user is allowed to access."""
        safe_requested_id = str(requested_schedule_id or '').strip()
        schedules = self.list_schedules(username)
        if safe_requested_id and any(schedule.get('id') == safe_requested_id for schedule in schedules):
            return safe_requested_id
        if username:
            default_schedule = self.ensure_default_schedule(username)
            if default_schedule:
                return default_schedule.get('id')
        return schedules[0]['id'] if schedules else None

    def create_schedule(self, name: str, owner_username: str,
                        members: Optional[List[str]] = None,
                        is_shared: bool = True) -> Dict:
        """Create a new schedule collection for sessions/events."""
        owner = str(owner_username or '').strip()
        title = str(name or '').strip() or 'Shared Schedule'
        if not owner:
            raise ValueError('owner_username is required')
        schedule_id = str(uuid.uuid4())[:8]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        clean_members = _clean_schedule_members([owner] + (members or []))
        schedule = {
            'id': schedule_id,
            'name': title,
            'owner': owner,
            'members': clean_members,
            'is_shared': bool(is_shared),
            'created_at': now,
            'updated_at': now,
        }
        self._get_schedules()[schedule_id] = schedule
        self._repo.save()
        return schedule

    def update_schedule(self, schedule_id: str, username: str,
                        name: str, members: Optional[List[str]] = None,
                        is_shared: Optional[bool] = None) -> Optional[Dict]:
        """Rename or re-share an existing schedule owned by *username*."""
        safe_schedule_id = str(schedule_id or '').strip()
        safe_username = str(username or '').strip()
        safe_name = str(name or '').strip()
        if not safe_schedule_id or not safe_username or not safe_name:
            return None
        schedule = self._get_schedules().get(safe_schedule_id)
        if not schedule:
            return None
        if str(schedule.get('owner') or '').strip().lower() != safe_username.lower():
            return None
        clean_members = _clean_schedule_members([safe_username] + (members or []))
        schedule['name'] = safe_name
        schedule['members'] = clean_members
        schedule['is_shared'] = bool(is_shared) if is_shared is not None else len(clean_members) > 1
        schedule['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._repo.save()
        return schedule

    def add_event(self, title: str, date: str, time_str: str,
                  duration_minutes: Optional[int] = None,
                  attendees: Optional[List[str]] = None,
                  game_name: str = '', notes: str = '',
                  game_appid: Optional[str] = None,
                  attendee_ids: Optional[List[str]] = None,
                  rsvp_statuses: Optional[Dict[str, str]] = None,
                  game_image_url: Optional[str] = None,
                  schedule_id: Optional[str] = None,
                  owner_username: Optional[str] = None,
                  discord_guild_id: Optional[str] = None,
                  timezone_name: Optional[str] = None,
                  timezone_offset_minutes: Optional[int] = None) -> Dict:
        """Create a new event and persist it.

        Args:
            title:     Short event title (required).
            date:      ISO date string, e.g. ``"2026-03-01"``.
            time_str:  Time string, e.g. ``"20:00"``.
            attendees: Participant names.
            game_name: Pre-chosen game (optional).
            notes:     Free-text notes.
            game_appid: Steam app ID or platform-specific game ID (optional).
            attendee_ids: List of attendee identifiers (Discord IDs, user names, etc).
            game_image_url: URL to game image (for Discord event).
            discord_guild_id: Discord server (guild) ID for linked Discord event.
            timezone_name: Browser/client IANA timezone name (e.g. Europe/Berlin).
            timezone_offset_minutes: Browser timezone offset in minutes (JS getTimezoneOffset).

        Returns:
            The new event dict including the generated ``id`` and
            ``created_at`` timestamp.
        """
        event_id = str(uuid.uuid4())[:8]
        resolved_schedule_id = self.resolve_schedule_for_user(schedule_id, owner_username)
        clean_attendees, clean_attendee_ids = _clean_schedule_participants(attendees, attendee_ids)
        event: Dict = {
            'id': event_id,
            'schedule_id': resolved_schedule_id,
            'title': title,
            'date': date,
            'time': time_str,
            'duration_minutes': duration_minutes,
            'attendees': clean_attendees,
            'game_name': game_name,
            'notes': notes,
            'game_appid': game_appid,
            'attendee_ids': clean_attendee_ids,
            'rsvp_statuses': _normalize_rsvp_statuses(clean_attendees, clean_attendee_ids, rsvp_statuses),
            'game_image_url': game_image_url,
            'discord_event_id': None,  # Will be set when Discord event is created
            'discord_guild_id': discord_guild_id,
            'created_by': owner_username,
            'timezone_name': timezone_name,
            'timezone_offset_minutes': timezone_offset_minutes,
            'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._get_events()[event_id] = event
        self._repo.save()
        return event

    def update_event(self, event_id: str, username: Optional[str] = None, **kwargs) -> Optional[Dict]:
        """Update allowed fields of an existing event.

        Only fields listed in ``_EDITABLE_FIELDS`` are accepted; anything else
        in *kwargs* is silently ignored.

        Returns:
            Updated event dict, or ``None`` if *event_id* not found.
        """
        event = self._get_events().get(event_id)
        if event is None:
            return None
        event = dict(event)
        previous_event = dict(event)
        for key in _EDITABLE_FIELDS:
            if key in kwargs and key not in ('attendees', 'attendee_ids', 'rsvp_statuses', 'schedule_id'):
                event[key] = kwargs[key]
        if 'schedule_id' in kwargs:
            resolved_schedule_id = self.resolve_schedule_for_user(kwargs.get('schedule_id'), username)
            if resolved_schedule_id:
                event['schedule_id'] = resolved_schedule_id
        next_attendees = kwargs.get('attendees', event.get('attendees', []))
        next_attendee_ids = kwargs.get('attendee_ids', event.get('attendee_ids', []))
        clean_attendees, clean_attendee_ids = _clean_schedule_participants(next_attendees, next_attendee_ids)
        event['attendees'] = clean_attendees
        event['attendee_ids'] = clean_attendee_ids
        event['rsvp_statuses'] = _normalize_rsvp_statuses(
            clean_attendees,
            clean_attendee_ids,
            kwargs.get('rsvp_statuses'),
            previous_event.get('rsvp_statuses'),
        )
        event['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._get_events()[event_id] = event
        self._repo.save()
        return event

    def remove_event(self, event_id: str) -> bool:
        """Delete an event.  Returns ``True`` if it existed."""
        events = self._get_events()
        if event_id not in events:
            return False
        del events[event_id]
        self._repo.save()
        return True

    def set_discord_event_id(self, event_id: str, discord_event_id: str) -> Optional[Dict]:
        """Set the Discord event ID for a scheduled event.
        
        Args:
            event_id: The schedule event ID.
            discord_event_id: The Discord scheduled event ID.
            
        Returns:
            Updated event dict, or ``None`` if event_id not found.
        """
        return self.set_discord_event_info(event_id, discord_event_id, None)

    def set_discord_event_info(self, event_id: str,
                               discord_event_id: str,
                               discord_guild_id: Optional[str]) -> Optional[Dict]:
        """Set Discord event linkage metadata for a scheduled event.

        Args:
            event_id: The schedule event ID.
            discord_event_id: The Discord scheduled event ID.
            discord_guild_id: The Discord guild ID where event is created.

        Returns:
            Updated event dict, or ``None`` if event_id not found.
        """
        event = self._get_events().get(event_id)
        if event is None:
            return None
        event = dict(event)
        event['discord_event_id'] = discord_event_id
        if discord_guild_id:
            event['discord_guild_id'] = str(discord_guild_id).strip()
        event['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._get_events()[event_id] = event
        self._repo.save()
        return event

    def get_events(self, schedule_id: Optional[str] = None,
                   username: Optional[str] = None) -> List[Dict]:
        """Return events sorted by date/time, optionally scoped to a schedule."""
        if username:
            self.ensure_default_schedule(username)
        safe_schedule_id = str(schedule_id or '').strip()
        events = list(self._get_events().values())
        if username:
            allowed_schedule_ids = {item.get('id') for item in self.list_schedules(username)}
            events = [
                event for event in events
                if (str(event.get('schedule_id') or self._default_schedule_id(username)).strip() in allowed_schedule_ids)
            ]
        if safe_schedule_id:
            events = [
                event for event in events
                if str(event.get('schedule_id') or '').strip() == safe_schedule_id
            ]
        events.sort(key=lambda e: (e.get('date', ''), e.get('time', '')))
        return events

    def get_schedule(self, schedule_id: Optional[str]) -> Optional[Dict]:
        """Fetch a schedule by identifier."""
        safe_schedule_id = str(schedule_id or '').strip()
        if not safe_schedule_id:
            return None
        return self._get_schedules().get(safe_schedule_id)

    def get_event(self, event_id: str) -> Optional[Dict]:
        """Fetch a scheduled event by identifier."""
        return self._get_events().get(str(event_id or '').strip())
