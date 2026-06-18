"""Achievement-hunt domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET /api/achievements                  (per-game achievements for the user)
  * POST /api/achievement-hunt             (start a hunt; 201)
  * PUT  /api/achievement-hunt/{hunt_id}   (update progress / status)

DB-backed: reuses the legacy ``_achievement_service`` singleton (with the same
direct-``database`` fallback) and a DB session. As in the legacy app, GET
degrades to an empty list when the DB is down while the write routes return 503.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

import gapi
import gapi_gui
from backend.dependencies import require_login
from backend.schemas.achievements import (
    HuntStartIn, HuntUpdateIn, PlatformSyncIn, SyncIn,
)

router = APIRouter(prefix="/api", tags=["achievements"])


@router.get("/achievements/stats")
def achievement_stats(username: str = Depends(require_login)):
    """Return achievement statistics for the current user."""
    if not gapi_gui.ensure_db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    db = next(gapi_gui.database.get_db())
    try:
        stats = gapi_gui.database.get_achievement_stats(db, username)
        by_platform = gapi_gui.database.get_achievement_stats_by_platform(db, username)
    finally:
        if db:
            db.close()
    if not stats:
        return {
            "total_tracked": 0, "total_unlocked": 0, "completion_percent": 0.0,
            "rarest_achievement": None, "games": [], "by_platform": [],
        }
    stats["by_platform"] = by_platform
    return stats


@router.get("/achievements/{app_id:int}")
def steam_achievements(app_id: int, username: str = Depends(require_login)):
    """Get achievement completion stats for a Steam game (live Steam API)."""
    picker = gapi_gui.ensure_picker_initialized(username)
    if not picker:
        raise HTTPException(status_code=400, detail="Not initialized")
    if not picker.steam_client:
        raise HTTPException(status_code=503, detail="Steam client not available")
    steam_id = picker.config.get("steam_id", "")
    if gapi.is_placeholder_value(steam_id):
        raise HTTPException(status_code=503, detail="Steam ID not configured")
    if not isinstance(picker.steam_client, gapi.SteamAPIClient):
        raise HTTPException(status_code=400, detail="Steam client not initialized")
    with gapi_gui.picker_lock:
        stats = picker.steam_client.get_player_achievements(steam_id, app_id)
    if stats is None:
        raise HTTPException(
            status_code=404, detail="Achievements unavailable for this game")
    return {"app_id": app_id, **stats}


@router.get("/achievements")
def get_achievements(username: str = Depends(require_login)):
    """Return the current user's achievements, grouped by game."""
    if not gapi_gui.DB_AVAILABLE:
        return {"achievements": []}
    db = gapi_gui.database.SessionLocal()
    try:
        svc = gapi_gui._achievement_service
        if svc:
            achievements = svc.get_all_by_user(db, username)
        else:
            user = gapi_gui.database.get_user_by_username(db, username)
            if not user:
                return {"achievements": []}
            by_game = {}
            for a in user.achievements:
                by_game.setdefault(a.app_id, {
                    "app_id": a.app_id, "game_name": a.game_name, "achievements": []})
                by_game[a.app_id]["achievements"].append({
                    "achievement_id": a.achievement_id,
                    "name": a.achievement_name,
                    "description": a.achievement_description,
                    "unlocked": a.unlocked,
                    "unlock_time": a.unlock_time.isoformat() if a.unlock_time else None,
                    "rarity": a.rarity,
                })
            achievements = list(by_game.values())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()
    return {"achievements": achievements}


