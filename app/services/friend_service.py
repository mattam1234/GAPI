"""Business logic for the in-app friends / social system."""
from typing import Dict, List, Tuple


class FriendService:
    """Manages friendship requests and the friends list for GAPI users,
    delegating persistence to the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``send_friend_request``, ``respond_friend_request``,
                ``get_app_friends``, and ``remove_app_friend``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_request(self, db, from_username: str,
                     to_username: str) -> Tuple[bool, str]:
        """Send a friend request from *from_username* to *to_username*.

        Returns:
            ``(True, message)`` on success; ``(False, reason)`` on failure.
        """
        return self._db.send_friend_request(db, from_username, to_username)

    def respond(self, db, username: str, requester_username: str,
                accept: bool) -> Tuple[bool, str]:
        """Accept or decline a pending friend request.

        Args:
            db:                 SQLAlchemy session.
            username:           Username of the user responding.
            requester_username: Username of the person who sent the request.
            accept:             ``True`` to accept, ``False`` to decline.

        Returns:
            ``(True, message)`` on success; ``(False, reason)`` on failure.
        """
        return self._db.respond_friend_request(db, username,
                                               requester_username, accept)

    def get_friends(self, db, username: str) -> Dict:
        """Return the friends list and pending requests for *username*.

        Returns:
            Dict with keys ``'friends'``, ``'sent'``, ``'received'``, each a
            list of user dicts with at least ``username`` and
            ``display_name``.
        """
        return self._db.get_app_friends(db, username)

    def remove(self, db, username: str, other_username: str) -> bool:
        """Remove the friendship between *username* and *other_username*.

        Returns:
            ``True`` if the friendship was removed, ``False`` otherwise.
        """
        return self._db.remove_app_friend(db, username, other_username)
