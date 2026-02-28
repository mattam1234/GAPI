"""Business logic for custom game playlists."""
from typing import Dict, List, Optional

from ..repositories.playlist_repository import PlaylistRepository


class PlaylistService:
    """Creates, manages, and queries named game playlists, delegating
    persistence to :class:`~app.repositories.playlist_repository.PlaylistRepository`.
    """

    def __init__(self, repository: PlaylistRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, name: str) -> bool:
        """Create a new empty playlist.

        Returns:
            ``True`` if created; ``False`` if the name already exists or is empty.
        """
        name = name.strip()
        if not name or self._repo.find(name) is not None:
            return False
        self._repo.upsert(name, [])
        return True

    def delete(self, name: str) -> bool:
        """Delete a playlist.  Returns ``True`` if it existed."""
        return self._repo.delete(name)

    def add_game(self, name: str, game_id: str) -> bool:
        """Append *game_id* to *name* (creates playlist if absent).

        Returns:
            ``True`` if the game was newly added; ``False`` if already present.
        """
        name = name.strip()
        if not name:
            return False
        current = list(self._repo.find(name) or [])
        if game_id in current:
            return False
        current.append(game_id)
        self._repo.upsert(name, current)
        return True

    def remove_game(self, name: str, game_id: str) -> bool:
        """Remove *game_id* from *name*.

        Returns:
            ``True`` if removed; ``False`` if the playlist or game wasn't found.
        """
        existing = self._repo.find(name)
        if existing is None or game_id not in existing:
            return False
        updated = [g for g in existing if g != game_id]
        self._repo.upsert(name, updated)
        return True

    def get_games(self, name: str,
                  all_games: List[Dict]) -> Optional[List[Dict]]:
        """Return game dicts for every ID in *name*.

        Unknown / stale IDs are silently skipped.

        Returns:
            List of matching game dicts, or ``None`` if the playlist doesn't exist.
        """
        ids = self._repo.find(name)
        if ids is None:
            return None
        id_set = set(ids)
        return [g for g in all_games if g.get('game_id') in id_set]

    def list_all(self) -> List[Dict]:
        """Return a summary list: ``[{'name': ..., 'count': ...}, ...]``."""
        return [
            {'name': n, 'count': len(ids)}
            for n, ids in self._repo.data.items()
        ]
