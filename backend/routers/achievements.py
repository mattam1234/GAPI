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

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.achievements import HuntStartIn, HuntUpdateIn

router = APIRouter(prefix="/api", tags=["achievements"])


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
