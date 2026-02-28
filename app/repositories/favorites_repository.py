"""Repository for the favourites list ([game_id, ...])."""
from typing import List
from .base import BaseRepository


class FavoritesRepository(BaseRepository):
    """Persists the favourites list to a JSON file.

    Schema::

        ["<game_id>", ...]

    Old-format entries (plain integers) are normalised to ``"steam:<id>"``
    on load for backward compatibility.
    """

    def __init__(self, file_path: str = '.gapi_favorites.json') -> None:
        super().__init__(file_path)
        raw: List = self._load([])
        # Normalise legacy int entries
        self.data: List[str] = [
            f"steam:{x}" if isinstance(x, int) else x for x in raw
        ]

    def contains(self, game_id: str) -> bool:
        return game_id in self.data

    def add(self, game_id: str) -> bool:
        """Append *game_id* if not already present.  Returns ``True`` if added."""
        if game_id in self.data:
            return False
        self.data.append(game_id)
        self.save()
        return True

    def remove(self, game_id: str) -> bool:
        """Remove *game_id*.  Returns ``True`` if it was present."""
        if game_id not in self.data:
            return False
        self.data.remove(game_id)
        self.save()
        return True

    def save(self) -> None:
        self._save(self.data)
