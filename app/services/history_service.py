"""Business logic for the game-picking history list."""
import json
import os
from typing import Dict, List, Optional

from ..repositories.history_repository import HistoryRepository


class HistoryService:
    """Manages the game-picking history, delegating persistence to
    :class:`~app.repositories.history_repository.HistoryRepository`.

    Provides append, clear, export, and import operations on top of the
    raw repository so that callers never need to handle file I/O directly.
    """

    def __init__(self, repository: HistoryRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def data(self) -> List[str]:
        """Return the in-memory history list (same object as the repo)."""
        return self._repo.data

    def append(self, game_id: str) -> None:
        """Append *game_id* to the history and persist."""
        self._repo.append(game_id)

    def clear(self) -> None:
        """Empty the history and persist."""
        self._repo.data.clear()
        self._repo.save()

    def export(self, filepath: str) -> bool:
        """Export the history to *filepath* as JSON with metadata.

        Returns:
            ``True`` on success, ``False`` on I/O failure.
        """
        import datetime
        import tempfile
        export_data: Dict = {
            'history': list(self._repo.data),
            'exported_at': datetime.datetime.now().isoformat(),
        }
        dir_name = os.path.dirname(os.path.abspath(filepath))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(export_data, fh, indent=2)
            os.replace(tmp_path, filepath)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False

    def import_from(self, filepath: str) -> Optional[int]:
        """Import history entries from *filepath*.

        Accepts either a plain list or an export dict produced by
        :meth:`export`.

        Returns:
            Number of entries loaded, or ``None`` on failure.
        """
        try:
            with open(filepath, 'r') as fh:
                raw = json.load(fh)
        except (IOError, json.JSONDecodeError):
            return None

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict) and 'history' in raw:
            entries = raw['history']
        else:
            return None

        self._repo.data.clear()
        self._repo.data.extend(entries)
        self._repo.save()
        return len(entries)
