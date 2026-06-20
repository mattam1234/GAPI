"""Platform-integrations domain (migrated to FastAPI).

Account-link / OAuth / library-fetch routes for five external storefronts:
Epic Games, GOG Galaxy, Xbox Game Pass, PlayStation Network, and the Nintendo
eShop. Each storefront gets its own ``APIRouter`` keyed on its ``/api/<plat>``
prefix. All handlers reuse the legacy singletons via ``gapi_gui`` at CALL TIME:

  * ``gapi_gui.picker``                  — the active GamePicker (holds ``clients``)
  * ``gapi_gui._get_platform_client``    — resolves the per-user client
  * ``gapi_gui.secrets``                 — OAuth state generation
  * the ``platform_clients`` classes     — for ``isinstance`` config checks

OAuth seam
----------
The legacy authorize routes wrote ``session['<plat>_oauth_state'] = state`` and
issued a Flask 302 redirect. To preserve that exactly, the FastAPI versions
merge ``<plat>_oauth_state`` into the existing Flask session payload and re-sign
the same session cookie onto a ``RedirectResponse`` (mirroring
``backend.routers.auth``). The default redirect URI is derived from
``request.base_url`` (the FastAPI equivalent of Flask's ``request.url_root``).

These routes make outbound HTTP to the storefront APIs through the platform
clients; tests MUST mock those clients — no route here performs network I/O on
its own.

Routes:
  Epic:     GET /api/epic/oauth/authorize  GET /api/epic/oauth/callback  GET /api/epic/library
  GOG:      GET /api/gog/oauth/authorize   GET /api/gog/oauth/callback   GET /api/gog/library
  Xbox:     GET /api/xbox/oauth/authorize  GET /api/xbox/oauth/callback  GET /api/xbox/library
  PSN:      POST /api/psn/connect          GET /api/psn/library          GET /api/psn/trophies
  Nintendo: GET /api/nintendo/search       GET /api/nintendo/game/{nsuid} GET /api/nintendo/prices
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

import gapi_gui
from backend.dependencies import require_login

psn_router = APIRouter(prefix="/api/psn", tags=["platforms"])
xbox_router = APIRouter(prefix="/api/xbox", tags=["platforms"])
epic_router = APIRouter(prefix="/api/epic", tags=["platforms"])
gog_router = APIRouter(prefix="/api/gog", tags=["platforms"])
nintendo_router = APIRouter(prefix="/api/nintendo", tags=["platforms"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


def _default_redirect_uri(request: Request, callback_path: str) -> str:
    """Build ``<scheme>://<host>/api/<plat>/oauth/callback`` from the request.

    FastAPI's ``request.base_url`` ends with a trailing ``/`` just like Flask's
    ``request.url_root``; ``.rstrip('/')`` then yields the same origin string.
    """
    return str(request.base_url).rstrip("/") + callback_path


def _redirect_with_state(request: Request, url: str, state_key: str,
                         state: str) -> RedirectResponse:
    """302 to *url*, persisting ``state_key=state`` in the Flask session cookie.

    Mirrors the legacy ``session['<plat>_oauth_state'] = state`` write so the
    later callback can validate CSRF state against the same cookie.
    """
    from backend.dependencies import _load_flask_session
    from backend.routers.auth import _set_session_cookie

    session_data = _load_flask_session(request)
    session_data[state_key] = state
    resp = RedirectResponse(url=url, status_code=302)
    _set_session_cookie(resp, session_data)
    return resp


# ---------------------------------------------------------------------------
# Epic Games
# ---------------------------------------------------------------------------

@epic_router.get("/oauth/authorize")
def api_epic_oauth_authorize(request: Request, _user: str = Depends(require_login)):
    """Redirect the browser to the Epic Games authorization page."""
    g = gapi_gui
    from platform_clients import EpicOAuthClient
    client = g._get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return _err(503, 'Epic OAuth client not configured. '
                    'Add epic_client_id and epic_enabled: true to config.json.')
    redirect_uri = request.query_params.get('redirect_uri') or (
        g.picker.config.get('epic_redirect_uri', '') if g.picker else ''
    )
    if not redirect_uri:
        redirect_uri = _default_redirect_uri(request, '/api/epic/oauth/callback')
    state = g.secrets.token_urlsafe(16)
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return _redirect_with_state(request, url, 'epic_oauth_state', state)


@epic_router.get("/oauth/callback")
def api_epic_oauth_callback(request: Request, _user: str = Depends(require_login)):
    """Handle the Epic Games OAuth2 callback."""
    g = gapi_gui
    from platform_clients import EpicOAuthClient
    client = g._get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return _err(503, 'Epic OAuth client not configured.')
    code = request.query_params.get('code', '')
    if not code:
        return _err(400, 'Missing authorization code.')
    redirect_uri = (g.picker.config.get('epic_redirect_uri', '') if g.picker else '') or (
        _default_redirect_uri(request, '/api/epic/oauth/callback')
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return _err(400, 'Token exchange failed. Check server logs.')
    return {'success': True, 'platform': 'epic'}


@epic_router.get("/library")
def api_epic_library(_user: str = Depends(require_login)):
    """Return the authenticated user's Epic Games library."""
    g = gapi_gui
    from platform_clients import EpicOAuthClient
    client = g._get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return _err(503, 'Epic OAuth client not configured.')
    if not client.is_authenticated:
        return _err(503, 'Epic account not authenticated. '
                    'Visit /api/epic/oauth/authorize first.')
    games = client.get_owned_games()
    return {'games': games, 'count': len(games), 'platform': 'epic'}


