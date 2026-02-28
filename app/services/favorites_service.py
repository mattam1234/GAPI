"""Business logic for the favourites list."""
from typing import List

from ..repositories.favorites_repository import FavoritesRepository


class FavoritesService:
    """Manages the user's favourites list, delegating persistence to
    :class:`~app.repositories.favorites_repository.FavoritesRepository`.

    Integer *game_id* values are accepted for backward compatibility and are
    automatically normalised to ``"steam:<id>"`` composite IDs.
    """

    def __init__(self, repository: FavoritesRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(game_id) -> str:
        if isinstance(game_id, int):
            return f"steam:{game_id}"
        return str(game_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, game_id) -> bool:
        """Add *game_id* to favourites.

        Returns:
            ``True`` if added; ``False`` if already in the list.
        """
        return self._repo.add(self._normalise(game_id))

    def remove(self, game_id) -> bool:
        """Remove *game_id* from favourites.

        Returns:
            ``True`` if removed; ``False`` if not found.
        """
        return self._repo.remove(self._normalise(game_id))

    def contains(self, game_id) -> bool:
        """Return ``True`` if *game_id* is in the favourites list."""
        return self._repo.contains(self._normalise(game_id))

    def get_all(self) -> List[str]:
        """Return the full favourites list."""
        return self._repo.data
