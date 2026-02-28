"""Business logic for leaderboard and user profile cards."""
from typing import Dict, Optional


class LeaderboardService:
    """Manages leaderboard rankings and user profile cards, delegating
    persistence to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_leaderboard``, ``get_user_card``, and
                ``update_user_profile``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_rankings(self, db, metric: str = 'playtime',
                     limit: int = 20) -> list:
        """Return a ranked list of users for the given metric.

        Args:
            db:     SQLAlchemy session.
            metric: One of ``'playtime'``, ``'games'``, ``'achievements'``.
            limit:  Maximum number of entries to return (default 20).

        Returns:
            List of dicts with ``rank``, ``username``, and ``score`` keys.
        """
        return self._db.get_leaderboard(db, metric=metric, limit=limit)

    def get_user_card(self, db, username: str) -> Optional[Dict]:
        """Return the profile card dict for *username*, or ``None`` if not
        found.

        The card includes display_name, bio, avatar_url, roles, stats
        (total_games, total_playtime_hours, total_achievements), and the
        user's join date.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            Profile card dict, or ``None`` when the user does not exist.
        """
        card = self._db.get_user_card(db, username)
        return card if card else None

    def update_profile(self, db, username: str,
                       display_name: str = None,
                       bio: str = None,
                       avatar_url: str = None) -> bool:
        """Update editable profile fields for *username*.

        Args:
            db:           SQLAlchemy session.
            username:     Target username.
            display_name: New display name (``None`` = no change).
            bio:          New bio text (max 500 chars; ``None`` = no change).
            avatar_url:   New avatar URL (``None`` = no change).

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.update_user_profile(
            db, username,
            display_name=display_name,
            bio=bio,
            avatar_url=avatar_url,
        )
