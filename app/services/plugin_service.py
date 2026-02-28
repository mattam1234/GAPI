"""Business logic for the plugin/addon registry."""


class PluginService:
    """Manages the plugin registry, delegating persistence to the
    ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``get_plugins``, ``register_plugin``,
                ``toggle_plugin``, and ``get_user_roles``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all(self, db) -> list:
        """Return all registered plugins as a list of dicts.

        Each dict contains ``id``, ``name``, ``description``, ``version``,
        ``author``, ``enabled``, and ``created_at``.
        """
        return self._db.get_plugins(db)

    def register(self, db, name: str, description: str = '',
                 version: str = '1.0.0', author: str = '',
                 config: dict = None) -> bool:
        """Register a new plugin or update an existing one by *name*.

        Args:
            db:          SQLAlchemy session.
            name:        Unique plugin name (required).
            description: Short description.
            version:     Semver string.
            author:      Author name.
            config:      Optional configuration dict (stored as JSON).

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.register_plugin(
            db, name,
            description=description,
            version=version,
            author=author,
            config=config,
        )

    def toggle(self, db, plugin_id: int, enabled: bool) -> bool:
        """Enable or disable the plugin identified by *plugin_id*.

        Args:
            db:        SQLAlchemy session.
            plugin_id: Database primary key of the plugin.
            enabled:   ``True`` to enable; ``False`` to disable.

        Returns:
            ``True`` if updated, ``False`` if the plugin was not found.
        """
        return self._db.toggle_plugin(db, plugin_id, enabled)

    def is_admin(self, db, username: str) -> bool:
        """Return ``True`` if *username* holds the ``'admin'`` role."""
        roles = self._db.get_user_roles(db, username)
        return 'admin' in roles
