"""Business logic for application-wide settings managed by admins."""
from typing import Optional


class AppSettingsService:
    """Manages admin-controlled application settings, delegating persistence
    to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_app_settings``, ``get_app_setting``,
                ``set_app_settings``, ``get_settings_with_meta``, and
                ``get_user_roles``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all(self, db) -> dict:
        """Return all app settings as a ``{key: value}`` dict.

        Missing keys are filled in from the database module's defaults.
        """
        return self._db.get_app_settings(db)

    def get(self, db, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return a single setting value by *key*.

        Args:
            db:      SQLAlchemy session.
            key:     Setting key.
            default: Value to return when the key is absent.

        Returns:
            The setting value as a string, or *default*.
        """
        return self._db.get_app_setting(db, key, default)

    def save(self, db, updates: dict, updated_by: str = None) -> bool:
        """Persist a ``{key: value}`` mapping of setting updates.

        Existing rows are updated; missing rows are created.

        Args:
            db:         SQLAlchemy session.
            updates:    Dict of ``{key: value}`` pairs.
            updated_by: Username of the admin making the change (for audit).

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.set_app_settings(db, updates, updated_by=updated_by)

    def get_with_meta(self, db) -> list:
        """Return settings as a list of dicts with ``key``, ``value``,
        ``default``, and ``description`` fields.

        This is the format exposed to the admin settings UI.
        """
        return self._db.get_settings_with_meta(db)

    def is_admin(self, db, username: str) -> bool:
        """Return ``True`` if *username* holds the ``'admin'`` role."""
        roles = self._db.get_user_roles(db, username)
        return 'admin' in roles
