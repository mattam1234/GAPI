"""Friends domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/friends                  (live Steam friends + recent activity)
  * POST   /api/friends/add              (placeholder friend request)
  * DELETE /api/friends/{username}       (placeholder remove)
  * DELETE /api/friends/follow/{username}(placeholder unfollow)

The GET is Steam-API backed (503 when Steam is unconfigured). The add/remove/
follow routes are the legacy placeholders (not yet persisted); behaviour is
preserved verbatim.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi
import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/friends", tags=["friends"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.get("")
def get_friends(username: str = Depends(require_login)):
    """Return the user's Steam friends and their recent activity."""
    g = gapi_gui
    user_ids = g.user_manager.get_user_ids(username)
    steam_id = user_ids.get("steam_id", "")
    if not steam_id or gapi.is_placeholder_value(steam_id):
        return _err(503, "Steam ID not configured")

    p = g.ensure_picker_initialized(username)
    if not p or not p.steam_client or not isinstance(p.steam_client, gapi.SteamAPIClient):
        return _err(503, "Steam client not available")
    steam_client = p.steam_client

    friends_raw = steam_client.get_friend_list(steam_id)
    if not friends_raw:
        return {"friends": []}
    friend_ids = [f["steamid"] for f in friends_raw]
    summaries = steam_client.get_player_summaries(friend_ids)
    summary_map = {s["steamid"]: s for s in summaries}

    result = []
    for fid in friend_ids:
        summary = summary_map.get(fid, {})
        entry = {
            "steamid": fid,
            "personaname": summary.get("personaname", fid),
            "avatarfull": summary.get("avatarfull", ""),
            "personastate": summary.get("personastate", 0),
        }
        if summary.get("gameextrainfo"):
            entry["current_game"] = summary["gameextrainfo"]
        if summary.get("gameid"):
            entry["current_gameid"] = summary["gameid"]
        try:
            recent = steam_client.get_recently_played(fid, count=5)
            entry["recently_played"] = [
                {"appid": gm["appid"], "name": gm.get("name", ""),
                 "playtime_2weeks": gm.get("playtime_2weeks", 0),
                 "playtime_forever": gm.get("playtime_forever", 0)}
                for gm in recent]
        except Exception:
            entry["recently_played"] = []
        result.append(entry)

    def _sort_key(f):
        if f.get("current_game"):
            return 0
        return 1 if f.get("personastate", 0) > 0 else 2

    result.sort(key=_sort_key)
    return {"friends": result}


@router.post("/add")
def add_friend(body: Optional[dict] = Body(default=None),
               username: str = Depends(require_login)):
    """Send a friend request (placeholder)."""
    target = (body or {}).get("username", "")
    if not target:
        return _err(400, "Username required")
    if target == username:
        return _err(400, "Cannot friend yourself")
    return {"success": True, "message": f"Friend request sent to {target}"}


@router.delete("/{other_username}")
def remove_friend(other_username: str, username: str = Depends(require_login)):
    """Remove a friend (placeholder)."""
    return {"success": True, "message": f"Removed {other_username}"}


@router.delete("/follow/{other_username}")
def unfollow_user(other_username: str, username: str = Depends(require_login)):
    """Unfollow a user (placeholder)."""
    return {"success": True, "message": f"Unfollowed {other_username}"}