@router.post("/achievement-hunt", status_code=201)
def start_hunt(body: HuntStartIn, username: str = Depends(require_login)):
    """Start tracking an achievement-hunting session."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    app_id = body.app_id
    game_name = body.game_name.strip() if isinstance(body.game_name, str) else ""
    difficulty = body.difficulty or "medium"
    target_achievements = body.target_achievements or 0
    if not app_id or not game_name:
        raise HTTPException(status_code=400, detail="app_id and game_name required")
    try:
        app_id = int(app_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="app_id must be an integer")

    db = gapi_gui.database.SessionLocal()
    try:
        svc = gapi_gui._achievement_service
        if svc:
            result = svc.start_hunt(db, username, app_id, game_name,
                                    difficulty=difficulty,
                                    target_achievements=target_achievements)
        else:
            user = gapi_gui.database.get_user_by_username(db, username)
            if not user:
                raise HTTPException(status_code=404, detail="User not found in database")
            hunt = gapi_gui.database.AchievementHunt(
                user_id=user.id, app_id=app_id, game_name=game_name,
                difficulty=difficulty, target_achievements=target_achievements)
            db.add(hunt)
            db.commit()
            result = _hunt_dict(hunt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()
    if not result:
        raise HTTPException(status_code=404, detail="User not found in database")
    return result


@router.put("/achievement-hunt/{hunt_id}")
def update_hunt(hunt_id: str, body: HuntUpdateIn,
                username: str = Depends(require_login)):
    """Update achievement-hunt progress or status."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    db = gapi_gui.database.SessionLocal()
    try:
        svc = gapi_gui._achievement_service
        if svc:
            result = svc.update_hunt(db, hunt_id,
                                     unlocked_achievements=body.unlocked_achievements,
                                     status=body.status)
        else:
            hunt = db.query(gapi_gui.database.AchievementHunt).filter(
                gapi_gui.database.AchievementHunt.id == hunt_id).first()
            if not hunt:
                raise HTTPException(status_code=404, detail="Hunt not found")
            if body.unlocked_achievements is not None:
                hunt.unlocked_achievements = body.unlocked_achievements
                if hunt.target_achievements > 0:
                    hunt.progress_percent = (
                        body.unlocked_achievements / hunt.target_achievements) * 100
            if body.status:
                hunt.status = body.status
                if body.status == "completed":
                    hunt.completed_at = datetime.now(timezone.utc)
            hunt.updated_at = datetime.now(timezone.utc)
            db.commit()
            result = _hunt_dict(hunt, with_completed=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()
    if not result:
        raise HTTPException(status_code=404, detail="Hunt not found")
    return result


def _hunt_dict(hunt, with_completed=False):
    d = {
        "hunt_id": hunt.id, "app_id": hunt.app_id, "game_name": hunt.game_name,
        "difficulty": hunt.difficulty,
        "target_achievements": hunt.target_achievements,
        "unlocked_achievements": hunt.unlocked_achievements,
        "progress_percent": hunt.progress_percent, "status": hunt.status,
        "started_at": hunt.started_at.isoformat(),
    }
    if with_completed:
        d["completed_at"] = hunt.completed_at.isoformat() if hunt.completed_at else None
    return d


# ── Steam achievement sync (Steam API -> DB) ───────────────────────────────

def _cached_library(db, username):
    if gapi_gui._library_service:
        return gapi_gui._library_service.get_cached(db, username)
    return gapi_gui.database.get_cached_library(db, username)


@router.post("/achievements/sync")
def sync_achievements(body: SyncIn, username: str = Depends(require_login)):
    """Sync achievements for one or more games from the Steam API into the DB."""
    if not gapi_gui.ensure_db_available():
        raise HTTPException(status_code=503, detail="Database not available")

    base_config = gapi_gui.load_base_config()
    steam_api_key = base_config.get("steam_api_key", "").strip()
    if not steam_api_key or gapi.is_placeholder_value(steam_api_key):
        raise HTTPException(status_code=400, detail="Steam API key not configured")

    db = next(gapi_gui.database.get_db())
    try:
        user = gapi_gui.database.get_user_by_username(db, username)
        steam_id = user.steam_id if user else None
    finally:
        if db:
            db.close()
    if not steam_id:
        raise HTTPException(
            status_code=400, detail="Steam ID not configured for this account")

    requested_app_ids = body.app_ids
    if not requested_app_ids:
        db2 = next(gapi_gui.database.get_db())
        try:
            cached = _cached_library(db2, username)
        finally:
            if db2:
                db2.close()
        if not cached:
            raise HTTPException(
                status_code=400,
                detail="No games in library cache. Sync your library first.")
        requested_app_ids = [str(g.get("app_id", "")) for g in (cached or [])
                             if g.get("app_id")]

    steam_client = gapi.SteamAPIClient(steam_api_key)
    synced, skipped, errors = [], [], []

    db3 = next(gapi_gui.database.get_db())
    try:
        cached_all = _cached_library(db3, username)
    finally:
        if db3:
            db3.close()
    name_map = {str(g.get("app_id", "")): g.get("name", g.get("app_id", ""))
                for g in (cached_all or [])}

    for app_id in list(requested_app_ids)[:50]:
        app_id = str(app_id).strip()
        if not app_id:
            continue
        game_name = name_map.get(app_id, app_id)
        try:
            player_achievements = steam_client.get_player_achievements_detailed(
                steam_id, app_id)
            if not player_achievements:
                skipped.append(app_id)
                continue
            schema = steam_client.get_schema_for_game(app_id)
            db4 = next(gapi_gui.database.get_db())
            try:
                result = gapi_gui.database.sync_steam_achievements(
                    db4, username, steam_id, app_id, game_name,
                    player_achievements, schema)
            finally:
                if db4:
                    db4.close()
            synced.append({
                "app_id": app_id, "game_name": game_name,
                "added": result["added"], "updated": result["updated"],
                "total": result["total"],
            })
        except Exception as exc:
            gapi_gui.gui_logger.error(
                "Error syncing achievements for app %s: %s", app_id, exc)
            errors.append(app_id)

    return {"synced": synced, "skipped": skipped, "errors": errors}


@router.post("/achievements/sync/platform")
def sync_achievements_platform(body: PlatformSyncIn,
                               username: str = Depends(require_login)):
    """Sync achievements for a specific connected platform."""
    if not gapi_gui.ensure_db_available():
        raise HTTPException(status_code=503, detail="Database not available")

    platform = str(body.platform or "").lower().strip()
    if not platform:
        raise HTTPException(status_code=400, detail="platform is required")
    handlers = gapi_gui._PLATFORM_SYNC_HANDLERS
    if platform not in handlers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform: {platform}. Supported: {list(handlers)}")
    if platform == "steam":
        return {"platform": "steam", "status": "ok",
                "message": "Use /api/achievements/sync for Steam"}

    db = next(gapi_gui.database.get_db())
    try:
        user = gapi_gui.database.get_user_by_username(db, username)
    finally:
        db.close()
    result = handlers[platform](username, user)
    result["platform"] = platform
    return result
