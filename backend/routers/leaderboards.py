"""Leaderboards domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET /api/leaderboards            (category rankings)
  * GET /api/leaderboards/seasonal   (period rankings + seasonal titles)
  * GET /api/leaderboard             (service-backed rankings by metric)

The two plural routes compute their rankings through the SQLAlchemy layer
(``database.get_category_leaderboard`` / ``get_seasonal_leaderboard``), which
queries the legacy ``picks`` / ``votes`` / ``live_sessions`` tables with
parameterised SQL and degrades to an empty leaderboard when they are absent.
(The legacy handlers read these through an undefined module-global
``db_service`` and always 500'd.) The singular route reuses
``_leaderboard_service`` (with the ``database.get_leaderboard`` fallback).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api", tags=["leaderboards"])


@router.get("/leaderboards")
def get_leaderboards(request: Request, username: str = Depends(require_login)):
    """Category leaderboard (picks / acceptance / votes / accuracy)."""
    args = request.query_params
    category = str(args.get("category", "picks")).lower()
    try:
        limit = min(int(args.get("limit", 10)), 100)
    except (ValueError, TypeError):
        limit = 10
    try:
        db = gapi_gui.database.SessionLocal()
        try:
            leaderboard = gapi_gui.database.get_category_leaderboard(
                db, category=category, limit=limit)
        finally:
            db.close()
        return {"leaderboard": leaderboard}
    except Exception as e:
        gapi_gui.gui_logger.error("Error getting leaderboards: %s", e)
        return JSONResponse(status_code=500,
                            content={"error": f"Failed to get leaderboards: {str(e)}"})


@router.get("/leaderboards/seasonal")
def seasonal_leaderboards(request: Request, username: str = Depends(require_login)):
    """Seasonal leaderboard (weekly / monthly / alltime) with seasonal titles."""
    period = str(request.query_params.get("period", "alltime")).lower()
    try:
        db = gapi_gui.database.SessionLocal()
        try:
            result = gapi_gui.database.get_seasonal_leaderboard(db, period=period)
        finally:
            db.close()
        return result
    except Exception as e:
        gapi_gui.gui_logger.error("Error getting seasonal leaderboards: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/leaderboard")
def leaderboard(request: Request, username: str = Depends(require_login)):
    """Ranked leaderboard of users by metric (service-backed)."""
    args = request.query_params
    metric = str(args.get("metric", "playtime"))
    try:
        limit = int(args.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20
    db = next(gapi_gui.database.get_db())
    try:
        if gapi_gui._leaderboard_service:
            rows = gapi_gui._leaderboard_service.get_rankings(db, metric=metric, limit=limit)
        else:
            rows = gapi_gui.database.get_leaderboard(db, metric=metric, limit=limit)
    finally:
        if db:
            db.close()
    return {"metric": metric, "entries": rows}
