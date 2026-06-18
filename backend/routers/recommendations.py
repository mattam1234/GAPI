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
