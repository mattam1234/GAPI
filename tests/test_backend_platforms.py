#!/usr/bin/env python3
"""Tests for the migrated platform-integrations domain (FastAPI).

Covers all 15 routes across five storefront routers:

  Epic:     GET /api/epic/oauth/authorize   GET /api/epic/oauth/callback   GET /api/epic/library
  GOG:      GET /api/gog/oauth/authorize    GET /api/gog/oauth/callback    GET /api/gog/library
  Xbox:     GET /api/xbox/oauth/authorize   GET /api/xbox/oauth/callback   GET /api/xbox/library
  PSN:      POST /api/psn/connect           GET /api/psn/library           GET /api/psn/trophies
  Nintendo: GET /api/nintendo/search        GET /api/nintendo/game/{nsuid} GET /api/nintendo/prices

The platform clients (which perform outbound HTTP) and the per-user picker live
on gapi_gui and are mocked so the tests never touch a real network or DB.

Run with:
    python -m pytest tests/test_backend_platforms.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
import platform_clients
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _patch_client(platform, client):
    """Patch gapi_gui._get_platform_client to return *client* for *platform*."""
    def _fake(p):
        return client if p == platform else None
    return patch.object(gapi_gui, '_get_platform_client', side_effect=_fake)


def _fake_picker(clients=None):
    p = MagicMock()
    p.clients = clients if clients is not None else {}
    p.config = {}
    p.API_TIMEOUT = 10
    return p


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating (401 for every route) ───────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_all_routes_require_login(self):
        cases = [
            ('get', '/api/epic/oauth/authorize'),
            ('get', '/api/epic/oauth/callback'),
            ('get', '/api/epic/library'),
            ('get', '/api/gog/oauth/authorize'),
            ('get', '/api/gog/oauth/callback'),
            ('get', '/api/gog/library'),
            ('get', '/api/xbox/oauth/authorize'),
            ('get', '/api/xbox/oauth/callback'),
            ('get', '/api/xbox/library'),
            ('post', '/api/psn/connect'),
            ('get', '/api/psn/library'),
            ('get', '/api/psn/trophies'),
            ('get', '/api/nintendo/search'),
            ('get', '/api/nintendo/game/70010000000025'),
            ('get', '/api/nintendo/prices'),
        ]
        for method, path in cases:
            with self.subTest(path=path):
                fn = getattr(self.client, method)
                kwargs = {'follow_redirects': False} if method == 'get' else {}
                if method == 'post':
                    kwargs['json'] = {}
                resp = fn(path, **kwargs)
                self.assertEqual(resp.status_code, 401, path)


# ── Epic ────────────────────────────────────────────────────────────────────

class EpicTest(_AuthedCase):
    def test_authorize_redirects_and_sets_state(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        client.build_auth_url.return_value = 'https://epic.example/authorize?x=1'
        with _patch_client('epic', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/epic/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['location'], 'https://epic.example/authorize?x=1')
        # the redirect re-signs the session cookie carrying the oauth state
        self.assertIn('session', resp.headers.get('set-cookie', ''))
        client.build_auth_url.assert_called_once()

    def test_authorize_not_configured_503(self):
        with _patch_client('epic', object()), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/epic/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not configured', resp.json()['error'])

    def test_callback_success(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        client.exchange_code.return_value = True
        with _patch_client('epic', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/epic/oauth/callback?code=abc')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'platform': 'epic'})

    def test_callback_missing_code_400(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        with _patch_client('epic', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/epic/oauth/callback')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Missing authorization code.')

    def test_callback_exchange_failed_400(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        client.exchange_code.return_value = False
        with _patch_client('epic', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/epic/oauth/callback?code=abc')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Token exchange failed. Check server logs.')

    def test_library_success(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        client.is_authenticated = True
        client.get_owned_games.return_value = [{'name': 'A'}, {'name': 'B'}]
        with _patch_client('epic', client):
            resp = self.client.get('/api/epic/library')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'games': [{'name': 'A'}, {'name': 'B'}],
                                       'count': 2, 'platform': 'epic'})

    def test_library_not_authenticated_503(self):
        client = MagicMock(spec=platform_clients.EpicOAuthClient)
        client.is_authenticated = False
        with _patch_client('epic', client):
            resp = self.client.get('/api/epic/library')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not authenticated', resp.json()['error'])


# ── GOG ──────────────────────────────────────────────────────────────────────

class GogTest(_AuthedCase):
    def test_authorize_redirects(self):
        client = MagicMock(spec=platform_clients.GOGOAuthClient)
        client.build_auth_url.return_value = 'https://gog.example/auth'
        with _patch_client('gog', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/gog/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['location'], 'https://gog.example/auth')

    def test_authorize_not_configured_503(self):
        with _patch_client('gog', object()), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/gog/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 503)

    def test_callback_success(self):
        client = MagicMock(spec=platform_clients.GOGOAuthClient)
        client.exchange_code.return_value = True
        with _patch_client('gog', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/gog/oauth/callback?code=xyz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'platform': 'gog'})

    def test_callback_missing_code_400(self):
        client = MagicMock(spec=platform_clients.GOGOAuthClient)
        with _patch_client('gog', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/gog/oauth/callback')
        self.assertEqual(resp.status_code, 400)

    def test_library_success(self):
        client = MagicMock(spec=platform_clients.GOGOAuthClient)
        client.is_authenticated = True
        client.get_owned_games.return_value = [{'name': 'G'}]
        with _patch_client('gog', client):
            resp = self.client.get('/api/gog/library')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'games': [{'name': 'G'}], 'count': 1,
                                       'platform': 'gog'})

    def test_library_not_authenticated_503(self):
        client = MagicMock(spec=platform_clients.GOGOAuthClient)
        client.is_authenticated = False
        with _patch_client('gog', client):
            resp = self.client.get('/api/gog/library')
        self.assertEqual(resp.status_code, 503)


# ── Xbox ──────────────────────────────────────────────────────────────────────

class XboxTest(_AuthedCase):
    def test_authorize_redirects(self):
        client = MagicMock(spec=platform_clients.XboxAPIClient)
        client.build_auth_url.return_value = 'https://xbox.example/auth'
        with _patch_client('xbox', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/xbox/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['location'], 'https://xbox.example/auth')

    def test_authorize_not_configured_503(self):
        with _patch_client('xbox', object()), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/xbox/oauth/authorize', follow_redirects=False)
        self.assertEqual(resp.status_code, 503)

    def test_callback_success(self):
        client = MagicMock(spec=platform_clients.XboxAPIClient)
        client.exchange_code.return_value = True
        with _patch_client('xbox', client), patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/xbox/oauth/callback?code=abc')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'platform': 'xbox'})

    def test_library_success(self):
        client = MagicMock(spec=platform_clients.XboxAPIClient)
        client._xsts_token = 'tok'
        client.get_owned_games.return_value = [{'name': 'X'}]
        with _patch_client('xbox', client):
            resp = self.client.get('/api/xbox/library')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'games': [{'name': 'X'}], 'count': 1,
                                       'platform': 'xbox'})

    def test_library_not_authenticated_503(self):
        client = MagicMock(spec=platform_clients.XboxAPIClient)
        client._xsts_token = None
        with _patch_client('xbox', client):
            resp = self.client.get('/api/xbox/library')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not authenticated', resp.json()['error'])


# ── PSN ───────────────────────────────────────────────────────────────────────

class PsnConnectTest(_AuthedCase):
    def test_success_with_existing_client(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.connect.return_value = True
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.post('/api/psn/connect', json={'npsso': 'tok'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'platform': 'psn'})
        client.connect.assert_called_once_with('tok')

    def test_auto_creates_client_when_missing(self):
        # No psn client configured -> the route constructs a real PSNClient and
        # stores it on picker.clients. connect() (outbound HTTP) is mocked.
        picker = _fake_picker({})
        with patch.object(gapi_gui, 'picker', picker), \
                patch.object(platform_clients.PSNClient, 'connect', return_value=True):
            resp = self.client.post('/api/psn/connect', json={'npsso': 'tok'})
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(picker.clients['psn'], platform_clients.PSNClient)

    def test_no_picker_400(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.post('/api/psn/connect', json={'npsso': 'tok'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Not initialized.')

    def test_missing_npsso_400(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.post('/api/psn/connect', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Missing npsso token in request body.')

    def test_connect_failure_400(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.connect.return_value = False
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.post('/api/psn/connect', json={'npsso': 'tok'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('PSN authentication failed', resp.json()['error'])


class PsnLibraryTest(_AuthedCase):
    def test_success(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.is_authenticated = True
        client.get_owned_games.return_value = [{'name': 'P'}]
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'games': [{'name': 'P'}], 'count': 1,
                                       'platform': 'psn'})

    def test_not_configured_503(self):
        picker = _fake_picker({})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not configured', resp.json()['error'])

    def test_not_authenticated_503(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.is_authenticated = False
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not authenticated', resp.json()['error'])


class PsnTrophiesTest(_AuthedCase):
    def test_success(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.is_authenticated = True
        client.get_trophies.return_value = [{'t': 1}, {'t': 2}]
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/trophies')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'trophyTitles': [{'t': 1}, {'t': 2}],
                                       'count': 2, 'platform': 'psn'})

    def test_not_configured_503(self):
        picker = _fake_picker({})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/trophies')
        self.assertEqual(resp.status_code, 503)

    def test_not_authenticated_503(self):
        client = MagicMock(spec=platform_clients.PSNClient)
        client.is_authenticated = False
        picker = _fake_picker({'psn': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/psn/trophies')
        self.assertEqual(resp.status_code, 503)


# ── Nintendo ──────────────────────────────────────────────────────────────────

class NintendoSearchTest(_AuthedCase):
    def test_success(self):
        client = MagicMock(spec=platform_clients.NintendoEShopClient)
        client.search_games.return_value = {'hits': [], 'nbHits': 0, 'page': 0, 'nbPages': 0}
        picker = _fake_picker({'nintendo': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/nintendo/search?q=mario&page=1&per_page=10')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['platform'], 'nintendo')
        client.search_games.assert_called_once_with(
            query='mario', filters='', page=1, hits_per_page=10)

    def test_auto_creates_client_when_missing(self):
        # No nintendo client configured -> the route constructs a real
        # NintendoEShopClient. search_games() (outbound HTTP) is mocked.
        picker = _fake_picker({})
        with patch.object(gapi_gui, 'picker', picker), \
                patch.object(platform_clients.NintendoEShopClient, 'search_games',
                             return_value={'hits': []}):
            resp = self.client.get('/api/nintendo/search')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(picker.clients['nintendo'],
                              platform_clients.NintendoEShopClient)

    def test_no_picker_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/nintendo/search')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('not configured', resp.json()['error'])


class NintendoGameTest(_AuthedCase):
    def test_success_cached(self):
        client = MagicMock(spec=platform_clients.NintendoEShopClient)
        client.get_game_by_nsuid.return_value = {'title': 'Zelda'}
        picker = _fake_picker({'nintendo': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/nintendo/game/70010000000025')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'game': {'title': 'Zelda'}, 'platform': 'nintendo'})

    def test_not_found_404(self):
        client = MagicMock(spec=platform_clients.NintendoEShopClient)
        client.get_game_by_nsuid.return_value = None
        client.search_games.return_value = {'hits': []}
        picker = _fake_picker({'nintendo': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/nintendo/game/99999999999999')
        self.assertEqual(resp.status_code, 404)
        self.assertIn('not found in cache', resp.json()['error'])

    def test_no_picker_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/nintendo/game/123')
        self.assertEqual(resp.status_code, 503)


class NintendoPricesTest(_AuthedCase):
    def test_success(self):
        client = MagicMock(spec=platform_clients.NintendoEShopClient)
        client.get_prices.return_value = {'70010000000025': {'regular_price': '59.99'}}
        picker = _fake_picker({'nintendo': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/nintendo/prices?nsuids=70010000000025,123&country=GB')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['platform'], 'nintendo')
        client.get_prices.assert_called_once_with(
            nsuids=['70010000000025', '123'], country='GB')

    def test_missing_nsuids_400(self):
        client = MagicMock(spec=platform_clients.NintendoEShopClient)
        picker = _fake_picker({'nintendo': client})
        with patch.object(gapi_gui, 'picker', picker):
            resp = self.client.get('/api/nintendo/prices')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Provide one or more nsuids', resp.json()['error'])

    def test_no_picker_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/nintendo/prices?nsuids=1')
        self.assertEqual(resp.status_code, 503)


if __name__ == '__main__':
    unittest.main()
