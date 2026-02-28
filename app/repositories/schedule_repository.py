"""Repository for game-night schedule events ({event_id: event_dict})."""
from typing import Dict, Optional
from .base import BaseRepository


class ScheduleRepository(BaseRepository):
    """Persists game-night events to a JSON file.

    Schema::

        {
            "<event_id>": {
                "id":         "<str>",
                "title":      "<str>",
                "date":       "<YYYY-MM-DD>",
                "time":       "<HH:MM>",
                "attendees":  ["<name>", ...],
                "game_name":  "<str>",
                "notes":      "<str>",
                "created_at": "<ISO-8601>"
            }
        }
    """

    def __init__(self, file_path: str = '.gapi_schedule.json') -> None:
        super().__init__(file_path)
        self.data: Dict[str, Dict] = self._load({})

    def find(self, event_id: str) -> Optional[Dict]:
        return self.data.get(event_id)

    def upsert(self, event_id: str, event: Dict) -> None:
        self.data[event_id] = event
        self.save()

    def delete(self, event_id: str) -> bool:
        if event_id not in self.data:
            return False
        del self.data[event_id]
        self.save()
        return True

    def save(self) -> None:
        self._save(self.data)
