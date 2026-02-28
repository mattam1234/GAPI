"""Business logic for per-user and shared game ignore lists."""
from typing import List


class IgnoredGamesService:
    """Manages the game ignore list for GAPI users, delegating persistence
    to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_ignored_games``, ``toggle_ignore_game``, and
                ``get_shared_ignore_games``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_ignored(self, db, username: str) -> List[str]:
        """Return the list of app IDs ignored by *username*.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            List of app ID strings (may be empty).
        """
        return self._db.get_ignored_games(db, username)

    def toggle(self, db, username: str, app_id: str,
               game_name: str = '', reason: str = '') -> bool:
        """Toggle the ignore status of *app_id* for *username*.

        If the game is currently ignored it is removed from the ignore list;
        otherwise it is added.

        Args:
            db:        SQLAlchemy session.
            username:  Target username.
            app_id:    Steam (or other platform) app ID string.
            game_name: Human-readable game name (stored alongside the ignore).
            reason:    Optional reason / note for ignoring the game.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.toggle_ignore_game(
            db, username, app_id,
            game_name=game_name, reason=reason,
        )

    def get_detailed(self, db, username: str) -> List[dict]:
        """Return full detail records for all games ignored by *username*.

        Unlike :meth:`get_ignored`, which returns only app-ID strings, this
        method returns a list of dicts containing ``app_id``, ``game_name``,
        ``reason``, and ``created_at`` — the same fields exposed by the REST
        API.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            List of dicts (may be empty).
        """
        return self._db.get_ignored_games_full(db, username)

    def get_shared_ignored(self, db, usernames: List[str]) -> List[str]:
        """Return app IDs that are ignored by *all* of the given users.

        This is used for multi-user sessions where a game is excluded from
        picking only when every participant has individually ignored it.

        Args:
            db:        SQLAlchemy session.
            usernames: List of usernames whose ignore lists are intersected.

        Returns:
            List of app ID strings common to all users' ignore lists.
        """
        return self._db.get_shared_ignore_games(db, usernames)
