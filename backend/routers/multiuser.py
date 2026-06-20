"""Multi-user picking domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * POST /api/multiuser/pick    (pick a common game for several users + filters)
  * GET  /api/multiuser/common  (common games for selected users)
  * GET  /api/multiuser/stats   (multi-user library statistics)

Reuses the legacy multi_picker machinery and records the pick to the audit log
for analytics.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/multiuser", tags=["multiuser"])


def _users_param(request: Request):
    user_names = request.query_params.get("users", "").split(",")
    return [u.strip() for u in user_names if u.strip()]


def _int_or(value, default=None):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _csv(value):
    text = str(value or "").strip()
    return [t.strip() for t in text.split(",")] if text else None


@router.post("/pick")
def multiuser_pick(body: Optional[dict] = Body(default=None),
                   username: str = Depends(require_login)):
    """Pick a common game for multiple users with optional filters."""
    gapi_gui._ensure_multi_picker()
    mp = gapi_gui.multi_picker
    if not mp:
        raise HTTPException(status_code=400,
                            detail="Multi-user picker not initialized")

    data = body or {}
    user_names = data.get("users", [])
    min_playtime = _int_or(data.get("min_playtime"), 0) if data.get("min_playtime") else 0
    platform_filter = str(data.get("platform_filter", "")).strip().lower() or None
    device_filter = str(data.get("device_filter", "")).strip().lower() or None

    with gapi_gui.multi_picker_lock:
        game = mp.pick_common_game(
            user_names if user_names else None,
            coop_only=data.get("coop_only", False),
            max_players=_int_or(data.get("max_players")),
            min_playtime=min_playtime,
            max_playtime=_int_or(data.get("max_playtime")),
            min_metacritic=_int_or(data.get("min_metacritic")),
            min_release_year=_int_or(data.get("min_release_year")),
            max_release_year=_int_or(data.get("max_release_year")),
            genres=_csv(data.get("genres")),
            exclude_genres=_csv(data.get("exclude_genres")),
            tags=_csv(data.get("tags")),
            exclude_game_ids=_csv(data.get("exclude_game_ids")),
            min_avg_playtime=_int_or(data.get("min_avg_playtime")),
            platforms=[platform_filter] if platform_filter else None,
            device_types=[device_filter] if device_filter else None,
        )
        if not game:
            raise HTTPException(
                status_code=404, detail="No common games found matching filters")

        app_id = game.get("appid")
        game_id = game.get("game_id") or (f"steam:{app_id}" if app_id else None)
        gapi_gui._audit(
            "pick", resource_type="game",
            resource_id=str(game_id) if game_id else (str(app_id) if app_id else None),
            description=game.get("name", "Unknown"),
        )
        return {
            "app_id": app_id,
            "name": game.get("name", "Unknown"),
            "playtime_hours": round(game.get("playtime_forever", 0) / 60, 1),
            "owners": game.get("owners", []),
            "is_coop": game.get("is_coop", False),
            "is_multiplayer": game.get("is_multiplayer", False),
            "steam_url": f"https://store.steampowered.com/app/{app_id}/",
            "steamdb_url": f"https://steamdb.info/app/{app_id}/",
        }


@router.get("/common")
def multiuser_common(request: Request, _user: str = Depends(require_login)):
    """Get common games for selected users."""
    gapi_gui._ensure_multi_picker()
    mp = gapi_gui.multi_picker
    if not mp:
        raise HTTPException(status_code=400,
                            detail="Multi-user picker not initialized")

    user_names = _users_param(request)

    with gapi_gui.multi_picker_lock:
        common_games = mp.find_common_games(user_names if user_names else None)

        games_data = []
        for game in common_games[:50]:  # Limit to 50 games
            games_data.append({
                "app_id": game.get("appid"),
                "name": game.get("name", "Unknown"),
                "playtime_hours": round(game.get("playtime_forever", 0) / 60, 1),
                "owners": game.get("owners", []),
            })

        return {
            "total_common": len(common_games),
            "games": games_data,
        }


@router.get("/stats")
def multiuser_stats(request: Request, _user: str = Depends(require_login)):
    """Get multi-user library statistics."""
    gapi_gui._ensure_multi_picker()
    mp = gapi_gui.multi_picker
    if not mp:
        raise HTTPException(status_code=400,
                            detail="Multi-user picker not initialized")

    user_names = _users_param(request)

    with gapi_gui.multi_picker_lock:
        return mp.get_library_stats(user_names if user_names else None)
