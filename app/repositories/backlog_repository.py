"""Repository for backlog collections and per-game statuses."""
from typing import Dict, Optional

from .base import BaseRepository


class BacklogRepository(BaseRepository):
    """Persists backlog data to a JSON file.

    Current schema::

        {
            "__collections__": {
                "<collection_id>": {
                    "id": "<str>",
                    "name": "<str>",
                    "owner": "<username>",
                    "members": ["<username>", ...]
                }
            },
            "__entries__": {
                "<collection_id>": {
                    "<game_id>": {
                        "status": "<status>",
                        "notes": "<optional note>",
                        "updated_at": "<iso timestamp>"
                    }
                }
            }
        }

    Older flat ``{game_id: status}`` payloads are migrated by
    :class:`app.services.backlog_service.BacklogService`.
    """

    def __init__(self, file_path: str = '.gapi_backlog.json', backend: str = 'file') -> None:
        super().__init__(file_path, backend=backend)
        self.data: Dict = self._load({})

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
