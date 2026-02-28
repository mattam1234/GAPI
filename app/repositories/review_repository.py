"""Repository for personal game reviews ({game_id: {rating, notes, updated_at}})."""
from typing import Dict, Optional
from .base import BaseRepository


class ReviewRepository(BaseRepository):
    """Persists per-game review data to a JSON file.

    Schema::

        {
            "<game_id>": {
                "rating":     <int 1-10>,
                "notes":      <str>,
                "updated_at": <ISO-8601 str>
            }
        }
    """

    def __init__(self, file_path: str = '.gapi_reviews.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, Dict] = self._load({})

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def find(self, game_id: str) -> Optional[Dict]:
        """Return the review dict for *game_id*, or ``None``."""
        return self.data.get(str(game_id))

    def upsert(self, game_id: str, review: Dict) -> None:
        """Insert or replace the review for *game_id*, then persist."""
        self.data[str(game_id)] = review
        self.save()

    def delete(self, game_id: str) -> bool:
        """Remove the review for *game_id*.  Returns ``True`` if it existed."""
        key = str(game_id)
        if key not in self.data:
            return False
        del self.data[key]
        self.save()
        return True

    def save(self) -> None:
        """Persist the current in-memory data to disk."""
        self._save(self.data)
