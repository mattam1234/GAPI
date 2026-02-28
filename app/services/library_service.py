"""Business logic for the library cache and game-details cache."""
from typing import Dict, List, Optional


class LibraryService:
    """Manages the user game-library cache and the per-game details cache,
    delegating persistence to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_cached_library``, ``cache_user_library``,
                ``get_library_cache_age``, ``get_game_details_cache``, and
                ``update_game_details_cache``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Library-cache API
    # ------------------------------------------------------------------

    def get_cached(self, db, username: str) -> List[Dict]:
        """Return the cached game library for *username*.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            List of game dicts (may be empty when no cache exists).
        """
        return self._db.get_cached_library(db, username)

    def cache(self, db, username: str, games: list) -> int:
        """Persist *games* as the library cache for *username*.

        Args:
            db:       SQLAlchemy session.
            username: Target username.
            games:    List of game dicts with ``app_id``, ``name``,
                      ``platform``, ``playtime_hours``, etc.

        Returns:
            Number of games successfully cached.
        """
        return self._db.cache_user_library(db, username, games)

    def get_cache_age(self, db, username: str) -> Optional[float]:
        """Return the age of the library cache in seconds.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            Age in seconds, or ``None`` when no cache exists.
        """
        return self._db.get_library_cache_age(db, username)

    # ------------------------------------------------------------------
    # Game-details cache API
    # ------------------------------------------------------------------

    def get_game_details(self, db, app_id: str, platform: str = 'steam',
                         max_age_hours: int = 1) -> Optional[Dict]:
        """Return cached game details if the cache is fresh enough.

        Args:
            db:            SQLAlchemy session.
            app_id:        Game app ID string.
            platform:      Platform name (``'steam'``, ``'epic'``, etc.).
            max_age_hours: Maximum age (hours) to treat the cache as fresh.

        Returns:
            Cached details dict, or ``None`` when missing or stale.
        """
        return self._db.get_game_details_cache(
            db, app_id, platform, max_age_hours=max_age_hours)

    def update_game_details(self, db, app_id: str, platform: str,
                            details: Dict) -> bool:
        """Persist (create or update) the game-details cache entry.

        Args:
            db:       SQLAlchemy session.
            app_id:   Game app ID string.
            platform: Platform name.
            details:  Details dict to cache.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.update_game_details_cache(db, app_id, platform, details)

    def get_game_platform(self, db, username: str, app_id) -> str:
        """Return the platform for *app_id* in *username*'s library cache.

        Args:
            db:       SQLAlchemy session.
            username: Target username.
            app_id:   Game app ID (string or int).

        Returns:
            Platform string (e.g. ``'steam'``, ``'epic'``).  Falls back to
            ``'steam'`` when no matching entry is found.
        """
        return self._db.get_game_platform_for_user(db, username, app_id)

    def get_stale_game_details(self, db, app_id, platform: str = 'steam') -> Optional[Dict]:
        """Return the last cached game-details entry regardless of age.

        Useful as a last-resort fallback when no fresh cache or API data
        is available.

        Args:
            db:       SQLAlchemy session.
            app_id:   Game app ID.
            platform: Platform name.

        Returns:
            Parsed details dict, or ``None`` when no entry exists.
        """
        return self._db.get_game_details_stale(db, app_id, platform)
