"""Library-comparison domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET  /api/library                    (cached library, search filter)
  * POST /api/library/sync               (manual sync trigger)
  * GET  /api/library/sync/settings      (admin)
  * POST /api/library/sync/settings      (admin)
  * GET  /api/library/sync/status        (per-user sync status)
  * GET  /api/library/compare/{username}

DB-backed: reuses the legacy ``_library_service`` (or the ``database`` cache
helpers) to load each user's cached library, then computes shared/exclusive
sets. 503 when the DB is unavailable.
"""
import threading
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login
from backend.schemas.library import LibraryComparison

router = APIRouter(prefix="/api/library", tags=["library"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


def _demo_games():
    return [{
        "app_id": g.get("appid"),
        "game_id": f"steam:{g.get('appid')}" if g.get("appid") else "",
        "name": g.get("name", "Unknown"),
        "playtime_hours": round(g.get("playtime_forever", 0) / 60, 1),
        "is_favorite": False,
        "platform": "steam",
        "genres": g.get("genres", []) if isinstance(g.get("genres", []), list) else [],
    } for g in gapi_gui.DEMO_GAMES]


@router.get("")
def api_library(request: Request, current: str = Depends(require_login)):
    """Get all games in library from database cache."""
    g = gapi_gui
    username = current

    if not g.ensure_db_available():
        # Fallback to demo games if DB not available
        return {"games": _demo_games()}

    try:
        db = g.database.SessionLocal()
        try:
            # Get cached library
            if g._library_service:
                cached_games = g._library_service.get_cached(db, username)
            else:
                cached_games = g.database.get_cached_library(db, username)

            # If cache is empty, trigger background sync and return early
            if not cached_games:
                def background_sync():
                    success, msg = g.sync_library_to_db(username, force=True)
                    g.gui_logger.info(f"Background library sync for {username}: {msg}")
                threading.Thread(target=background_sync, daemon=True).start()
                return {
                    "games": [],
                    "message": "Library is being loaded from Steam. Please refresh in a few seconds.",
                }

            # Check if cache is old (>6 hours) and trigger background refresh
            if g._library_service:
                cache_age = g._library_service.get_cache_age(db, username)
            else:
                cache_age = g.database.get_library_cache_age(db, username)
            if cache_age and cache_age > 21600:  # 6 hours
                def background_sync():
                    success, msg = g.sync_library_to_db(username, force=False)
                    g.gui_logger.info(f"Background library refresh for {username}: {msg}")
                threading.Thread(target=background_sync, daemon=True).start()

            search = request.query_params.get("search", "").lower()

            # Get user's favorites from database
            if g._db_favorites_service:
                favorite_ids = set(str(fav) for fav in g._db_favorites_service.get_all(db, username))
            else:
                favorite_ids = set(str(fav) for fav in g.database.get_user_favorites(db, username))

            # Filter and format games
            games = []
            for game in cached_games:
                name = game.get("name", "Unknown")
                if search and search not in name.lower():
                    continue

                app_id = game.get("app_id")
                safe_app_token = str(app_id).strip() if app_id is not None else ""
                try:
                    app_id_int = int(app_id) if app_id else None
                except (ValueError, TypeError):
                    app_id_int = None

                games.append({
                    "app_id": app_id_int,
                    "game_id": game.get("game_id") or (f"{str(game.get('platform') or 'steam').strip().lower()}:{safe_app_token}" if safe_app_token else ""),
                    "name": name,
                    "playtime_hours": round(game.get("playtime_hours", 0), 1),
                    "is_favorite": str(app_id) in favorite_ids if app_id else False,
                    "platform": game.get("platform", "steam"),
                    "last_played": game.get("last_played").isoformat() if game.get("last_played") else None,
                    "genres": game.get("genres", []) if isinstance(game.get("genres", []), list) else [],
                    "tags": game.get("tags", []) if isinstance(game.get("tags", []), list) else [],
                })
        finally:
            db.close()

        return {
            "games": games,
            "cache_age_minutes": int(cache_age / 60) if cache_age else 0,
        }

    except Exception as e:
        g.gui_logger.exception(f"Error loading library from database: {e}")
        # Fallback to demo games on error
        return {"games": _demo_games()}


@router.post("/sync")
def api_sync_library(current: str = Depends(require_login)):
    """Manually trigger library sync from Steam API to database."""
    g = gapi_gui
    username = current
    try:
        success, message = g.sync_scheduler.trigger_sync(username)
        if success:
            return {"message": message}
        return _err(400, message)
    except Exception as e:
        g.gui_logger.exception(f"Error in manual sync: {e}")
        return _err(500, str(e))


@router.get("/sync/settings")
def api_get_sync_settings(_admin: str = Depends(require_admin_um)):
    """Get library sync settings (admin only)."""
    g = gapi_gui
    return {
        "sync_interval_hours": g.sync_scheduler.get_interval(),
        "last_sync_times": {
            username: time.isoformat()
            for username, time in g.sync_scheduler.last_sync_times.items()
        },
    }


@router.post("/sync/settings")
def api_update_sync_settings(body: Optional[dict] = Body(default=None),
                             _admin: str = Depends(require_admin_um)):
    """Update library sync interval (admin only)."""
    g = gapi_gui
    data = body or {}
    interval = data.get("sync_interval_hours")

    if interval is None:
        return _err(400, "sync_interval_hours is required")

    try:
        interval_float = float(interval)
        if interval_float < 1 or interval_float > 168:
            return _err(400, "Interval must be between 1 and 168 hours")

        g.sync_scheduler.set_interval(interval_float)

        return {
            "message": "Sync interval updated successfully",
            "sync_interval_hours": g.sync_scheduler.get_interval(),
        }
    except ValueError:
        return _err(400, "Invalid interval value")


@router.get("/sync/status")
def api_sync_status(current: str = Depends(require_login)):
    """Get sync status for current user."""
    g = gapi_gui
    username = current

    if not g.ensure_db_available():
        return _err(503, "Database not available")

    try:
        db = g.database.SessionLocal()
        try:
            if g._library_service:
                cache_age = g._library_service.get_cache_age(db, username)
                cached_games = g._library_service.get_cached(db, username)
            else:
                cache_age = g.database.get_library_cache_age(db, username)
                cached_games = g.database.get_cached_library(db, username)
        finally:
            db.close()

        last_sync = g.sync_scheduler.last_sync_times.get(username)

        return {
            "last_sync": last_sync.isoformat() if last_sync else None,
            "cache_age_hours": round(cache_age / 3600, 2) if cache_age else None,
            "sync_interval_hours": g.sync_scheduler.get_interval(),
            "games_cached": len(cached_games),
            "should_sync": g.sync_scheduler.should_sync(username),
            "is_syncing": username in g.sync_scheduler.in_progress,
        }
    except Exception as e:
        g.gui_logger.exception(f"Error getting sync status: {e}")
        return _err(500, str(e))


@router.get("/compare/{other_username}", response_model=LibraryComparison)
def compare_libraries(other_username: str,
                      current: str = Depends(require_login)):
    """Compare the current user's library with another user's."""
    if not gapi_gui.ensure_db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        db = gapi_gui.database.SessionLocal()
        try:
            if gapi_gui._library_service:
                your_raw = gapi_gui._library_service.get_cached(db, current)
                their_raw = gapi_gui._library_service.get_cached(db, other_username)
            else:
                your_raw = gapi_gui.database.get_cached_library(db, current)
                their_raw = gapi_gui.database.get_cached_library(db, other_username)
        finally:
            db.close()

        def _key(g):
            return g.get("app_id") or g.get("name", "")

        your_map = {_key(g): g.get("name", "Unknown") for g in your_raw if _key(g)}
        their_map = {_key(g): g.get("name", "Unknown") for g in their_raw if _key(g)}

        shared_keys = set(your_map) & set(their_map)
        shared_games = sorted(your_map[k] for k in shared_keys)
        your_only = sorted(your_map[k] for k in set(your_map) - shared_keys)
        their_only = sorted(their_map[k] for k in set(their_map) - shared_keys)

        return LibraryComparison(
            your_games=sorted(your_map.values()),
            their_games=sorted(their_map.values()),
            shared_games=shared_games,
            your_only=your_only,
            their_only=their_only,
            your_count=len(your_map),
            their_count=len(their_map),
            shared_count=len(shared_games),
        )
    except Exception as e:
        gapi_gui.gui_logger.error(
            "Error comparing libraries for %s vs %s: %s",
            current, other_username, e)
        raise HTTPException(status_code=500, detail=str(e))
