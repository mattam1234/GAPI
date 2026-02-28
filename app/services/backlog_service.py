"""Business logic for the game backlog status tracker."""
from typing import Dict, List, Optional

from ..repositories.backlog_repository import BacklogRepository

VALID_STATUSES = ('want_to_play', 'playing', 'completed', 'dropped')


class BacklogService:
    """Sets, queries, and removes backlog statuses, delegating persistence to
    :class:`~app.repositories.backlog_repository.BacklogRepository`.

    Valid statuses: ``want_to_play``, ``playing``, ``completed``, ``dropped``.
    """

    def __init__(self, repository: BacklogRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, game_id: str, status: str) -> bool:
        """Set the backlog status for *game_id*.

        Returns:
            ``True`` on success; ``False`` if *status* is not one of the valid values.
        """
        if status not in VALID_STATUSES:
            return False
        self._repo.upsert(game_id, status)
        return True

    def remove(self, game_id: str) -> bool:
        """Remove *game_id* from the backlog.  Returns ``True`` if it existed."""
        return self._repo.delete(game_id)

    def get_status(self, game_id: str) -> Optional[str]:
        """Return the backlog status for *game_id*, or ``None``."""
        return self._repo.find(game_id)

    def get_games(self, all_games: List[Dict],
                  status: Optional[str] = None) -> List[Dict]:
        """Return game dicts for all backlog entries, optionally filtered by *status*.

        Each returned dict has an additional ``backlog_status`` key.
        """
        id_to_status = dict(self._repo.data)
        if status:
            id_to_status = {k: v for k, v in id_to_status.items() if v == status}
        id_set = set(id_to_status)
        result = []
        for game in all_games:
            gid = game.get('game_id')
            if gid in id_set:
                entry = dict(game)
                entry['backlog_status'] = id_to_status[gid]
                result.append(entry)
        return result
