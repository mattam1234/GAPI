"""Presence domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * POST /api/presence          (heartbeat -> updates last_seen; DB-backed)
  * POST /api/presence/update   (Discord Rich Presence for the last pick)
  * POST /api/presence/clear    (clear Discord Rich Presence)

The Discord-RPC routes degrade gracefully (200 with ok=False) when RPC is not
configured; the heartbeat no-ops (success=True) when the DB is down.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/presence", tags=["presence"])


@router.post("")
def heartbeat(username: str = Depends(require_login)):
    """Update the current user's last_seen timestamp."""
    if not gapi_gui.DB_AVAILABLE:
        return {"success": True}
    db = next(gapi_gui.database.get_db())
    try:
        gapi_gui.database.update_user_presence(db, username)
    finally:
        if db:
            db.close()
    return {"success": True}


@router.post("/update")
def presence_update(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Update Discord Rich Presence for the user's last-picked game."""
    rpc = gapi_gui._discord_rpc
    if not rpc or not rpc.enabled:
        return {"ok": False, "error": "Discord Rich Presence not configured on "
                "server (DISCORD_CLIENT_ID not set)"}
    data = body or {}
    game = str(data.get("game", "")).strip()
    if not game:
        raise HTTPException(status_code=400, detail="game name required")
    playtime = data.get("playtime_hours")
    try:
        playtime_f = float(playtime) if playtime is not None else None
    except (TypeError, ValueError):
        playtime_f = None
    updated = rpc.update(game, playtime_hours=playtime_f)
    return {"ok": True, "updated": updated}


@router.post("/clear")
def presence_clear(username: str = Depends(require_login)):
    """Clear the Discord Rich Presence status."""
    rpc = gapi_gui._discord_rpc
    if not rpc or not rpc.enabled:
        return {"ok": False, "error": "Discord Rich Presence not configured"}
    cleared = rpc.clear()
    return {"ok": True, "cleared": cleared}
