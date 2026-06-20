"""Chat domain (migrated to FastAPI).

Faithful port of the legacy Flask chat API:
  * GET    /api/chat/messages
  * POST   /api/chat/send
  * GET    /api/chat/online-users
  * POST   /api/chat/typing
  * GET    /api/chat/typing/{room}
  * POST   /api/chat/update-room
  * GET    /api/chat/room-users
  * POST   /api/chat/invite
  * POST   /api/chat/message/{message_id}/react
  * DELETE /api/chat/message/{message_id}/react
  * PATCH  /api/chat/message/{message_id}
  * DELETE /api/chat/message/{message_id}

All chat state (in-memory rooms, typing indicators, locks) and helpers live on
``gapi_gui`` and are referenced at CALL TIME so reassignments are picked up. The
legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (chat is not in the cacheable-prefix allowlist); that header is set
explicitly here to preserve behaviour.
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/chat", tags=["chat"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


@router.get("/messages")
def api_chat_messages(request: Request, username: str = Depends(require_login)):
    """Fetch messages from a chat room."""
    g = gapi_gui
    args = request.query_params
    room = g._normalize_chat_room_name(args.get("room", "general"))
    if not g._can_access_chat_room(username, room):
        return _err(403, f'Access denied for private room "{room}"')
    try:
        since_id = int(args.get("since_id", 0))
        before_id = int(args.get("before_id", 0))
        limit = int(args.get("limit", 50))
    except ValueError:
        since_id, before_id, limit = 0, 0, 50
    db = next(g.database.get_db())
    try:
        if g._chat_service:
            messages = g._chat_service.get_messages(db, room=room, limit=limit,
                                                     since_id=since_id, before_id=before_id)
        else:
            messages = g.database.get_chat_messages(db, room=room, limit=limit,
                                                    since_id=since_id, before_id=before_id)
    finally:
        if db:
            db.close()
    return _ok({"room": room, "messages": messages})


@router.post("/send")
def api_chat_send(body: Optional[dict] = Body(default=None),
                  username: str = Depends(require_login)):
    """Send a chat message to a room."""
    g = gapi_gui
    data = body or {}
    message = data.get("message", "").strip()
    room = g._normalize_chat_room_name(data.get("room", "general"))
    if not message:
        return _err(400, "message is required")
    if len(message) > 500:
        return _err(400, "message must be 500 characters or fewer")
    db = next(g.database.get_db())
    try:
        if not g._can_access_chat_room(username, room):
            return _err(403, f'Access denied for private room "{room}"')

        # Update user's current room and activity
        with g.user_room_lock:
            g.user_current_room[username] = room
            g.user_last_activity[username] = datetime.utcnow().timestamp()

        with g.chat_rooms_lock:
            state = g.chat_rooms.get(room)
            if state:
                state["members"].add(username)

        if message.startswith("/"):
            # First, save the command text itself (visible only to sender/admins)
            if g._chat_service:
                g._chat_service.send(db, sender_username=username,
                                     message=message, room=room, command_only=True)
            else:
                g.database.send_chat_message(db, sender_username=username,
                                             message=message, room=room, command_only=True)

            # Now handle the command and get the result
            cmd_result = g._handle_chat_command(db, username=username, room=room, message=message)
            if not cmd_result.get("ok"):
                return _err(int(cmd_result.get("status", 400)),
                            cmd_result.get("text", "Command failed"))

            if not cmd_result.get("announce", False):
                # Save command-only result as a private message
                cmd_text = cmd_result.get("text", "").strip()
                if g._chat_service:
                    msg = g._chat_service.send(db, sender_username=username,
                                               message=cmd_text, room=room, command_only=True)
                else:
                    msg = g.database.send_chat_message(db, sender_username=username,
                                                       message=cmd_text, room=room, command_only=True)
                if msg:
                    msg["command"] = True
                    if "room_name" in cmd_result:
                        msg["room_name"] = cmd_result["room_name"]
                    return _ok(msg, int(cmd_result.get("status", 200)))
                resp = {
                    "command": True,
                    "room": room,
                    "message": cmd_text,
                }
                if "room_name" in cmd_result:
                    resp["room_name"] = cmd_result["room_name"]
                return _ok(resp, int(cmd_result.get("status", 200)))

            # Announcement message - visible to everyone
            announcement = cmd_result.get("text", "").strip()
            if g._chat_service:
                msg = g._chat_service.send(db, sender_username=username,
                                           message=announcement, room=room)
            else:
                msg = g.database.send_chat_message(db, sender_username=username,
                                                   message=announcement, room=room)
            if not msg:
                return _err(500, "Command succeeded but announcement message could not be sent")
            msg["command"] = True
            return _ok(msg, int(cmd_result.get("status", 200)))

        if g._chat_service:
            msg = g._chat_service.send(db, sender_username=username,
                                       message=message, room=room)
        else:
            reply_to_id = data.get("reply_to_id")
            msg = g.database.send_chat_message(db, sender_username=username,
                                               message=message, room=room, reply_to_id=reply_to_id)

        # Detect @mentions and create notifications
        if msg:
            mention_pattern = r"@(\w+)"
            mentioned_users = re.findall(mention_pattern, message)
            if mentioned_users:
                for mentioned_user in set(mentioned_users):  # avoid duplicate notifications
                    # Don't notify the sender
                    if mentioned_user != username:
                        # Check if user exists
                        mentioned_user_obj = db.query(g.database.User).filter(
                            g.database.User.username == mentioned_user).first()
                        if mentioned_user_obj:
                            # Create notification
                            notification_title = f"💬 {username} mentioned you in {room}"
                            notification_message = f"{message[:100]}{'...' if len(message) > 100 else ''}"
                            g.database.create_notification(db, mentioned_user, notification_title,
                                                           notification_message, type="mention")
    finally:
        if db:
            db.close()
    if not msg:
        return _err(500, "Failed to send message")
    return _ok(msg, 201)


@router.get("/online-users")
def api_chat_online_users(username: str = Depends(require_login)):
    """Get list of online users and their current rooms."""
    g = gapi_gui
    online_users = {}
    current_time = datetime.utcnow().timestamp()

    with g.user_room_lock:
        # Filter out inactive users (not active in last 5 minutes)
        for user, room in g.user_current_room.items():
            last_activity = g.user_last_activity.get(user, current_time)
            if current_time - last_activity < 300:
                if room not in online_users:
                    online_users[room] = []
                online_users[room].append(user)

    return _ok({"online_users": online_users})


@router.post("/typing")
def api_chat_typing(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Indicate user is typing in a room."""
    g = gapi_gui
    data = body or {}
    room = g._normalize_chat_room_name(data.get("room", "general"))
    is_typing = data.get("typing", True)

    with g.user_room_lock:
        if is_typing:
            g.user_typing_indicators[f"{room}:{username}"] = datetime.utcnow().timestamp()
        else:
            g.user_typing_indicators.pop(f"{room}:{username}", None)

    return _ok({"ok": True})


