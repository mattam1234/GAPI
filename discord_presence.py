#!/usr/bin/env python3
"""
Discord Rich Presence support for GAPI.

When enabled (``DISCORD_CLIENT_ID`` environment variable is set), GAPI will
update the local Discord client's Rich Presence whenever a game is picked,
showing the game name and how long the user has played it.

The integration is **opt-in** and **fails gracefully** — if ``pypresence`` is
not installed, or if Discord is not running on the host machine, GAPI will log
a debug message and continue normally without raising an exception.

Usage
-----
    from discord_presence import DiscordPresence
    rpc = DiscordPresence()          # reads DISCORD_CLIENT_ID from environment
    rpc.update("Portal 2", playtime_hours=45.3)
    rpc.clear()
    rpc.close()

Configuration
-------------
Set ``DISCORD_CLIENT_ID`` in ``.env`` (or as a real environment variable) to
the numeric Client ID of your Discord application.  You can create a free
application at https://discord.com/developers/applications — no Bot token is
required for Rich Presence.
"""

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger('gapi.presence')

try:
    from pypresence import Presence, exceptions as rpc_exceptions  # type: ignore[import]
    _PYPRESENCE_AVAILABLE = True
except ImportError:
    _PYPRESENCE_AVAILABLE = False
    Presence = None  # type: ignore[assignment,misc]
    rpc_exceptions = None  # type: ignore[assignment]


# How many seconds to wait before retrying a failed connection.
_RECONNECT_DELAY = 15

# Text displayed in the Discord Rich Presence panel
_RP_LARGE_TEXT = 'GAPI — Game Picker'
_RP_LARGE_IMAGE = 'gapi_logo'
_RP_SMALL_IMAGE = 'controller'
_RP_DEFAULT_STATE = 'GAPI picked this game'


class DiscordPresence:
    """Thread-safe Discord Rich Presence manager.

    A single background thread owns the ``pypresence.Presence`` object so that
    blocking socket I/O never blocks a Flask request handler.
    """

    def __init__(self, client_id: Optional[str] = None) -> None:
        self._client_id: Optional[str] = client_id or os.getenv('DISCORD_CLIENT_ID', '').strip() or None
        self._rpc: Optional[object] = None  # pypresence.Presence instance
        self._lock = threading.Lock()
        self._enabled = bool(self._client_id and _PYPRESENCE_AVAILABLE)
        self._start_time: int = int(time.time())
        self._connected = False

        if self._client_id and not _PYPRESENCE_AVAILABLE:
            logger.warning(
                'DISCORD_CLIENT_ID is set but pypresence is not installed. '
                'Install it with: pip install pypresence'
            )
        elif self._enabled:
            logger.info('Discord Rich Presence enabled (client_id=%s)', self._client_id)
        else:
            logger.debug('Discord Rich Presence disabled (DISCORD_CLIENT_ID not set)')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True when a client ID is configured *and* pypresence is installed."""
        return self._enabled

    def update(
        self,
        game_name: str,
        playtime_hours: Optional[float] = None,
        details: Optional[str] = None,
    ) -> bool:
        """Update Discord Rich Presence to reflect *game_name*.

        Args:
            game_name: The name of the picked game.
            playtime_hours: Optional playtime in hours (shown as part of the
                state string, e.g. "45.3 hours played").
            details: Optional override for the details line.  Defaults to
                "Playing: <game_name>".

        Returns:
            ``True`` on success, ``False`` if the update was skipped or failed.
        """
        if not self._enabled:
            return False
        threading.Thread(
            target=self._update_worker,
            args=(game_name, playtime_hours, details),
            daemon=True,
            name='discord-rpc-update',
        ).start()
        return True

    def clear(self) -> bool:
        """Clear the Rich Presence status (e.g. on logout).

        Returns:
            ``True`` on success / queued, ``False`` if disabled or failed.
        """
        if not self._enabled:
            return False
        threading.Thread(
            target=self._clear_worker,
            daemon=True,
            name='discord-rpc-clear',
        ).start()
        return True

    def close(self) -> None:
        """Disconnect from the local Discord IPC socket."""
        if not self._enabled:
            return
        with self._lock:
            self._disconnect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Open the IPC connection.  Caller must hold ``self._lock``."""
        if self._connected:
            return True
        try:
            rpc = Presence(self._client_id)  # type: ignore[call-arg]
            rpc.connect()
            self._rpc = rpc
            self._connected = True
            logger.debug('Discord IPC connected')
            return True
        except Exception as exc:
            logger.debug('Could not connect to Discord IPC: %s', exc)
            self._rpc = None
            self._connected = False
            return False

    def _disconnect(self) -> None:
        """Close the IPC connection.  Caller must hold ``self._lock``."""
        if self._rpc is not None:
            try:
                self._rpc.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._rpc = None
        self._connected = False

    def _update_worker(
        self,
        game_name: str,
        playtime_hours: Optional[float],
        details_override: Optional[str],
    ) -> None:
        details_line = details_override or f'Playing: {game_name}'
        state_line = f'{playtime_hours:.1f}h played' if playtime_hours is not None else _RP_DEFAULT_STATE

        with self._lock:
            if not self._connect():
                return
            try:
                self._rpc.update(  # type: ignore[union-attr]
                    details=details_line,
                    state=state_line,
                    start=self._start_time,
                    large_image=_RP_LARGE_IMAGE,
                    large_text=_RP_LARGE_TEXT,
                    small_image=_RP_SMALL_IMAGE,
                    small_text=game_name,
                )
                logger.info('Discord Rich Presence updated: %s', game_name)
            except Exception as exc:
                logger.debug('Discord Rich Presence update failed: %s', exc)
                self._disconnect()

    def _clear_worker(self) -> None:
        with self._lock:
            if not self._connect():
                return
            try:
                self._rpc.clear()  # type: ignore[union-attr]
                logger.debug('Discord Rich Presence cleared')
            except Exception as exc:
                logger.debug('Discord Rich Presence clear failed: %s', exc)
                self._disconnect()
