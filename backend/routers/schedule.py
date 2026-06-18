"""Schedule domain — migrated to FastAPI in chunks (this is chunk 1).

Chunk 1 — schedule collections (shared/personal), analogous to backlog
collections:
  * GET    /api/schedules
  * POST   /api/schedules                    (201)
  * PUT    /api/schedules/{schedule_id}
  * DELETE /api/schedules/{schedule_id}

Reuses the per-user picker ``schedule_service`` + ``picker_lock`` and the shared
``_parse_shared_member_usernames`` helper. 400 when the picker is not
initialised (legacy schedule contract). Responses are plain dicts.

Follow-up chunks (still in Flask for now): event CRUD + RSVP
(/api/schedule[...]), fuzzy search, Discord events, and iCal export.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.schedule import (
    CommonGamesIn, CreateScheduleIn, RsvpIn, SearchIn, UpdateScheduleIn,
)

router = APIRouter(prefix="/api/schedules", tags=["schedule"])

# Event routes live under the singular /api/schedule prefix.
event_router = APIRouter(prefix="/api/schedule", tags=["schedule"])

_RSVP_STATUSES = {"accepted", "maybe", "declined", "pending"}


def _picker(username: str = Depends(require_login)):
    """Per-user picker; 400 if not initialised (legacy schedule contract)."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(status_code=400, detail="Not initialized")
    return p


def _norm(value) -> str:
    return str(value or "").strip().lower()


@router.get("")
def list_schedules(schedule_id: Optional[str] = None,
                   username: str = Depends(require_login),
                   picker=Depends(_picker)):
    """List schedule collections available to the current user."""
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        schedules = svc.list_schedules(username=username)
        active_schedule_id = svc.resolve_schedule_for_user(schedule_id, username)
    return {
        "schedules": schedules,
        "count": len(schedules),
        "active_schedule_id": active_schedule_id,
    }


