"""Leaderboards domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET /api/leaderboards            (category rankings; raw SQL via db_service)
  * GET /api/leaderboards/seasonal   (period rankings + seasonal titles; raw SQL)
  * GET /api/leaderboard             (service-backed rankings by metric)

The two plural routes execute the legacy hand-written SQL verbatim through the
reused ``gapi_gui.db_service``; the singular route reuses ``_leaderboard_service``
(with the ``database.get_leaderboard`` fallback).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api", tags=["leaderboards"])

_CATEGORY_SQL = {
    "picks": """
        SELECT u.username, COUNT(DISTINCT ps.game_id) as value
        FROM users u
        LEFT JOIN live_sessions ls ON u.username = ls.host
        LEFT JOIN picks ps ON ls.session_id = ps.session_id
        WHERE u.username IS NOT NULL
        GROUP BY u.username ORDER BY value DESC LIMIT ?
    """,
    "acceptance": """
        SELECT u.username,
            CAST(COUNT(CASE WHEN v.user != ps.user THEN 1 END) * 100.0 /
            NULLIF(COUNT(DISTINCT ps.id), 0) AS INTEGER) as value
        FROM users u
        LEFT JOIN picks ps ON u.username = ps.user
        LEFT JOIN votes v ON ps.id = v.pick_id
        WHERE u.username IS NOT NULL
        GROUP BY u.username HAVING COUNT(DISTINCT ps.id) > 0
        ORDER BY value DESC LIMIT ?
    """,
    "votes": """
        SELECT u.username, COUNT(v.id) as value
        FROM users u
        LEFT JOIN votes v ON u.username = v.user
        WHERE u.username IS NOT NULL
        GROUP BY u.username ORDER BY value DESC LIMIT ?
    """,
    "accuracy": """
        SELECT u.username,
            CAST(COUNT(CASE WHEN v.user != ps.user AND ps.id IN (
                SELECT pick_id FROM votes WHERE session_id = ps.session_id
                GROUP BY pick_id ORDER BY COUNT(*) DESC LIMIT 1
            ) THEN 1 END) * 100.0 /
            NULLIF(COUNT(v.id), 0) AS INTEGER) as value
        FROM users u
        LEFT JOIN votes v ON u.username = v.user
        LEFT JOIN picks ps ON v.pick_id = ps.id
        WHERE u.username IS NOT NULL
        GROUP BY u.username HAVING COUNT(v.id) > 0
        ORDER BY value DESC LIMIT ?
    """,
}

_SEASONAL = {
    "weekly": ("""
        SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
               CASE WHEN COUNT(DISTINCT ps.game_id) >= 5 THEN '🔥 Weekly Star' ELSE NULL END as seasonal_title
        FROM users u
        LEFT JOIN live_sessions ls ON u.username = ls.host
        LEFT JOIN picks ps ON ls.session_id = ps.session_id
        WHERE datetime(ls.created_at) >= datetime('now', '-7 days')
        GROUP BY u.username ORDER BY value DESC LIMIT 20
    """, "This Week's Top Performers"),
    "monthly": ("""
        SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
               CASE WHEN COUNT(DISTINCT ps.game_id) >= 15 THEN '⭐ Monthly Champion' ELSE NULL END as seasonal_title
        FROM users u
        LEFT JOIN live_sessions ls ON u.username = ls.host
        LEFT JOIN picks ps ON ls.session_id = ps.session_id
        WHERE datetime(ls.created_at) >= datetime('now', '-30 days')
        GROUP BY u.username ORDER BY value DESC LIMIT 20
    """, "This Month's Top Players"),
    "alltime": ("""
        SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
               CASE WHEN COUNT(DISTINCT ps.game_id) >= 50 THEN '👑 Legendary' ELSE NULL END as seasonal_title
        FROM users u
        LEFT JOIN live_sessions ls ON u.username = ls.host
        LEFT JOIN picks ps ON ls.session_id = ps.session_id
        WHERE u.username IS NOT NULL
        GROUP BY u.username ORDER BY value DESC LIMIT 20
    """, "All-Time Rankings"),
}


@router.get("/leaderboards")
def get_leaderboards(request: Request, username: str = Depends(require_login)):
    """Category leaderboard (picks / acceptance / votes / accuracy)."""
    args = request.query_params
    category = str(args.get("category", "picks")).lower()
    try:
        limit = min(int(args.get("limit", 10)), 100)
    except (ValueError, TypeError):
        limit = 10
    if category not in _CATEGORY_SQL:
        category = "picks"
    try:
        db = gapi_gui.db_service.get_db()
        cursor = db.execute(_CATEGORY_SQL[category], (limit,))
        leaderboard = [{"username": r[0], "value": r[1]} for r in cursor.fetchall()]
        return {"leaderboard": leaderboard}
    except Exception as e:
        gapi_gui.gui_logger.error("Error getting leaderboards: %s", e)
        return JSONResponse(status_code=500,
                            content={"error": f"Failed to get leaderboards: {str(e)}"})


@router.get("/leaderboards/seasonal")
def seasonal_leaderboards(request: Request, username: str = Depends(require_login)):
    """Seasonal leaderboard (weekly / monthly / alltime) with seasonal titles."""
    period = str(request.query_params.get("period", "alltime")).lower()
    if period not in _SEASONAL:
        period = "alltime"
    query, period_info = _SEASONAL[period]
    try:
        db = gapi_gui.db_service.get_db()
        cursor = db.execute(query)
        leaderboard = [{"username": r[0], "value": r[1], "seasonal_title": r[2]}
                       for r in cursor.fetchall()]
        return {"leaderboard": leaderboard, "period_info": period_info}
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
