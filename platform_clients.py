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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_title_image(title: Dict[str, Any]) -> str:
    """Safely extract the image URL from a PSN title dict."""
    image = title.get('image')
    if isinstance(image, dict):
        return image.get('url', '')
    if isinstance(image, str):
        return image
    return ''


# ---------------------------------------------------------------------------
# PlayStation Network Client
# ---------------------------------------------------------------------------

class PSNClient(_OAuth2Mixin):
    """PlayStation Network client using Sony's NPSSO token authentication.

    Sony's PlayStation Network does not have an official public OAuth application
    registration flow for third-party developers.  Instead, users provide their
    **NPSSO token** — a long-lived session token that PlayStation stores in the
    browser cookie ``npsso`` when logged in at ``my.playstation.com``.

    Auth flow
    ---------
    1. User retrieves their NPSSO token from browser cookies (see README).
    2. ``connect(npsso)`` exchanges the NPSSO for a short-lived OAuth access
       token via the Sony SSO endpoint.
    3. Subsequent calls to ``get_owned_games()`` / ``get_trophies()`` use the
       access token, refreshing automatically when it expires.

    Args:
        timeout: HTTP request timeout in seconds.

    Example config::

        "psn_enabled": true,
        "psn_npsso": "YOUR_PSN_NPSSO_TOKEN_HERE"
    """

    _SSO_URL      = "https://ca.account.sony.com/api/authz/v3/oauth/token"
    _EXCHANGE_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token"
    _TITLES_URL   = "https://m.np.playstation.com/api/gamelist/v2/users/me/titles"
    _TROPHIES_URL = "https://m.np.playstation.com/api/trophy/v1/users/me/trophyTitles"
    # Known public client credentials used by the PlayStation Android app.
    # These are widely published in the PlayStation community (PSDLE, psn-php,
    # psnawp, etc.) and are not secret — Sony intentionally ships them in the
    # public Android APK.  They do NOT grant elevated API access; they are
    # required only to complete the standard OAuth2 code-exchange flow for
    # any PSN OAuth application.
    _CLIENT_ID    = "09515159-7237-4370-9b40-3806e67c0891"
    _CLIENT_SECRET = "ucIBBpU6QUVYETxW"
    _SCOPE         = "psn:mobile.v2.core psn:clientapp"

    def __init__(self, timeout: int = 10) -> None:
        _OAuth2Mixin.__init__(self)
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': (
                'PlayStation/21090100 CFNetwork/1126 Darwin/19.5.0'
            )
        })
        self.details_cache: Dict[str, Any] = {}

    def get_platform_name(self) -> str:
        return "psn"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def connect(self, npsso: str) -> bool:
        """Exchange an NPSSO token for a PlayStation Network access token.

        The NPSSO token can be obtained by logging in to
        ``https://my.playstation.com`` and extracting the ``npsso`` cookie
        value (available in browser DevTools → Application → Cookies).

        Args:
            npsso: The NPSSO session token string.

        Returns:
            ``True`` on success, ``False`` on any HTTP or JSON error.
        """
        # Step 1: obtain an authorization code from the SSO endpoint
        auth_code_url = (
            "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
            "?access_type=offline"
            "&client_id=09515159-7237-4370-9b40-3806e67c0891"
            "&redirect_uri=com.scee.psxandroid.sceabroker%3A%2F%2Fpsxbroker"
            "&response_type=code"
            "&scope=psn%3Amobile.v2.core%20psn%3Aclientapp"
        )
        try:
            resp = self._session.get(
                auth_code_url,
                headers={'Cookie': f'npsso={npsso}'},
                allow_redirects=False,
                timeout=self._timeout,
            )
            location = resp.headers.get('Location', '')
            if 'code=' not in location:
                logger.warning("PSN: NPSSO exchange did not return auth code. "
                               "Token may be expired or invalid.")
                return False
            # Extract code from redirect location
            from urllib.parse import urlparse, parse_qs
            parsed  = urlparse(location)
            qs      = parse_qs(parsed.query)
            codes   = qs.get('code', [])
            if not codes:
                return False
            auth_code = codes[0]
        except requests.RequestException as exc:
            logger.warning("PSN: NPSSO → auth code failed: %s", exc)
            return False

        # Step 2: exchange auth code for access + refresh tokens
        data = {
            'code':          auth_code,
            'grant_type':    'authorization_code',
            'redirect_uri':  'com.scee.psxandroid.sceabroker://psxbroker',
            'token_format':  'jwt',
        }
        try:
            resp = self._session.post(
                self._SSO_URL,
                data=data,
                auth=(self._CLIENT_ID, self._CLIENT_SECRET),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            self._store_tokens(resp.json())
            logger.info("PSN: authenticated successfully")
            return True
        except requests.RequestException as exc:
            logger.warning("PSN: token exchange failed: %s", exc)
            return False

    def refresh_tokens(self) -> bool:
        """Refresh the PSN access token using the stored refresh token.

        Returns:
            ``True`` on success.
        """
        if not self._refresh_token:
            return False
        data = {
            'grant_type':    'refresh_token',
            'refresh_token': self._refresh_token,
            'token_format':  'jwt',
            'scope':         self._SCOPE,
        }
        try:
            resp = self._session.post(
                self._SSO_URL,
                data=data,
                auth=(self._CLIENT_ID, self._CLIENT_SECRET),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            self._store_tokens(resp.json())
            return True
        except requests.RequestException as exc:
            logger.warning("PSN: token refresh failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def get_owned_games(self, user_id: str = '') -> List[Dict[str, Any]]:
        """Fetch the authenticated user's PlayStation game library.

        Uses the PSN mobile game-list API to retrieve all titles associated
        with the account, normalised to the GAPI game dict shape.

        Args:
            user_id: Ignored; identity is from the OAuth access token.

        Returns:
            List of game dicts with ``name``, ``game_id``, ``platform``,
            ``appid``, ``playtime_forever`` (always 0 — PSN has no playtime
            API), ``psn_title_id``, and ``concept_id``.
        """
        if not self.is_authenticated:
            logger.info("PSN: not authenticated — call connect(npsso) first")
            return []
        if self._is_token_expired():
            self.refresh_tokens()

        games: List[Dict[str, Any]] = []
        offset = 0
        limit  = 100

        while True:
            try:
                resp = self._session.get(
                    self._TITLES_URL,
                    params={
                        'categories': 'ps4_game,ps5_native_game,pspc_game',
                        'limit':      limit,
                        'offset':     offset,
                    },
                    headers=self._auth_header(),
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                body = resp.json()
            except requests.RequestException as exc:
                logger.warning("PSN get_owned_games failed: %s", exc)
                break

            titles = body.get('titles', [])
            for title in titles:
                title_id   = title.get('titleId', '')
                concept_id = str(title.get('conceptId', ''))
                name       = title.get('name', title_id)
                game: Dict[str, Any] = {
                    'name':             name,
                    'appid':            title_id,
                    'game_id':          f'psn:{title_id}',
                    'platform':         'psn',
                    'playtime_forever': 0,
                    'psn_title_id':     title_id,
                    'concept_id':       concept_id,
                    'category':         title.get('category', ''),
                }
                # Store basic details
                self.details_cache[title_id] = {
                    'title':       name,
                    'description': '',
                    'genres':      [],
                    'developers':  [],
                    'publishers':  [],
                    'image_url':   _extract_title_image(title),
                }
                games.append(game)

            # Paginate
            total  = body.get('totalItemCount', len(titles))
            offset += len(titles)
            if offset >= total or not titles:
                break

        return games

    def get_game_details(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Return cached details for *game_id* (PSN title ID).

        Returns:
            Details dict or ``None``.
        """
        return self.details_cache.get(game_id)

    def get_trophies(self, account_id: str = 'me') -> List[Dict[str, Any]]:
        """Fetch trophy titles for the authenticated user.

        Args:
            account_id: PSN account ID (default ``'me'`` for authenticated user).

        Returns:
            List of trophy-title dicts with ``npServiceName``, ``trophySetVersion``,
            ``trophyTitleName``, ``npCommunicationId``, and progress fields.
        """
        if not self.is_authenticated:
            return []
        if self._is_token_expired():
            self.refresh_tokens()

        trophies: List[Dict[str, Any]] = []
        offset = 0
        limit  = 100

        while True:
            url = self._TROPHIES_URL.replace('/me/', f'/{account_id}/')
            try:
                resp = self._session.get(
                    url,
                    params={'limit': limit, 'offset': offset},
                    headers=self._auth_header(),
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                body = resp.json()
            except requests.RequestException as exc:
                logger.warning("PSN get_trophies failed: %s", exc)
                break

            items  = body.get('trophyTitles', [])
            trophies.extend(items)
            total   = body.get('totalItemCount', len(items))
            offset += len(items)
            if offset >= total or not items:
                break

        return trophies


# ---------------------------------------------------------------------------
# Nintendo eShop Client (public catalog only — no library API available)
# ---------------------------------------------------------------------------

class NintendoEShopClient:
    """Nintendo eShop client for public catalog browsing and price lookup.

    Nintendo does not provide a public API for user game libraries.  This
    client uses Nintendo's public *algolia*-powered eShop search API (same
    backend used by the Nintendo website) to browse and search the game
    catalog.

    Region support
    --------------
    The Nintendo eShop has separate regional storefronts.  Supported
    ``region`` values: ``US``, ``EU``, ``JP``.

    Args:
        region:  Store region (default ``"US"``).
        timeout: HTTP request timeout in seconds.

    Note:
        Library access is **not available** without an official Nintendo
        developer API agreement.  This client is catalog-only.
    """

    # Public Algolia credentials used by Nintendo's own website.
    # App ID and API key are the same for all regions; only the index name
    # varies by region/language.
    _ALGOLIA_APP_ID  = 'U3B6GR4UA3'
    _ALGOLIA_API_KEY = '9a20c93440cf63cf1a7008d75f7438bf'
    _ALGOLIA_INDICES: Dict[str, str] = {
        'US': 'noa_aem_game_en_us',
        'EU': 'noa_aem_game_en_gb',
        'JP': 'noa_aem_game_ja_jp',
    }
    _ALGOLIA_SEARCH_URL = (
        "https://{app_id}-dsn.algolia.net/1/indexes/{index}/query"
    )
    _PRICE_URL = "https://api.ec.nintendo.com/v1/price"

    def __init__(self, region: str = 'US', timeout: int = 10) -> None:
        self._region  = region.upper()
        self._timeout = timeout
        self._session = requests.Session()
        self.details_cache: Dict[str, Any] = {}

    def get_platform_name(self) -> str:
        return "nintendo"

    def _algolia_headers(self) -> Dict[str, str]:
        return {
            'X-Algolia-Application-Id': self._ALGOLIA_APP_ID,
            'X-Algolia-API-Key':        self._ALGOLIA_API_KEY,
            'Content-Type':             'application/json',
        }

    def search_games(
        self,
        query: str = '',
        filters: str = '',
        page: int = 0,
        hits_per_page: int = 50,
    ) -> Dict[str, Any]:
        """Search the Nintendo eShop catalog.

        Args:
            query:         Free-text search term.  Empty string returns all
                           games sorted by relevance / popularity.
            filters:       Algolia filter string (e.g.
                           ``'playerFilters:1-4 players'``).
            page:          Zero-based page number.
            hits_per_page: Results per page (max 100).

        Returns:
            Dict with ``hits`` (list of game dicts), ``nbHits`` (total count),
            ``page``, and ``nbPages``.  Each hit includes ``title``,
            ``nsuid``, ``url``, ``players``, ``categories``, ``platform``,
            ``releaseDate``, and ``msrp``.
        """
        app_id = self._ALGOLIA_APP_ID
        index  = self._ALGOLIA_INDICES.get(self._region, self._ALGOLIA_INDICES['US'])
        url    = self._ALGOLIA_SEARCH_URL.format(app_id=app_id, index=index)

        payload: Dict[str, Any] = {
            'params': f'query={urllib.parse.quote(query)}'
                      f'&hitsPerPage={hits_per_page}'
                      f'&page={page}'
                      + (f'&filters={urllib.parse.quote(filters)}' if filters else ''),
        }
        try:
            resp = self._session.post(
                url,
                json=payload,
                headers=self._algolia_headers(),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            # Normalise hits to GAPI-friendly dicts
            hits = []
            for hit in data.get('hits', []):
                nsuid = hit.get('nsuid', '')
                game: Dict[str, Any] = {
                    'title':       hit.get('title', ''),
                    'nsuid':       nsuid,
                    'url':         'https://www.nintendo.com' + hit.get('url', ''),
                    'description': hit.get('description', ''),
                    'players':     hit.get('players', ''),
                    'categories':  hit.get('categories', []),
                    'platform':    hit.get('platform', 'Nintendo Switch'),
                    'releaseDate': hit.get('releaseDate', ''),
                    'msrp':        hit.get('msrp', 0),
                    'publishers':  hit.get('publishers', []),
                    'developers':  hit.get('developers', []),
                    'esrb':        hit.get('esrb', ''),
                    'boxart':      hit.get('boxart', ''),
                    # GAPI-standard keys
                    'name':             hit.get('title', ''),
                    'game_id':          f'nintendo:{nsuid}',
                    'appid':            nsuid,
                    'playtime_forever': 0,
                    'source':           'nintendo',
                }
                if nsuid:
                    self.details_cache[nsuid] = game
                hits.append(game)

            return {
                'hits':     hits,
                'nbHits':   data.get('nbHits', 0),
                'page':     data.get('page', 0),
                'nbPages':  data.get('nbPages', 0),
            }
        except requests.RequestException as exc:
            logger.warning("Nintendo search_games failed: %s", exc)
            return {'hits': [], 'nbHits': 0, 'page': 0, 'nbPages': 0}

    def get_game_by_nsuid(self, nsuid: str) -> Optional[Dict[str, Any]]:
        """Return details for a game by its *nsuid* (Nintendo Switch unique ID).

        Checks the in-process cache first.  Fetches price data from the
        Nintendo price API to enrich the result.

        Args:
            nsuid: The 14-digit Nintendo Switch game ID.

        Returns:
            Game detail dict or ``None``.
        """
        if nsuid in self.details_cache:
            # Enrich with current price if not yet fetched
            entry = self.details_cache[nsuid]
            if 'current_price' not in entry:
                self._enrich_price(nsuid, entry)
            return entry
        return None

    def get_prices(self, nsuids: List[str], country: str = 'US') -> Dict[str, Any]:
        """Fetch current eShop prices for one or more games.

        Uses Nintendo's public price API which requires no authentication.

        Args:
            nsuids:  List of 14-digit nsuid strings (up to 50 per request).
            country: Two-letter ISO country code (default ``"US"``).

        Returns:
            Dict mapping nsuid → ``{'regular_price': ..., 'discount_price': ...}``.
        """
        result: Dict[str, Any] = {}
        # API accepts up to 50 nsuids per call
        for chunk_start in range(0, len(nsuids), 50):
            chunk = nsuids[chunk_start: chunk_start + 50]
            try:
                resp = self._session.get(
                    self._PRICE_URL,
                    params={
                        'country': country,
                        'lang':    'en',
                        'ids':     ','.join(chunk),
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                for price_data in data.get('prices', []):
                    nsuid_str = str(price_data.get('title_id', ''))
                    regular   = price_data.get('regular_price', {})
                    discount  = price_data.get('discount_price', {})
                    result[nsuid_str] = {
                        'regular_price':        regular.get('raw_value'),
                        'regular_price_str':    regular.get('amount', ''),
                        'discount_price':       discount.get('raw_value') if discount else None,
                        'discount_price_str':   discount.get('amount', '') if discount else '',
                        'sales_status':         price_data.get('sales_status', ''),
                    }
            except requests.RequestException as exc:
                logger.warning("Nintendo get_prices failed: %s", exc)
        return result

    def _enrich_price(self, nsuid: str, entry: Dict[str, Any]) -> None:
        """Add current price data to *entry* in-place."""
        prices = self.get_prices([nsuid])
        if nsuid in prices:
            entry['current_price']     = prices[nsuid].get('regular_price')
            entry['current_price_str'] = prices[nsuid].get('regular_price_str', '')
            entry['discount_price']    = prices[nsuid].get('discount_price')
            entry['sales_status']      = prices[nsuid].get('sales_status', '')

    # ------------------------------------------------------------------
    # Stub (no library API available)
    # ------------------------------------------------------------------

    def get_owned_games(self, user_id: str = '') -> List[Dict[str, Any]]:
        """Not available — Nintendo has no public library API.

        Returns an empty list.  Use :meth:`search_games` to browse the
        catalog instead.
        """
        logger.info(
            "Nintendo eShop library access is not available via a public API. "
            "Use search_games() to browse the catalog."
        )
        return []
