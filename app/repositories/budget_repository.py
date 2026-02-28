"""Repository for game purchase / budget entries ({game_id: entry_dict})."""
from typing import Dict, Optional
from .base import BaseRepository


class BudgetRepository(BaseRepository):
    """Persists per-game budget entries to a JSON file.

    Schema::

        {
            "<game_id>": {
                "game_id":       "<str>",
                "price":         <float>,
                "currency":      "<ISO-4217>",
                "purchase_date": "<YYYY-MM-DD or ''>",
                "notes":         "<str>"
            }
        }
    """

    def __init__(self, file_path: str = '.gapi_budget.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, Dict] = self._load({})

    def find(self, game_id: str) -> Optional[Dict]:
        return self.data.get(game_id)

    def upsert(self, game_id: str, entry: Dict) -> None:
        self.data[game_id] = entry
        self.save()

    def delete(self, game_id: str) -> bool:
        if game_id not in self.data:
            return False
        del self.data[game_id]
        self.save()
        return True

    def save(self) -> None:
        self._save(self.data)