# ---------------------------------------------------------------------------
# GOG Galaxy
# ---------------------------------------------------------------------------

@gog_router.get("/oauth/authorize")
def api_gog_oauth_authorize(request: Request, _user: str = Depends(require_login)):
    """Redirect the browser to the GOG Galaxy authorization page."""
    g = gapi_gui
    from platform_clients import GOGOAuthClient
    client = g._get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return _err(503, 'GOG OAuth client not configured. '
                    'Add gog_client_id and gog_enabled: true to config.json.')
    redirect_uri = (g.picker.config.get('gog_redirect_uri', '') if g.picker else '') or (
        _default_redirect_uri(request, '/api/gog/oauth/callback')
    )
    state = g.secrets.token_urlsafe(16)
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return _redirect_with_state(request, url, 'gog_oauth_state', state)


@gog_router.get("/oauth/callback")
def api_gog_oauth_callback(request: Request, _user: str = Depends(require_login)):
    """Handle the GOG Galaxy OAuth2 callback."""
    g = gapi_gui
    from platform_clients import GOGOAuthClient
    client = g._get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return _err(503, 'GOG OAuth client not configured.')
    code = request.query_params.get('code', '')
    if not code:
        return _err(400, 'Missing authorization code.')
    redirect_uri = (g.picker.config.get('gog_redirect_uri', '') if g.picker else '') or (
        _default_redirect_uri(request, '/api/gog/oauth/callback')
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return _err(400, 'Token exchange failed. Check server logs.')
    return {'success': True, 'platform': 'gog'}


@gog_router.get("/library")
def api_gog_library(_user: str = Depends(require_login)):
    """Return the authenticated user's GOG library."""
    g = gapi_gui
    from platform_clients import GOGOAuthClient
    client = g._get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return _err(503, 'GOG OAuth client not configured.')
    if not client.is_authenticated:
        return _err(503, 'GOG account not authenticated. '
                    'Visit /api/gog/oauth/authorize first.')
    games = client.get_owned_games()
    return {'games': games, 'count': len(games), 'platform': 'gog'}


# ---------------------------------------------------------------------------
# Xbox Game Pass
# ---------------------------------------------------------------------------

@xbox_router.get("/oauth/authorize")
def api_xbox_oauth_authorize(request: Request, _user: str = Depends(require_login)):
    """Redirect the browser to the Microsoft/Xbox authorization page."""
    g = gapi_gui
    from platform_clients import XboxAPIClient
    client = g._get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return _err(503, 'Xbox OAuth client not configured. '
                    'Add xbox_client_id and xbox_enabled: true to config.json.')
    redirect_uri = (g.picker.config.get('xbox_redirect_uri', '') if g.picker else '') or (
        _default_redirect_uri(request, '/api/xbox/oauth/callback')
    )
    state = g.secrets.token_urlsafe(16)
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return _redirect_with_state(request, url, 'xbox_oauth_state', state)


@xbox_router.get("/oauth/callback")
def api_xbox_oauth_callback(request: Request, _user: str = Depends(require_login)):
    """Handle the Microsoft/Xbox OAuth2 callback."""
    g = gapi_gui
    from platform_clients import XboxAPIClient
    client = g._get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return _err(503, 'Xbox OAuth client not configured.')
    code = request.query_params.get('code', '')
    if not code:
        return _err(400, 'Missing authorization code.')
    redirect_uri = (g.picker.config.get('xbox_redirect_uri', '') if g.picker else '') or (
        _default_redirect_uri(request, '/api/xbox/oauth/callback')
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return _err(400, 'Token exchange failed. Check server logs.')
    return {'success': True, 'platform': 'xbox'}


@xbox_router.get("/library")
def api_xbox_library(_user: str = Depends(require_login)):
    """Return the authenticated user's Xbox title history / Game Pass library."""
    g = gapi_gui
    from platform_clients import XboxAPIClient
    client = g._get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return _err(503, 'Xbox OAuth client not configured.')
    if not client._xsts_token:
        return _err(503, 'Xbox account not authenticated. '
                    'Visit /api/xbox/oauth/authorize first.')
    games = client.get_owned_games()
    return {'games': games, 'count': len(games), 'platform': 'xbox'}


# ---------------------------------------------------------------------------
# PlayStation Network
# ---------------------------------------------------------------------------

@psn_router.post("/connect")
def api_psn_connect(body: Optional[dict] = Body(default=None),
                    _user: str = Depends(require_login)):
    """Authenticate with PlayStation Network using an NPSSO token."""
    g = gapi_gui
    from platform_clients import PSNClient
    if not g.picker:
        return _err(400, 'Not initialized.')
    client = g.picker.clients.get('psn')
    if not isinstance(client, PSNClient):
        # Auto-create a PSN client if not already configured
        from platform_clients import PSNClient as _PSN
        client = _PSN(timeout=g.picker.API_TIMEOUT)
        g.picker.clients['psn'] = client
    data = body or {}
    npsso = data.get('npsso', '').strip()
    if not npsso:
        return _err(400, 'Missing npsso token in request body.')
    ok = client.connect(npsso)
    if not ok:
        return _err(400,
                    'PSN authentication failed. '
                    'The NPSSO token may be expired or invalid. '
                    'Please obtain a fresh token from https://my.playstation.com')
    return {'success': True, 'platform': 'psn'}


@psn_router.get("/library")
def api_psn_library(_user: str = Depends(require_login)):
    """Return the authenticated user's PlayStation game library."""
    g = gapi_gui
    from platform_clients import PSNClient
    client = g.picker.clients.get('psn') if g.picker else None
    if not isinstance(client, PSNClient):
        return _err(503, 'PSN client not configured. '
                    'POST /api/psn/connect with your npsso token first.')
    if not client.is_authenticated:
        return _err(503, 'PSN account not authenticated. '
                    'POST /api/psn/connect with your npsso token first.')
    games = client.get_owned_games()
    return {'games': games, 'count': len(games), 'platform': 'psn'}


@psn_router.get("/trophies")
def api_psn_trophies(_user: str = Depends(require_login)):
    """Return the authenticated user's PlayStation trophy titles."""
    g = gapi_gui
    from platform_clients import PSNClient
    client = g.picker.clients.get('psn') if g.picker else None
    if not isinstance(client, PSNClient):
        return _err(503, 'PSN client not configured.')
    if not client.is_authenticated:
        return _err(503, 'PSN account not authenticated.')
    trophies = client.get_trophies()
    return {'trophyTitles': trophies, 'count': len(trophies), 'platform': 'psn'}


# ---------------------------------------------------------------------------
# Nintendo eShop
# ---------------------------------------------------------------------------

@nintendo_router.get("/search")
def api_nintendo_search(request: Request, _user: str = Depends(require_login)):
    """Search the Nintendo eShop catalog."""
    g = gapi_gui
    from platform_clients import NintendoEShopClient
    client = g.picker.clients.get('nintendo') if g.picker else None
    if not isinstance(client, NintendoEShopClient):
        # Auto-create a Nintendo client if not configured
        if g.picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=g.picker.API_TIMEOUT)
            g.picker.clients['nintendo'] = client
        else:
            return _err(503, 'Nintendo client not configured. '
                        'Add nintendo_enabled: true to config.json.')

    args = request.query_params
    query = args.get('q', '')
    page = max(0, int(args.get('page', 0)))
    per_page = max(1, min(int(args.get('per_page', 20)), 100))
    filters = args.get('filters', '')

    result = client.search_games(
        query=query,
        filters=filters,
        page=page,
        hits_per_page=per_page,
    )
    result['platform'] = 'nintendo'
    return result


@nintendo_router.get("/game/{nsuid}")
def api_nintendo_game(nsuid: str, _user: str = Depends(require_login)):
    """Return details for a single Nintendo Switch game by nsuid."""
    g = gapi_gui
    from platform_clients import NintendoEShopClient
    client = g.picker.clients.get('nintendo') if g.picker else None
    if not isinstance(client, NintendoEShopClient):
        if g.picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=g.picker.API_TIMEOUT)
            g.picker.clients['nintendo'] = client
        else:
            return _err(503, 'Nintendo client not configured.')

    game = client.get_game_by_nsuid(nsuid)
    if game is None:
        # Try to search for it
        result = client.search_games(query='', page=0, hits_per_page=1)
        game = client.get_game_by_nsuid(nsuid)
    if game is None:
        return _err(404, f'Game {nsuid} not found in cache. '
                    'Search for it first via /api/nintendo/search.')
    return {'game': game, 'platform': 'nintendo'}


@nintendo_router.get("/prices")
def api_nintendo_prices(request: Request, _user: str = Depends(require_login)):
    """Fetch current eShop prices for one or more games."""
    g = gapi_gui
    from platform_clients import NintendoEShopClient
    client = g.picker.clients.get('nintendo') if g.picker else None
    if not isinstance(client, NintendoEShopClient):
        if g.picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=g.picker.API_TIMEOUT)
            g.picker.clients['nintendo'] = client
        else:
            return _err(503, 'Nintendo client not configured.')

    args = request.query_params
    nsuids_param = args.get('nsuids', '')
    nsuids = [n.strip() for n in nsuids_param.split(',') if n.strip()]
    if not nsuids:
        return _err(400, 'Provide one or more nsuids as ?nsuids=id1,id2')
    country = args.get('country', 'US')
    prices = client.get_prices(nsuids=nsuids, country=country)
    return {'prices': prices, 'platform': 'nintendo'}
