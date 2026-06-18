"""Game-details domain (migrated to FastAPI).

Mirrors the legacy Flask route:
  * GET /api/game/{app_id}/details   (detailed info with smart caching)

DB-backed with a fresh/stale cache and a live Steam fallback. Reuses the legacy
``_library_service`` / ``database`` cache helpers and the per-user picker's Steam
client. 503 when the DB is down.
"""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import gapi
import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api", tags=["game"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.get("/game/{app_id:int}/details")
def game_details(app_id: int, username: str = Depends(require_login)):
    """Get detailed game info with smart caching (cache -> Steam API -> stale)."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, "Database not available")

    db = None
    try:
        db = g.database.SessionLocal()

        platform = "steam"
        try:
            if g._library_service:
                platform = g._library_service.get_game_platform(db, username, app_id)
            else:
                user = g.database.get_user_by_username(db, username)
                if user:
                    lib_entry = db.query(g.database.GameLibraryCache).filter(
                        g.database.GameLibraryCache.user_id == user.id,
                        g.database.GameLibraryCache.app_id == str(app_id)).first()
                    if lib_entry:
                        platform = lib_entry.platform or "steam"
        except Exception as e:
            g.gui_logger.debug("Could not determine platform from library: %s", e)

        if g._library_service:
            cached_details = g._library_service.get_game_details(
                db, app_id, platform, max_age_hours=1)
        else:
            cached_details = g.database.get_game_details_cache(
                db, app_id, platform, max_age_hours=1)
        if cached_details:
            return {**cached_details, "source": "cache",
                    "app_id": app_id, "platform": platform}

        api_details = None
        p = g.ensure_picker_initialized(username)
        if p:
            try:
                if p.steam_client and isinstance(p.steam_client, gapi.SteamAPIClient):
                    api_details = p.steam_client.get_game_details(app_id)
            except Exception as e:
                g.gui_logger.debug("Could not fetch from Steam API: %s", e)

        if api_details:
            response = {"app_id": app_id, "platform": platform,
                        "source": "api", "steam_integration": True}
            if "header_image" in api_details:
                response["header_image"] = api_details["header_image"]
            if "capsule_image" in api_details:
                response["capsule_image"] = api_details["capsule_image"]
            if "short_description" in api_details:
                response["description"] = api_details["short_description"]
            if "genres" in api_details:
                response["genres"] = [x["description"] for x in api_details["genres"]]
            if "release_date" in api_details:
                response["release_date"] = api_details["release_date"].get("date", "Unknown")
            if "metacritic" in api_details:
                response["metacritic_score"] = api_details["metacritic"].get("score")
            try:
                if p and p.steam_client and isinstance(p.steam_client, gapi.SteamAPIClient):
                    protondb = p.steam_client.get_protondb_rating(app_id)
                    if protondb:
                        response["protondb"] = protondb
            except Exception:
                pass
            if g._library_service:
                g._library_service.update_game_details(db, app_id, platform, response)
            else:
                g.database.update_game_details_cache(db, app_id, platform, response)
            return response

        try:
            if g._library_service:
                stale_details = g._library_service.get_stale_game_details(
                    db, app_id, platform)
            else:
                last_cache = db.query(g.database.GameDetailsCache).filter(
                    g.database.GameDetailsCache.app_id == str(app_id),
                    g.database.GameDetailsCache.platform == platform).first()
                stale_details = json.loads(last_cache.details_json) if last_cache else None
            if stale_details:
                return {**stale_details, "source": "cache_stale",
                        "app_id": app_id, "platform": platform}
        except Exception as e:
            g.gui_logger.debug("Could not get last cache: %s", e)

        return {"app_id": app_id, "platform": platform,
                "steam_integration": False, "source": "none",
                "message": "Steam integration not configured for this user"}
    except Exception as e:
        g.gui_logger.exception("Error getting game details: %s", e)
        return _err(500, f"Failed to load game details: {str(e)}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
