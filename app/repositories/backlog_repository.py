"""Repository for backlog collections and per-game statuses."""
from typing import Dict

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
                    "<game_id>": "<status>"
                }
            }
        }

    Older flat ``{game_id: status}`` payloads are migrated by
    :class:`app.services.backlog_service.BacklogService`.
    """

    def __init__(self, file_path: str = '.gapi_backlog.json') -> None:
        super().__init__(file_path)
        self.data: Dict = self._load({})

    def save(self) -> None:
        self._save(self.data)
