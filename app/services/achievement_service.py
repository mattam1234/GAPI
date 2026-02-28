"""Business logic for achievement tracking and achievement hunt sessions."""
from typing import Dict, List, Optional


class AchievementService:
    """Manages achievement data and achievement-hunt sessions, delegating
    persistence to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_user_achievements_grouped``,
                ``start_achievement_hunt``, and ``update_achievement_hunt``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_by_user(self, db, username: str) -> List[Dict]:
        """Return all achievements for *username* grouped by game.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            List of ``{'app_id', 'game_name', 'achievements': [...]}`` dicts.
        """
        return self._db.get_user_achievements_grouped(db, username)

    def start_hunt(self, db, username: str, app_id: int, game_name: str,
                   difficulty: str = 'medium',
                   target_achievements: int = 0) -> Optional[Dict]:
        """Create a new achievement-hunt session for *username*.

        Args:
            db:                   SQLAlchemy session.
            username:             Target username.
            app_id:               Integer Steam app ID.
            game_name:            Human-readable game name.
            difficulty:           ``'easy'``, ``'medium'``, ``'hard'``, or
                                  ``'extreme'`` (default ``'medium'``).
            target_achievements:  Total number of achievements to unlock;
                                  ``0`` means "all available".

        Returns:
            Dict with hunt details on success, ``None`` on failure.
        """
        result = self._db.start_achievement_hunt(
            db, username, app_id, game_name,
            difficulty=difficulty,
            target_achievements=target_achievements,
        )
        return result if result else None

    def update_hunt(self, db, hunt_id, unlocked_achievements=None,
                    status: str = None) -> Optional[Dict]:
        """Update the progress or status of an existing achievement hunt.

        Args:
            db:                    SQLAlchemy session.
            hunt_id:               Primary-key ID of the hunt record.
            unlocked_achievements: New unlocked count (``None`` → unchanged).
            status:                New status string (``None`` → unchanged).

        Returns:
            Dict with updated hunt details on success, ``None`` if the hunt
            was not found or an error occurred.
        """
        result = self._db.update_achievement_hunt(
            db, hunt_id,
            unlocked_achievements=unlocked_achievements,
            status=status,
        )
        return result if result else None
