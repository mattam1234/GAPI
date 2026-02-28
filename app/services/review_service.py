"""Business logic for personal game reviews."""
import datetime
from typing import Dict, Optional

from ..repositories.review_repository import ReviewRepository


class ReviewService:
    """Validates and applies review operations, delegating persistence to
    :class:`~app.repositories.review_repository.ReviewRepository`.

    Rules
    -----
    * ``rating`` must be an integer in the range **1–10** (inclusive).
    * ``notes`` is free-text and optional (defaults to ``""``).
    * A second call for the same *game_id* replaces the existing review
      (upsert semantics).
    """

    def __init__(self, repository: ReviewRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_or_update(self, game_id: str, rating: int,
                      notes: str = '') -> bool:
        """Add or replace a review.

        Returns:
            ``True`` on success; ``False`` if *rating* is out of range.
        """
        if not 1 <= int(rating) <= 10:
            return False
        self._repo.upsert(str(game_id), {
            'rating': int(rating),
            'notes': notes,
            'updated_at': datetime.datetime.now().isoformat(),
        })
        return True

    def remove(self, game_id: str) -> bool:
        """Delete the review for *game_id*.

        Returns:
            ``True`` if the review existed and was removed; ``False`` otherwise.
        """
        return self._repo.delete(str(game_id))

    def get(self, game_id: str) -> Optional[Dict]:
        """Return the review dict for *game_id*, or ``None``."""
        return self._repo.find(str(game_id))

    def get_all(self) -> Dict[str, Dict]:
        """Return all reviews as a ``{game_id: review_dict}`` mapping."""
        return self._repo.data
