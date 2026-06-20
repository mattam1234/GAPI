"""Search domain (migrated to FastAPI).

Advanced game search, saved searches, trending searches, and per-user search
history. All handlers reuse the legacy ``_search_service`` singleton and the
``database`` helpers via ``gapi_gui`` at CALL TIME so reassignments are picked
up.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (search is not in the cacheable-prefix allowlist); that header is set
explicitly here to preserve behaviour.

Routes:
  POST   /api/search/advanced
  POST   /api/search/save
  GET    /api/search/saved
  DELETE /api/search/saved/{search_id}
  GET    /api/search/trending
  GET    /api/search/history
  DELETE /api/search/history
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/search", tags=["search"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


@router.post("/advanced")
def api_search_advanced(body: Optional[dict] = Body(default=None),
                        username: str = Depends(require_login)):
    """Advanced game search with filters."""
    g = gapi_gui
    if not g._search_service:
        return _err(503, "Search service not available")

    db = next(g.database.get_db())
    try:
        data = body or {}
        query = data.get("query", "")
        filters = data.get("filters", {})

        results = g._search_service.search_games(db, query, filters, username)
        count = len(results)

        # Record in search history (best-effort, never blocks the response)
        if username and query:
            try:
                g.database.record_search(db, username, query, filters,
                                         result_count=count)
            except Exception:
                pass

        return _ok({
            "query": query,
            "results": results[:50],  # Limit to 50 results
            "count": count,
        })
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/save")
def api_save_search(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Save a search for future use."""
    g = gapi_gui
    if not g._search_service:
        return _err(503, "Search service not available")

    db = next(g.database.get_db())
    try:
        data = body or {}
        search_name = data.get("name", "Unnamed Search").strip()
        query = data.get("query", "").strip()
        filters = data.get("filters", {})

        if not search_name or not query:
            return _err(400, "Name and query required")

        ok = g._search_service.save_search(db, username, search_name, query, filters)
        return _ok({"success": ok})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.get("/saved")
def api_get_saved_searches(username: str = Depends(require_login)):
    """Get user's saved searches."""
    g = gapi_gui
    if not g._search_service:
        return _err(503, "Search service not available")

    db = next(g.database.get_db())
    try:
        searches = g._search_service.get_saved_searches(db, username)
        return _ok({"searches": searches})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.delete("/saved/{search_id}")
def api_delete_saved_search(search_id: int, username: str = Depends(require_login)):
    """Delete a saved search."""
    g = gapi_gui
    if not g._search_service:
        return _err(503, "Search service not available")

    db = next(g.database.get_db())
    try:
        ok = g._search_service.delete_saved_search(db, search_id)
        return _ok({"success": ok})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.get("/trending")
def api_trending_searches(request: Request, username: str = Depends(require_login)):
    """Get trending searches."""
    g = gapi_gui
    if not g._search_service:
        return _err(503, "Search service not available")

    db = next(g.database.get_db())
    try:
        args = request.query_params
        days = int(args.get("days", 7))
        limit = int(args.get("limit", 10))
        trending = g._search_service.get_trending_searches(db, days, limit)
        return _ok({"trending": trending})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.get("/history")
def api_get_search_history(request: Request, username: str = Depends(require_login)):
    """Return the current user's recent search history (Item 3).

    Query parameters:
      ``limit``  – max results (default 20, max 50)

    Response JSON:
      ``history``  – list of ``{id, query, filters, result_count, searched_at}``
      ``count``    – number of results returned
    """
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"history": [], "count": 0})
    try:
        limit = max(1, min(50, int(request.query_params.get("limit", 20))))
    except (ValueError, TypeError):
        limit = 20
    try:
        db = next(g.database.get_db())
        history = g.database.get_search_history(db, username, limit=limit)
        return _ok({"history": history, "count": len(history)})
    except Exception as e:
        g.gui_logger.error("api_get_search_history error: %s", e)
        return _err(500, str(e))


@router.delete("/history")
def api_clear_search_history(username: str = Depends(require_login)):
    """Clear the current user's search history (Item 3).

    Response JSON:
      ``ok``  – True on success
    """
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"ok": True})
    try:
        db = next(g.database.get_db())
        ok = g.database.clear_search_history(db, username)
        return _ok({"ok": ok})
    except Exception as e:
        g.gui_logger.error("api_clear_search_history error: %s", e)
        return _err(500, str(e))
