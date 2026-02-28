"""Business logic for user management helpers not covered by UserManager."""
from typing import List


class UserService:
    """Provides thin service wrappers for user-management operations that
    are not already encapsulated in the ``UserManager`` class.

    Currently covers:
    * Role catalogue — listing all available roles.
    * User count — how many registered users exist.
    * Initial admin creation — bootstrapping the first admin account.
    * Platform-ID retrieval.
    * User existence check.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_roles``, ``get_user_count``, and
                ``create_or_update_user``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_roles(self, db) -> List[str]:
        """Return all role names defined in the database.

        Args:
            db: SQLAlchemy session.

        Returns:
            Alphabetically sorted list of role name strings.
        """
        return self._db.get_roles(db)

    def get_platform_ids(self, db, username: str) -> dict:
        """Return the platform IDs (steam_id, epic_id, gog_id) for *username*.

        Args:
            db:       SQLAlchemy session.
            username: Target username.

        Returns:
            Dict with ``steam_id``, ``epic_id``, and ``gog_id`` keys.  Any
            missing value is an empty string.  Returns an empty dict when the
            user is not found.
        """
        return self._db.get_user_platform_ids(db, username)

    def user_exists(self, db, username: str) -> bool:
        """Return True if *username* exists in the database.

        Args:
            db:       SQLAlchemy session.
            username: Username to look up.

        Returns:
            ``True`` when the user is found, ``False`` otherwise.
        """
        return self._db.user_exists(db, username)

    def get_all(self, db) -> list:
        """Return all registered users.

        Args:
            db: SQLAlchemy session.

        Returns:
            List of user ORM instances (may be empty).
        """
        return self._db.get_all_users(db)

    def get_count(self, db) -> int:
        """Return the total number of registered users.

        Args:
            db: SQLAlchemy session.

        Returns:
            Integer count of all users (0 when the database is empty).
        """
        return self._db.get_user_count(db)

    def create_admin(self, db, username: str, password_hash: str):
        """Create the initial admin user account.

        This method should only be called when no users exist yet
        (i.e., ``get_count(db) == 0``).

        Args:
            db:            SQLAlchemy session.
            username:      Desired admin username.
            password_hash: Pre-hashed password string.

        Returns:
            The newly created :class:`~database.User` ORM instance on
            success, or ``None`` on failure.
        """
        return self._db.create_or_update_user(
            db, username, password_hash, '', '', '',
            role='admin', roles=['admin'],
        )
