"""Repository for custom game playlists ({name: [game_id, ...]})."""
from typing import Dict, List, Optional
from .base import BaseRepository


class PlaylistRepository(BaseRepository):
    """Persists named game playlists to a JSON file.

    Schema::

        { "<playlist_name>": ["<game_id>", ...] }
    """

    def __init__(self, file_path: str = '.gapi_playlists.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, List[str]] = self._load({})

    def find(self, name: str) -> Optional[List[str]]:
        """Return the game-ID list for *name*, or ``None`` if the playlist doesn't exist."""
        return self.data.get(name)

    def upsert(self, name: str, game_ids: List[str]) -> None:
        self.data[name] = game_ids
        self.save()

    def delete(self, name: str) -> bool:
        if name not in self.data:
            return False
        del self.data[name]
        self.save()
        return True

    def save(self) -> None:
        self._save(self.data)