@router.post("", status_code=201)
def create_schedule(body: CreateScheduleIn,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Create a personal or shared schedule collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    with gapi_gui.picker_lock:
        schedule = picker.schedule_service.create_schedule(
            name=name, owner_username=username,
            members=members, is_shared=bool(body.is_shared),
        )
    return schedule


@router.put("/{schedule_id}")
def update_schedule(schedule_id: str, body: UpdateScheduleIn,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Rename or re-share a schedule collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    with gapi_gui.picker_lock:
        schedule = picker.schedule_service.update_schedule(
            schedule_id=schedule_id, username=username, name=name,
            members=members,
            is_shared=bool(body.is_shared) if body.is_shared is not None else None,
        )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Delete a schedule collection owned by the current user."""
    safe_id = str(schedule_id or "").strip()
    if not safe_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    default_id = f"personal:{_norm(username)}"
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        schedule = svc.get_schedule(safe_id)
        if not schedule or not svc._can_access_schedule(schedule, username):
            raise HTTPException(status_code=404, detail="Schedule not found")
        if _norm(schedule.get("owner")) != _norm(username):
            raise HTTPException(
                status_code=403, detail="Only the schedule owner can delete it")
        if safe_id == default_id:
            raise HTTPException(
                status_code=400,
                detail="Your personal schedule cannot be deleted")
        deleted = svc.remove_schedule(safe_id, username=username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True}


# ── Events (chunk 2: list / update / RSVP) ─────────────────────────────────

@event_router.get("")
def get_schedule(schedule_id: Optional[str] = None,
                 username: str = Depends(require_login),
                 picker=Depends(_picker)):
    """Return all game-night events for the active schedule, sorted by date."""
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        schedules = svc.list_schedules(username=username)
        active_schedule_id = svc.resolve_schedule_for_user(schedule_id, username)
        events = svc.get_events(schedule_id=active_schedule_id, username=username)
    for event in events:
        if not event.get("game_image_url"):
            event["game_image_url"] = gapi_gui._resolve_schedule_game_image_url(
                game_appid=event.get("game_appid"),
                existing_url=event.get("game_image_url"),
            )
    return {
        "events": events,
        "count": len(events),
        "schedules": schedules,
        "active_schedule_id": active_schedule_id,
    }


@event_router.put("/{event_id}")
def update_event(event_id: str, body: Optional[dict] = Body(default=None),
                 username: str = Depends(require_login),
                 picker=Depends(_picker)):
    """Update a game-night event (RSVP changes must use the rsvp endpoint)."""
    data = body or {}
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        existing_event = svc.get_event(event_id)
    if existing_event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if "rsvp_statuses" in data:
        raise HTTPException(
            status_code=403,
            detail="Use /api/schedule/<event_id>/rsvp for attendee-driven "
                   "RSVP updates.",
        )

    safe: dict = {}
    for k in ("title", "date", "time", "game_name", "notes", "game_appid",
              "game_image_url", "discord_guild_id", "timezone_name",
              "schedule_id"):
        if k in data:
            safe[k] = str(data[k]).strip()
    if "duration_minutes" in data:
        try:
            safe["duration_minutes"] = (
                int(data["duration_minutes"])
                if data["duration_minutes"] is not None else None)
        except (TypeError, ValueError):
            safe["duration_minutes"] = None
    for list_key in ("attendees", "attendee_ids"):
        if list_key in data:
            raw = data[list_key]
            if isinstance(raw, str):
                safe[list_key] = [a.strip() for a in raw.split(",") if a.strip()]
            else:
                safe[list_key] = [str(a).strip() for a in (raw or [])
                                  if str(a).strip()]
    if "timezone_offset_minutes" in data:
        try:
            safe["timezone_offset_minutes"] = (
                int(data["timezone_offset_minutes"])
                if data["timezone_offset_minutes"] is not None else None)
        except (TypeError, ValueError):
            safe["timezone_offset_minutes"] = None

    with gapi_gui.picker_lock:
        event = svc.update_event(event_id, username=username, **safe)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    before_members = gapi_gui._schedule_event_members(existing_event)
    after_members = gapi_gui._schedule_event_members(event)
    newly_invited = [after_members[key] for key in after_members
                     if key not in before_members]
    if newly_invited:
        title = event.get("title", "Game Night")
        gapi_gui._send_schedule_in_app_notifications(
            newly_invited,
            title=f"📨 Schedule invite: {title}",
            message=f'{username} invited you to "{title}" on '
                    f'{event.get("date", "")} at {event.get("time", "")}.',
            exclude_usernames={username},
            link=f"#schedule/{event_id}",
        )
    return event


@event_router.post("/{event_id}/rsvp")
def update_rsvp(event_id: str, body: RsvpIn,
                username: str = Depends(require_login),
                picker=Depends(_picker)):
    """Let an invited attendee update only their own RSVP status."""
    status = (body.status or "").strip().lower()
    if status not in _RSVP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status must be accepted, maybe, declined, or pending")

    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        event = svc.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    invite_pairs = gapi_gui._schedule_invitee_pairs(event)
    requester_key = gapi_gui._normalize_schedule_username(username)
    resolved_attendee_id = None
    for attendee_name, attendee_id in invite_pairs:
        if (gapi_gui._normalize_schedule_username(attendee_id) == requester_key
                or gapi_gui._normalize_schedule_username(attendee_name) == requester_key):
            resolved_attendee_id = attendee_id
            break
    if not resolved_attendee_id:
        raise HTTPException(
            status_code=403,
            detail="Only invited users can RSVP for this event")

    with gapi_gui.picker_lock:
        updated_event = svc.update_event_rsvp(
            event_id, resolved_attendee_id, status)
    if updated_event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    if status == "accepted":
        linked_members = gapi_gui._schedule_event_members(updated_event)
        title = updated_event.get("title", "Game Night")
        gapi_gui._send_schedule_in_app_notifications(
            list(linked_members.values()),
            title=f"✅ Invite accepted: {title}",
            message=f'{username} accepted the invite for "{title}".',
            exclude_usernames={username},
        )
        rsvp_map = updated_event.get("rsvp_statuses") or {}
        accepted_keys = {
            gapi_gui._normalize_schedule_username(attendee_id)
            for _, attendee_id in gapi_gui._schedule_invitee_pairs(updated_event)
            if str(rsvp_map.get(attendee_id, "pending")).strip().lower() == "accepted"
        }
        host_username = str(updated_event.get("created_by") or "").strip()
        host_key = gapi_gui._normalize_schedule_username(host_username)
        dm_targets = [value for key, value in linked_members.items()
                      if key in accepted_keys and key != requester_key]
        if host_key and host_key != requester_key:
            dm_targets.append(host_username)
        seen = set()
        for target in dm_targets:
            dm_key = gapi_gui._normalize_schedule_username(target)
            if not dm_key or dm_key in seen:
                continue
            seen.add(dm_key)
            gapi_gui._send_schedule_discord_dm(
                target,
                f'{username} accepted "{title}" on '
                f'{updated_event.get("date", "")} at '
                f'{updated_event.get("time", "")}.')

    return updated_event


# ── Events (chunk 3: fuzzy search + common-game picker) ────────────────────

def _candidate_games(picker, username, data):
    """Compute the candidate game pool for a schedule event picker.

    Always includes the current user's library; with invitees, intersects with
    the games all invitees share; then narrows to a backlog collection if given.
    Returns (candidate_games, attendees, collection_id).
    """
    attendees_raw = data.get("attendees", [])
    collection_id = str(data.get("collection_id") or data.get("list_id") or "").strip()
    if isinstance(attendees_raw, str):
        attendees = [v.strip() for v in attendees_raw.split(",") if v.strip()]
    else:
        attendees = [str(v).strip() for v in (attendees_raw or []) if str(v).strip()]
    attendees = list(dict.fromkeys(
        a for a in attendees if a.lower() != (username or "").lower()))

    current_user_games = list(picker.games or [])
    if not attendees:
        candidate_games = current_user_games
    else:
        gapi_gui._ensure_multi_picker()
        mp = gapi_gui.multi_picker
        if mp:
            with gapi_gui.multi_picker_lock:
                invitee_common = mp.find_common_games(attendees)
        else:
            invitee_common = []
        if not invitee_common:
            candidate_games = []
        else:
            current_ids = set()
            for g in current_user_games:
                appid = str(g.get("appid") or g.get("app_id") or "").strip()
                if appid:
                    current_ids.add(
                        (str(g.get("platform") or "steam").lower(), appid.lower()))
            candidate_games = [
                g for g in invitee_common
                if (str(g.get("platform") or "steam").lower(),
                    str(g.get("appid") or g.get("app_id") or "").strip().lower())
                in current_ids
            ]

    if collection_id:
        service = gapi_gui._get_shared_backlog_service()
        resolved = service.resolve_collection_for_user(collection_id, username)
        candidate_games = service.get_games(
            candidate_games, username=username, collection_id=resolved)
    return candidate_games, attendees, collection_id


def _schedule_game_summary(game):
    app_id = str(game.get("appid") or game.get("app_id") or "").strip()
    return {
        "app_id": app_id,
        "name": game.get("name", "Unknown"),
        "owners": game.get("owners", []),
        "platform": game.get("platform", "steam"),
        "image_url": gapi_gui._resolve_schedule_game_image_url(
            game=game, game_appid=app_id, existing_url=game.get("image_url")),
    }


@event_router.post("/search-games")
def search_games(body: SearchIn, username: str = Depends(require_login),
                 picker=Depends(_picker)):
    """Fuzzy-search the user's library by title or app id."""
    query = (body.query or "").strip()
    limit = gapi_gui._parse_search_limit(body.limit)
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        with gapi_gui.picker_lock:
            results = gapi_gui._fuzzy_search_games(query, picker.games, limit=limit)
        clean = []
        for game in results:
            genres = game.get("genres", [])
            clean.append({
                "name": game.get("name", ""),
                "appid": str(game.get("appid") or game.get("app_id", "")),
                "image_url": gapi_gui._resolve_schedule_game_image_url(
                    game=game,
                    game_appid=str(game.get("appid") or game.get("app_id", "")),
                    existing_url=game.get("image_url")),
                "platform": game.get("platform", "steam"),
                "playtime_hours": gapi_gui._safe_playtime_hours(game),
                "genres": genres if isinstance(genres, list) else [],
            })
    except Exception as e:
        gapi_gui.gui_logger.error('Game search failed for "%s": %s', query, e)
        raise HTTPException(status_code=500, detail="Game search failed")
    return {"results": clean, "count": len(clean)}


@event_router.post("/search-attendees")
def search_attendees(body: SearchIn, username: str = Depends(require_login),
                     picker=Depends(_picker)):
    """Fuzzy-search potential attendees from the multi-user roster."""
    query = (body.query or "").strip()
    limit = gapi_gui._parse_search_limit(body.limit)
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        gapi_gui._ensure_multi_picker()
        with gapi_gui.multi_picker_lock:
            mp = gapi_gui.multi_picker
            users_list = mp.users if mp else []
            results = gapi_gui._fuzzy_search_users(query, users_list, limit=limit)
        clean = [{"name": u.get("name", ""), "id": u.get("name", ""),
                  "discord_id": u.get("discord_id", "")} for u in results]
    except Exception as e:
        gapi_gui.gui_logger.error('Attendee search failed for "%s": %s', query, e)
        raise HTTPException(status_code=500, detail="Attendee search failed")
    return {"results": clean, "count": len(clean)}


@event_router.post("/common-games")
def common_games(body: CommonGamesIn, username: str = Depends(require_login),
                 picker=Depends(_picker)):
    """Return games eligible for a schedule event's game picker."""
    candidate_games, attendees, collection_id = _candidate_games(
        picker, username, body.model_dump())
    games = [_schedule_game_summary(g) for g in candidate_games[:100]]
    return {
        "games": games,
        "count": len(games),
        "attendees": attendees,
        "collection_id": collection_id,
    }


@event_router.post("/common-games/random")
def common_games_random(body: CommonGamesIn,
                        username: str = Depends(require_login),
                        picker=Depends(_picker)):
    """Pick a random game from the eligible pool for a schedule event."""
    import random
    candidate_games, attendees, collection_id = _candidate_games(
        picker, username, body.model_dump())
    if not candidate_games:
        raise HTTPException(status_code=404, detail="No games found in your library")
    game = random.choice(candidate_games)
    return {
        "game": _schedule_game_summary(game),
        "attendees": attendees,
        "collection_id": collection_id,
    }