@router.get("/typing/{room}")
def api_chat_get_typing(room: str, username: str = Depends(require_login)):
    """Get list of users currently typing in a room."""
    g = gapi_gui
    room = g._normalize_chat_room_name(room)

    typing_users = []
    current_time = datetime.utcnow().timestamp()

    with g.user_room_lock:
        # Clean up old typing indicators (older than 5 seconds)
        to_remove = []
        for key, timestamp in list(g.user_typing_indicators.items()):
            if current_time - timestamp > 5:
                to_remove.append(key)
        for key in to_remove:
            g.user_typing_indicators.pop(key, None)

        # Get typing users for this room
        for key in g.user_typing_indicators:
            if key.startswith(f"{room}:"):
                typing_user = key.split(":", 1)[1]
                if typing_user != username:
                    typing_users.append(typing_user)

    return _ok({"typing": typing_users})


@router.post("/update-room")
def api_chat_update_room(body: Optional[dict] = Body(default=None),
                         username: str = Depends(require_login)):
    """Update the current user's active room."""
    g = gapi_gui
    data = body or {}
    room = g._normalize_chat_room_name(data.get("room", "general"))

    with g.user_room_lock:
        g.user_current_room[username] = room
        g.user_last_activity[username] = datetime.utcnow().timestamp()

    return _ok({"ok": True, "room": room})


