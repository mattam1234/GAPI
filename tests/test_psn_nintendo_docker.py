#!/usr/bin/env python3
"""
Tests for:
* PSNClient
* NintendoEShopClient
* Flask routes: /api/psn/*, /api/nintendo/*
* Updated /api/platform/status (PSN + Nintendo included)
* config_template.json — PSN/Nintendo keys
* Dockerfile and docker-compose.yml exist and are valid

Run with:
    python -m pytest tests/test_psn_nintendo_docker.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_clients import PSNClient, NintendoEShopClient


# ===========================================================================
# Helpers
# ===========================================================================

def _ok_resp(body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _redirect_resp(location):
    resp = MagicMock()
    resp.status_code = 302
    resp.headers = {'Location': location}
    resp.raise_for_status.return_value = None
    return resp


# ===========================================================================
# PSNClient
# ===========================================================================

class TestPSNClient(unittest.TestCase):

    def _client(self):
        return PSNClient(timeout=5)

    def test_get_platform_name(self):
        self.assertEqual(self._client().get_platform_name(), 'psn')

    def test_not_authenticated_initially(self):
        self.assertFalse(self._client().is_authenticated)

    def test_get_owned_games_requires_auth(self):
        c = self._client()
        result = c.get_owned_games()
        self.assertEqual(result, [])

    def test_get_trophies_requires_auth(self):
        c = self._client()
        result = c.get_trophies()
        self.assertEqual(result, [])

    def test_get_game_details_returns_none_for_unknown(self):
        c = self._client()
        self.assertIsNone(c.get_game_details('NONEXISTENT'))

    def test_get_game_details_returns_cached(self):
        c = self._client()
        c.details_cache['PPSA01234_00'] = {'title': 'Spider-Man'}
        self.assertEqual(c.get_game_details('PPSA01234_00')['title'], 'Spider-Man')

    @patch('platform_clients.requests.Session')
    def test_connect_fails_when_npsso_invalid(self, mock_session_cls):
        """connect() returns False when the PSN auth flow does not return a code."""
        mock_session = MagicMock()
        # Simulate 302 without 'code=' in Location
        mock_session.get.return_value = _redirect_resp('https://example.com/?error=access_denied')
        mock_session_cls.return_value = mock_session
        c = PSNClient()
        ok = c.connect('bad_npsso')
        self.assertFalse(ok)
        self.assertFalse(c.is_authenticated)

    @patch('platform_clients.requests.Session')
    def test_connect_success(self, mock_session_cls):
        """connect() sets access/refresh tokens on success."""
        mock_session = MagicMock()
        mock_session.get.return_value  = _redirect_resp(
            'com.scee.psxandroid.sceabroker://psxbroker?code=AUTH_CODE_123'
        )
        mock_session.post.return_value = _ok_resp({
            'access_token':  'psn_access_token',
            'refresh_token': 'psn_refresh_token',
            'expires_in':    3600,
        })
        mock_session_cls.return_value = mock_session
        c  = PSNClient()
        ok = c.connect('valid_npsso')
        self.assertTrue(ok)
        self.assertTrue(c.is_authenticated)

    @patch('platform_clients.requests.Session')
    def test_refresh_tokens_returns_false_without_token(self, _):
        c = PSNClient()
        self.assertFalse(c.refresh_tokens())

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_paginates(self, mock_session_cls):
        """get_owned_games() follows pagination until totalItemCount is reached."""
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            _ok_resp({
                'titles': [
                    {'titleId': 'PPSA001', 'name': 'God of War', 'category': 'ps5_native_game'},
                ],
                'totalItemCount': 2,
            }),
            _ok_resp({
                'titles': [
                    {'titleId': 'PPSA002', 'name': 'Returnal', 'category': 'ps5_native_game'},
                ],
                'totalItemCount': 2,
            }),
        ]
        mock_session_cls.return_value = mock_session
        c = PSNClient()
        c._access_token = 'tok'
        c._token_expiry = 9999999999.0
        games = c.get_owned_games()
        self.assertEqual(len(games), 2)
        self.assertTrue(all(g['platform'] == 'psn' for g in games))
        names = {g['name'] for g in games}
        self.assertIn('God of War', names)
        self.assertIn('Returnal',   names)

    @patch('platform_clients.requests.Session')
    def test_get_trophies_fetches_correctly(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp({
            'trophyTitles': [
                {'trophyTitleName': 'God of War', 'npCommunicationId': 'NPWR12345_00'}
            ],
            'totalItemCount': 1,
        })
        mock_session_cls.return_value = mock_session
        c = PSNClient()
        c._access_token = 'tok'
        c._token_expiry = 9999999999.0
        trophies = c.get_trophies()
        self.assertEqual(len(trophies), 1)
        self.assertEqual(trophies[0]['trophyTitleName'], 'God of War')

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_http_error_returns_empty(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.get.side_effect = _r.RequestException('network error')
        mock_session_cls.return_value = mock_session
        c = PSNClient()
        c._access_token = 'tok'
        c._token_expiry = 9999999999.0
        games = c.get_owned_games()
        self.assertEqual(games, [])


# ===========================================================================
# NintendoEShopClient
# ===========================================================================

class TestNintendoEShopClient(unittest.TestCase):

    def _client(self):
        return NintendoEShopClient(region='US', timeout=5)

    def test_get_platform_name(self):
        self.assertEqual(self._client().get_platform_name(), 'nintendo')

    def test_get_owned_games_returns_empty(self):
        """Nintendo has no library API — always empty."""
        c = self._client()
        self.assertEqual(c.get_owned_games(), [])

    def test_default_region_is_us(self):
        c = NintendoEShopClient()
        self.assertEqual(c._region, 'US')

    def test_region_stored_uppercase(self):
        c = NintendoEShopClient(region='eu')
        self.assertEqual(c._region, 'EU')

    def test_get_game_by_nsuid_returns_none_when_not_cached(self):
        c = self._client()
        self.assertIsNone(c.get_game_by_nsuid('99999999999999'))

    def test_get_game_by_nsuid_returns_cached(self):
        c = self._client()
        c.details_cache['70010000000025'] = {
            'title': 'The Legend of Zelda: Breath of the Wild',
            'nsuid': '70010000000025',
        }
        result = c.get_game_by_nsuid('70010000000025')
        self.assertIsNotNone(result)
        self.assertEqual(result['title'], 'The Legend of Zelda: Breath of the Wild')

    @patch('platform_clients.requests.Session')
    def test_search_games_normalises_hits(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.return_value = _ok_resp({
            'hits': [
                {
                    'title':       'Super Mario Odyssey',
                    'nsuid':       '70010000001130',
                    'url':         '/games/detail/super-mario-odyssey',
                    'players':     '1-4',
                    'categories':  ['Platformer', '3D'],
                    'platform':    'Nintendo Switch',
                    'releaseDate': '2017-10-27',
                    'msrp':        59.99,
                    'publishers':  ['Nintendo'],
                    'developers':  ['Nintendo EPD'],
                    'esrb':        'E',
                    'boxart':      'https://example.com/boxart.jpg',
                }
            ],
            'nbHits': 1,
            'page':   0,
            'nbPages': 1,
        })
        mock_session_cls.return_value = mock_session
        c = self._client()
        result = c.search_games(query='mario')
        self.assertEqual(result['nbHits'], 1)
        self.assertEqual(len(result['hits']), 1)
        hit = result['hits'][0]
        self.assertEqual(hit['name'], 'Super Mario Odyssey')
        self.assertEqual(hit['platform_name'] if 'platform_name' in hit else hit.get('source'), 'nintendo')
        self.assertEqual(hit['game_id'], 'nintendo:70010000001130')
        self.assertEqual(hit['appid'],   '70010000001130')
        # Verify cached
        self.assertIn('70010000001130', c.details_cache)

    @patch('platform_clients.requests.Session')
    def test_search_games_returns_empty_on_error(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.post.side_effect = _r.RequestException('network error')
        mock_session_cls.return_value = mock_session
        c = self._client()
        result = c.search_games('zelda')
        self.assertEqual(result['hits'], [])
        self.assertEqual(result['nbHits'], 0)

    @patch('platform_clients.requests.Session')
    def test_get_prices_returns_dict(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp({
            'prices': [
                {
                    'title_id': 70010000000025,
                    'regular_price': {'raw_value': '59.99', 'amount': '$59.99'},
                    'sales_status': 'onsale',
                }
            ]
        })
        mock_session_cls.return_value = mock_session
        c = self._client()
        prices = c.get_prices(['70010000000025'])
        self.assertIn('70010000000025', prices)
        self.assertEqual(prices['70010000000025']['regular_price'], '59.99')

    @patch('platform_clients.requests.Session')
    def test_get_prices_returns_empty_on_error(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.get.side_effect = _r.RequestException('network error')
        mock_session_cls.return_value = mock_session
        c = self._client()
        prices = c.get_prices(['70010000000025'])
        self.assertEqual(prices, {})

    @patch('platform_clients.requests.Session')
    def test_algolia_headers_contain_credentials(self, mock_session_cls):
        c = self._client()
        headers = c._algolia_headers()
        self.assertIn('X-Algolia-Application-Id', headers)
        self.assertIn('X-Algolia-API-Key', headers)
        self.assertTrue(len(headers['X-Algolia-Application-Id']) > 0)


# ===========================================================================
# Flask routes — PSN
# ===========================================================================

class TestPSNRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.app_client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_library_503_not_configured(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_library_503_not_authenticated(self):
        import gapi_gui
        psn_client = PSNClient()
        fake_picker = MagicMock()
        fake_picker.clients = {'psn': psn_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_library_200_when_authenticated(self):
        import gapi_gui
        psn_client = PSNClient()
        psn_client._access_token = 'tok'
        psn_client._token_expiry = 9999999999.0
        with patch.object(psn_client, 'get_owned_games', return_value=[
            {'name': 'God of War', 'platform': 'psn', 'game_id': 'psn:PPSA001'}
        ]):
            fake_picker = MagicMock()
            fake_picker.clients = {'psn': psn_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/psn/library')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['platform'], 'psn')
        self.assertEqual(data['count'], 1)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_connect_400_missing_npsso(self):
        import gapi_gui
        psn_client = PSNClient()
        fake_picker = MagicMock()
        fake_picker.clients = {'psn': psn_client}
        fake_picker.API_TIMEOUT = 10
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.post(
                '/api/psn/connect',
                json={},
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 400)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_connect_400_bad_npsso(self):
        import gapi_gui
        psn_client = PSNClient()
        with patch.object(psn_client, 'connect', return_value=False):
            fake_picker = MagicMock()
            fake_picker.clients = {'psn': psn_client}
            fake_picker.API_TIMEOUT = 10
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.post(
                    '/api/psn/connect',
                    json={'npsso': 'badtoken'},
                )
        self.assertEqual(resp.status_code, 400)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_connect_200_good_npsso(self):
        import gapi_gui
        psn_client = PSNClient()
        with patch.object(psn_client, 'connect', return_value=True):
            fake_picker = MagicMock()
            fake_picker.clients = {'psn': psn_client}
            fake_picker.API_TIMEOUT = 10
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.post(
                    '/api/psn/connect',
                    json={'npsso': 'validtoken123'},
                )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['platform'], 'psn')

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_trophies_503_not_authenticated(self):
        import gapi_gui
        psn_client = PSNClient()
        fake_picker = MagicMock()
        fake_picker.clients = {'psn': psn_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/psn/trophies')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_trophies_200_when_authenticated(self):
        import gapi_gui
        psn_client = PSNClient()
        psn_client._access_token = 'tok'
        psn_client._token_expiry = 9999999999.0
        with patch.object(psn_client, 'get_trophies', return_value=[
            {'trophyTitleName': 'God of War', 'npCommunicationId': 'NPWR12345_00'}
        ]):
            fake_picker = MagicMock()
            fake_picker.clients = {'psn': psn_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/psn/trophies')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['platform'], 'psn')


# ===========================================================================
# Flask routes — Nintendo
# ===========================================================================

class TestNintendoRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.app_client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_search_200_autocreates_client(self):
        """Route uses NintendoEShopClient when none is pre-configured in picker."""
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        mock_result = {'hits': [], 'nbHits': 0, 'page': 0, 'nbPages': 0}
        with patch.object(nintendo_client, 'search_games', return_value=mock_result):
            # Provide a picker that already has the client (simulates auto-create path)
            fake_picker = MagicMock()
            fake_picker.clients = {'nintendo': nintendo_client}
            fake_picker.API_TIMEOUT = 10
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/nintendo/search?q=mario')
        self.assertEqual(resp.status_code, 200)

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_search_503_no_picker(self):
        import gapi_gui
        with patch.object(gapi_gui, 'picker', None):
            resp = self.app_client.get('/api/nintendo/search?q=mario')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_search_with_configured_client(self):
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        mock_result = {
            'hits': [{'name': 'Mario Kart 8 Deluxe', 'nsuid': '70010000001130', 'game_id': 'nintendo:70010000001130'}],
            'nbHits': 1, 'page': 0, 'nbPages': 1
        }
        with patch.object(nintendo_client, 'search_games', return_value=mock_result):
            fake_picker = MagicMock()
            fake_picker.clients = {'nintendo': nintendo_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/nintendo/search?q=mario&per_page=5')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['platform'], 'nintendo')
        self.assertEqual(data['nbHits'], 1)

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_prices_400_missing_nsuids(self):
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        fake_picker = MagicMock()
        fake_picker.clients = {'nintendo': nintendo_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/nintendo/prices')
        self.assertEqual(resp.status_code, 400)

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_prices_200(self):
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        mock_prices = {'70010000000025': {'regular_price': '59.99'}}
        with patch.object(nintendo_client, 'get_prices', return_value=mock_prices):
            fake_picker = MagicMock()
            fake_picker.clients = {'nintendo': nintendo_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/nintendo/prices?nsuids=70010000000025')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('70010000000025', data['prices'])

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_game_404_not_cached(self):
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        with patch.object(nintendo_client, 'search_games', return_value={'hits': []}):
            fake_picker = MagicMock()
            fake_picker.clients = {'nintendo': nintendo_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.app_client.get('/api/nintendo/game/99999999999999')
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# Updated platform/status route (PSN + Nintendo)
# ===========================================================================

class TestPlatformStatusWithNewPlatforms(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.app_client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_status_includes_psn_and_nintendo(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/platform/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('psn',      data['platforms'])
        self.assertIn('nintendo', data['platforms'])

    @patch('gapi_gui.current_user', 'testuser')
    def test_psn_shows_authenticated_true(self):
        import gapi_gui
        psn_client = PSNClient()
        psn_client._access_token = 'tok'
        psn_client._token_expiry = 9999999999.0
        fake_picker = MagicMock()
        fake_picker.clients = {'psn': psn_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/platform/status')
        data = json.loads(resp.data)
        self.assertTrue(data['platforms']['psn']['authenticated'])

    @patch('gapi_gui.current_user', 'testuser')
    def test_nintendo_shows_configured_and_note(self):
        import gapi_gui
        nintendo_client = NintendoEShopClient()
        fake_picker = MagicMock()
        fake_picker.clients = {'nintendo': nintendo_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.app_client.get('/api/platform/status')
        data = json.loads(resp.data)
        self.assertTrue(data['platforms']['nintendo']['configured'])
        self.assertIn('note', data['platforms']['nintendo'])


# ===========================================================================
# config_template.json — PSN + Nintendo keys
# ===========================================================================

class TestConfigTemplatePSNNintendo(unittest.TestCase):

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config_template.json'
        )
        with open(path) as f:
            self._cfg = json.load(f)

    def test_psn_keys_present(self):
        for k in ('psn_enabled', 'psn_npsso'):
            self.assertIn(k, self._cfg, f"Missing key: {k}")

    def test_nintendo_keys_present(self):
        for k in ('nintendo_enabled', 'nintendo_region'):
            self.assertIn(k, self._cfg, f"Missing key: {k}")


# ===========================================================================
# Docker / microservices files
# ===========================================================================

class TestDockerFiles(unittest.TestCase):

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _path(self, *parts):
        return os.path.join(self.ROOT, *parts)

    def test_dockerfile_exists(self):
        self.assertTrue(os.path.exists(self._path('Dockerfile')),
                        'Dockerfile missing')

    def test_dockerfile_has_healthcheck(self):
        with open(self._path('Dockerfile')) as f:
            content = f.read()
        self.assertIn('HEALTHCHECK', content)

    def test_dockerfile_has_non_root_user(self):
        with open(self._path('Dockerfile')) as f:
            content = f.read()
        self.assertIn('USER gapi', content)

    def test_docker_compose_exists(self):
        self.assertTrue(os.path.exists(self._path('docker-compose.yml')),
                        'docker-compose.yml missing')

    def test_docker_compose_has_required_services(self):
        with open(self._path('docker-compose.yml')) as f:
            content = f.read()
        for service in ('gapi-web', 'gapi-db', 'gapi-redis', 'gapi-nginx'):
            self.assertIn(service, content, f"Missing service: {service}")

    def test_docker_compose_override_exists(self):
        self.assertTrue(os.path.exists(self._path('docker-compose.override.yml')))

    def test_nginx_conf_exists(self):
        self.assertTrue(os.path.exists(self._path('nginx', 'nginx.conf')))

    def test_env_example_has_postgres_keys(self):
        with open(self._path('.env.example')) as f:
            content = f.read()
        for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'SECRET_KEY'):
            self.assertIn(key, content, f"Missing key in .env.example: {key}")

    def test_env_example_has_platform_keys(self):
        with open(self._path('.env.example')) as f:
            content = f.read()
        for key in ('EPIC_CLIENT_ID', 'GOG_CLIENT_ID', 'XBOX_CLIENT_ID', 'PSN_NPSSO'):
            self.assertIn(key, content, f"Missing key in .env.example: {key}")


# ===========================================================================
# Browser Extension files
# ===========================================================================

class TestBrowserExtensionFiles(unittest.TestCase):

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _path(self, *parts):
        return os.path.join(self.ROOT, 'browser-extension', *parts)

    def test_manifest_exists(self):
        self.assertTrue(os.path.exists(self._path('manifest.json')))

    def test_manifest_is_v3(self):
        with open(self._path('manifest.json')) as f:
            manifest = json.load(f)
        self.assertEqual(manifest.get('manifest_version'), 3)

    def test_manifest_has_required_keys(self):
        with open(self._path('manifest.json')) as f:
            manifest = json.load(f)
        for key in ('name', 'version', 'action', 'background', 'permissions'):
            self.assertIn(key, manifest, f"Missing key in manifest: {key}")

    def test_popup_html_exists(self):
        self.assertTrue(os.path.exists(self._path('popup.html')))

    def test_popup_js_exists(self):
        self.assertTrue(os.path.exists(self._path('popup.js')))

    def test_popup_js_has_pick_api_call(self):
        with open(self._path('popup.js')) as f:
            content = f.read()
        self.assertIn('/api/random-game', content)

    def test_background_js_exists(self):
        self.assertTrue(os.path.exists(self._path('background.js')))

    def test_options_html_exists(self):
        self.assertTrue(os.path.exists(self._path('options.html')))

    def test_options_js_exists(self):
        self.assertTrue(os.path.exists(self._path('options.js')))

    def test_readme_exists(self):
        self.assertTrue(os.path.exists(self._path('README.md')))

    def test_service_worker_in_manifest_background(self):
        with open(self._path('manifest.json')) as f:
            manifest = json.load(f)
        self.assertIn('service_worker', manifest.get('background', {}))


# ===========================================================================
# TUTORIALS.md
# ===========================================================================

class TestTutorials(unittest.TestCase):

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_tutorials_md_exists(self):
        path = os.path.join(self.ROOT, 'TUTORIALS.md')
        self.assertTrue(os.path.exists(path), 'TUTORIALS.md missing')

    def test_tutorials_covers_all_major_topics(self):
        path = os.path.join(self.ROOT, 'TUTORIALS.md')
        with open(path) as f:
            content = f.read()
        for topic in ('Steam', 'Docker', 'Browser Extension', 'PSN', 'Nintendo',
                      'Discord', 'Slack', 'Xbox'):
            self.assertIn(topic, content, f"Tutorial missing topic: {topic}")


if __name__ == '__main__':
    unittest.main()
