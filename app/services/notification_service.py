"""Business logic for in-app notifications."""
from typing import List, Optional


class NotificationService:
    """Manages notifications for GAPI users, delegating persistence to
    the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``create_notification``, ``get_notifications``,
                ``mark_notifications_read``, and ``get_user_roles``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, db, username: str, title: str, message: str,
               notif_type: str = 'info') -> bool:
        """Create a notification for *username*.

        Args:
            db:         SQLAlchemy session.
            username:   Recipient username.
            title:      Short notification title.
            message:    Full notification text.
            notif_type: One of ``'info'``, ``'warning'``, ``'success'``,
                        ``'error'``, ``'friend_request'``.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        return self._db.create_notification(db, username, title, message,
                                            type=notif_type)

    def get_all(self, db, username: str,
                unread_only: bool = False) -> List[dict]:
        """Return notifications for *username*.

        Args:
            db:          SQLAlchemy session.
            username:    Target username.
            unread_only: When ``True`` only return unread notifications.

        Returns:
            List of notification dicts with keys ``id``, ``type``,
            ``title``, ``message``, ``is_read``, ``created_at``.
        """
        return self._db.get_notifications(db, username,
                                          unread_only=unread_only)

    def mark_read(self, db, username: str,
                  ids: Optional[List[int]] = None) -> bool:
        """Mark notifications as read.

        Args:
            db:       SQLAlchemy session.
            username: Owner username.
            ids:      List of notification IDs to mark.  Pass ``None``
                      to mark *all* notifications for the user as read.

        Returns:
            ``True`` on success.
        """
        return self._db.mark_notifications_read(db, username,
                                                notification_ids=ids)

    def is_admin(self, db, username: str) -> bool:
        """Return ``True`` if *username* has the ``'admin'`` role."""
        roles = self._db.get_user_roles(db, username)
        return 'admin' in roles
