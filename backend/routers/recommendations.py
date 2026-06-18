"""Recommendations domain (migrated to FastAPI, chunk 1).

Chunk 1 — the base personalised recommendations route:
  * GET /api/recommendations

Picker-backed (``GamePicker.get_recommendations``). The ML / smart / variant /
ai sub-routes are migrated in follow-up chunks and remain in Flask for now.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.get("")
def get_recommendations(request: Request, username: str = Depends(require_login)):
    """Return personalised game recommendations for the current user."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        return _err(400, "Not initialized. Please log in and ensure your "
                    "Steam ID is set.")

    args = request.query_params
    try:
        count = min(int(args.get("count", 10)), 50)
    except (ValueError, TypeError):
        count = 10
    platforms_param = str(args.get("platforms", "")).strip()
    platforms = ([x.strip() for x in platforms_param.split(",") if x.strip()]
                 if platforms_param else None)
    max_budget = None
    mbp = str(args.get("max_budget", "")).strip()
    if mbp:
        try:
            max_budget = float(mbp)
        except (ValueError, TypeError):
            max_budget = None
    include_new = str(args.get("include_new", "")).lower() in ("true", "1", "yes")
    refresh_seed = str(args.get("refresh_seed", "")).strip() or None

    try:
        with gapi_gui.picker_lock:
            recs = p.get_recommendations(
                count=count, platforms=platforms, max_budget=max_budget,
                include_new_releases=include_new, refresh_seed=refresh_seed)
    except TypeError:
        # Backward-compat: older pickers don't accept the new kwargs.
        try:
            with gapi_gui.picker_lock:
                recs = p.get_recommendations(count=count)
        except Exception as e2:
            gapi_gui.gui_logger.error("Error calling get_recommendations: %s", e2)
            return _err(500, f"Failed to generate recommendations: {str(e2)}")
    except Exception as e:
        gapi_gui.gui_logger.error("Error generating recommendations: %s", e)
        return _err(500, f"Failed to generate recommendations: {str(e)}")

    return {"recommendations": recs}


@router.get("/variant")
def recommendation_variant(request: Request, username: str = Depends(require_login)):
    """Return the A/B experiment variant assigned to the current user."""
    experiment_name = str(request.query_params.get("experiment", "")).strip()
    if not experiment_name:
        return _err(400, "'experiment' query parameter is required")
    if not gapi_gui.DB_AVAILABLE:
        return {"experiment": experiment_name, "variant": None}
    try:
        db = next(gapi_gui.database.get_db())
        variant = gapi_gui.database.get_or_assign_variant(db, username, experiment_name)
        return {"experiment": experiment_name, "variant": variant}
    except Exception as e:
        gapi_gui.gui_logger.error("recommendation_variant error: %s", e)
        return _err(500, str(e))


@router.get("/ai")
def ai_recommendations(username: str = Depends(require_login)):
    """AI recommendations from the ai_recommendations table (raw SQL).

    Note: like the legacy handler this reads via ``db_service`` (undefined in
    production), so it falls back to the default recommendation set.
    """
    try:
        db = gapi_gui.db_service.get_db()
        user = gapi_gui.db_service.get_current_user(username)
        rec_query = ("SELECT game_name, match_score, reason FROM ai_recommendations "
                     "WHERE user_id = ? ORDER BY match_score DESC LIMIT 6")
        rows = db.execute(rec_query, (user.id,)).fetchall()
        recommendations = [
            {"id": str(idx), "name": game, "match_score": score, "reason": reason}
            for idx, (game, score, reason) in enumerate(rows, 1)]
        return {"recommendations": recommendations}
    except Exception as e:
        gapi_gui.gui_logger.error("Error getting AI recommendations: %s", e)
        return {"recommendations": [
            {"id": "1", "name": "Baldurs Gate 3", "match_score": 94,
             "reason": "Similar to games you love"},
            {"id": "2", "name": "Hollow Knight", "match_score": 87,
             "reason": "Challenging & story-driven"},
        ]}


@router.get("/smart")
def smart_recommendations(request: Request, username: str = Depends(require_login)):
    """AI-enhanced multi-factor recommendations (uses the global picker)."""
    from app.services.recommendation_service import SmartRecommendationEngine

    picker = gapi_gui.picker
    if not picker:
        return _err(400, "Not initialized. Please log in and ensure your "
                    "Steam ID is set.")
    args = request.query_params
    try:
        count = max(1, min(int(args.get("count", 10)), 50))
    except (ValueError, TypeError):
        count = 10
    platforms_param = str(args.get("platforms", "")).strip()
    platforms = ([x.strip() for x in platforms_param.split(",") if x.strip()]
                 if platforms_param else None)
    max_budget = None
    mbp = str(args.get("max_budget", "")).strip()
    if mbp:
        try:
            max_budget = float(mbp)
        except (ValueError, TypeError):
            max_budget = None
    include_new = str(args.get("include_new", "")).lower() in ("true", "1", "yes")

    with gapi_gui.picker_lock:
        games = list(picker.games) if picker.games else []
        history = list(picker.history) if hasattr(picker, "history") else []
        cache = {}
        steam_client = picker.clients.get("steam") if hasattr(picker, "clients") else None
        if steam_client and hasattr(steam_client, "details_cache"):
            cache = dict(steam_client.details_cache)
        well_mins = getattr(picker, "WELL_PLAYED_THRESHOLD_MINUTES", 600)
        barely_mins = getattr(picker, "BARELY_PLAYED_THRESHOLD_MINUTES", 120)
        budget_svc = getattr(picker, "budget_service", None)

    engine = SmartRecommendationEngine(
        games=games, details_cache=cache, history=history,
        well_played_mins=well_mins, barely_played_mins=barely_mins,
        budget_service=budget_svc)
    recs = engine.recommend(count=count, platforms=platforms,
                            max_budget=max_budget, include_new_releases=include_new)
    return {"recommendations": recs, "engine": "smart"}


@router.get("/ml")
def ml_recommendations(request: Request, username: str = Depends(require_login)):
    """ML-powered recommendations (item-CF / ALS matrix factorization / hybrid).

    Uses the global picker (server-wide library) like the legacy route.
    """
    from app.services.ml_recommendation_service import MLRecommendationEngine

    picker = gapi_gui.picker
    if not picker:
        return _err(400, "Not initialized. Please log in and ensure your "
                    "Steam ID is set.")
    args = request.query_params
    try:
        count = max(1, min(int(args.get("count", 10)), 50))
    except (ValueError, TypeError):
        count = 10
    method = args.get("method", "cf")
    if method not in ("cf", "mf", "hybrid"):
        method = "cf"

    with gapi_gui.picker_lock:
        games = list(picker.games) if picker.games else []
        history = list(picker.history) if hasattr(picker, "history") else []
        cache = {}
        steam_client = picker.clients.get("steam") if hasattr(picker, "clients") else None
        if steam_client and hasattr(steam_client, "details_cache"):
            cache = dict(steam_client.details_cache)
        well_mins = getattr(picker, "WELL_PLAYED_THRESHOLD_MINUTES", 600)
        barely_mins = getattr(picker, "BARELY_PLAYED_THRESHOLD_MINUTES", 120)

    engine = MLRecommendationEngine(
        games=games, details_cache=cache, history=history,
        well_played_mins=well_mins, barely_played_mins=barely_mins)
    recs = engine.recommend(count=count, method=method)
    return {"recommendations": recs, "engine": "ml", "method": method}