@router.get("/room-users")
def api_chat_room_users(request: Request, username: str = Depends(require_login)):
    """Get members and invite status for a room."""
    g = gapi_gui
    room = g._normalize_chat_room_name(request.query_params.get("room", "general"))
    if not g._can_access_chat_room(username, room):
        return _err(403, f'Access denied for private room "{room}"')

    state = g._ensure_chat_room(room)
    with g.chat_rooms_lock:
        return _ok({
            "room": room,
            "owner": state.get("owner"),
            "is_private": state.get("is_private", False),
            "members": list(state.get("members", [])),
            "invites": list(state.get("invites", [])) if state.get("is_private") else [],
        })


@router.post("/invite")
def api_chat_invite(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Send an invite to a user for a private room."""
    g = gapi_gui
    data = body or {}
    target_username = data.get("target_username", "").strip()
    room = g._normalize_chat_room_name(data.get("room", "general"))

    if not target_username:
        return _err(400, "target_username is required")

    ok, msg, _ = g._invite_to_chat_room(username, target_username, room)
    status = 200 if ok else 403
    return _ok({"ok": ok, "message": msg}, status)


@router.post("/message/{message_id}/react")
def api_chat_add_reaction(message_id: int, body: Optional[dict] = Body(default=None),
                          username: str = Depends(require_login)):
    """Add a reaction (emoji) to a chat message."""
    g = gapi_gui
    data = body or {}
    emoji = data.get("emoji", "").strip()

    if not emoji:
        return _err(400, "emoji is required")

    db = next(g.database.get_db())
    try:
        success = g.database.add_message_reaction(db, message_id, username, emoji)
        if success:
            return _ok({"ok": True, "message": "Reaction added"})
        return _err(400, "Failed to add reaction")
    finally:
        if db:
            db.close()


@router.delete("/message/{message_id}/react")
def api_chat_remove_reaction(message_id: int, request: Request,
                             username: str = Depends(require_login)):
    """Remove a reaction from a chat message."""
    g = gapi_gui
    emoji = request.query_params.get("emoji", "").strip()

    if not emoji:
        return _err(400, "emoji is required")

    db = next(g.database.get_db())
    try:
        success = g.database.remove_message_reaction(db, message_id, username, emoji)
        if success:
            return _ok({"ok": True, "message": "Reaction removed"})
        return _err(400, "Failed to remove reaction")
    finally:
        if db:
            db.close()


@router.patch("/message/{message_id}")
def api_chat_edit_message(message_id: int, body: Optional[dict] = Body(default=None),
                          username: str = Depends(require_login)):
    """Edit a chat message (only sender can edit)."""
    g = gapi_gui
    data = body or {}
    new_message = data.get("message", "").strip()

    if not new_message:
        return _err(400, "message is required")

    if len(new_message) > 500:
        return _err(400, "message must be 500 characters or fewer")

    db = next(g.database.get_db())
    try:
        success = g.database.edit_chat_message(db, message_id, username, new_message)
        if success:
            return _ok({"ok": True, "message": "Message edited"})
        return _err(403, "Failed to edit message (not found or not owner)")
    finally:
        if db:
            db.close()


@router.delete("/message/{message_id}")
def api_chat_delete_message(message_id: int, username: str = Depends(require_login)):
    """Delete a chat message (only sender can delete)."""
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        success = g.database.delete_chat_message(db, message_id, username)
        if success:
            return _ok({"ok": True, "message": "Message deleted"})
        return _err(403, "Failed to delete message (not found or not owner)")
    finally:
        if db:
            db.close()
