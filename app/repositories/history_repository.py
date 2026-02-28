"""Repository for game-picking history ([game_id, ...])."""
from typing import List
from .base import BaseRepository


class HistoryRepository(BaseRepository):
    """Persists the game-picking history list to a JSON file.

    Schema::

        ["<game_id>", ...]

    Old-format entries (plain integers) are normalised to ``"steam:<id>"``
    on load.  The list is capped at *max_size* entries on every save.
    """

    def __init__(self, file_path: str = '.gapi_history.json',
                 max_size: int = 20) -> None:
        super().__init__(file_path)
        self.max_size = max_size
        raw: List = self._load([])
        self.data: List[str] = [
            f"steam:{x}" if isinstance(x, int) else x for x in raw
        ]

    def append(self, game_id: str) -> None:
        """Add *game_id* to the history and persist (trimmed to *max_size*)."""
        self.data.append(game_id)
        self.save()

    def save(self) -> None:
        """Persist the history, trimming to the configured *max_size*."""
        self._save(self.data[-self.max_size:])
