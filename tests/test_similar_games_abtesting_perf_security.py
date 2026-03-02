#!/usr/bin/env python3
"""
Tests for:
  - Similar Games endpoint (Item 8)
  - A/B Testing Framework for Recommendations (Item 13)
  - Security Headers: HSTS + CSP (Item 19)
  - CSRF Protection (Item 19)
  - Cache-Control headers (Item 18)
  - Resource hints in HTML (Item 18)

Run with:
    python -m pytest tests/test_similar_games_abtesting_perf_security.py
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui
import database


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _set_user_session(client, username='bob'):
    with client.session_transaction() as sess:
        sess['username'] = username


# ---------------------------------------------------------------------------
# GET /api/games/<app_id>/similar
# ---------------------------------------------------------------------------

class TestSimilarGames(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.get('/api/games/123/similar')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_empty_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/games/123/similar')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['similar'], [])

    def test_returns_200_with_correct_shape(self):
        mock_db = MagicMock()
        fake_similar = [
            {'app_id': '456', 'game_name': 'Similar Game', 'platform': 'steam',
             'similarity_score': 0.75},
        ]
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_similar_games', return_value=fake_similar), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/games/123/similar')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('app_id', data)
        self.assertIn('platform', data)
        self.assertIn('similar', data)
        self.assertEqual(len(data['similar']), 1)
        self.assertIn('similarity_score', data['similar'][0])

    def test_default_platform_is_steam(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_similar_games', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/games/999/similar')
            args, kwargs = mock_fn.call_args
            # platform arg: positional or keyword
            platform = kwargs.get('platform') or (args[2] if len(args) > 2 else 'steam')
            self.assertEqual(platform, 'steam')

    def test_custom_platform_forwarded(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_similar_games', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/games/999/similar?platform=epic')
            _, kwargs = mock_fn.call_args
            platform = kwargs.get('platform') or mock_fn.call_args[0][2]
            self.assertEqual(platform, 'epic')

    def test_limit_capped_at_50(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_similar_games', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/games/999/similar?limit=999')
            _, kwargs = mock_fn.call_args
            limit = kwargs.get('limit') or mock_fn.call_args[0][3]
            self.assertLessEqual(limit, 50)

    def test_invalid_limit_defaults_to_10(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_similar_games', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/games/999/similar?limit=abc')
            _, kwargs = mock_fn.call_args
            limit = kwargs.get('limit') or mock_fn.call_args[0][3]
            self.assertEqual(limit, 10)


# ---------------------------------------------------------------------------
# POST /api/admin/ab-tests
# ---------------------------------------------------------------------------

class TestCreateABTest(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/ab-tests',
                                json={'name': 'exp1', 'variants': ['a', 'b']})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'name': 'exp1', 'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 503)

    def test_missing_name_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 400)

    def test_single_variant_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'name': 'exp', 'variants': ['only_one']})
        self.assertEqual(resp.status_code, 400)

    def test_non_list_variants_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'name': 'exp', 'variants': 'a,b'})
        self.assertEqual(resp.status_code, 400)

    def test_create_returns_201_with_experiment(self):
        mock_db = MagicMock()
        fake_exp = {'id': 1, 'name': 'test_exp', 'variants': ['control', 'ml'],
                    'status': 'draft', 'description': '',
                    'created_by': 'admin', 'created_at': '2026-03-01T00:00:00',
                    'started_at': None, 'ended_at': None}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_experiment', return_value=fake_exp), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'name': 'test_exp', 'variants': ['control', 'ml']})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.data)
        self.assertEqual(data['name'], 'test_exp')
        self.assertIn('variants', data)

    def test_conflict_returns_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_experiment', return_value={}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/ab-tests',
                                        json={'name': 'dup', 'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 409)


# ---------------------------------------------------------------------------
# GET /api/admin/ab-tests
# ---------------------------------------------------------------------------

class TestListABTests(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/ab-tests')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_experiments_with_variant_counts(self):
        mock_db = MagicMock()
        fake_exps = [{'id': 1, 'name': 'exp1', 'variants': ['control', 'ml'],
                      'status': 'active', 'description': '',
                      'created_by': 'admin', 'created_at': '2026-01-01T00:00:00',
                      'started_at': None, 'ended_at': None}]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.list_experiments', return_value=fake_exps), \
                 patch('database.get_experiment_variant_counts', return_value={'control': 5, 'ml': 3}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('experiments', data)
        self.assertEqual(len(data['experiments']), 1)
        self.assertIn('variant_counts', data['experiments'][0])

    def test_empty_db_returns_empty_list(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['experiments'], [])


# ---------------------------------------------------------------------------
# PATCH /api/admin/ab-tests/<id>
# ---------------------------------------------------------------------------

class TestUpdateABTest(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.patch('/api/admin/ab-tests/1', json={'status': 'active'})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.patch('/api/admin/ab-tests/1', json={'status': 'active'})
        self.assertEqual(resp.status_code, 503)

    def test_invalid_status_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.patch('/api/admin/ab-tests/1', json={'status': 'running'})
        self.assertEqual(resp.status_code, 400)

    def test_not_found_returns_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.update_experiment_status', return_value={}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.patch('/api/admin/ab-tests/99', json={'status': 'active'})
        self.assertEqual(resp.status_code, 404)

    def test_successful_update_returns_200(self):
        mock_db = MagicMock()
        fake_exp = {'id': 1, 'name': 'exp1', 'variants': ['control', 'ml'],
                    'status': 'active', 'description': '',
                    'created_by': 'admin', 'created_at': '2026-01-01T00:00:00',
                    'started_at': '2026-01-02T00:00:00', 'ended_at': None}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.update_experiment_status', return_value=fake_exp), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.patch('/api/admin/ab-tests/1', json={'status': 'active'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['status'], 'active')


# ---------------------------------------------------------------------------
# GET /api/recommendations/variant
# ---------------------------------------------------------------------------

class TestGetRecommendationVariant(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.get('/api/recommendations/variant?experiment=myexp')
        self.assertIn(resp.status_code, (401, 403))

    def test_missing_experiment_returns_400(self):
        _set_user_session(self.client)
        resp = self.client.get('/api/recommendations/variant')
        self.assertEqual(resp.status_code, 400)

    def test_returns_null_variant_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/recommendations/variant?experiment=myexp')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsNone(data['variant'])

    def test_returns_assigned_variant(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_or_assign_variant', return_value='ml'), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/recommendations/variant?experiment=myexp')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['variant'], 'ml')
        self.assertEqual(data['experiment'], 'myexp')

    def test_returns_null_for_inactive_experiment(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_or_assign_variant', return_value=None), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/recommendations/variant?experiment=inactive_exp')
        data = json.loads(resp.data)
        self.assertIsNone(data['variant'])


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _get_any_response(self):
        """Get a simple API response to inspect headers."""
        return self.client.get('/api/permissions')

    def test_x_content_type_options(self):
        resp = self._get_any_response()
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')

    def test_x_frame_options(self):
        resp = self._get_any_response()
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'SAMEORIGIN')

    def test_referrer_policy(self):
        resp = self._get_any_response()
        self.assertEqual(resp.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')

    def test_hsts_header_present(self):
        resp = self._get_any_response()
        hsts = resp.headers.get('Strict-Transport-Security', '')
        self.assertIn('max-age=', hsts)
        self.assertIn('31536000', hsts)

    def test_csp_header_present(self):
        resp = self._get_any_response()
        csp = resp.headers.get('Content-Security-Policy', '')
        self.assertIn("default-src", csp)
        self.assertIn("'self'", csp)

    def test_csp_contains_script_src(self):
        resp = self._get_any_response()
        csp = resp.headers.get('Content-Security-Policy', '')
        self.assertIn("script-src", csp)

    def test_csp_frame_ancestors_none(self):
        resp = self._get_any_response()
        csp = resp.headers.get('Content-Security-Policy', '')
        self.assertIn("frame-ancestors 'none'", csp)

    def test_permissions_policy(self):
        resp = self._get_any_response()
        pp = resp.headers.get('Permissions-Policy', '')
        self.assertIn('geolocation=()', pp)


# ---------------------------------------------------------------------------
# CSRF Token endpoint
# ---------------------------------------------------------------------------

class TestCSRFToken(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_get_csrf_token_returns_200(self):
        resp = self.client.get('/api/csrf-token')
        self.assertEqual(resp.status_code, 200)

    def test_response_contains_token(self):
        resp = self.client.get('/api/csrf-token')
        data = json.loads(resp.data)
        self.assertIn('token', data)
        self.assertIsInstance(data['token'], str)
        self.assertGreater(len(data['token']), 10)

    def test_sets_csrf_cookie(self):
        resp = self.client.get('/api/csrf-token')
        # Cookie is set via Set-Cookie header
        set_cookie = resp.headers.get('Set-Cookie', '')
        self.assertIn('csrf_token', set_cookie)

    def test_cookie_value_matches_body_token(self):
        resp = self.client.get('/api/csrf-token')
        data = json.loads(resp.data)
        token_in_body = data['token']
        set_cookie = resp.headers.get('Set-Cookie', '')
        # The cookie value appears right after "csrf_token="
        self.assertIn(f'csrf_token={token_in_body}', set_cookie)

    def test_tokens_are_unique_across_requests(self):
        r1 = json.loads(self.client.get('/api/csrf-token').data)['token']
        r2 = json.loads(self.client.get('/api/csrf-token').data)['token']
        self.assertNotEqual(r1, r2)

    def test_csrf_validation_bypassed_in_testing_mode(self):
        """TESTING=True should bypass CSRF so unit tests remain unaffected."""
        # POST without CSRF token should still succeed when TESTING is True
        _set_user_session(self.client)
        resp = self.client.post('/api/notifications/preferences', json={})
        # Should NOT be 403 (CSRF failure). May be 200, 500 (db not available), or 503.
        self.assertNotEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# Cache-Control headers
# ---------------------------------------------------------------------------

class TestCacheControlHeaders(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_public_endpoint_is_cacheable(self):
        resp = self.client.get('/api/permissions')
        cc = resp.headers.get('Cache-Control', '')
        self.assertIn('public', cc)
        self.assertIn('max-age=60', cc)

    def test_changelog_endpoint_is_cacheable(self):
        resp = self.client.get('/api/changelog')
        cc = resp.headers.get('Cache-Control', '')
        self.assertIn('public', cc)

    def test_authenticated_endpoint_has_no_store(self):
        _set_user_session(self.client)
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notification_prefs', return_value={
                 'email_enabled': False, 'push_enabled': True,
                 'friend_requests': True, 'challenge_updates': True,
                 'trade_offers': True, 'team_events': True,
                 'system_announcements': True, 'digest_frequency': 'never',
                 'updated_at': '2026-01-01T00:00:00',
             }), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/notifications/preferences')
        cc = resp.headers.get('Cache-Control', '')
        self.assertIn('no-store', cc)


# ---------------------------------------------------------------------------
# Resource hints in HTML template
# ---------------------------------------------------------------------------

class TestResourceHints(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _get_html(self):
        resp = self.client.get('/')
        return resp.data.decode('utf-8', errors='replace')

    def test_dns_prefetch_present(self):
        html = self._get_html()
        self.assertIn('dns-prefetch', html)

    def test_preconnect_present(self):
        html = self._get_html()
        self.assertIn('preconnect', html)

    def test_fonts_googleapis_hint(self):
        html = self._get_html()
        self.assertIn('fonts.googleapis.com', html)


# ---------------------------------------------------------------------------
# Database helpers: get_similar_games
# ---------------------------------------------------------------------------

class TestGetSimilarGamesHelper(unittest.TestCase):
    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        eng = create_engine('sqlite:///:memory:', echo=False)
        database.Base.metadata.create_all(bind=eng)
        Session = sessionmaker(bind=eng)
        return eng, Session()

    def test_returns_empty_when_db_none(self):
        result = database.get_similar_games(None, '123')
        self.assertEqual(result, [])

    def test_returns_empty_when_no_data(self):
        _, db = self._make_db()
        result = database.get_similar_games(db, '123')
        self.assertEqual(result, [])
        db.close()

    def test_finds_similar_game_by_genre_overlap(self):
        import json as _json
        _, db = self._make_db()
        # Insert target game
        target = database.GameDetailsCache(
            app_id='100', platform='steam',
            details_json=_json.dumps({
                'name': 'Action Hero',
                'genres': [{'description': 'Action'}, {'description': 'Adventure'}],
                'categories': [], 'tags': ['fps', 'shooter'],
            }),
        )
        # Similar game (same genres)
        similar = database.GameDetailsCache(
            app_id='200', platform='steam',
            details_json=_json.dumps({
                'name': 'Action Man',
                'genres': [{'description': 'Action'}],
                'categories': [], 'tags': ['fps'],
            }),
        )
        # Unrelated game
        unrelated = database.GameDetailsCache(
            app_id='300', platform='steam',
            details_json=_json.dumps({
                'name': 'Puzzle Quest',
                'genres': [{'description': 'Puzzle'}],
                'categories': [], 'tags': ['casual'],
            }),
        )
        db.add_all([target, similar, unrelated])
        db.commit()
        results = database.get_similar_games(db, '100', platform='steam', limit=5)
        self.assertGreater(len(results), 0)
        # Scores should be sorted descending
        scores = [r['similarity_score'] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # The similar game should rank above the unrelated one
        ids = [r['app_id'] for r in results]
        if '300' in ids:
            idx_similar = ids.index('200')
            idx_unrelated = ids.index('300')
            self.assertLess(idx_similar, idx_unrelated)
        db.close()

    def test_different_platform_excluded(self):
        import json as _json
        _, db = self._make_db()
        target = database.GameDetailsCache(
            app_id='100', platform='steam',
            details_json=_json.dumps({'name': 'GameA', 'genres': [{'description': 'Action'}],
                                      'categories': [], 'tags': []}),
        )
        epic_game = database.GameDetailsCache(
            app_id='200', platform='epic',
            details_json=_json.dumps({'name': 'GameB', 'genres': [{'description': 'Action'}],
                                      'categories': [], 'tags': []}),
        )
        db.add_all([target, epic_game])
        db.commit()
        results = database.get_similar_games(db, '100', platform='steam')
        ids = [r['app_id'] for r in results]
        self.assertNotIn('200', ids)
        db.close()

    def test_limit_respected(self):
        import json as _json
        _, db = self._make_db()
        target = database.GameDetailsCache(
            app_id='0', platform='steam',
            details_json=_json.dumps({'name': 'Base', 'genres': [{'description': 'Action'}],
                                      'categories': [], 'tags': []}),
        )
        db.add(target)
        for i in range(1, 15):
            db.add(database.GameDetailsCache(
                app_id=str(i), platform='steam',
                details_json=_json.dumps({
                    'name': f'Game{i}',
                    'genres': [{'description': 'Action'}],
                    'categories': [], 'tags': [],
                }),
            ))
        db.commit()
        results = database.get_similar_games(db, '0', platform='steam', limit=3)
        self.assertLessEqual(len(results), 3)
        db.close()


# ---------------------------------------------------------------------------
# Database helpers: A/B testing
# ---------------------------------------------------------------------------

class TestABTestingHelpers(unittest.TestCase):
    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        eng = create_engine('sqlite:///:memory:', echo=False)
        database.Base.metadata.create_all(bind=eng)
        Session = sessionmaker(bind=eng)
        return eng, Session()

    def test_create_experiment_returns_dict(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'test_exp', ['control', 'ml'], 'test')
        self.assertIn('id', exp)
        self.assertEqual(exp['name'], 'test_exp')
        self.assertEqual(exp['status'], 'draft')
        self.assertEqual(exp['variants'], ['control', 'ml'])
        db.close()

    def test_create_experiment_returns_empty_on_none_db(self):
        result = database.create_experiment(None, 'x', ['a', 'b'])
        self.assertEqual(result, {})

    def test_list_experiments(self):
        _, db = self._make_db()
        database.create_experiment(db, 'exp_a', ['x', 'y'])
        database.create_experiment(db, 'exp_b', ['p', 'q'])
        exps = database.list_experiments(db)
        self.assertEqual(len(exps), 2)
        names = {e['name'] for e in exps}
        self.assertIn('exp_a', names)
        self.assertIn('exp_b', names)
        db.close()

    def test_list_experiments_empty_on_none_db(self):
        self.assertEqual(database.list_experiments(None), [])

    def test_update_status_active(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'exp_c', ['a', 'b'])
        updated = database.update_experiment_status(db, exp['id'], 'active')
        self.assertEqual(updated['status'], 'active')
        self.assertIsNotNone(updated['started_at'])
        db.close()

    def test_update_status_concluded_sets_ended_at(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'exp_d', ['a', 'b'])
        database.update_experiment_status(db, exp['id'], 'active')
        updated = database.update_experiment_status(db, exp['id'], 'concluded')
        self.assertEqual(updated['status'], 'concluded')
        self.assertIsNotNone(updated['ended_at'])
        db.close()

    def test_update_status_returns_empty_for_missing(self):
        _, db = self._make_db()
        result = database.update_experiment_status(db, 99999, 'active')
        self.assertEqual(result, {})
        db.close()

    def test_get_or_assign_variant_returns_none_for_inactive(self):
        _, db = self._make_db()
        database.create_experiment(db, 'draft_exp', ['a', 'b'])
        result = database.get_or_assign_variant(db, 'alice', 'draft_exp')
        self.assertIsNone(result)
        db.close()

    def test_get_or_assign_variant_active(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'active_exp', ['control', 'treatment'])
        database.update_experiment_status(db, exp['id'], 'active')
        variant = database.get_or_assign_variant(db, 'alice', 'active_exp')
        self.assertIn(variant, ('control', 'treatment'))
        db.close()

    def test_get_or_assign_variant_deterministic(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'det_exp', ['control', 'treatment'])
        database.update_experiment_status(db, exp['id'], 'active')
        v1 = database.get_or_assign_variant(db, 'bob', 'det_exp')
        v2 = database.get_or_assign_variant(db, 'bob', 'det_exp')
        self.assertEqual(v1, v2)
        db.close()

    def test_get_or_assign_variant_returns_none_for_none_db(self):
        self.assertIsNone(database.get_or_assign_variant(None, 'alice', 'exp'))

    def test_get_experiment_variant_counts(self):
        _, db = self._make_db()
        exp = database.create_experiment(db, 'count_exp', ['x', 'y'])
        database.update_experiment_status(db, exp['id'], 'active')
        for user in ['u1', 'u2', 'u3']:
            database.get_or_assign_variant(db, user, 'count_exp')
        counts = database.get_experiment_variant_counts(db, exp['id'])
        self.assertIsInstance(counts, dict)
        self.assertEqual(sum(counts.values()), 3)
        db.close()

    def test_get_experiment_variant_counts_empty_on_none_db(self):
        self.assertEqual(database.get_experiment_variant_counts(None, 1), {})


if __name__ == '__main__':
    unittest.main()
