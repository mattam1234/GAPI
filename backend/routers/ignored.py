"""Ignored-games domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET  /api/ignored-games
  * POST /api/ignored-games   (toggle ignore status)

Unlike the picker-backed domains, this one is DB-backed: it reuses the legacy
``_ignored_games_service`` / ``_user_service`` singletons and a DB session.
Note the asymmetric DB-availability contract is preserved exactly — GET returns
an empty list (200) when the DB is down, while POST returns 503.
"""
from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.ignored import (
    IgnoredGamesList, ToggleIgnoreIn, ToggleResult,
)

router = APIRouter(prefix="/api", tags=["ignored-games"])


@router.get("/ignored-games", response_model=IgnoredGamesList)
def get_ignored_games(username: str = Depends(require_login)):
    """Return the current user's ignored games."""
    if not gapi_gui.DB_AVAILABLE:
        return IgnoredGamesList(ignored_games=[])
    db = gapi_gui.database.SessionLocal()
    try:
        svc = gapi_gui._ignored_games_service
        if svc:
            ignored = svc.get_detailed(db, username)
        else:
            user = gapi_gui.database.get_user_by_username(db, username)
            if not user:
                return IgnoredGamesList(ignored_games=[])
            ignored = [
                {
                    "app_id": ig.app_id,
                    "game_name": ig.game_name,
                    "reason": ig.reason,
                    "created_at": ig.created_at.isoformat() if ig.created_at else None,
                }
                for ig in user.ignored_games
            ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    finally:
        db.close()
    return IgnoredGamesList(ignored_games=ignored)


@router.post("/ignored-games", response_model=ToggleResult)
def toggle_ignored_game(body: ToggleIgnoreIn,
                        username: str = Depends(require_login)):
    """Toggle a game's ignore status for the current user."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    app_id = body.app_id
    game_name = body.game_name.strip() if isinstance(body.game_name, str) else ""
    reason = body.reason.strip() if isinstance(body.reason, str) else ""

    if not app_id:
        raise HTTPException(status_code=400, detail="app_id required")
    try:
        int(app_id)  # validate integer
        app_id = str(app_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="app_id must be an integer")

    db = None
    try:
        db = gapi_gui.database.SessionLocal()
        if gapi_gui._user_service:
            exists = gapi_gui._user_service.user_exists(db, username)
        else:
            exists = gapi_gui.database.user_exists(db, username)
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in database",
            )
        svc = gapi_gui._ignored_games_service
        if svc:
            success = svc.toggle(db, username, app_id,
                                 game_name=game_name, reason=reason)
        else:
            success = gapi_gui.database.toggle_ignore_game(
                db, username, app_id, game_name, reason)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    finally:
        if db:
            db.close()

    if success:
        return ToggleResult(message="Game ignore status toggled")
    raise HTTPException(status_code=400, detail="Failed to toggle ignore")
