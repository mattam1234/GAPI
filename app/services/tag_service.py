"""Business logic for custom game tags."""
from typing import Dict, List

from ..repositories.tag_repository import TagRepository


class TagService:
    """Manages per-game tag labels, delegating persistence to
    :class:`~app.repositories.tag_repository.TagRepository`.

    Rules
    -----
    * Tag strings are stripped of leading/trailing whitespace.
    * Adding a tag that already exists is a no-op (returns ``False``).
    * Removing the last tag for a game cleans up the entry entirely.
    """

    def __init__(self, repository: TagRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, game_id: str, tag: str) -> bool:
        """Add *tag* to *game_id*.

        Returns:
            ``True`` if added; ``False`` if it was already present or the tag
            is empty after stripping.
        """
        tag = tag.strip()
        if not tag:
            return False
        gid = str(game_id)
        current = list(self._repo.find(gid))  # copy
        if tag in current:
            return False
        current.append(tag)
        self._repo.upsert(gid, current)
        return True

    def remove(self, game_id: str, tag: str) -> bool:
        """Remove *tag* from *game_id*.

        Returns:
            ``True`` if removed; ``False`` if not found.
        """
        gid = str(game_id)
        current = list(self._repo.find(gid))
        if tag not in current:
            return False
        current.remove(tag)
        if current:
            self._repo.upsert(gid, current)
        else:
            self._repo.delete_entry(gid)
        return True

    def get(self, game_id: str) -> List[str]:
        """Return the tag list for *game_id* (empty list if none)."""
        return self._repo.find(str(game_id))

    def get_all(self) -> Dict[str, List[str]]:
        """Return the full ``{game_id: [tag, ...]}`` mapping."""
        return self._repo.data

    def all_tag_names(self) -> List[str]:
        """Return a sorted, deduplicated list of every tag in use."""
        tags = set()
        for tag_list in self._repo.data.values():
            tags.update(tag_list)
        return sorted(tags)

    def filter_by_tag(self, tag: str,
                      all_games: List[Dict]) -> List[Dict]:
        """Return games from *all_games* that have *tag* attached."""
        tagged = {gid for gid, tags in self._repo.data.items() if tag in tags}
        return [g for g in all_games if g.get('game_id') in tagged]
