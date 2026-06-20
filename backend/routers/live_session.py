"""Live-session domain — migrated to FastAPI.

Ports the legacy ``/api/live-session`` routes (in-memory live pick sessions and
their Discord-linked DB-backed counterparts) faithfully:

  * GET    /api/live-session/discord-locations
  * POST   /api/live-session/create                       (201)
  * GET    /api/live-session/active
  * POST   /api/live-session/{session_id}/join
  * POST   /api/live-session/{session_id}/leave
  * POST   /api/live-session/{session_id}/disband
  * POST   /api/live-session/{session_id}/pick
  * GET    /api/live-session/{session_id}
  * POST   /api/live-session/{session_id}/vote
  * POST   /api/live-session/{session_id}/invite
  * GET    /api/live-session/{session_id}/events          (SSE)

Reuses the legacy singletons/state on ``gapi_gui`` (``live_sessions``,
``live_sessions_lock``, ``_sse_subscribers`` machinery, ``multi_picker``) and
the shared ``database`` layer. Auth maps the legacy ``@require_login`` decorator
to :func:`require_login`; the authenticated username is supplied explicitly (the
legacy ``get_current_username()`` read the Flask session, which is absent in a
FastAPI request).

Route ORDER matters: the literal ``/discord-locations`` and ``/active`` GETs are
registered BEFORE the catch-all ``/{session_id}`` GET so they are not shadowed.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/live-session", tags=["live-session"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


def _current_user_record(username: str):
    """Return the current DB user record for *username*, when available.

    Mirrors ``gapi_gui._get_current_user_record`` but takes the username
    explicitly instead of reading the Flask session (absent under FastAPI).
    """
    g = gapi_gui
    if not g.DB_AVAILABLE or not g.ensure_db_available():
        return None
    if not username:
        return None
    db = None
    try:
        db = g.database.SessionLocal()
        user = g.database.get_user_by_username(db, username)
        if not user:
            return None
        return {
            "username": user.username,
            "discord_id": str(getattr(user, "discord_id", "") or "").strip(),
            "steam_id": str(getattr(user, "steam_id", "") or "").strip(),
        }
    except Exception as exc:
        g.gui_logger.warning("Failed to load current user record: %s", exc)
        return None
    finally:
        if db:
            db.close()


# ── Literal paths (must precede the catch-all /{session_id} GET) ────────────

@router.get("/discord-locations")
def discord_locations(username: str = Depends(require_login)):
    """List cached Discord guild/channel targets for the linked current user."""
    g = gapi_gui
    user = _current_user_record(username)
    if not user or not user.get("discord_id"):
        return {"guilds": [], "error": "Link your Discord ID in Settings before "
                "creating a Discord-linked session."}
    if not g.DB_AVAILABLE or not g.ensure_db_available():
        return {"guilds": [], "error": "Database unavailable"}
    db = None
    try:
        db = g.database.SessionLocal()
        guilds = g.database.list_discord_locations_for_user(db, user["discord_id"])
        return {"guilds": guilds, "discord_id": user["discord_id"]}
    finally:
        if db:
            db.close()


@router.post("/create", status_code=201)
def create_session(body: Optional[dict] = Body(default=None),
                   username: str = Depends(require_login)):
    """Create a new live pick session (host becomes first participant)."""
    g = gapi_gui
    data = body or {}
    discord_guild_id = str(data.get("discord_guild_id", "") or "").strip()
    discord_channel_id = str(data.get("discord_channel_id", "") or "").strip()
    if discord_guild_id or discord_channel_id:
        if not discord_guild_id or not discord_channel_id:
            return _err(400, "Both discord_guild_id and discord_channel_id are required")
        user = _current_user_record(username)
        if not user or not user.get("discord_id"):
            return _err(400, "Link your Discord ID in Settings before creating a "
                             "Discord-linked session")
        if not user.get("steam_id") or g.gapi.is_placeholder_value(user.get("steam_id")):
            return _err(400, "A valid Steam ID is required before creating a "
                             "Discord-linked session")
        if not g.DB_AVAILABLE or not g.ensure_db_available():
            return _err(503, "Database unavailable for Discord-linked sessions")
        db = None
        try:
            db = g.database.SessionLocal()
            discord_location = g.database.get_discord_channel_for_user(
                db, user["discord_id"], discord_guild_id, discord_channel_id)
            if not discord_location:
                return _err(403, "Selected Discord server or channel is unavailable "
                                 "for this linked user")
            session_id = str(uuid.uuid4())
            linked_session = g.database.create_linked_pick_session(
                db=db,
                session_id=session_id,
                host_username=username,
                host_discord_id=user["discord_id"],
                name=data.get("name", f"{username}'s session"),
                discord_location=discord_location,
                coop_only=bool(data.get("coop_only", False)),
            )
            if not linked_session:
                return _err(500, "Failed to create linked session")
            view = g._attach_live_session_common_count(
                g.database.linked_pick_session_to_dict(db, linked_session))
        finally:
            if db:
                db.close()
        g._sse_publish(session_id, "session", view)
        return view
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "host": username,
        "name": data.get("name", f"{username}'s session"),
        "participants": [username],
        "status": "waiting",
        "created_at": datetime.utcnow(),
        "picked_game": None,
        "coop_only": bool(data.get("coop_only", False)),
        "round": 0,
        "rejected_game_ids": [],
        "vote_state": {
            "round": 0,
            "required_for_majority": 1,
            "votes_by_user": {},
            "result": "pending",
        },
    }
    with g.live_sessions_lock:
        g.live_sessions[session_id] = session
    return g._live_session_view(session)


@router.get("/active")
def active_sessions(_user: str = Depends(require_login)):
    """Return all active (non-completed) live pick sessions."""
    g = gapi_gui
    with g.live_sessions_lock:
        active = [
            g._live_session_view(s)
            for s in g.live_sessions.values()
            if s["status"] != "completed"
        ]
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            active.extend([
                g._attach_live_session_common_count(
                    g.database.linked_pick_session_to_dict(db, session))
                for session in g.database.list_active_linked_pick_sessions(db)
            ])
        except Exception as exc:
            g.gui_logger.warning("Failed to load linked sessions: %s", exc)
        finally:
            if db:
                db.close()
    return {"sessions": active}


# ── Parameterised routes ────────────────────────────────────────────────────

@router.post("/{session_id}/join")
def join_session(session_id: str, username: str = Depends(require_login)):
    """Join an existing live pick session."""
    g = gapi_gui
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                if linked_session.status in ("completed", "closed"):
                    return _err(400, "Session has already completed")
                participants = g.database.get_linked_session_participants(linked_session)
                if username not in participants:
                    participants.append(username)
                g.database.save_linked_session_state(
                    db, linked_session, participants=participants)
                view = g._attach_live_session_common_count(
                    g.database.linked_pick_session_to_dict(db, linked_session))
                g._sse_publish(session_id, "session", view)
                return view
        finally:
            if db:
                db.close()
    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if session["status"] == "completed":
            return _err(400, "Session has already completed")
        if username not in session["participants"]:
            session["participants"].append(username)
        view = g._live_session_view(session)
    g._sse_publish(session_id, "session", view)
    return view


@router.post("/{session_id}/leave")
def leave_session(session_id: str, username: str = Depends(require_login)):
    """Leave an active live pick session (host hand-off / close when empty)."""
    g = gapi_gui
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                participants = g.database.get_linked_session_participants(linked_session)
                if username in participants:
                    participants.remove(username)
                if not participants:
                    g.database.save_linked_session_state(
                        db, linked_session, participants=[], status="closed",
                        picked_game=None)
                    g._sse_publish(session_id, "session",
                                   {"status": "closed", "session_id": session_id})
                    return {"success": True,
                            "message": "Session closed (no participants left)"}
                host_username = linked_session.host_username
                if host_username == username:
                    host_username = participants[0]
                g.database.save_linked_session_state(
                    db, linked_session, participants=participants,
                    host_username=host_username)
                view = g._attach_live_session_common_count(
                    g.database.linked_pick_session_to_dict(db, linked_session))
                g._sse_publish(session_id, "session", view)
                return {"success": True, "session": view}
        finally:
            if db:
                db.close()
    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if username in session["participants"]:
            session["participants"].remove(username)
        if not session["participants"]:
            del g.live_sessions[session_id]
            g._sse_publish(session_id, "session",
                           {"status": "closed", "session_id": session_id})
            return {"success": True,
                    "message": "Session closed (no participants left)"}
        if session["host"] == username:
            session["host"] = session["participants"][0]
        view = g._live_session_view(session)
    g._sse_publish(session_id, "session", view)
    return {"success": True, "session": view}


@router.post("/{session_id}/disband")
def disband_session(session_id: str, username: str = Depends(require_login)):
    """Disband a live session (host or admin)."""
    g = gapi_gui
    is_admin = bool(g.user_manager.is_admin(username))
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                if linked_session.host_username != username and not is_admin:
                    return _err(403, "Only the session host or an admin can disband "
                                     "this session")
                g.database.save_linked_session_state(
                    db,
                    linked_session,
                    participants=[],
                    status="closed",
                    picked_game=None,
                    vote_state={
                        "round": int(linked_session.round or 0),
                        "required_for_majority": 1,
                        "votes_by_user": {},
                        "result": "disbanded",
                    },
                )
                g._sse_publish(session_id, "session",
                               {"status": "closed", "session_id": session_id})
                return {"success": True, "message": "Session disbanded"}
        finally:
            if db:
                db.close()

    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if session.get("host") != username and not is_admin:
            return _err(403, "Only the session host or an admin can disband this "
                             "session")
        g.live_sessions.pop(session_id, None)
    g._sse_publish(session_id, "session",
                   {"status": "closed", "session_id": session_id})
    return {"success": True, "message": "Session disbanded"}


@router.post("/{session_id}/pick")
def pick_session(session_id: str, body: Optional[dict] = Body(default=None),
                 username: str = Depends(require_login)):
    """Pick a common game for all participants (host only)."""
    g = gapi_gui
    data = body or {}
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                if linked_session.host_username != username:
                    return _err(403, "Only the session host can start a pick")
                if linked_session.status == "completed":
                    return _err(400, "Session has already completed")
                participants = g.database.get_linked_session_participants(linked_session)
                coop_only = bool(data.get("coop_only", False) or linked_session.coop_only)
                rejected_game_ids = g.database.get_linked_session_rejected_game_ids(
                    linked_session)
                g.database.save_linked_session_state(
                    db, linked_session, status="picking", coop_only=coop_only)

                g._ensure_multi_picker()
                if not g.multi_picker:
                    return _err(400, "Multi-user picker not initialized")

                with g.multi_picker_lock:
                    game = g.multi_picker.pick_common_game(
                        user_names=participants,
                        coop_only=coop_only,
                        max_players=len(participants),
                        exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
                    )

                next_round = int(linked_session.round or 0) + 1
                if not game:
                    g.database.save_linked_session_state(
                        db, linked_session, status="waiting")
                    return _err(404, "No common game found for all participants")

                participants_count = max(1, len(participants))
                vote_state = {
                    "round": next_round,
                    "required_for_majority": (participants_count // 2) + 1,
                    "votes_by_user": {},
                    "result": "pending",
                }
                g.database.save_linked_session_state(
                    db,
                    linked_session,
                    round=next_round,
                    picked_game=game,
                    vote_state=vote_state,
                    status="awaiting_vote",
                    coop_only=coop_only,
                )
                view = g._attach_live_session_common_count(
                    g.database.linked_pick_session_to_dict(db, linked_session))
        finally:
            if db:
                db.close()

        if g.DB_AVAILABLE:
            game_name = (view.get("picked_game") or {}).get("name", "a game")
            for participant in view.get("participants", []):
                db = next(g.database.get_db())
                try:
                    g.database.create_notification(
                        db,
                        participant,
                        title="Game picked - vote required",
                        message=f'{username} picked "{game_name}" for your live '
                                f"session. Vote to accept or reject it.",
                        type="success",
                    )
                except Exception as exc:
                    g.gui_logger.warning(
                        "Failed to notify %s after linked pick: %s", participant, exc)
                finally:
                    if db:
                        db.close()

        g._sse_publish(session_id, "session", view)
        return {"picked_game": view.get("picked_game"), "session": view}
    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if session["host"] != username:
            return _err(403, "Only the session host can start a pick")
        if session["status"] == "completed":
            return _err(400, "Session has already completed")
        participants = list(session["participants"])
        session["coop_only"] = bool(data.get("coop_only", session.get("coop_only", False)))
        rejected_game_ids = list(session.get("rejected_game_ids", []))
        session["status"] = "picking"

    coop_only = bool(data.get("coop_only", False) or session.get("coop_only", False))

    g._ensure_multi_picker()
    if not g.multi_picker:
        return _err(400, "Multi-user picker not initialized")

    with g.multi_picker_lock:
        game = g.multi_picker.pick_common_game(
            user_names=participants,
            coop_only=coop_only,
            max_players=len(participants),
            exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
        )

    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if session:
            session["round"] = int(session.get("round", 0)) + 1
            if game:
                session["picked_game"] = game
                participants_count = max(1, len(session.get("participants", [])))
                session["vote_state"] = {
                    "round": session["round"],
                    "required_for_majority": (participants_count // 2) + 1,
                    "votes_by_user": {},
                    "result": "pending",
                }
                session["status"] = "awaiting_vote"
            else:
                session["status"] = "waiting"

    if not game:
        return _err(404, "No common game found for all participants")

    # Notify all participants that a game was picked (best-effort)
    if g.DB_AVAILABLE:
        game_name = game.get("name", "a game")
        for participant in participants:
            db = next(g.database.get_db())
            try:
                g.database.create_notification(
                    db,
                    participant,
                    title="Game picked - vote required",
                    message=f'{username} picked "{game_name}" for your live '
                            f"session. Vote to accept or reject it.",
                    type="success",
                )
            except Exception as exc:
                g.gui_logger.warning(
                    "Failed to notify %s after pick: %s", participant, exc)
            finally:
                if db:
                    db.close()

    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if session:
            g._sse_publish(session_id, "session", g._live_session_view(session))

    return {"picked_game": game,
            "session": g._live_session_view(session) if session else None}


@router.get("/{session_id}")
def get_session(session_id: str, _user: str = Depends(require_login)):
    """Return the current state of a specific live pick session."""
    g = gapi_gui
    linked_session = g._get_db_linked_session(session_id)
    if linked_session:
        return linked_session
    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        return g._live_session_view(session)


@router.post("/{session_id}/vote")
def vote_session(session_id: str, body: Optional[dict] = Body(default=None),
                 username: str = Depends(require_login)):
    """Cast an accept/reject vote for the currently picked game."""
    g = gapi_gui
    data = body or {}
    if "accept" not in data:
        return _err(400, "accept is required")
    accept = bool(data.get("accept"))
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                participants = g.database.get_linked_session_participants(linked_session)
                if username not in participants:
                    return _err(403, "Only participants can vote")
                current_game = g.database.get_linked_session_picked_game(linked_session)
                if linked_session.status != "awaiting_vote" or not current_game:
                    return _err(400, "No active game vote in this session")
                vote_state = g.database.get_linked_session_vote_state(linked_session) or {}
                votes_by_user = vote_state.setdefault("votes_by_user", {})
                votes_by_user[username] = accept
                required = (max(1, len(participants)) // 2) + 1
                vote_state["required_for_majority"] = required
                vote_state["round"] = int(vote_state.get("round", linked_session.round or 0))

                yes_count = sum(1 for v in votes_by_user.values() if bool(v))
                no_count = sum(1 for v in votes_by_user.values() if not bool(v))

                if yes_count >= required:
                    vote_state["result"] = "accepted"
                    g.database.save_linked_session_state(
                        db, linked_session, vote_state=vote_state, status="completed")
                    view = g._attach_live_session_common_count(
                        g.database.linked_pick_session_to_dict(db, linked_session))
                    g._sse_publish(session_id, "session", view)
                    return {"success": True, "result": "accepted", "session": view}

                if no_count < required:
                    vote_state["result"] = "pending"
                    g.database.save_linked_session_state(
                        db, linked_session, vote_state=vote_state)
                    view = g._attach_live_session_common_count(
                        g.database.linked_pick_session_to_dict(db, linked_session))
                    g._sse_publish(session_id, "session", view)
                    return {"success": True, "result": "pending", "session": view}

                rejected_game_ids = g.database.get_linked_session_rejected_game_ids(
                    linked_session)
                rejected_app_id = str((current_game or {}).get("appid", "")).strip()
                if rejected_app_id:
                    rejected_game_ids.append(rejected_app_id)

                g._ensure_multi_picker()
                if not g.multi_picker:
                    g.database.save_linked_session_state(
                        db, linked_session, status="waiting", picked_game=None,
                        vote_state={
                            "round": int(linked_session.round or 0),
                            "required_for_majority": required,
                            "votes_by_user": {},
                            "result": "pending",
                        })
                    view = g._attach_live_session_common_count(
                        g.database.linked_pick_session_to_dict(db, linked_session))
                    g._sse_publish(session_id, "session", view)
                    return {"success": True, "result": "rejected_no_repick",
                            "session": view}

                with g.multi_picker_lock:
                    next_game = g.multi_picker.pick_common_game(
                        user_names=participants,
                        coop_only=bool(linked_session.coop_only),
                        max_players=len(participants),
                        exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
                    )

                if not next_game:
                    g.database.save_linked_session_state(
                        db,
                        linked_session,
                        status="waiting",
                        picked_game=None,
                        vote_state={
                            "round": int(linked_session.round or 0),
                            "required_for_majority": required,
                            "votes_by_user": {},
                            "result": "rejected",
                        },
                        rejected_game_ids=rejected_game_ids,
                    )
                    view = g._attach_live_session_common_count(
                        g.database.linked_pick_session_to_dict(db, linked_session))
                    g._sse_publish(session_id, "session", view)
                    return {"success": True, "result": "rejected_no_more_games",
                            "session": view}

                next_round = int(linked_session.round or 0) + 1
                g.database.save_linked_session_state(
                    db,
                    linked_session,
                    round=next_round,
                    picked_game=next_game,
                    status="awaiting_vote",
                    rejected_game_ids=rejected_game_ids,
                    vote_state={
                        "round": next_round,
                        "required_for_majority": required,
                        "votes_by_user": {},
                        "result": "pending",
                    },
                )
                view = g._attach_live_session_common_count(
                    g.database.linked_pick_session_to_dict(db, linked_session))
                g._sse_publish(session_id, "session", view)
                return {"success": True, "result": "rejected_repicked", "session": view}
        finally:
            if db:
                db.close()

    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if username not in session.get("participants", []):
            return _err(403, "Only participants can vote")
        if session.get("status") != "awaiting_vote" or not session.get("picked_game"):
            return _err(400, "No active game vote in this session")

        vote_state = session.setdefault("vote_state", {
            "round": session.get("round", 0),
            "required_for_majority": (max(1, len(session.get("participants", []))) // 2) + 1,
            "votes_by_user": {},
            "result": "pending",
        })
        votes_by_user = vote_state.setdefault("votes_by_user", {})
        votes_by_user[username] = accept

        participants = list(session.get("participants", []))
        required = (max(1, len(participants)) // 2) + 1
        vote_state["required_for_majority"] = required

        yes_count = sum(1 for v in votes_by_user.values() if bool(v))
        no_count = sum(1 for v in votes_by_user.values() if not bool(v))

        if yes_count >= required:
            vote_state["result"] = "accepted"
            session["status"] = "completed"
            view = g._live_session_view(session)
            g._sse_publish(session_id, "session", view)
            return {"success": True, "result": "accepted", "session": view}

        if no_count < required:
            view = g._live_session_view(session)
            g._sse_publish(session_id, "session", view)
            return {"success": True, "result": "pending", "session": view}

        # Rejected by majority: pick a new game and restart vote
        vote_state["result"] = "rejected"
        rejected_game_ids = session.setdefault("rejected_game_ids", [])
        rejected_app_id = str(session.get("picked_game", {}).get("appid", "")).strip()
        if rejected_app_id:
            rejected_game_ids.append(rejected_app_id)
        coop_only = bool(session.get("coop_only", False))
        session["status"] = "picking"

    g._ensure_multi_picker()
    if not g.multi_picker:
        with g.live_sessions_lock:
            session = g.live_sessions.get(session_id)
            if session:
                session["status"] = "waiting"
                session["picked_game"] = None
                session["vote_state"] = {
                    "round": int(session.get("round", 0)),
                    "required_for_majority": (max(1, len(session.get("participants", []))) // 2) + 1,
                    "votes_by_user": {},
                    "result": "pending",
                }
                view = g._live_session_view(session)
                g._sse_publish(session_id, "session", view)
                return {"success": True, "result": "rejected_no_repick", "session": view}
        return _err(400, "Multi-user picker not initialized")

    with g.multi_picker_lock:
        next_game = g.multi_picker.pick_common_game(
            user_names=participants,
            coop_only=coop_only,
            max_players=len(participants),
            exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
        )

    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")

        if not next_game:
            session["status"] = "waiting"
            session["picked_game"] = None
            session["vote_state"] = {
                "round": int(session.get("round", 0)),
                "required_for_majority": (max(1, len(session.get("participants", []))) // 2) + 1,
                "votes_by_user": {},
                "result": "rejected",
            }
            view = g._live_session_view(session)
            g._sse_publish(session_id, "session", view)
            return {"success": True, "result": "rejected_no_more_games", "session": view}

        session["round"] = int(session.get("round", 0)) + 1
        session["picked_game"] = next_game
        session["status"] = "awaiting_vote"
        session["vote_state"] = {
            "round": session["round"],
            "required_for_majority": (max(1, len(session.get("participants", []))) // 2) + 1,
            "votes_by_user": {},
            "result": "pending",
        }
        view = g._live_session_view(session)

    g._sse_publish(session_id, "session", view)
    return {"success": True, "result": "rejected_repicked", "session": view}


@router.post("/{session_id}/invite")
def invite_session(session_id: str, body: Optional[dict] = Body(default=None),
                   username: str = Depends(require_login)):
    """Invite one or more users to a live pick session (host only)."""
    g = gapi_gui
    deep_link = f"#session/{session_id}"
    data = body or {}

    # ── DB-linked (Discord) session path ──────────────────────────────────
    if g.DB_AVAILABLE and g.ensure_db_available():
        db = None
        try:
            db = g.database.SessionLocal()
            linked_session = g.database.get_linked_pick_session(db, session_id)
            if linked_session:
                if linked_session.host_username != username:
                    return _err(403, "Only the session host can invite users")
                session_name = linked_session.name
                usernames = data.get("usernames", [])
                if not usernames or not isinstance(usernames, list):
                    return _err(400, "usernames (list) is required")
                sent, failed = [], []
                for target in [str(u).strip() for u in usernames if str(u).strip()]:
                    try:
                        ok = g._send_invite_notification(
                            target,
                            title=f"🎮 Session invite from {username}",
                            message=(
                                f"{username} invited you to join their Discord-linked "
                                f'live pick session "{session_name}".'
                            ),
                            link=deep_link,
                        )
                        (sent if ok else failed).append(target)
                    except Exception as exc:
                        g.gui_logger.warning(
                            "Failed linked session invite to %s: %s", target, exc)
                        failed.append(target)
                return {"sent": sent, "failed": failed}
        finally:
            if db:
                db.close()

    # ── In-memory session path ────────────────────────────────────────────
    with g.live_sessions_lock:
        session = g.live_sessions.get(session_id)
        if not session:
            return _err(404, "Session not found")
        if session["host"] != username:
            return _err(403, "Only the session host can invite users")
        session_name = session.get("name", session_id)
    usernames = data.get("usernames", [])
    if not usernames or not isinstance(usernames, list):
        return _err(400, "usernames (list) is required")
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available for notifications")
    sent, failed = [], []
    for target in [str(u).strip() for u in usernames if str(u).strip()]:
        try:
            ok = g._send_invite_notification(
                target,
                title=f"🎮 Session invite from {username}",
                message=(
                    f"{username} invited you to join their live pick session "
                    f'"{session_name}".'
                ),
                link=deep_link,
            )
            (sent if ok else failed).append(target)
        except Exception as exc:
            g.gui_logger.warning(
                "Failed to send invite notification to %s: %s", target, exc)
            failed.append(target)
    return {"sent": sent, "failed": failed}


@router.get("/{session_id}/events")
def session_events(session_id: str, _user: str = Depends(require_login)):
    """Server-Sent Events stream for a live pick session."""
    g = gapi_gui
    linked_session = g._get_db_linked_session(session_id)
    if linked_session:
        initial_data = linked_session
    else:
        with g.live_sessions_lock:
            session = g.live_sessions.get(session_id)
            if not session:
                return _err(404, "Session not found")
            initial_data = g._live_session_view(session)

    sub_queue = g._queue.Queue(maxsize=64)
    with g._sse_subscribers_lock:
        g._sse_subscribers.setdefault(session_id, []).append(sub_queue)

    def _generate():
        import json as _json
        # Send initial state immediately
        yield f"event: session\ndata: {_json.dumps(initial_data)}\n\n"
        while True:
            try:
                payload = sub_queue.get(timeout=25)
                yield f"event: session\ndata: {payload}\n\n"
                # Stop streaming when the session is completed or closed
                try:
                    parsed = _json.loads(payload)
                    if isinstance(parsed, dict):
                        data_part = parsed.get("data", {})
                        if data_part.get("status") in ("completed", "closed"):
                            break
                except Exception:
                    pass
            except g._queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
        with g._sse_subscribers_lock:
            if session_id in g._sse_subscribers:
                try:
                    g._sse_subscribers[session_id].remove(sub_queue)
                except ValueError:
                    pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
