#!/usr/bin/env python3
"""
Tests for twitch_client.py and the Twitch + PWA Flask routes in gapi_gui.py.

Run with:
    python -m pytest tests/test_twitch_pwa.py
"""
import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from twitch_client import TwitchClient, TwitchAuthError, TwitchAPIError


# ===========================================================================
# TwitchClient unit tests (no real HTTP)
# ===========================================================================

def _make_token_response(token: str = "fake_token", expires_in: int = 3600):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": token, "expires_in": expires_in}
    resp.raise_for_status.return_value = None
    return resp


def _make_games_response(names):
    items = [
        {
            "id": str(i + 1),
            "name": name,
            "viewer_count": (20 - i) * 1000,
            "box_art_url": f"https://example.com/{i}.jpg",
        }
        for i, name in enumerate(names)
    ]
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": items, "pagination": {}}
    resp.raise_for_status.return_value = None
    return resp


class TestTwitchClientInit(unittest.TestCase):

    def test_requires_client_id(self):
        with self.assertRaises(ValueError):
            TwitchClient(client_id="", client_secret="secret")

    def test_requires_client_secret(self):
        with self.assertRaises(ValueError):
            TwitchClient(client_id="id", client_secret="")

    def test_creates_successfully(self):
        c = TwitchClient(client_id="id", client_secret="secret")
        self.assertEqual(c._client_id, "id")


class TestTwitchClientGetToken(unittest.TestCase):

    @patch("twitch_client.requests.post")
    def test_fetches_token(self, mock_post):
        mock_post.return_value = _make_token_response("tok123")
        c = TwitchClient(client_id="id", client_secret="secret")
        token = c._get_token()
        self.assertEqual(token, "tok123")
        mock_post.assert_called_once()

    @patch("twitch_client.requests.post")
    def test_caches_token(self, mock_post):
        mock_post.return_value = _make_token_response("tok_cached")
        c = TwitchClient(client_id="id", client_secret="secret")
        c._get_token()
        c._get_token()
        self.assertEqual(mock_post.call_count, 1, "Token should be cached")

    @patch("twitch_client.requests.post")
    def test_raises_on_network_error(self, mock_post):
        import requests as _requests
        mock_post.side_effect = _requests.RequestException("network down")
        c = TwitchClient(client_id="id", client_secret="secret")
        with self.assertRaises(TwitchAuthError):
            c._get_token()

    @patch("twitch_client.requests.post")
    def test_raises_when_token_missing_from_response(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"no_token": True}
        resp.raise_for_status.return_value = None
        mock_post.return_value = resp
        c = TwitchClient(client_id="id", client_secret="secret")
        with self.assertRaises(TwitchAuthError):
            c._get_token()


