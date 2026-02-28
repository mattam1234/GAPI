"""Repository for custom game tags ({game_id: [tag, ...]})."""
from typing import Dict, List
from .base import BaseRepository


class TagRepository(BaseRepository):
    """Persists per-game tag lists to a JSON file.

    Schema::

        { "<game_id>": ["<tag1>", "<tag2>", ...] }
    """

    def __init__(self, file_path: str = '.gapi_tags.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, List[str]] = self._load({})

    def find(self, game_id: str) -> List[str]:
        """Return the tag list for *game_id* (empty list if none)."""
        return self.data.get(str(game_id), [])

    def upsert(self, game_id: str, tags: List[str]) -> None:
        """Replace the tag list for *game_id* and persist."""
        self.data[str(game_id)] = tags
        self.save()

    def delete_entry(self, game_id: str) -> None:
        """Remove the entire entry for *game_id* if it exists."""
        self.data.pop(str(game_id), None)
        self.save()

    def save(self) -> None:
        self._save(self.data)
