#!/usr/bin/env python3
"""
Tests for:
* EpicOAuthClient
* GOGOAuthClient
* XboxAPIClient
* MLRecommendationEngine
* Flask routes: /api/epic/*, /api/gog/*, /api/xbox/*, /api/platform/status,
  /api/recommendations/ml

Run with:
    python -m pytest tests/test_platform_clients_ml.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_clients import EpicOAuthClient, GOGOAuthClient, XboxAPIClient, _OAuth2Mixin
from app.services.ml_recommendation_service import MLRecommendationEngine


# ===========================================================================
# Helpers
# ===========================================================================

def _ok_resp(body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _err_resp():
    import requests as _r
    resp = MagicMock()
    resp.status_code = 500
    resp.raise_for_status.side_effect = _r.HTTPError(response=resp)
    return resp


def _game(appid, name, playtime_mins=0):
    return {
        'appid': appid,
        'name': name,
        'playtime_forever': playtime_mins,
        'game_id': f'steam:{appid}',
        'platform': 'steam',
    }


def _details(genres=None, developers=None):
    d = {}
    if genres:
        d['genres'] = [{'description': g} for g in genres]
    if developers:
        d['developers'] = list(developers)
    return d


# ===========================================================================
# _OAuth2Mixin
# ===========================================================================

class TestOAuth2Mixin(unittest.TestCase):

    def _mixin(self):
        m = _OAuth2Mixin.__new__(_OAuth2Mixin)
        _OAuth2Mixin.__init__(m)
        return m

    def test_not_authenticated_initially(self):
        m = self._mixin()
        self.assertFalse(m.is_authenticated)

    def test_store_tokens_sets_access_token(self):
        m = self._mixin()
        m._store_tokens({'access_token': 'abc', 'refresh_token': 'xyz', 'expires_in': 3600})
        self.assertTrue(m.is_authenticated)
        self.assertEqual(m._access_token, 'abc')
        self.assertEqual(m._refresh_token, 'xyz')

    def test_auth_header_contains_bearer_token(self):
        m = self._mixin()
        m._store_tokens({'access_token': 'mytoken', 'expires_in': 3600})
        self.assertIn('mytoken', m._auth_header()['Authorization'])

    def test_is_token_expired_when_expiry_zero(self):
        m = self._mixin()
        # expiry = 0 → always expired
        self.assertTrue(m._is_token_expired())

    def test_token_not_expired_after_store(self):
        import time
        m = self._mixin()
        m._store_tokens({'access_token': 'tok', 'expires_in': 3600})
        self.assertFalse(m._is_token_expired())


# ===========================================================================
# EpicOAuthClient
# ===========================================================================

class TestEpicOAuthClient(unittest.TestCase):

    def _client(self):
        return EpicOAuthClient(client_id='epic_id', client_secret='epic_secret')

    def test_get_platform_name(self):
        self.assertEqual(self._client().get_platform_name(), 'epic')

    def test_build_auth_url_contains_client_id(self):
        c   = self._client()
        url = c.build_auth_url('http://localhost/cb', state='mystate')
        self.assertIn('epic_id', url)
        self.assertIn('mystate', url)
        self.assertIn('code_challenge', url)

    def test_build_auth_url_sets_code_verifier(self):
        c = self._client()
        c.build_auth_url('http://localhost/cb')
        self.assertTrue(len(c._code_verifier) > 0)

    def test_build_auth_url_produces_new_verifier_each_call(self):
        c   = self._client()
        c.build_auth_url('http://localhost/cb')
        v1  = c._code_verifier
        c.build_auth_url('http://localhost/cb')
        v2  = c._code_verifier
        self.assertNotEqual(v1, v2)

    @patch('platform_clients.requests.Session')
    def test_exchange_code_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.return_value = _ok_resp({
            'access_token': 'atoken', 'refresh_token': 'rtoken', 'expires_in': 3600
        })
        mock_session_cls.return_value = mock_session
        c  = EpicOAuthClient('cid', 'csec')
        ok = c.exchange_code('mycode', 'http://localhost/cb')
        self.assertTrue(ok)
        self.assertTrue(c.is_authenticated)

    @patch('platform_clients.requests.Session')
    def test_exchange_code_failure(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.post.side_effect = _r.RequestException('fail')
        mock_session_cls.return_value = mock_session
        c  = EpicOAuthClient('cid', 'csec')
        ok = c.exchange_code('code', 'http://localhost/cb')
        self.assertFalse(ok)

    @patch('platform_clients.requests.Session')
    def test_refresh_tokens_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.return_value = _ok_resp({
            'access_token': 'new', 'expires_in': 3600
        })
        mock_session_cls.return_value = mock_session
        c = EpicOAuthClient('cid', 'csec')
        c._refresh_token = 'rtoken'
        ok = c.refresh_tokens()
        self.assertTrue(ok)

    def test_refresh_tokens_without_refresh_token_returns_false(self):
        c = EpicOAuthClient('cid', 'csec')
        self.assertFalse(c.refresh_tokens())

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_returns_empty_when_not_authenticated(self, mock_session_cls):
        c = EpicOAuthClient('cid')
        self.assertEqual(c.get_owned_games(), [])

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_fetches_library(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp([
            {'appName': 'Fortnite', 'catalogItemId': 'fn123', 'labelName': 'LIVE', 'namespace': 'fn'},
        ])
        mock_session_cls.return_value = mock_session
        c = EpicOAuthClient('cid', 'csec')
        c._access_token  = 'tok'
        c._token_expiry  = 9999999999.0
        # details fetch will fail; test just the list shape
        with patch.object(c, 'get_game_details', return_value=None):
            games = c.get_owned_games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['platform'], 'epic')

    def test_get_game_details_returns_none_when_not_authenticated(self):
        c = EpicOAuthClient('cid')
        self.assertIsNone(c.get_game_details('any'))

    def test_get_game_details_returns_cached(self):
        c = EpicOAuthClient('cid')
        c.details_cache['g1'] = {'title': 'Cached Game'}
        self.assertEqual(c.get_game_details('g1')['title'], 'Cached Game')


# ===========================================================================
# GOGOAuthClient
# ===========================================================================

class TestGOGOAuthClient(unittest.TestCase):

    def _client(self):
        return GOGOAuthClient(client_id='gog_id', client_secret='gog_secret')

    def test_get_platform_name(self):
        self.assertEqual(self._client().get_platform_name(), 'gog')

    def test_build_auth_url_contains_client_id(self):
        c   = self._client()
        url = c.build_auth_url('http://localhost/cb', state='csrf')
        self.assertIn('gog_id', url)
        self.assertIn('csrf', url)

    @patch('platform_clients.requests.Session')
    def test_exchange_code_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp({
            'access_token': 'gacc', 'refresh_token': 'gref', 'expires_in': 3600
        })
        mock_session_cls.return_value = mock_session
        c  = GOGOAuthClient('gid', 'gsec')
        ok = c.exchange_code('code123', 'http://localhost/cb')
        self.assertTrue(ok)
        self.assertTrue(c.is_authenticated)

    @patch('platform_clients.requests.Session')
    def test_exchange_code_failure(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.get.side_effect = _r.RequestException('fail')
        mock_session_cls.return_value = mock_session
        c  = GOGOAuthClient('gid', 'gsec')
        ok = c.exchange_code('code', 'http://localhost/cb')
        self.assertFalse(ok)

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_returns_empty_when_not_authenticated(self, _):
        c = GOGOAuthClient('gid', 'gsec')
        self.assertEqual(c.get_owned_games(), [])

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_normalises_ids(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp({'owned': [111111, 222222]})
        mock_session_cls.return_value = mock_session
        c = GOGOAuthClient('gid', 'gsec')
        c._access_token = 'tok'
        c._token_expiry = 9999999999.0
        with patch.object(c, 'get_game_details', return_value=None):
            games = c.get_owned_games()
        self.assertEqual(len(games), 2)
        self.assertTrue(all(g['platform'] == 'gog' for g in games))

    def test_get_game_details_returns_cached(self):
        c = self._client()
        c.details_cache['42'] = {'title': 'Witcher 3'}
        self.assertEqual(c.get_game_details('42')['title'], 'Witcher 3')

    @patch('platform_clients.requests.Session')
    def test_get_game_details_fetches_from_api(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value = _ok_resp({
            'title': 'CD Projekt Game',
            'summary': 'A great RPG',
            '_embedded': {
                'developers': [{'name': 'CD Projekt Red'}],
                'publisher': {'developers': [{'name': 'CD Projekt'}]},
                'genres': [{'name': 'RPG'}],
                'tags': [],
            }
        })
        mock_session_cls.return_value = mock_session
        c = GOGOAuthClient('gid', 'gsec')
        d = c.get_game_details('9999')
        self.assertEqual(d['title'], 'CD Projekt Game')
        self.assertIn('RPG', [g['description'] for g in d['genres']])


# ===========================================================================
# XboxAPIClient
# ===========================================================================

class TestXboxAPIClient(unittest.TestCase):

    def _client(self):
        return XboxAPIClient(client_id='xid', client_secret='xsec')

    def test_get_platform_name(self):
        self.assertEqual(self._client().get_platform_name(), 'xbox')

    def test_build_auth_url_contains_client_id(self):
        c   = self._client()
        url = c.build_auth_url('http://localhost/cb', state='st')
        self.assertIn('xid', url)
        self.assertIn('XboxLive.signin', url)

    @patch('platform_clients.requests.Session')
    def test_exchange_code_msa_failure_returns_false(self, mock_session_cls):
        import requests as _r
        mock_session = MagicMock()
        mock_session.post.side_effect = _r.RequestException('msa fail')
        mock_session_cls.return_value = mock_session
        c  = XboxAPIClient('xid', 'xsec')
        ok = c.exchange_code('code', 'http://localhost/cb')
        self.assertFalse(ok)

    def test_get_owned_games_returns_empty_when_not_authenticated(self):
        c = XboxAPIClient('xid', 'xsec')
        self.assertEqual(c.get_owned_games(), [])

    def test_get_game_details_returns_cached(self):
        c = self._client()
        c.details_cache['123'] = {'title': 'Halo'}
        self.assertEqual(c.get_game_details('123')['title'], 'Halo')

    def test_xbox_live_auth_header_format(self):
        c = self._client()
        c._user_hash  = 'uhash'
        c._xsts_token = 'xsts_tok'
        h = c._xbox_live_auth_header()
        self.assertIn('XBL3.0', h['Authorization'])
        self.assertIn('uhash', h['Authorization'])
        self.assertIn('xsts_tok', h['Authorization'])

    @patch('platform_clients.requests.Session')
    def test_get_owned_games_paginates(self, mock_session_cls):
        """get_owned_games follows continuationToken until exhausted."""
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            _ok_resp({
                'titles': [{'titleId': '1', 'name': 'Game1', 'gamePass': {}}],
                'pagingInfo': {'continuationToken': 'tok2'},
            }),
            _ok_resp({
                'titles': [{'titleId': '2', 'name': 'Game2', 'gamePass': {}}],
                'pagingInfo': {},
            }),
        ]
        mock_session_cls.return_value = mock_session
        c = XboxAPIClient('xid', 'xsec')
        c._xsts_token = 'xsts'
        c._user_hash  = 'uh'
        games = c.get_owned_games()
        self.assertEqual(len(games), 2)
        self.assertTrue(all(g['platform'] == 'xbox' for g in games))

    @patch('platform_clients.requests.Session')
    def test_refresh_tokens_returns_false_without_refresh_token(self, _):
        c = XboxAPIClient('xid', 'xsec')
        self.assertFalse(c.refresh_tokens())


# ===========================================================================
# MLRecommendationEngine
# ===========================================================================

class TestMLRecommendationEngineBasic(unittest.TestCase):

    def test_empty_games_returns_empty(self):
        eng = MLRecommendationEngine(games=[])
        self.assertEqual(eng.recommend(10), [])

    def test_returns_at_most_count(self):
        games = [_game(i, f'G{i}') for i in range(20)]
        self.assertLessEqual(len(MLRecommendationEngine(games=games).recommend(5)), 5)

    def test_result_has_ml_keys(self):
        games = [_game(1, 'Portal 2')]
        recs  = MLRecommendationEngine(games=games).recommend(1)
        for key in ('ml_score', 'ml_reason', 'playtime_hours'):
            self.assertIn(key, recs[0])

    def test_unplayed_scores_higher_than_barely_played(self):
        games = [_game(1, 'Unplayed', 0), _game(2, 'Barely', 60)]
        recs  = MLRecommendationEngine(games=games, barely_played_mins=120).recommend(2)
        self.assertEqual(recs[0]['name'], 'Unplayed')

    def test_all_methods_run_without_error(self):
        games = [_game(i, f'G{i}', 0) for i in range(5)]
        cache = {i: _details(genres=['Action']) for i in range(5)}
        for method in ('cf', 'mf', 'hybrid'):
            eng  = MLRecommendationEngine(games=games, details_cache=cache)
            recs = eng.recommend(3, method=method)
            self.assertGreater(len(recs), 0, f"method={method} returned no results")

    def test_history_penalty_reduces_score(self):
        games = [_game(1, 'Recent', 0), _game(2, 'Never', 0)]
        eng_with    = MLRecommendationEngine(games=games, history=['steam:1'] * 10)
        eng_without = MLRecommendationEngine(games=games, history=[])
        s_with    = next(r['ml_score'] for r in eng_with.recommend(2)    if r['name'] == 'Recent')
        s_without = next(r['ml_score'] for r in eng_without.recommend(2) if r['name'] == 'Recent')
        self.assertLess(s_with, s_without)

    def test_playtime_hours_computed_correctly(self):
        games = [_game(1, 'G', playtime_mins=120)]
        recs  = MLRecommendationEngine(games=games, barely_played_mins=200).recommend(1)
        self.assertAlmostEqual(recs[0]['playtime_hours'], 2.0)

    def test_fallback_when_no_genres(self):
        """With no genre cache, CF still returns results."""
        games = [_game(i, f'G{i}') for i in range(10)]
        recs  = MLRecommendationEngine(games=games, details_cache={}).recommend(5)
        self.assertLessEqual(len(recs), 5)


class TestMLRecommendationEngineWithGenres(unittest.TestCase):

    def _engine(self):
        games = [
            _game(1, 'Action Hero',   playtime_mins=1200),   # well-played action
            _game(2, 'Action Sequel', playtime_mins=0),
            _game(3, 'Puzzle Master', playtime_mins=0),
        ]
        cache = {
            1: _details(genres=['Action']),
            2: _details(genres=['Action']),
            3: _details(genres=['Puzzle']),
        }
        return MLRecommendationEngine(
            games=games,
            details_cache=cache,
            well_played_mins=600,
            barely_played_mins=120,
        )

    def test_cf_prefers_genre_match(self):
        recs = self._engine().recommend(2, method='cf')
        self.assertEqual(recs[0]['name'], 'Action Sequel')

    def test_mf_runs_without_error(self):
        recs = self._engine().recommend(2, method='mf')
        self.assertGreater(len(recs), 0)

    def test_hybrid_returns_results(self):
        recs = self._engine().recommend(2, method='hybrid')
        self.assertGreater(len(recs), 0)

    def test_method_in_reason(self):
        recs = self._engine().recommend(1, method='cf')
        self.assertIn('item-CF', recs[0]['ml_reason'])

    def test_matrix_built_once(self):
        eng = self._engine()
        eng.recommend(1)
        eng.recommend(1)
        self.assertTrue(eng._built)


class TestMLRecommendationEngineHeuristic(unittest.TestCase):
    """Test the no-numpy heuristic fallback path."""

    def test_heuristic_fallback_works(self):
        games = [_game(i, f'G{i}') for i in range(10)]
        eng   = MLRecommendationEngine(games=games)
        # Manually call the fallback
        recs  = eng._heuristic_fallback(5)
        self.assertLessEqual(len(recs), 5)
        self.assertIn('ml_score', recs[0])
        self.assertIn('Heuristic', recs[0]['ml_reason'])


# ===========================================================================
# Flask route tests
# ===========================================================================

class TestPlatformStatusRoute(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_status_returns_all_platforms(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/platform/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        for plat in ('steam', 'epic', 'gog', 'xbox'):
            self.assertIn(plat, data['platforms'])


class TestEpicRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_epic_library_503_when_not_configured(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/epic/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_epic_library_503_when_not_authenticated(self):
        import gapi_gui
        epic_client = EpicOAuthClient('cid')
        fake_picker = MagicMock()
        fake_picker.clients = {'epic': epic_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/epic/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_epic_library_200_when_authenticated(self):
        import gapi_gui
        epic_client = EpicOAuthClient('cid')
        epic_client._access_token  = 'tok'
        epic_client._token_expiry  = 9999999999.0
        with patch.object(epic_client, 'get_owned_games', return_value=[
            {'name': 'Fortnite', 'platform': 'epic', 'game_id': 'epic:fn'}
        ]):
            fake_picker = MagicMock()
            fake_picker.clients = {'epic': epic_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.client.get('/api/epic/library')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['platform'], 'epic')
        self.assertEqual(data['count'], 1)


class TestGOGRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_gog_library_503_when_not_configured(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/gog/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_gog_library_200_when_authenticated(self):
        import gapi_gui
        gog_client = GOGOAuthClient('gid', 'gsec')
        gog_client._access_token = 'tok'
        gog_client._token_expiry = 9999999999.0
        with patch.object(gog_client, 'get_owned_games', return_value=[
            {'name': 'Witcher 3', 'platform': 'gog', 'game_id': 'gog:9999'}
        ]):
            fake_picker = MagicMock()
            fake_picker.clients = {'gog': gog_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.client.get('/api/gog/library')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['platform'], 'gog')

    @patch('gapi_gui.current_user', 'testuser')
    def test_gog_oauth_callback_400_missing_code(self):
        import gapi_gui
        gog_client = GOGOAuthClient('gid', 'gsec')
        fake_picker = MagicMock()
        fake_picker.clients = {'gog': gog_client}
        fake_picker.config  = {'gog_redirect_uri': 'http://localhost/cb'}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/gog/oauth/callback')
        self.assertEqual(resp.status_code, 400)


class TestXboxRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    def test_xbox_library_503_when_not_configured(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/xbox/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_xbox_library_503_when_not_authenticated(self):
        import gapi_gui
        xbox_client = XboxAPIClient('xid', 'xsec')
        fake_picker = MagicMock()
        fake_picker.clients = {'xbox': xbox_client}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/xbox/library')
        self.assertEqual(resp.status_code, 503)

    @patch('gapi_gui.current_user', 'testuser')
    def test_xbox_library_200_when_authenticated(self):
        import gapi_gui
        xbox_client = XboxAPIClient('xid', 'xsec')
        xbox_client._xsts_token = 'xsts'
        with patch.object(xbox_client, 'get_owned_games', return_value=[
            {'name': 'Halo', 'platform': 'xbox', 'game_id': 'xbox:12345'}
        ]):
            fake_picker = MagicMock()
            fake_picker.clients = {'xbox': xbox_client}
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.client.get('/api/xbox/library')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['platform'], 'xbox')
        self.assertEqual(data['count'], 1)


class TestMLRecommendationsRoute(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    @patch('gapi_gui.picker', None)
    def test_returns_400_when_not_initialized(self):
        resp = self.client.get('/api/recommendations/ml')
        self.assertEqual(resp.status_code, 400)

    @patch('gapi_gui.current_user', 'testuser')
    def test_returns_200_with_games(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.games = [_game(1, 'Portal 2', 0)]
        fake_picker.history = []
        fake_picker.clients = {}
        fake_picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        fake_picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/recommendations/ml?count=5')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('recommendations', data)
        self.assertEqual(data['engine'], 'ml')

    @patch('gapi_gui.current_user', 'testuser')
    def test_valid_method_param(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.games = []
        fake_picker.history = []
        fake_picker.clients = {}
        fake_picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        fake_picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        for method in ('cf', 'mf', 'hybrid'):
            with patch.object(gapi_gui, 'picker', fake_picker):
                resp = self.client.get(f'/api/recommendations/ml?method={method}')
            data = json.loads(resp.data)
            self.assertEqual(data.get('method'), method)

    @patch('gapi_gui.current_user', 'testuser')
    def test_invalid_method_defaults_to_cf(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.games = []
        fake_picker.history = []
        fake_picker.clients = {}
        fake_picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        fake_picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/recommendations/ml?method=bogus')
        data = json.loads(resp.data)
        self.assertEqual(data.get('method'), 'cf')


class TestConfigTemplatePlatforms(unittest.TestCase):
    """config_template.json must contain all new platform keys."""

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config_template.json'
        )
        with open(path) as f:
            self._cfg = json.load(f)

    def test_epic_keys_present(self):
        for k in ('epic_enabled', 'epic_client_id', 'epic_redirect_uri'):
            self.assertIn(k, self._cfg, f"Missing: {k}")

    def test_gog_keys_present(self):
        for k in ('gog_enabled', 'gog_client_id', 'gog_redirect_uri'):
            self.assertIn(k, self._cfg, f"Missing: {k}")

    def test_xbox_keys_present(self):
        for k in ('xbox_enabled', 'xbox_client_id', 'xbox_redirect_uri'):
            self.assertIn(k, self._cfg, f"Missing: {k}")


if __name__ == '__main__':
    unittest.main()
