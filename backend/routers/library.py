"""Library-comparison domain (migrated to FastAPI).

Mirrors the legacy Flask route:
  * GET /api/library/compare/{username}

DB-backed: reuses the legacy ``_library_service`` (or the ``database`` cache
helpers) to load each user's cached library, then computes shared/exclusive
sets. 503 when the DB is unavailable.
"""
from fastapi import APIRouter, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.library import LibraryComparison

router = APIRouter(prefix="/api/library", tags=["library"])


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