class TestTwitchClientGetTopGames(unittest.TestCase):

    @patch("twitch_client.requests.get")
    @patch("twitch_client.requests.post")
    def test_returns_top_games(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        names = ["Counter-Strike 2", "Dota 2", "Grand Theft Auto V"]
        mock_get.return_value = _make_games_response(names)
        c = TwitchClient(client_id="id", client_secret="secret")
        games = c.get_top_games(count=3)
        self.assertEqual(len(games), 3)
        self.assertEqual(games[0]["name"], "Counter-Strike 2")

    @patch("twitch_client.requests.get")
    @patch("twitch_client.requests.post")
    def test_result_has_required_keys(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_games_response(["Portal 2"])
        c = TwitchClient(client_id="id", client_secret="secret")
        games = c.get_top_games(count=1)
        required = {"id", "name", "viewer_count", "box_art_url", "twitch_url"}
        self.assertEqual(required - games[0].keys(), set())

    @patch("twitch_client.requests.get")
    @patch("twitch_client.requests.post")
    def test_twitch_url_is_valid(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_games_response(["Counter-Strike 2"])
        c = TwitchClient(client_id="id", client_secret="secret")
        games = c.get_top_games(count=1)
        url = games[0]["twitch_url"]
        self.assertTrue(url.startswith("https://www.twitch.tv/directory/game/"))

    @patch("twitch_client.requests.get")
    @patch("twitch_client.requests.post")
    def test_count_clamped_to_100(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_get.return_value = _make_games_response(["Game A"])
        c = TwitchClient(client_id="id", client_secret="secret")
        # Should not raise; clamping happens internally
        c.get_top_games(count=200)

    @patch("twitch_client.requests.get")
    @patch("twitch_client.requests.post")
    def test_raises_on_api_error(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        import requests as _requests
        err_resp = MagicMock()
        err_resp.status_code = 401
        err_resp.text = "Unauthorized"
        http_err = _requests.HTTPError(response=err_resp)
        err_resp.raise_for_status.side_effect = http_err
        mock_get.return_value = err_resp
        c = TwitchClient(client_id="id", client_secret="secret")
        with self.assertRaises(TwitchAPIError):
            c.get_top_games(count=5)


class TestTwitchClientLibraryOverlap(unittest.TestCase):

    def _client(self):
        return TwitchClient(client_id="id", client_secret="secret")

    def test_finds_exact_match(self):
        trending = [{"id": "1", "name": "Portal 2", "viewer_count": 5000,
                     "box_art_url": "", "twitch_url": ""}]
        library  = [{"appid": 620, "name": "Portal 2", "playtime_forever": 2720}]
        overlap  = self._client().find_library_overlap(trending, library)
        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0]["name"], "Portal 2")
        self.assertEqual(overlap[0]["trending_rank"], 1)

    def test_no_overlap_when_no_match(self):
        trending = [{"id": "1", "name": "Fortnite", "viewer_count": 5000,
                     "box_art_url": "", "twitch_url": ""}]
        library  = [{"appid": 620, "name": "Portal 2", "playtime_forever": 0}]
        overlap  = self._client().find_library_overlap(trending, library)
        self.assertEqual(overlap, [])

    def test_result_contains_viewer_count(self):
        trending = [{"id": "1", "name": "Team Fortress 2", "viewer_count": 12345,
                     "box_art_url": "", "twitch_url": ""}]
        library  = [{"appid": 440, "name": "Team Fortress 2", "playtime_forever": 100}]
        overlap  = self._client().find_library_overlap(trending, library)
        self.assertEqual(overlap[0]["viewer_count"], 12345)

    def test_sorted_by_trending_rank(self):
        trending = [
            {"id": "1", "name": "Dota 2",  "viewer_count": 9000, "box_art_url": "", "twitch_url": ""},
            {"id": "2", "name": "Portal 2", "viewer_count": 5000, "box_art_url": "", "twitch_url": ""},
        ]
        library = [
            {"appid": 620, "name": "Portal 2", "playtime_forever": 0},
            {"appid": 570, "name": "Dota 2",   "playtime_forever": 0},
        ]
        overlap = self._client().find_library_overlap(trending, library)
        self.assertEqual(overlap[0]["name"], "Dota 2")
        self.assertEqual(overlap[1]["name"], "Portal 2")

    def test_case_insensitive_match(self):
        trending = [{"id": "1", "name": "COUNTER-STRIKE 2", "viewer_count": 1000,
                     "box_art_url": "", "twitch_url": ""}]
        library  = [{"appid": 730, "name": "Counter-Strike 2", "playtime_forever": 200}]
        overlap  = self._client().find_library_overlap(trending, library)
        self.assertEqual(len(overlap), 1)

    def test_no_duplicates_in_result(self):
        trending = [{"id": "1", "name": "Portal 2", "viewer_count": 1000,
                     "box_art_url": "", "twitch_url": ""}]
        library = [
            {"appid": 620, "name": "Portal 2", "playtime_forever": 0},
            {"appid": 620, "name": "Portal 2", "playtime_forever": 100},
        ]
        overlap = self._client().find_library_overlap(trending, library)
        self.assertEqual(len(overlap), 1)

    def test_empty_library(self):
        trending = [{"id": "1", "name": "Fortnite", "viewer_count": 5000,
                     "box_art_url": "", "twitch_url": ""}]
        overlap = self._client().find_library_overlap(trending, [])
        self.assertEqual(overlap, [])

    def test_empty_trending(self):
        library = [{"appid": 620, "name": "Portal 2", "playtime_forever": 0}]
        overlap = self._client().find_library_overlap([], library)
        self.assertEqual(overlap, [])


class TestTwitchGameUrl(unittest.TestCase):

    def test_encodes_spaces(self):
        url = TwitchClient._game_url("Grand Theft Auto V")
        self.assertIn("Grand%20Theft%20Auto%20V", url)

    def test_base_url(self):
        url = TwitchClient._game_url("Dota 2")
        self.assertTrue(url.startswith("https://www.twitch.tv/directory/game/"))


# ===========================================================================
# Flask route tests
# ===========================================================================

class TestPWARoutes(unittest.TestCase):
    """Verify /manifest.json and /sw.js are served correctly."""

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    def test_manifest_returns_200(self):
        resp = self.client.get('/manifest.json')
        self.assertEqual(resp.status_code, 200)

    def test_manifest_content_type(self):
        resp = self.client.get('/manifest.json')
        self.assertIn('manifest+json', resp.content_type)

    def test_manifest_has_required_fields(self):
        resp = self.client.get('/manifest.json')
        data = json.loads(resp.data)
        for field in ('name', 'short_name', 'start_url', 'display', 'icons'):
            self.assertIn(field, data, f"Manifest missing field: {field}")

    def test_manifest_display_standalone(self):
        resp = self.client.get('/manifest.json')
        data = json.loads(resp.data)
        self.assertEqual(data['display'], 'standalone')

    def test_manifest_start_url(self):
        resp = self.client.get('/manifest.json')
        data = json.loads(resp.data)
        self.assertEqual(data['start_url'], '/')

    def test_sw_returns_200(self):
        resp = self.client.get('/sw.js')
        self.assertEqual(resp.status_code, 200)

    def test_sw_content_type(self):
        resp = self.client.get('/sw.js')
        self.assertIn('javascript', resp.content_type)

    def test_sw_no_cache_header(self):
        resp = self.client.get('/sw.js')
        self.assertIn('no-cache', resp.headers.get('Cache-Control', '').lower())

    def test_sw_scope_header(self):
        resp = self.client.get('/sw.js')
        self.assertEqual(resp.headers.get('Service-Worker-Allowed'), '/')

    def test_sw_contains_cache_name(self):
        resp = self.client.get('/sw.js')
        self.assertIn(b'gapi-v1', resp.data)

    def test_sw_registers_fetch_handler(self):
        resp = self.client.get('/sw.js')
        self.assertIn(b"addEventListener('fetch'", resp.data)

    def test_sw_registers_install_handler(self):
        resp = self.client.get('/sw.js')
        self.assertIn(b"addEventListener('install'", resp.data)

    def test_sw_registers_activate_handler(self):
        resp = self.client.get('/sw.js')
        self.assertIn(b"addEventListener('activate'", resp.data)


class TestTwitchRoutesNoCredentials(unittest.TestCase):
    """Twitch routes should return 503 when no credentials are configured."""

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    @patch('gapi_gui._get_twitch_client', return_value=None)
    def test_trending_503_without_credentials(self, _mock):
        resp = self.client.get('/api/twitch/trending')
        self.assertEqual(resp.status_code, 503)
        data = json.loads(resp.data)
        self.assertIn('error', data)

    @patch('gapi_gui.current_user', 'testuser')
    @patch('gapi_gui._get_twitch_client', return_value=None)
    def test_library_overlap_503_without_credentials(self, _mock):
        import gapi_gui
        # picker must be truthy so the route reaches the credentials check
        fake_picker = MagicMock()
        fake_picker.games = []
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/twitch/library-overlap')
        self.assertEqual(resp.status_code, 503)
        data = json.loads(resp.data)
        self.assertIn('error', data)


class TestPWAMetaTags(unittest.TestCase):
    """Verify the HTML template contains PWA meta tags."""

    def _html(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates', 'index.html'
        )
        with open(path) as f:
            return f.read()

    def test_manifest_link_present(self):
        html = self._html()
        self.assertIn('rel="manifest"', html)
        self.assertIn('href="/manifest.json"', html)

    def test_theme_color_meta_present(self):
        html = self._html()
        self.assertIn('name="theme-color"', html)
        self.assertIn('#667eea', html)

    def test_apple_mobile_capable_present(self):
        html = self._html()
        self.assertIn('apple-mobile-web-app-capable', html)

    def test_sw_registration_script_present(self):
        html = self._html()
        self.assertIn("serviceWorker", html)
        self.assertIn("sw.js", html)


class TestConfigTemplate(unittest.TestCase):
    """config_template.json must include Twitch credential placeholders."""

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config_template.json'
        )
        with open(path) as f:
            self._cfg = json.load(f)

    def test_twitch_client_id_present(self):
        self.assertIn('twitch_client_id', self._cfg)

    def test_twitch_client_secret_present(self):
        self.assertIn('twitch_client_secret', self._cfg)


if __name__ == '__main__':
    unittest.main()
