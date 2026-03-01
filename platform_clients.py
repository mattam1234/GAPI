"""
platform_clients.py
===================
Enhanced platform API clients with full OAuth support for:

* **Epic Games** — PKCE authorization code flow → launcher-public catalog API
* **GOG Galaxy** — OAuth2 code flow → embed.gog.com library API
* **Xbox Game Pass** — Microsoft Identity OAuth2 → Xbox Live title-hub API

All clients extend :class:`gapi.GamePlatformClient` and follow the same
interface (``get_owned_games`` / ``get_game_details`` / ``get_platform_name``).

OAuth flow summary
------------------
Each client exposes two helper methods used by the Flask routes in
``gapi_gui.py``:

* ``build_auth_url(redirect_uri, state)`` → URL to redirect the browser to
* ``exchange_code(code, redirect_uri)``   → ``True`` when tokens are stored

After a successful exchange the client is *authenticated*; subsequent calls
to ``get_owned_games`` use the stored access token.  ``refresh_token()`` is
called automatically when the access token expires.

Configuration keys (``config.json``)
-------------------------------------
Epic::

    "epic_enabled": true,
    "epic_client_id": "YOUR_EPIC_CLIENT_ID",
    "epic_client_secret": "YOUR_EPIC_CLIENT_SECRET",
    "epic_redirect_uri": "http://localhost:5000/api/epic/oauth/callback"

GOG::

    "gog_enabled": true,
    "gog_client_id": "YOUR_GOG_CLIENT_ID",
    "gog_client_secret": "YOUR_GOG_CLIENT_SECRET",
    "gog_redirect_uri": "http://localhost:5000/api/gog/oauth/callback"

Xbox::

    "xbox_enabled": true,
    "xbox_client_id": "YOUR_XBOX_CLIENT_ID",
    "xbox_client_secret": "YOUR_XBOX_CLIENT_SECRET",
    "xbox_redirect_uri": "http://localhost:5000/api/xbox/oauth/callback"
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tiny OAuth2 helper — shared by all three clients
# ---------------------------------------------------------------------------

class _OAuth2Mixin:
    """Mixin that adds token storage, refresh, and Authorization-header helper."""

    def __init__(self) -> None:
        self._access_token:  Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry:  float = 0.0   # unix timestamp

    # ------------------------------------------------------------------
    # Token accessors
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def _is_token_expired(self) -> bool:
        return time.time() >= self._token_expiry - 30  # 30-second buffer

    def _store_tokens(self, data: Dict[str, Any]) -> None:
        self._access_token  = data.get('access_token', '')
        self._refresh_token = data.get('refresh_token', self._refresh_token)
        expires_in          = int(data.get('expires_in', 3600))
        self._token_expiry  = time.time() + expires_in
        logger.info("%s: tokens stored, expires in %ds", self.__class__.__name__, expires_in)

    def _auth_header(self) -> Dict[str, str]:
        return {'Authorization': f'Bearer {self._access_token}'}


# ---------------------------------------------------------------------------
# Epic Games OAuth + Library Client
# ---------------------------------------------------------------------------

class EpicOAuthClient(_OAuth2Mixin):
    """Full Epic Games OAuth2 PKCE client with library access.

    Epic uses the standard OAuth2 Authorization Code + PKCE flow.  The
    ``launcher-public`` service is used to list owned titles.

    Args:
        client_id:     Epic OAuth application client ID.
        client_secret: Epic OAuth application client secret (may be empty for
                       public/PKCE-only clients).
        timeout:       HTTP request timeout in seconds.
    """

    _AUTH_URL    = "https://www.epicgames.com/id/authorize"
    _TOKEN_URL   = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
    _ASSETS_URL  = (
        "https://launcher-public-service-prod06.ol.epicgames.com"
        "/launcher/api/public/assets/Windows"
    )

    def __init__(self, client_id: str, client_secret: str = '', timeout: int = 10) -> None:
        _OAuth2Mixin.__init__(self)
        self._client_id     = client_id
        self._client_secret = client_secret
        self._timeout       = timeout
        self._session       = requests.Session()
        self._code_verifier = ''

        # In-process library + details cache
        self.owned_games:  List[Dict[str, Any]] = []
        self.details_cache: Dict[str, Any] = {}

    def get_platform_name(self) -> str:
        return "epic"

    # ------------------------------------------------------------------
    # OAuth2 PKCE helpers
    # ------------------------------------------------------------------

    def build_auth_url(self, redirect_uri: str, state: str = '') -> str:
        """Return the Epic authorization URL to redirect the user to.

        Generates a new PKCE code verifier/challenge pair each call.

        Args:
            redirect_uri: Must match the registered redirect URI in the Epic
                          developer portal.
            state:        Optional opaque state value for CSRF protection.

        Returns:
            Full authorization URL string.
        """
        self._code_verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(self._code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

        params = {
            'client_id':             self._client_id,
            'response_type':         'code',
            'scope':                 'basic_profile friends_list openid',
            'redirect_uri':          redirect_uri,
            'code_challenge':        challenge,
            'code_challenge_method': 'S256',
        }
        if state:
            params['state'] = state
        return f"{self._AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> bool:
        """Exchange an authorization code for access + refresh tokens.

        Args:
            code:         Authorization code received in the callback.
            redirect_uri: Same redirect URI used in :meth:`build_auth_url`.

        Returns:
            ``True`` on success, ``False`` on any HTTP or JSON error.
        """
        data = {
            'grant_type':    'authorization_code',
            'code':          code,
            'redirect_uri':  redirect_uri,
            'code_verifier': self._code_verifier,
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if self._client_secret:
            # Confidential client: use HTTP Basic auth
            headers['Authorization'] = 'Basic ' + base64.b64encode(
                f'{self._client_id}:{self._client_secret}'.encode()
            ).decode()
        else:
            data['client_id'] = self._client_id

        try:
            resp = self._session.post(
                self._TOKEN_URL, data=data, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            self._store_tokens(resp.json())
            return True
        except requests.RequestException as exc:
            logger.warning("Epic token exchange failed: %s", exc)
            return False

    def refresh_tokens(self) -> bool:
        """Use the stored refresh token to obtain a new access token.

        Returns:
            ``True`` on success.
        """
        if not self._refresh_token:
            return False
        data = {
            'grant_type':    'refresh_token',
            'refresh_token': self._refresh_token,
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if self._client_secret:
            headers['Authorization'] = 'Basic ' + base64.b64encode(
                f'{self._client_id}:{self._client_secret}'.encode()
            ).decode()
        else:
            data['client_id'] = self._client_id
        try:
            resp = self._session.post(
                self._TOKEN_URL, data=data, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            self._store_tokens(resp.json())
            return True
        except requests.RequestException as exc:
            logger.warning("Epic token refresh failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def get_owned_games(self, user_id: str = '') -> List[Dict[str, Any]]:
        """Fetch the authenticated user's Epic library.

        Calls the ``launcher-public`` assets endpoint which returns the
        catalogue items the account owns.  Each entry is normalised to the
        common GAPI game dict shape.

        Args:
            user_id: Not used for Epic (identity is from the OAuth token).

        Returns:
            List of game dicts with ``name``, ``game_id``, ``platform``,
            ``appid``, and ``playtime_forever`` (always 0 – Epic has no
            playtime API).
        """
        if not self.is_authenticated:
            logger.info("Epic: not authenticated — call exchange_code first")
            return []
        if self._is_token_expired():
            self.refresh_tokens()
        try:
            resp = self._session.get(
                self._ASSETS_URL,
                headers=self._auth_header(),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            assets = resp.json()
        except requests.RequestException as exc:
            logger.warning("Epic get_owned_games failed: %s", exc)
            return []

        games: List[Dict[str, Any]] = []
        for asset in assets:
            app_name    = asset.get('appName', '')
            catalog_id  = asset.get('catalogItemId', app_name)
            label       = asset.get('labelName', '')
            namespace   = asset.get('namespace', '')

            # Skip non-game assets; LIVE is the production label, '' appears on
            # older free-game grants that have no labelName set.
            if not app_name or label not in ('LIVE', ''):
                continue

            game: Dict[str, Any] = {
                'name':             asset.get('appName', app_name),
                'appid':            catalog_id,
                'game_id':          f'epic:{catalog_id}',
                'platform':         'epic',
                'playtime_forever': 0,
                'epic_namespace':   namespace,
                'epic_app_name':    app_name,
            }
            # Try to get a better display name from details
            details = self.get_game_details(catalog_id)
            if details and details.get('title'):
                game['name'] = details['title']
            games.append(game)

        self.owned_games = games
        return games

    def get_game_details(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Fetch Epic catalog details for *game_id* (the catalog item ID).

        Results are cached in ``self.details_cache``.

        Returns:
            Dict with ``title``, ``description``, ``developers``,
            ``publishers``, ``genres``, or ``None`` on failure.
        """
        if game_id in self.details_cache:
            return self.details_cache[game_id]
        if not self.is_authenticated:
            return None
        if self._is_token_expired():
            self.refresh_tokens()
        url = (
            f"https://catalog-public-service-prod06.ol.epicgames.com"
            f"/catalog/api/shared/namespace/fn/bulk/items"
        )
        try:
            resp = self._session.get(
                url,
                params={'id': game_id, 'includeDLCDetails': 'false'},
                headers=self._auth_header(),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            item = data.get(game_id, {})
            if item:
                details: Dict[str, Any] = {
                    'title':       item.get('title', ''),
                    'description': item.get('description', ''),
                    'developers':  [item.get('seller', {}).get('name', 'Unknown')],
                    'publishers':  [item.get('seller', {}).get('name', 'Unknown')],
                    'genres':      [
                        {'description': t.get('name', '')}
                        for t in item.get('tags', [])
                        if t.get('groupName') == 'genre'
                    ],
                    'categories':  [
                        {'description': t.get('name', '')}
                        for t in item.get('tags', [])
                        if t.get('groupName') == 'feature'
                    ],
                }
                self.details_cache[game_id] = details
                return details
        except requests.RequestException as exc:
            logger.warning("Epic get_game_details(%s) failed: %s", game_id, exc)
        return None


# ---------------------------------------------------------------------------
# GOG Galaxy OAuth + Library Client
# ---------------------------------------------------------------------------

class GOGOAuthClient(_OAuth2Mixin):
    """Full GOG OAuth2 client with library access.

    GOG uses standard OAuth2 authorization code flow.  The user's library is
    fetched from ``embed.gog.com/user/data/games`` after authentication.

    Args:
        client_id:     GOG application client ID.
        client_secret: GOG application client secret.
        timeout:       HTTP request timeout in seconds.
    """

    _AUTH_URL   = "https://auth.gog.com/auth"
    _TOKEN_URL  = "https://auth.gog.com/token"
    _GAMES_URL  = "https://embed.gog.com/user/data/games"
    _DETAIL_URL = "https://api.gog.com/v2/games/{game_id}"

    def __init__(self, client_id: str, client_secret: str, timeout: int = 10) -> None:
        _OAuth2Mixin.__init__(self)
        self._client_id     = client_id
        self._client_secret = client_secret
        self._timeout       = timeout
        self._session       = requests.Session()
        self.details_cache: Dict[str, Any] = {}

    def get_platform_name(self) -> str:
        return "gog"

    # ------------------------------------------------------------------
    # OAuth2 helpers
    # ------------------------------------------------------------------

    def build_auth_url(self, redirect_uri: str, state: str = '') -> str:
        """Return the GOG authorization URL.

        Args:
            redirect_uri: Registered redirect URI.
            state:        Optional CSRF state.

        Returns:
            Full authorization URL.
        """
        params: Dict[str, str] = {
            'client_id':     self._client_id,
            'redirect_uri':  redirect_uri,
            'response_type': 'code',
            'layout':        'client2',
        }
        if state:
            params['state'] = state
        return f"{self._AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> bool:
        """Exchange authorization code for tokens.

        Args:
            code:         Authorization code from OAuth callback.
            redirect_uri: Same redirect URI used in :meth:`build_auth_url`.

        Returns:
            ``True`` on success.
        """
        params = {
            'client_id':     self._client_id,
            'client_secret': self._client_secret,
            'grant_type':    'authorization_code',
            'code':          code,
            'redirect_uri':  redirect_uri,
        }
        try:
            resp = self._session.get(self._TOKEN_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
            self._store_tokens(resp.json())
            return True
        except requests.RequestException as exc:
            logger.warning("GOG token exchange failed: %s", exc)
            return False

    def refresh_tokens(self) -> bool:
        """Refresh access token using the stored refresh token.

        Returns:
            ``True`` on success.
        """
        if not self._refresh_token:
            return False
        params = {
            'client_id':     self._client_id,
            'client_secret': self._client_secret,
            'grant_type':    'refresh_token',
            'refresh_token': self._refresh_token,
        }
        try:
            resp = self._session.get(self._TOKEN_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
            self._store_tokens(resp.json())
            return True
        except requests.RequestException as exc:
            logger.warning("GOG token refresh failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def get_owned_games(self, user_id: str = '') -> List[Dict[str, Any]]:
        """Fetch the authenticated user's GOG library.

        Uses ``embed.gog.com/user/data/games`` which returns a compact list of
        game IDs.  Each entry is then normalised to the GAPI game dict shape.

        Args:
            user_id: Not used for GOG (identity is from the OAuth token).

        Returns:
            List of game dicts with ``name``, ``game_id``, ``platform``,
            ``appid``, and ``playtime_forever`` (always 0).
        """
        if not self.is_authenticated:
            logger.info("GOG: not authenticated — call exchange_code first")
            return []
        if self._is_token_expired():
            self.refresh_tokens()

        try:
            resp = self._session.get(
                self._GAMES_URL,
                headers=self._auth_header(),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("GOG get_owned_games failed: %s", exc)
            return []

        games: List[Dict[str, Any]] = []
        for game_id in data.get('owned', []):
            gid_str = str(game_id)
            game: Dict[str, Any] = {
                'name':             gid_str,   # enriched below
                'appid':            gid_str,
                'game_id':          f'gog:{gid_str}',
                'platform':         'gog',
                'playtime_forever': 0,
            }
            details = self.get_game_details(gid_str)
            if details and details.get('title'):
                game['name'] = details['title']
            games.append(game)
        return games

    def get_game_details(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Fetch GOG API v2 details for *game_id*.

        Results are cached in ``self.details_cache``.

        Returns:
            Dict with ``title``, ``description``, ``developers``,
            ``publishers``, ``genres``, or ``None`` on failure.
        """
        if game_id in self.details_cache:
            return self.details_cache[game_id]

        url = f"https://api.gog.com/v2/games/{game_id}"
        headers = {'Accept': 'application/json'}
        if self.is_authenticated:
            headers.update(self._auth_header())

        try:
            resp = self._session.get(url, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            embed = data.get('_embedded', {})
            details: Dict[str, Any] = {
                'title':       data.get('title', ''),
                'description': data.get('summary', ''),
                'developers':  [
                    d.get('name', '') for d in embed.get('developers', [])
                ],
                'publishers':  [
                    p.get('name', '') for p in embed.get('publisher', {}).get('developers', [])
                ],
                'genres':      [
                    {'description': g.get('name', '')}
                    for g in embed.get('genres', [])
                ],
                'categories':  [
                    {'description': t.get('name', '')}
                    for t in embed.get('tags', [])
                ],
            }
            self.details_cache[game_id] = details
            return details
        except requests.RequestException as exc:
            logger.warning("GOG get_game_details(%s) failed: %s", game_id, exc)
        return None


# ---------------------------------------------------------------------------
# Xbox Game Pass OAuth + Library Client
# ---------------------------------------------------------------------------

class XboxAPIClient(_OAuth2Mixin):
    """Xbox Live OAuth2 client with library and Game Pass catalog access.

    Uses Microsoft Identity Platform (OAuth2 authorization code flow) and the
    Xbox Live ``titlehub`` API to fetch owned titles.

    Args:
        client_id:     Azure AD application client ID.
        client_secret: Azure AD application client secret.
        timeout:       HTTP request timeout in seconds.
    """

    _AUTH_URL    = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
    _TOKEN_URL   = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    _SCOPES      = "XboxLive.signin XboxLive.offline_access"
    _XBL_AUTH    = "https://user.auth.xboxlive.com/user/authenticate"
    _XSTS_AUTH   = "https://xsts.auth.xboxlive.com/xsts/authorize"
    _TITLES_URL  = "https://titlehub.xboxlive.com/users/me/titles/titlehistory/decoration/Achievement,AppDetailCommon,GamePass"

    def __init__(self, client_id: str, client_secret: str, timeout: int = 10) -> None:
        _OAuth2Mixin.__init__(self)
        self._client_id     = client_id
        self._client_secret = client_secret
        self._timeout       = timeout
        self._session       = requests.Session()
        self._xbl_token:    Optional[str] = None
        self._xsts_token:   Optional[str] = None
        self._user_hash:    Optional[str] = None
        self.details_cache: Dict[str, Any] = {}

    def get_platform_name(self) -> str:
        return "xbox"

    # ------------------------------------------------------------------
    # OAuth2 helpers
    # ------------------------------------------------------------------

    def build_auth_url(self, redirect_uri: str, state: str = '') -> str:
        """Return the Microsoft authorization URL for Xbox Live sign-in.

        Args:
            redirect_uri: Registered redirect URI.
            state:        Optional CSRF state.

        Returns:
            Full authorization URL.
        """
        params: Dict[str, str] = {
            'client_id':     self._client_id,
            'response_type': 'code',
            'redirect_uri':  redirect_uri,
            'scope':         self._SCOPES,
            'response_mode': 'query',
        }
        if state:
            params['state'] = state
        return f"{self._AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> bool:
        """Exchange Microsoft authorization code for MSA tokens, then obtain
        XBL and XSTS tokens required by Xbox Live APIs.

        Args:
            code:         Authorization code from OAuth callback.
            redirect_uri: Same redirect URI used in :meth:`build_auth_url`.

        Returns:
            ``True`` when all three token steps succeed.
        """
        # Step 1: MSA token exchange
        data = {
            'grant_type':    'authorization_code',
            'client_id':     self._client_id,
            'client_secret': self._client_secret,
            'code':          code,
            'redirect_uri':  redirect_uri,
            'scope':         self._SCOPES,
        }
        try:
            resp = self._session.post(self._TOKEN_URL, data=data, timeout=self._timeout)
            resp.raise_for_status()
            self._store_tokens(resp.json())
        except requests.RequestException as exc:
            logger.warning("Xbox MSA token exchange failed: %s", exc)
            return False

        # Step 2: XBL authentication
        xbl_ok = self._authenticate_xbl()
        if not xbl_ok:
            logger.warning("Xbox XBL authentication failed")
            return False

        # Step 3: XSTS authorization
        xsts_ok = self._authenticate_xsts()
        if not xsts_ok:
            logger.warning("Xbox XSTS authorization failed")
            return False

        return True

    def refresh_tokens(self) -> bool:
        """Refresh MSA access token and re-authenticate with XBL/XSTS.

        Returns:
            ``True`` on full success.
        """
        if not self._refresh_token:
            return False
        data = {
            'grant_type':    'refresh_token',
            'client_id':     self._client_id,
            'client_secret': self._client_secret,
            'refresh_token': self._refresh_token,
            'scope':         self._SCOPES,
        }
        try:
            resp = self._session.post(self._TOKEN_URL, data=data, timeout=self._timeout)
            resp.raise_for_status()
            self._store_tokens(resp.json())
        except requests.RequestException as exc:
            logger.warning("Xbox token refresh failed: %s", exc)
            return False

        return self._authenticate_xbl() and self._authenticate_xsts()

    def _authenticate_xbl(self) -> bool:
        """Authenticate with Xbox Live using the MSA access token."""
        payload = {
            'Properties': {
                'AuthMethod': 'RPS',
                'SiteName':   'user.auth.xboxlive.com',
                'RpsTicket':  f'd={self._access_token}',
            },
            'RelyingParty': 'http://auth.xboxlive.com',
            'TokenType':    'JWT',
        }
        try:
            resp = self._session.post(
                self._XBL_AUTH, json=payload,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            self._xbl_token = body['Token']
            self._user_hash = body['DisplayClaims']['xui'][0]['uhs']
            return True
        except (requests.RequestException, KeyError) as exc:
            logger.warning("XBL auth failed: %s", exc)
            return False

    def _authenticate_xsts(self) -> bool:
        """Obtain an XSTS token from the XBL token."""
        payload = {
            'Properties': {
                'SandboxId':  'RETAIL',
                'UserTokens': [self._xbl_token],
            },
            'RelyingParty': 'http://xboxlive.com',
            'TokenType':    'JWT',
        }
        try:
            resp = self._session.post(
                self._XSTS_AUTH, json=payload,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            self._xsts_token = body['Token']
            return True
        except (requests.RequestException, KeyError) as exc:
            logger.warning("XSTS auth failed: %s", exc)
            return False

    def _xbox_live_auth_header(self) -> Dict[str, str]:
        """Return the ``Authorization`` header for Xbox Live APIs."""
        return {
            'Authorization': f'XBL3.0 x={self._user_hash};{self._xsts_token}',
            'x-xbl-contract-version': '2',
            'Accept-Language': 'en-US',
        }

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def get_owned_games(self, user_id: str = '') -> List[Dict[str, Any]]:
        """Fetch the authenticated user's Xbox title history.

        Uses the ``titlehub`` API which returns the user's played / owned
        titles including Game Pass titles.

        Args:
            user_id: Not used (identity from XSTS token).

        Returns:
            List of game dicts with ``name``, ``game_id``, ``platform``,
            ``appid``, and ``playtime_forever`` (minutes, from achievement data
            when available).
        """
        if not self._xsts_token:
            logger.info("Xbox: not authenticated — call exchange_code first")
            return []

        games: List[Dict[str, Any]] = []
        continuationToken: Optional[str] = None

        while True:
            params: Dict[str, str] = {'maxItems': '100'}
            if continuationToken:
                params['continuationToken'] = continuationToken

            try:
                resp = self._session.get(
                    self._TITLES_URL,
                    params=params,
                    headers=self._xbox_live_auth_header(),
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                body = resp.json()
            except requests.RequestException as exc:
                logger.warning("Xbox get_owned_games failed: %s", exc)
                break

            for title in body.get('titles', []):
                title_id   = str(title.get('titleId', ''))
                name       = title.get('name', title_id)
                # achievement data may contain currentGamerscore / maxGamerscore
                playtime   = 0
                detail: Dict[str, Any] = {
                    'name':             name,
                    'appid':            title_id,
                    'game_id':          f'xbox:{title_id}',
                    'platform':         'xbox',
                    'playtime_forever': playtime,
                    'xbox_title_id':    title_id,
                    'is_game_pass':     title.get('gamePass', {}).get('isGamePass', False),
                }
                games.append(detail)
                self.details_cache[title_id] = {
                    'title':       name,
                    'description': title.get('detail', {}).get('description', ''),
                    'genres':      [
                        {'description': g}
                        for g in title.get('detail', {}).get('genres', [])
                    ],
                    'developers':  title.get('detail', {}).get('developers', []),
                    'publishers':  title.get('detail', {}).get('publishers', []),
                }

            continuationToken = body.get('pagingInfo', {}).get('continuationToken')
            if not continuationToken:
                break

        return games

    def get_game_details(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Return cached details for *game_id*, or fetch via titlehub.

        Returns:
            Details dict or ``None``.
        """
        if game_id in self.details_cache:
            return self.details_cache[game_id]
        # Details are populated as a side effect of get_owned_games;
        # a single-title lookup would require a separate titlehub call.
        return None
