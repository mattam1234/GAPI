"""Business logic for the game-night scheduler."""
import datetime
import uuid
from typing import Dict, List, Optional

from ..repositories.schedule_repository import ScheduleRepository

_EDITABLE_FIELDS = ('title', 'date', 'time', 'attendees', 'game_name', 'notes')


class ScheduleService:
    """Creates, updates, and deletes game-night events, delegating persistence
    to :class:`~app.repositories.schedule_repository.ScheduleRepository`.
    """

    def __init__(self, repository: ScheduleRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, title: str, date: str, time_str: str,
                  attendees: Optional[List[str]] = None,
                  game_name: str = '', notes: str = '') -> Dict:
        """Create a new event and persist it.

        Args:
            title:     Short event title (required).
            date:      ISO date string, e.g. ``"2026-03-01"``.
            time_str:  Time string, e.g. ``"20:00"``.
            attendees: Participant names.
            game_name: Pre-chosen game (optional).
            notes:     Free-text notes.

        Returns:
            The new event dict including the generated ``id`` and
            ``created_at`` timestamp.
        """
        event_id = str(uuid.uuid4())[:8]
        event: Dict = {
            'id': event_id,
            'title': title,
            'date': date,
            'time': time_str,
            'attendees': attendees or [],
            'game_name': game_name,
            'notes': notes,
            'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._repo.upsert(event_id, event)
        return event

    def update_event(self, event_id: str, **kwargs) -> Optional[Dict]:
        """Update allowed fields of an existing event.

        Only fields listed in ``_EDITABLE_FIELDS`` are accepted; anything else
        in *kwargs* is silently ignored.

        Returns:
            Updated event dict, or ``None`` if *event_id* not found.
        """
        event = self._repo.find(event_id)
        if event is None:
            return None
        event = dict(event)
        for key in _EDITABLE_FIELDS:
            if key in kwargs:
                event[key] = kwargs[key]
        event['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._repo.upsert(event_id, event)
        return event

    def remove_event(self, event_id: str) -> bool:
        """Delete an event.  Returns ``True`` if it existed."""
        return self._repo.delete(event_id)

    def get_events(self) -> List[Dict]:
        """Return all events sorted by date then time (ascending)."""
        events = list(self._repo.data.values())
        events.sort(key=lambda e: (e.get('date', ''), e.get('time', '')))
        return events
