"""Repository for game backlog statuses ({game_id: status})."""
from typing import Dict, Optional
from .base import BaseRepository


class BacklogRepository(BaseRepository):
    """Persists per-game backlog statuses to a JSON file.

    Valid statuses: ``want_to_play``, ``playing``, ``completed``, ``dropped``.

    Schema::

        { "<game_id>": "<status>" }
    """

    def __init__(self, file_path: str = '.gapi_backlog.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, str] = self._load({})

    def find(self, game_id: str) -> Optional[str]:
        return self.data.get(game_id)

    def upsert(self, game_id: str, status: str) -> None:
        self.data[game_id] = status
        self.save()

    def delete(self, game_id: str) -> bool:
        if game_id not in self.data:
            return False
        del self.data[game_id]
        self.save()
        return True

    def save(self) -> None:
        self._save(self.data)
