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

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import get_current_user, require_login
from backend.schemas.schedule import (
    CommonGamesIn, CreateDiscordEventIn, CreateScheduleIn, RsvpIn, SearchIn,
    UpdateScheduleIn,
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


# ── iCal export / sync (chunk 4a) ──────────────────────────────────────────

@event_router.get("/ical-sync-info")
def ical_sync_info(request: Request, username: str = Depends(require_login)):
    """Return private iCal subscription URLs for the current user."""
    return gapi_gui._build_schedule_ical_sync_urls(
        username, base_url=str(request.base_url))


@event_router.get("/export.ics")
def export_ics(token: str = "", download: str = "1",
               username: Optional[str] = Depends(get_current_user)):
    """Download the schedule as an RFC 5545 iCalendar document.

    Auth is by signed feed token (for calendar apps) or the session cookie.
    """
    token = (token or "").strip()
    if token:
        username = gapi_gui._resolve_schedule_ical_username(token)
        if not username:
            raise HTTPException(status_code=401, detail="Invalid iCal token")
    if not username:
        raise HTTPException(status_code=401, detail="Not logged in")
    picker = gapi_gui.ensure_picker_initialized(username)
    if not picker:
        raise HTTPException(status_code=400, detail="Not initialized")

    with gapi_gui.picker_lock:
        events = picker.schedule_service.get_events(username=username)

    esc = gapi_gui._ical_escape
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GAPI//Game Night Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for ev in events:
        date_str = ev.get("date", "")
        time_str = ev.get("time", "00:00")
        dtstart = ""
        if date_str:
            clean_date = date_str.replace("-", "")
            clean_time = time_str.replace(":", "")
            if len(clean_time) == 4:
                clean_time += "00"
            dtstart = f"{clean_date}T{clean_time}"
        invitee_names = ev.get("invited_attendees", ev.get("attendees", []))
        invitee_ids = ev.get("invited_attendee_ids", ev.get("attendee_ids", []))
        attendees = ", ".join(invitee_names or [])
        game_name = ev.get("game_name", "")
        notes = ev.get("notes", "")
        rsvp_statuses = ev.get("rsvp_statuses", {}) if isinstance(
            ev.get("rsvp_statuses"), dict) else {}
        desc_parts = []
        if game_name:
            desc_parts.append(f"Game: {game_name}")
        if attendees:
            desc_parts.append(f"Attendees: {attendees}")
        rsvp_lines = []
        for index, attendee_name in enumerate(invitee_names or []):
            attendee_id = (invitee_ids[index]
                           if isinstance(invitee_ids, list) and index < len(invitee_ids)
                           else attendee_name)
            status = str(rsvp_statuses.get(attendee_id)
                         or rsvp_statuses.get(attendee_name)
                         or "pending").strip().lower()
            rsvp_lines.append(f"{attendee_name} ({status})")
        if rsvp_lines:
            desc_parts.append(f'RSVP: {", ".join(rsvp_lines)}')
        if notes:
            desc_parts.append(notes)
        description = "\n".join(esc(part) for part in desc_parts)
        uid = f"{ev.get('id', 'unknown')}@gapi"

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f'SUMMARY:{esc(ev.get("title", "Game Night"))}')
        if dtstart:
            lines.append(f"DTSTART:{dtstart}")
        if description:
            lines.append(f"DESCRIPTION:{description}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    ical_body = "\r\n".join(lines) + "\r\n"
    headers = {}
    if str(download or "1").strip() != "0":
        headers["Content-Disposition"] = 'attachment; filename="gapi_schedule.ics"'
    return Response(content=ical_body,
                    media_type="text/calendar; charset=utf-8", headers=headers)


# ── Discord integration (chunk 4b: guilds + per-event create) ──────────────

@event_router.get("/discord-guilds")
def discord_guilds(username: str = Depends(require_login)):
    """List cached Discord guilds available to the current linked user."""
    user = gapi_gui._get_current_user_record()
    if not user or not user.get("discord_id"):
        return {"guilds": [], "error": "Link your Discord ID in Settings before "
                "syncing schedule events to Discord."}
    if not gapi_gui.DB_AVAILABLE or not gapi_gui.ensure_db_available():
        return {"guilds": [], "error": "Database unavailable"}
    db = None
    try:
        db = gapi_gui.database.SessionLocal()
        guilds = gapi_gui.database.list_discord_locations_for_user(db, user["discord_id"])
        return {
            "guilds": [
                {"guild_id": g.get("guild_id"), "guild_name": g.get("guild_name"),
                 "icon_url": g.get("icon_url")}
                for g in guilds
            ],
            "discord_id": user["discord_id"],
        }
    finally:
        if db:
            db.close()


@event_router.post("/{event_id}/create-discord-event")
def create_discord_event(event_id: str, body: CreateDiscordEventIn,
                         username: str = Depends(require_login),
                         picker=Depends(_picker)):
    """Create a Discord scheduled event for a game-night schedule event."""
    import base64
    import json as _json
    import os
    from datetime import timedelta

    import requests

    guild_id = str(body.guild_id or "").strip()
    timezone_name = str(body.timezone_name or "").strip() or None
    try:
        timezone_offset_minutes = (
            int(body.timezone_offset_minutes)
            if body.timezone_offset_minutes is not None else None)
    except (TypeError, ValueError):
        timezone_offset_minutes = None

    if not guild_id:
        raise HTTPException(status_code=400, detail="guild_id is required")

    with gapi_gui.picker_lock:
        event = picker.schedule_service.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    discord_token = None
    try:
        config_path = os.environ.get("GAPI_DISCORD_CONFIG", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                discord_token = _json.load(f).get("discord_bot_token")
    except Exception as e:
        gapi_gui.gui_logger.error("Could not load Discord token: %s", e)
        raise HTTPException(status_code=500, detail="Discord bot token not configured")
    if not discord_token:
        raise HTTPException(
            status_code=500, detail="Discord bot token not found in config.json")

    try:
        date_part = event.get("date", "")
        time_part = event.get("time", "").replace(".", ":")
        try:
            event_datetime = gapi_gui._schedule_local_to_utc(
                date_part, time_part,
                timezone_name=timezone_name or event.get("timezone_name"),
                timezone_offset_minutes=(
                    timezone_offset_minutes if timezone_offset_minutes is not None
                    else event.get("timezone_offset_minutes")),
            )
        except (ValueError, AttributeError) as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid event date/time format: {e}")
        end_time = event_datetime + timedelta(hours=2)

        description = gapi_gui._build_discord_schedule_description(
            game_name=event.get("game_name", "TBA"),
            game_appid=event.get("game_appid"),
            notes=event.get("notes", ""),
            attendees=event.get("attendees", []),
        )
        payload = {
            "name": event.get("title", "Game Night")[:100],
            "privacy_level": 2,
            "scheduled_start_time": event_datetime.isoformat(),
            "scheduled_end_time": end_time.isoformat(),
            "entity_type": 3,
            "entity_metadata": {"location": event.get("game_name", "Online")[:100]},
            "description": description[:1000],
        }

        game_image_url = gapi_gui._resolve_schedule_game_image_url(
            game_appid=event.get("game_appid"),
            existing_url=event.get("game_image_url"))
        if game_image_url:
            try:
                img_resp = requests.get(game_image_url, timeout=5)
                if img_resp.status_code == 200 and len(img_resp.content) < 10 * 1024 * 1024:
                    content_type = img_resp.headers.get("content-type", "image/jpeg")
                    img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
                    payload["image"] = f"data:{content_type};base64,{img_b64}"
            except Exception as img_err:
                gapi_gui.gui_logger.warning("Could not fetch game image: %s", img_err)

        discord_api_url = (
            f"https://discord.com/api/v10/guilds/{guild_id}/scheduled-events")
        headers = {"Authorization": f"Bot {discord_token}",
                   "Content-Type": "application/json"}
        response = requests.post(discord_api_url, json=payload, headers=headers,
                                 timeout=10)

        if response.status_code in (200, 201):
            discord_event_id = response.json().get("id")
            with gapi_gui.picker_lock:
                picker.schedule_service.set_discord_event_info(
                    event_id, discord_event_id, guild_id)
            return {
                "success": True,
                "message": "Discord scheduled event created successfully",
                "event_id": event_id,
                "discord_event_id": discord_event_id,
                "discord_event_url":
                    f"https://discord.com/events/{guild_id}/{discord_event_id}",
            }
        error_data = (response.json()
                      if response.headers.get("content-type", "").startswith("application/json")
                      else {})
        error_msg = error_data.get("message", f"HTTP {response.status_code}")
        gapi_gui.gui_logger.error("Discord API error: %s - %s",
                                  response.status_code, error_msg)
        return JSONResponse(
            status_code=response.status_code,
            content={"error": f"Discord API error: {error_msg}",
                     "status_code": response.status_code, "details": error_data})
    except HTTPException:
        raise
    except Exception as e:
        gapi_gui.gui_logger.error("Error creating Discord event: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Failed to create Discord event: {str(e)}")


# ── Events (chunk 4c: create + delete, with inline Discord) ────────────────

def _csv_or_list(raw):
    if isinstance(raw, str):
        return [a.strip() for a in raw.split(",") if a.strip()]
    return [str(a).strip() for a in (raw or []) if str(a).strip()]


@event_router.post("", status_code=201)
def create_event(body: Optional[dict] = Body(default=None),
                 username: str = Depends(require_login),
                 picker=Depends(_picker)):
    """Create a game-night event, optionally syncing a Discord scheduled event."""
    import base64
    import json as _json
    import os
    from datetime import timedelta

    import requests

    data = body or {}
    title = str(data.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    date = str(data.get("date", "")).strip()
    time_str = str(data.get("time", "")).strip()
    attendees = _csv_or_list(data.get("attendees", ""))
    attendee_ids = _csv_or_list(data.get("attendee_ids", ""))

    rsvp_statuses = {}
    rsvp_raw = data.get("rsvp_statuses", {})
    if isinstance(rsvp_raw, dict):
        for key, value in rsvp_raw.items():
            safe_key = str(key or "").strip()
            if safe_key:
                rsvp_statuses[safe_key] = str(value or "pending").strip().lower()

    game_name = str(data.get("game_name", "")).strip()
    game_appid = str(data.get("game_appid", "")).strip() or None
    game_image_url = str(data.get("game_image_url", "")).strip() or None
    if not game_image_url:
        with gapi_gui.picker_lock:
            selected_game = next(
                (g for g in picker.games
                 if str(g.get("appid") or g.get("app_id") or "").strip()
                 == str(game_appid or "").strip()),
                None)
        game_image_url = gapi_gui._resolve_schedule_game_image_url(
            game=selected_game, game_appid=game_appid,
            existing_url=game_image_url) or None

    notes = str(data.get("notes", "")).strip()
    try:
        duration_minutes = (int(data["duration_minutes"])
                            if data.get("duration_minutes") is not None else None)
    except (TypeError, ValueError, KeyError):
        duration_minutes = None
    create_discord_event = data.get("create_discord_event", False)
    discord_guild_id = data.get("discord_guild_id")
    schedule_id = str(data.get("schedule_id", "")).strip() or None
    timezone_name = str(data.get("timezone_name", "")).strip() or None
    try:
        timezone_offset_minutes = (
            int(data["timezone_offset_minutes"])
            if data.get("timezone_offset_minutes") is not None else None)
    except (TypeError, ValueError, KeyError):
        timezone_offset_minutes = None

    with gapi_gui.picker_lock:
        event = picker.schedule_service.add_event(
            title, date, time_str, duration_minutes, attendees, game_name, notes,
            game_appid=game_appid, attendee_ids=attendee_ids,
            rsvp_statuses=rsvp_statuses, game_image_url=game_image_url,
            schedule_id=schedule_id, owner_username=username,
            discord_guild_id=str(discord_guild_id).strip() if discord_guild_id else None,
            timezone_name=timezone_name,
            timezone_offset_minutes=timezone_offset_minutes,
        )

    invite_recipients = [
        str(invitee_id or invitee_name).strip()
        for invitee_name, invitee_id in gapi_gui._schedule_invitee_pairs(event)
        if str(invitee_id or invitee_name).strip()
    ]
    event_id = event.get("id", "")
    gapi_gui._send_schedule_in_app_notifications(
        invite_recipients,
        title=f"📨 Schedule invite: {title}",
        message=f'{username} invited you to "{title}" on {date} at {time_str}.',
        exclude_usernames={username},
        link=f"#schedule/{event_id}" if event_id else None,
    )

    discord_result = None
    if create_discord_event and discord_guild_id:
        try:
            discord_token = None
            config_path = os.environ.get("GAPI_DISCORD_CONFIG", "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    discord_token = _json.load(f).get("discord_bot_token")
            if discord_token:
                event_datetime = gapi_gui._schedule_local_to_utc(
                    date, time_str, timezone_name=timezone_name,
                    timezone_offset_minutes=timezone_offset_minutes)
                end_time = event_datetime + timedelta(hours=2)
                description = gapi_gui._build_discord_schedule_description(
                    game_name=game_name, game_appid=game_appid,
                    notes=notes, attendees=attendees)
                payload = {
                    "name": title[:100], "privacy_level": 2,
                    "scheduled_start_time": event_datetime.isoformat(),
                    "scheduled_end_time": end_time.isoformat(),
                    "entity_type": 3,
                    "entity_metadata": {"location": game_name[:100] if game_name else "Online"},
                    "description": description[:1000],
                }
                if game_image_url:
                    try:
                        img_resp = requests.get(game_image_url, timeout=5)
                        if img_resp.status_code == 200 and len(img_resp.content) < 10 * 1024 * 1024:
                            ctype = img_resp.headers.get("content-type", "image/jpeg")
                            b64 = base64.b64encode(img_resp.content).decode("utf-8")
                            payload["image"] = f"data:{ctype};base64,{b64}"
                    except Exception as img_err:
                        gapi_gui.gui_logger.error("Error fetching game image: %s", img_err)
                url = f"https://discord.com/api/v10/guilds/{discord_guild_id}/scheduled-events"
                headers = {"Authorization": f"Bot {discord_token}",
                           "Content-Type": "application/json"}
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code in (200, 201):
                    discord_event_id = response.json().get("id")
                    with gapi_gui.picker_lock:
                        picker.schedule_service.set_discord_event_info(
                            event["id"], discord_event_id, str(discord_guild_id).strip())
                    event["discord_event_id"] = discord_event_id
                    event["discord_guild_id"] = str(discord_guild_id).strip()
                    discord_result = {
                        "success": True, "discord_event_id": discord_event_id,
                        "discord_event_url":
                            f"https://discord.com/events/{discord_guild_id}/{discord_event_id}",
                    }
                else:
                    gapi_gui.gui_logger.error("Discord API error: %s", response.status_code)
                    discord_result = {"success": False, "error": "Discord API error"}
        except Exception as e:
            gapi_gui.gui_logger.error("Error creating Discord event: %s", e)
            discord_result = {"success": False, "error": str(e)}

    if discord_result:
        event["discord_result"] = discord_result
    return event


@event_router.delete("/{event_id}")
def delete_event(event_id: str, body: Optional[dict] = Body(default=None),
                 username: str = Depends(require_login), picker=Depends(_picker)):
    """Delete a game-night event, cancelling any linked Discord event first."""
    import json as _json
    import os

    import requests

    data = body or {}
    override_guild_id = str(data.get("guild_id", "")).strip()
    with gapi_gui.picker_lock:
        event = picker.schedule_service.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    discord_event_id = str(event.get("discord_event_id") or "").strip()
    discord_guild_id = str(event.get("discord_guild_id") or "").strip() or override_guild_id

    if discord_event_id:
        if not discord_guild_id:
            return JSONResponse(status_code=400, content={
                "error": "Discord guild ID is required to cancel linked Discord event",
                "requires_guild_id": True})
        try:
            discord_token = None
            config_path = os.environ.get("GAPI_DISCORD_CONFIG", "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    discord_token = _json.load(f).get("discord_bot_token")
            if not discord_token:
                return JSONResponse(status_code=500, content={
                    "error": "Discord bot token not found in config.json"})
            url = (f"https://discord.com/api/v10/guilds/{discord_guild_id}"
                   f"/scheduled-events/{discord_event_id}")
            response = requests.delete(
                url, headers={"Authorization": f"Bot {discord_token}"}, timeout=10)
            if response.status_code not in (204, 404):
                error_data = (response.json()
                              if response.headers.get("content-type", "").startswith("application/json")
                              else {})
                error_msg = error_data.get("message", f"HTTP {response.status_code}")
                gapi_gui.gui_logger.error("Failed to cancel Discord event %s: %s - %s",
                                          discord_event_id, response.status_code, error_msg)
                return JSONResponse(status_code=502, content={
                    "error": f"Failed to cancel Discord event: {error_msg}",
                    "status_code": response.status_code, "details": error_data})
        except Exception as exc:
            gapi_gui.gui_logger.error("Error cancelling Discord event %s: %s",
                                      discord_event_id, exc)
            return JSONResponse(status_code=502, content={
                "error": f"Failed to cancel Discord event: {str(exc)}"})

    with gapi_gui.picker_lock:
        removed = picker.schedule_service.remove_event(event_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True, "id": event_id,
            "discord_cancelled": bool(discord_event_id)}
