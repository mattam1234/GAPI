"""Business logic for in-app chat messaging."""
from typing import List


class ChatService:
    """Manages chat messages between GAPI users, delegating persistence to
    the ``database`` module's helper functions.

    All methods accept a *db* SQLAlchemy session as the first argument so
    that callers (Flask route handlers) control the session lifecycle.
    """

    def __init__(self, db_module) -> None:
        """
        Args:
            db_module: The imported ``database`` module (or any object that
                exposes ``send_chat_message`` and ``get_chat_messages``).
        """
        self._db = db_module

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, db, sender_username: str, message: str,
             room: str = 'general',
             recipient_username: str = None) -> dict:
        """Save a chat message and return the persisted message dict.

        Args:
            db:                 SQLAlchemy session.
            sender_username:    Username of the sender.
            message:            Message text.
            room:               Chat room name (default ``'general'``).
            recipient_username: Optional direct-message recipient.

        Returns:
            Dict with ``id``, ``sender``, ``room``, ``message``,
            ``created_at`` keys, or an empty dict on failure.
        """
        return self._db.send_chat_message(
            db, sender_username, message,
            room=room, recipient_username=recipient_username,
        )

    def get_messages(self, db, room: str = 'general',
                     limit: int = 50, since_id: int = 0) -> List[dict]:
        """Fetch messages from a chat room.

        Args:
            db:       SQLAlchemy session.
            room:     Room to fetch from (default ``'general'``).
            limit:    Maximum messages to return (default 50).
            since_id: Return only messages with ``id > since_id``
                      (default 0 = no filter).

        Returns:
            List of message dicts sorted by ``created_at`` ascending.
        """
        return self._db.get_chat_messages(
            db, room=room, limit=limit, since_id=since_id,
        )
