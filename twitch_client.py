"""
twitch_client.py
================
Lightweight wrapper around the Twitch Helix API used by GAPI to surface
trending games and cross-reference them with the user's library.

Authentication
--------------
The client uses the Twitch *client credentials* (app-access) flow:

    POST https://id.twitch.tv/oauth2/token
        ?client_id=<YOUR_CLIENT_ID>
        &client_secret=<YOUR_CLIENT_SECRET>
        &grant_type=client_credentials

Obtain credentials at https://dev.twitch.tv/console/apps.

Usage
-----
::

    from twitch_client import TwitchClient

    client = TwitchClient(client_id="abc", client_secret="xyz")
    top = client.get_top_games(count=10)
    # [{"id": "509658", "name": "Just Chatting", "viewer_count": 120000, ...}, ...]

    overlap = client.find_library_overlap(top, user_games)
    # [{"name": "Counter-Strike 2", "viewer_count": 75000, ...}, ...]
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TOKEN_URL   = "https://id.twitch.tv/oauth2/token"
_HELIX_BASE  = "https://api.twitch.tv/helix"
_DEFAULT_TIMEOUT = 10  # seconds
# Minimum seconds to keep a cached token before re-fetching
_TOKEN_MIN_TTL   = 60


class TwitchAuthError(Exception):
    """Raised when the Twitch OAuth token cannot be obtained."""


class TwitchAPIError(Exception):
    """Raised when the Twitch Helix API returns an unexpected error."""


class TwitchClient:
    """Minimal Twitch Helix API client with automatic token refresh."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        """
        Args:
            client_id:     Twitch application client ID.
            client_secret: Twitch application client secret.
            timeout:       HTTP request timeout in seconds.
        """
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret must not be empty")
        self._client_id     = client_id
        self._client_secret = client_secret
        self._timeout       = timeout
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0  # Unix timestamp when token expires

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_top_games(self, count: int = 20) -> List[Dict[str, Any]]:
        """Return the top *count* games currently live on Twitch.

        Each entry contains::

            {
              "id":           "32982",   # Twitch game/category ID
              "name":         "Grand Theft Auto V",
              "viewer_count": 87452,     # approximate live viewer count
              "box_art_url":  "https://...",
              "twitch_url":   "https://www.twitch.tv/directory/game/..."
            }

        Args:
            count: Number of games to return (1–100).

        Returns:
            List of game dicts, ordered by viewer count (descending).

        Raises:
            TwitchAuthError: Token could not be obtained.
            TwitchAPIError:  Helix API returned an error status.
        """
        count = max(1, min(count, 100))
        token = self._get_token()

        games: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        while len(games) < count:
            batch_size = min(count - len(games), 100)
            params: Dict[str, Any] = {"first": batch_size}
            if cursor:
                params["after"] = cursor

            data = self._get(
                "/games/top",
                params=params,
                token=token,
            )
            batch = data.get("data", [])
            if not batch:
                break

            for raw in batch:
                games.append({
                    "id":           raw.get("id", ""),
                    "name":         raw.get("name", ""),
                    "viewer_count": raw.get("viewer_count", 0),
                    "box_art_url":  raw.get("box_art_url", ""),
                    "twitch_url":   self._game_url(raw.get("name", "")),
                })

            pagination = data.get("pagination", {})
            cursor = pagination.get("cursor")
            if not cursor:
                break

        return games[:count]

    def find_library_overlap(
        self,
        trending: List[Dict[str, Any]],
        user_games: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return user games that appear in the *trending* list.

        Matching is performed by normalising game names to lower-case and
        stripping punctuation so that minor differences (e.g. "Counter-Strike
        2" vs "Counter-Strike: 2") are tolerated.

        Each result dict merges the user-game dict with the Twitch data::

            {
              # — from user_games —
              "appid": 730, "name": "Counter-Strike 2", "playtime_forever": 4560,
              # — added by this method —
              "twitch_id":     "32398",
              "viewer_count":  75000,
              "box_art_url":   "https://...",
              "twitch_url":    "https://www.twitch.tv/directory/game/...",
              "trending_rank": 3,         # 1-based position in trending list
            }

        Args:
            trending:   Output of :meth:`get_top_games`.
            user_games: List of user-library game dicts (must include ``name``).

        Returns:
            Merged list sorted by trending rank (ascending).
        """
        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

        trending_map: Dict[str, Dict[str, Any]] = {}
        for rank, g in enumerate(trending, start=1):
            key = _norm(g["name"])
            if key and key not in trending_map:
                trending_map[key] = {**g, "trending_rank": rank}

        results: List[Dict[str, Any]] = []
        seen: set = set()
        for game in user_games:
            key = _norm(game.get("name", ""))
            if key in trending_map and key not in seen:
                seen.add(key)
                t = trending_map[key]
                results.append({
                    **game,
                    "twitch_id":     t["id"],
                    "viewer_count":  t["viewer_count"],
                    "box_art_url":   t["box_art_url"],
                    "twitch_url":    t["twitch_url"],
                    "trending_rank": t["trending_rank"],
                })

        results.sort(key=lambda x: x["trending_rank"])
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid Bearer token, fetching a new one if needed."""
        now = time.time()
        if self._access_token and now < self._token_expiry - _TOKEN_MIN_TTL:
            return self._access_token

        try:
            resp = requests.post(
                _TOKEN_URL,
                params={
                    "client_id":     self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type":    "client_credentials",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise TwitchAuthError(f"Failed to obtain Twitch token: {exc}") from exc

        body = resp.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in", 3600)
        if not token:
            raise TwitchAuthError(
                f"Twitch token response missing 'access_token': {body}"
            )

        self._access_token = token
        self._token_expiry = now + expires_in
        logger.debug("Obtained new Twitch access token (expires in %ds)", expires_in)
        return token

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform a GET request against the Helix API and return parsed JSON."""
        if token is None:
            token = self._get_token()

        url = _HELIX_BASE + path
        headers = {
            "Client-ID":    self._client_id,
            "Authorization": f"Bearer {token}",
        }
        try:
            resp = requests.get(
                url,
                headers=headers,
                params=params or {},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise TwitchAPIError(
                f"Twitch API error {resp.status_code} for {path}: {resp.text}"
            ) from exc
        except requests.RequestException as exc:
            raise TwitchAPIError(f"Network error calling Twitch API: {exc}") from exc

        return resp.json()

    @staticmethod
    def _game_url(name: str) -> str:
        """Build the Twitch directory URL for a game name."""
        encoded = urllib.parse.quote(name, safe="")
        return f"https://www.twitch.tv/directory/game/{encoded}"
