"""Duplicate-detection domain (migrated to FastAPI).

Mirrors the legacy Flask route:
  * GET /api/duplicates   (games owned on more than one platform)

Picker-backed; returns an empty list when the library is not loaded.
"""
from fastapi import APIRouter, Depends

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api", tags=["duplicates"])


@router.get("/duplicates")
def get_duplicates(username: str = Depends(require_login)):
    """Return games that appear on more than one platform."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p or not p.games:
        return {"duplicates": []}
    with gapi_gui.picker_lock:
        raw = p.find_duplicates()
    result = []
    for group in raw:
        slim = [
            {
                "app_id": g.get("appid"),
                "game_id": g.get("game_id"),
                "name": g.get("name", ""),
                "platform": g.get("platform", "steam"),
                "playtime_hours": round(g.get("playtime_forever", 0) / 60, 1),
            }
            for g in group["games"]
        ]
        result.append({
            "name": group["name"],
            "platforms": group["platforms"],
            "games": slim,
        })
    result.sort(key=lambda g: g["name"].lower())
    return {"duplicates": result}
