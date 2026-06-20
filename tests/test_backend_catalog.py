#!/usr/bin/env python3
"""Tests for the migrated catalog grab-bag cluster (FastAPI).

Covers all routes across the seven prefixes:
  optimized:
    GET    /api/optimized/users
    GET    /api/optimized/games
    GET    /api/optimized/leaderboard
    GET    /api/optimized/chat/messages
    GET    /api/optimized/games/search
  collections:
    GET    /api/collections
  favorites:
    GET    /api/favorites
  favorite:
    POST   /api/favorite/{app_id}
    DELETE /api/favorite/{app_id}
  games:
    GET    /api/games/{app_id}/similar
  filters:
    GET    /api/filters/platform-options
  hltb:
    GET    /api/hltb/{game_name}

Services / DB / cache live on gapi_gui and are mocked so the tests never touch a
real database. Auth is via a signed Flask session cookie.

Run with:
    python -m pytest tests/test_backend_catalog.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _fake_db():
    """A MagicMock that satisfies ``next(database.get_db())`` + ``.close()``."""
    return MagicMock()


def _patch_get_db():
    """Patch database.get_db to yield a single fake session."""
    return patch.object(gapi_gui.database, 'get_db', side_effect=lambda: iter([_fake_db()]))


def _patch_session_local(db=None):
    """Patch database.SessionLocal to return a fake (closeable) session."""
    return patch.object(gapi_gui.database, 'SessionLocal',
                        return_value=db if db is not None else _fake_db())


def _patch_session_local_error(msg):
    """Patch database.SessionLocal so calling it raises (simulates a DB error)."""
    return patch.object(gapi_gui.database, 'SessionLocal',
                        side_effect=RuntimeError(msg))


def _query_db(count=0, rows=None):
    """A fake session whose ``query(...).order_by(...).limit(...).offset(...).all()``

    returns *rows* and whose ``query(...).count()`` returns *count*.
    """
    rows = rows or []
    db = MagicMock()
    q = db.query.return_value
    q.count.return_value = count
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.offset.return_value = q
    q.all.return_value = rows
    return db


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_optimized_users_requires_login(self):
        self.assertEqual(self.client.get('/api/optimized/users').status_code, 401)

    def test_optimized_games_requires_login(self):
        self.assertEqual(self.client.get('/api/optimized/games').status_code, 401)

    def test_optimized_leaderboard_requires_login(self):
        self.assertEqual(self.client.get('/api/optimized/leaderboard').status_code, 401)

    def test_optimized_chat_messages_requires_login(self):
        self.assertEqual(self.client.get('/api/optimized/chat/messages').status_code, 401)

    def test_optimized_games_search_requires_login(self):
        self.assertEqual(self.client.get('/api/optimized/games/search?q=do').status_code, 401)

    def test_collections_requires_login(self):
        self.assertEqual(self.client.get('/api/collections').status_code, 401)

    def test_favorites_requires_login(self):
        self.assertEqual(self.client.get('/api/favorites').status_code, 401)

    def test_favorite_post_requires_login(self):
        self.assertEqual(self.client.post('/api/favorite/42').status_code, 401)

    def test_favorite_delete_requires_login(self):
        self.assertEqual(self.client.delete('/api/favorite/42').status_code, 401)

    def test_similar_requires_login(self):
        self.assertEqual(self.client.get('/api/games/42/similar').status_code, 401)

    def test_filters_requires_login(self):
        self.assertEqual(self.client.get('/api/filters/platform-options').status_code, 401)

    def test_hltb_requires_login(self):
        self.assertEqual(self.client.get('/api/hltb/Portal%202').status_code, 401)


# ── GET /api/optimized/users ────────────────────────────────────────────────

class OptimizedUsersTest(_AuthedCase):
    def test_performance_unavailable_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/optimized/users')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Performance module not available')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_db_error_500(self):
        # A failure in the SQLAlchemy layer surfaces as a 500 (no-store).
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local_error('boom'):
            resp = self.client.get('/api/optimized/users')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success_real_data(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)

        def _paginate(items, page, per_page, total_count):
            return {'items': items, 'page': page, 'total': total_count}
        perf.Paginator.paginate.side_effect = _paginate

        u = MagicMock(id=7, username='alice', email='a@x.io', created_at='2026-01-01')
        db = _query_db(count=1, rows=[u])
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local(db):
            resp = self.client.get('/api/optimized/users')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['endpoint'], 'optimized-users')
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['items'][0], {
            'id': 7, 'username': 'alice', 'email': 'a@x.io',
            'created_at': '2026-01-01'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── GET /api/optimized/games ────────────────────────────────────────────────

class OptimizedGamesTest(_AuthedCase):
    def test_performance_unavailable_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/optimized/games')
        self.assertEqual(resp.status_code, 503)

    def test_success(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        perf.Paginator.paginate.return_value = {'items': [{'name': 'Doom'}], 'page': 1}
        picker = MagicMock()
        picker.games = [{'name': 'Doom'}]
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/optimized/games')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['endpoint'], 'optimized-games')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_error_500(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf):
            resp = self.client.get('/api/optimized/games')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


# ── GET /api/optimized/leaderboard ──────────────────────────────────────────

class OptimizedLeaderboardTest(_AuthedCase):
    def test_performance_unavailable_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/optimized/leaderboard')
        self.assertEqual(resp.status_code, 503)

    def test_cache_hit_returns_cached_true(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        perf.get_cache.return_value.get.return_value = [{'username': 'a', 'value': 1}]
        perf.Paginator.paginate.return_value = {'items': [{'username': 'a'}]}
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf):
            resp = self.client.get('/api/optimized/leaderboard')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['cached'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_cache_miss_queries_real_data(self):
        # On cache miss, the route queries the SQLAlchemy layer and caches it.
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        perf.get_cache.return_value.get.return_value = None

        def _paginate(items, page, per_page, total_count):
            return {'items': items, 'page': page, 'total': total_count}
        perf.Paginator.paginate.side_effect = _paginate

        rows = [{'username': 'alice', 'value': 9}, {'username': 'bob', 'value': 4}]
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local(), \
                patch.object(gapi_gui.database, 'get_category_leaderboard',
                             return_value=rows):
            resp = self.client.get('/api/optimized/leaderboard')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['cached'])
        self.assertEqual(body['items'][0],
                         {'username': 'alice', 'value': 9, 'rank': 1})
        # The computed leaderboard was cached for next time.
        perf.get_cache.return_value.set.assert_called_once()

    def test_cache_miss_db_error_500(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        perf.get_cache.return_value.get.return_value = None
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local(), \
                patch.object(gapi_gui.database, 'get_category_leaderboard',
                             side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/optimized/leaderboard')
        self.assertEqual(resp.status_code, 500)


# ── GET /api/optimized/chat/messages ────────────────────────────────────────

class OptimizedChatMessagesTest(_AuthedCase):
    def test_performance_unavailable_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/optimized/chat/messages')
        self.assertEqual(resp.status_code, 503)

    def test_db_error_500(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local_error('boom'):
            resp = self.client.get('/api/optimized/chat/messages')
        self.assertEqual(resp.status_code, 500)

    def test_success_real_data(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)

        def _paginate(items, page, per_page, total_count):
            return {'items': items, 'page': page, 'total': total_count}
        perf.Paginator.paginate.side_effect = _paginate

        msg = MagicMock(id=3, message='hi', created_at='2026-01-02')
        msg.sender = MagicMock(username='alice')
        db = _query_db(count=1, rows=[msg])
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                _patch_session_local(db):
            resp = self.client.get('/api/optimized/chat/messages?room=general')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['room'], 'general')
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['items'][0], {
            'id': 3, 'username': 'alice', 'message': 'hi',
            'created_at': '2026-01-02'})


# ── GET /api/optimized/games/search ─────────────────────────────────────────

class OptimizedGamesSearchTest(_AuthedCase):
    def test_performance_unavailable_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/optimized/games/search?q=doom')
        self.assertEqual(resp.status_code, 503)

    def test_short_query_returns_empty(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf):
            resp = self.client.get('/api/optimized/games/search?q=d')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'items': [], 'page': 1, 'total': 0})

    def test_no_picker_returns_empty(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/optimized/games/search?q=doom')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'items': [], 'page': 1, 'total': 0})

    def test_success_filters_by_query(self):
        perf = MagicMock()
        perf.LazyLoadHelper.extract_pagination_params.return_value = (1, 20)
        perf.Paginator.paginate.return_value = {'items': [{'name': 'Doom'}], 'page': 1}
        picker = MagicMock()
        picker.games = [{'name': 'Doom'}, {'name': 'Halo'}]
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/optimized/games/search?q=doom')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['query'], 'doom')
        # only the matching game was passed to paginate
        passed = perf.Paginator.paginate.call_args.args[0]
        self.assertEqual(passed, [{'name': 'Doom'}])


# ── GET /api/collections ────────────────────────────────────────────────────

class CollectionsTest(_AuthedCase):
    def test_success_static_payload(self):
        resp = self.client.get('/api/collections')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['mastery_tier'], 'Silver')
        self.assertEqual(body['total_completion'], 49)
        self.assertEqual(len(body['collections']), 3)
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── GET /api/favorites ──────────────────────────────────────────────────────

class FavoritesTest(_AuthedCase):
    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/favorites')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Database not available')

    def test_success_maps_known_and_unknown(self):
        fav_svc = MagicMock()
        fav_svc.get_all.return_value = ['100', '200']
        lib_svc = MagicMock()
        lib_svc.get_cached.return_value = [
            {'app_id': '100', 'name': 'Doom', 'playtime_hours': 3.4,
             'platform': 'steam', 'tags': ['fps'], 'game_id': 'steam:100'},
        ]
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc), \
                patch.object(gapi_gui, '_library_service', lib_svc):
            resp = self.client.get('/api/favorites')
        self.assertEqual(resp.status_code, 200)
        favs = resp.json()['favorites']
        self.assertEqual(favs[0]['name'], 'Doom')
        self.assertEqual(favs[1]['name'], 'App ID 200 (Not in library)')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_error_500(self):
        fav_svc = MagicMock()
        fav_svc.get_all.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc), \
                patch.object(gapi_gui, '_library_service', MagicMock()):
            resp = self.client.get('/api/favorites')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to load favorites')


# ── POST / DELETE /api/favorite/{app_id} ────────────────────────────────────

class ToggleFavoriteTest(_AuthedCase):
    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.post('/api/favorite/42')
        self.assertEqual(resp.status_code, 503)

    def test_add_success(self):
        fav_svc = MagicMock()
        fav_svc.add.return_value = True
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc):
            resp = self.client.post('/api/favorite/42')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'action': 'added'})
        fav_svc.add.assert_called_once()
        self.assertEqual(fav_svc.add.call_args.args[2], '42')

    def test_remove_success(self):
        fav_svc = MagicMock()
        fav_svc.remove.return_value = True
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc):
            resp = self.client.delete('/api/favorite/42')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'action': 'removed'})

    def test_add_failure_500(self):
        fav_svc = MagicMock()
        fav_svc.add.return_value = False
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc):
            resp = self.client.post('/api/favorite/42')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to add favorite')

    def test_non_int_app_id_422(self):
        resp = self.client.post('/api/favorite/notanint')
        self.assertEqual(resp.status_code, 422)

    def test_exception_500(self):
        fav_svc = MagicMock()
        fav_svc.add.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_db_favorites_service', fav_svc):
            resp = self.client.post('/api/favorite/42')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to toggle favorite')


# ── GET /api/games/{app_id}/similar ─────────────────────────────────────────

class SimilarGamesTest(_AuthedCase):
    def test_db_unavailable_returns_empty(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/games/42/similar')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'app_id': '42', 'similar': []})

    def test_success(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_similar_games',
                             return_value=[{'app_id': '7', 'game_name': 'X'}]):
            resp = self.client.get('/api/games/42/similar?platform=steam&limit=5')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['app_id'], '42')
        self.assertEqual(body['platform'], 'steam')
        self.assertEqual(body['similar'], [{'app_id': '7', 'game_name': 'X'}])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_bad_limit_defaults_to_10(self):
        captured = {}

        def _fake(db, app_id, platform, limit):
            captured['limit'] = limit
            return []

        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_similar_games', side_effect=_fake):
            resp = self.client.get('/api/games/42/similar?limit=notanumber')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured['limit'], 10)

    def test_limit_clamped_to_50(self):
        captured = {}

        def _fake(db, app_id, platform, limit):
            captured['limit'] = limit
            return []

        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_similar_games', side_effect=_fake):
            self.client.get('/api/games/42/similar?limit=999')
        self.assertEqual(captured['limit'], 50)

    def test_error_500(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_similar_games',
                             side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/games/42/similar')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


# ── GET /api/filters/platform-options ───────────────────────────────────────

class FilterPlatformOptionsTest(_AuthedCase):
    def test_success_default_user(self):
        with patch.object(gapi_gui, '_collect_available_platforms',
                          return_value=['steam', 'xbox']):
            resp = self.client.get('/api/filters/platform-options')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        values = [p['value'] for p in body['platforms']]
        self.assertEqual(values, ['steam', 'xbox'])
        device_values = {d['value'] for d in body['devices']}
        self.assertEqual(device_values, {'pc', 'console'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_users_param_passed_through(self):
        captured = {}

        def _fake(usernames):
            captured['usernames'] = usernames
            return []

        with patch.object(gapi_gui, '_collect_available_platforms', side_effect=_fake):
            resp = self.client.get('/api/filters/platform-options?users=bob,carol')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured['usernames'], ['bob', 'carol'])


# ── GET /api/hltb/{game_name} ───────────────────────────────────────────────

class HltbTest(_AuthedCase):
    def test_success(self):
        data = {'game_name': 'Portal 2', 'main': 8.5}
        with patch.object(gapi_gui.gapi, 'get_hltb_data', return_value=data):
            resp = self.client.get('/api/hltb/Portal%202')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), data)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_path_is_url_decoded(self):
        captured = {}

        def _fake(name):
            captured['name'] = name
            return {'game_name': name}

        with patch.object(gapi_gui.gapi, 'get_hltb_data', side_effect=_fake):
            self.client.get('/api/hltb/Portal%202')
        self.assertEqual(captured['name'], 'Portal 2')

    def test_no_data_503(self):
        with patch.object(gapi_gui.gapi, 'get_hltb_data', return_value=None):
            resp = self.client.get('/api/hltb/Unknown')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'No HLTB data available for this game')


if __name__ == '__main__':
    unittest.main()
