"""Business logic for the database-backed favorites list."""
from typing import List


class DBFavoritesService:
    """Manages the database-persisted favorites list for a user, delegating
    persistence to the ``database`` module's helper functions.

    This service is distinct from the file-backed :class:`FavoritesService`
    which stores data in a local JSON file.  Use this service when the
    application is running with a live database session.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_user_favorites``, ``add_favorite``, and
                ``remove_favorite``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all(self, db, username: str) -> List[str]:
        """Return the list of favorite app IDs for *username*.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            List of app ID strings (may be empty).
        """
        return self._db.get_user_favorites(db, username)

    def add(self, db, username: str, app_id: str,
            platform: str = 'steam') -> bool:
        """Add *app_id* to *username*'s favorites.

        Args:
            db:       SQLAlchemy session.
            username: Target username.
            app_id:   Game app ID string.
            platform: Platform name (default ``'steam'``).

        Returns:
            ``True`` if added (or already present), ``False`` on error.
        """
        return self._db.add_favorite(db, username, app_id, platform)

    def remove(self, db, username: str, app_id: str) -> bool:
        """Remove *app_id* from *username*'s favorites.

        Args:
            db:       SQLAlchemy session.
            username: Target username.
            app_id:   Game app ID string.

        Returns:
            ``True`` on success (including when the entry was absent),
            ``False`` on error.
        """
        return self._db.remove_favorite(db, username, app_id)
