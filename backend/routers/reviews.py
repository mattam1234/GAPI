"""Reviews domain — personal game reviews (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/reviews
  * GET    /api/reviews/{game_id}
  * POST   /api/reviews/{game_id}   (also PUT — upsert)
  * PUT    /api/reviews/{game_id}
  * DELETE /api/reviews/{game_id}

Reviews are stored per-user via the picker's ``review_service``; the router
reuses the legacy ``ensure_picker_initialized`` + ``picker_lock`` machinery so
storage, locking, and behavior are identical during the migration.
"""
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.reviews import DeleteResult, Review, ReviewIn, ReviewSaved

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _picker(username: str):
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Picker not initialized",
        )
    return p


@router.get("", response_model=Dict[str, Review])
def list_reviews(username: str = Depends(require_login)):
    """Return all of the user's reviews, keyed by game id."""
    p = _picker(username)
    with gapi_gui.picker_lock:
        return p.review_service.get_all()


@router.get("/{game_id}", response_model=Review)
def get_review(game_id: str, username: str = Depends(require_login)):
    """Return the review for a specific game (404 if none)."""
    p = _picker(username)
    with gapi_gui.picker_lock:
        review = p.review_service.get(game_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No review found"
        )
    return review


@router.post("/{game_id}", response_model=ReviewSaved)
@router.put("/{game_id}", response_model=ReviewSaved)
def save_review(game_id: str, body: ReviewIn,
                username: str = Depends(require_login)):
    """Add or update a review. Body: {"rating": 1-10, "notes": "..."}.

    Preserves the legacy 400 contract for missing / non-integer / out-of-range
    ratings (rather than FastAPI's default 422).
    """
    if body.rating is None:
        raise HTTPException(status_code=400, detail="rating is required (1-10)")
    try:
        rating = int(body.rating)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rating must be an integer")

    notes = body.notes or ""
    p = _picker(username)
    with gapi_gui.picker_lock:
        ok = p.review_service.add_or_update(game_id, rating, notes)
    if not ok:
        raise HTTPException(
            status_code=400, detail="rating must be between 1 and 10"
        )
    return ReviewSaved(game_id=game_id, rating=rating, notes=notes)


@router.delete("/{game_id}", response_model=DeleteResult)
def delete_review(game_id: str, username: str = Depends(require_login)):
    """Delete a review (404 if none)."""
    p = _picker(username)
    with gapi_gui.picker_lock:
        removed = p.review_service.remove(game_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No review found"
        )
    return DeleteResult()
