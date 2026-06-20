#!/usr/bin/env python3
"""Tests for the migrated search domain (FastAPI).

Covers all 7 routes under /api/search:
  * POST   /api/search/advanced
  * POST   /api/search/save
  * GET    /api/search/saved
  * DELETE /api/search/saved/{search_id}
  * GET    /api/search/trending
  * GET    /api/search/history
  * DELETE /api/search/history

The search service and database helpers live on gapi_gui and are mocked so the
tests never touch a real database.

Run with:
    python -m pytest tests/test_backend_search.py
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


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_advanced_requires_login(self):
        self.assertEqual(
            self.client.post('/api/search/advanced', json={}).status_code, 401)

    def test_save_requires_login(self):
        self.assertEqual(
            self.client.post('/api/search/save', json={}).status_code, 401)

    def test_saved_requires_login(self):
        self.assertEqual(self.client.get('/api/search/saved').status_code, 401)

    def test_delete_saved_requires_login(self):
        self.assertEqual(self.client.delete('/api/search/saved/1').status_code, 401)

    def test_trending_requires_login(self):
        self.assertEqual(self.client.get('/api/search/trending').status_code, 401)

    def test_history_get_requires_login(self):
        self.assertEqual(self.client.get('/api/search/history').status_code, 401)

    def test_history_delete_requires_login(self):
        self.assertEqual(self.client.delete('/api/search/history').status_code, 401)


# ── POST /api/search/advanced ───────────────────────────────────────────────

class AdvancedSearchTest(_AuthedCase):
    def test_success_limits_and_records(self):
        svc = MagicMock()
        svc.search_games.return_value = [{'id': i} for i in range(60)]
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db(), \
                patch.object(gapi_gui.database, 'record_search') as rec:
            resp = self.client.post('/api/search/advanced',
                                    json={'query': 'doom', 'filters': {'genre': 'fps'}})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['query'], 'doom')
        self.assertEqual(body['count'], 60)
        self.assertEqual(len(body['results']), 50)  # capped at 50
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        svc.search_games.assert_called_once()
        rec.assert_called_once()

    def test_no_record_when_query_empty(self):
        svc = MagicMock()
        svc.search_games.return_value = []
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db(), \
                patch.object(gapi_gui.database, 'record_search') as rec:
            resp = self.client.post('/api/search/advanced', json={'filters': {}})
        self.assertEqual(resp.status_code, 200)
        rec.assert_not_called()

    def test_record_failure_is_swallowed(self):
        svc = MagicMock()
        svc.search_games.return_value = [{'id': 1}]
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db(), \
                patch.object(gapi_gui.database, 'record_search',
                             side_effect=RuntimeError('boom')):
            resp = self.client.post('/api/search/advanced', json={'query': 'x'})
        self.assertEqual(resp.status_code, 200)

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_search_service', None):
            resp = self.client.post('/api/search/advanced', json={'query': 'x'})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Search service not available')

    def test_service_error_500(self):
        svc = MagicMock()
        svc.search_games.side_effect = RuntimeError('kaboom')
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.post('/api/search/advanced', json={'query': 'x'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'kaboom')


# ── POST /api/search/save ───────────────────────────────────────────────────

class SaveSearchTest(_AuthedCase):
    def test_success(self):
        svc = MagicMock()
        svc.save_search.return_value = True
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.post('/api/search/save',
                                    json={'name': 'My Search', 'query': 'doom',
                                          'filters': {}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})

    def test_missing_name_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.post('/api/search/save',
                                    json={'name': '  ', 'query': 'doom'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Name and query required')

    def test_missing_query_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.post('/api/search/save',
                                    json={'name': 'X', 'query': ''})
        self.assertEqual(resp.status_code, 400)

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_search_service', None):
            resp = self.client.post('/api/search/save',
                                    json={'name': 'X', 'query': 'y'})
        self.assertEqual(resp.status_code, 503)

    def test_service_error_500(self):
        svc = MagicMock()
        svc.save_search.side_effect = RuntimeError('db down')
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.post('/api/search/save',
                                    json={'name': 'X', 'query': 'y'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'db down')


# ── GET /api/search/saved ───────────────────────────────────────────────────

class GetSavedSearchesTest(_AuthedCase):
    def test_success(self):
        svc = MagicMock()
        svc.get_saved_searches.return_value = [{'id': 1, 'name': 'A'}]
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.get('/api/search/saved')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'searches': [{'id': 1, 'name': 'A'}]})

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_search_service', None):
            resp = self.client.get('/api/search/saved')
        self.assertEqual(resp.status_code, 503)

    def test_service_error_500(self):
        svc = MagicMock()
        svc.get_saved_searches.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.get('/api/search/saved')
        self.assertEqual(resp.status_code, 500)


# ── DELETE /api/search/saved/{search_id} ────────────────────────────────────

class DeleteSavedSearchTest(_AuthedCase):
    def test_success(self):
        svc = MagicMock()
        svc.delete_saved_search.return_value = True
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.delete('/api/search/saved/42')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})
        svc.delete_saved_search.assert_called_once()
        self.assertEqual(svc.delete_saved_search.call_args.args[1], 42)

    def test_non_int_id_404(self):
        # Typed path param: a non-int id does not match the route.
        svc = MagicMock()
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.delete('/api/search/saved/notanint')
        self.assertEqual(resp.status_code, 422)

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_search_service', None):
            resp = self.client.delete('/api/search/saved/1')
        self.assertEqual(resp.status_code, 503)

    def test_service_error_500(self):
        svc = MagicMock()
        svc.delete_saved_search.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.delete('/api/search/saved/1')
        self.assertEqual(resp.status_code, 500)


# ── GET /api/search/trending ────────────────────────────────────────────────

class TrendingSearchesTest(_AuthedCase):
    def test_success_defaults(self):
        svc = MagicMock()
        svc.get_trending_searches.return_value = [{'query': 'doom', 'count': 9}]
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.get('/api/search/trending')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'trending': [{'query': 'doom', 'count': 9}]})
        svc.get_trending_searches.assert_called_once_with(unittest.mock.ANY, 7, 10)

    def test_success_custom_params(self):
        svc = MagicMock()
        svc.get_trending_searches.return_value = []
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.get('/api/search/trending?days=30&limit=5')
        self.assertEqual(resp.status_code, 200)
        svc.get_trending_searches.assert_called_once_with(unittest.mock.ANY, 30, 5)

    def test_bad_param_500(self):
        # int('abc') raises ValueError inside the try -> 500.
        svc = MagicMock()
        with patch.object(gapi_gui, '_search_service', svc), _patch_get_db():
            resp = self.client.get('/api/search/trending?days=abc')
        self.assertEqual(resp.status_code, 500)

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_search_service', None):
            resp = self.client.get('/api/search/trending')
        self.assertEqual(resp.status_code, 503)


# ── GET /api/search/history ─────────────────────────────────────────────────

class GetSearchHistoryTest(_AuthedCase):
    def test_success(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_search_history',
                             return_value=[{'id': 1, 'query': 'doom'}]):
            resp = self.client.get('/api/search/history?limit=10')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['history'], [{'id': 1, 'query': 'doom'}])

    def test_db_unavailable_returns_empty(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'history': [], 'count': 0})

    def test_bad_limit_defaults_to_20(self):
        captured = {}

        def _fake_hist(db, username, limit):
            captured['limit'] = limit
            return []

        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_search_history',
                             side_effect=_fake_hist):
            resp = self.client.get('/api/search/history?limit=notanumber')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured['limit'], 20)

    def test_limit_clamped_to_50(self):
        captured = {}

        def _fake_hist(db, username, limit):
            captured['limit'] = limit
            return []

        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_search_history',
                             side_effect=_fake_hist):
            self.client.get('/api/search/history?limit=999')
        self.assertEqual(captured['limit'], 50)

    def test_error_500(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'get_search_history',
                             side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/search/history')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


# ── DELETE /api/search/history ──────────────────────────────────────────────

class ClearSearchHistoryTest(_AuthedCase):
    def test_success(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'clear_search_history',
                             return_value=True):
            resp = self.client.delete('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})

    def test_db_unavailable_returns_ok(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.delete('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})

    def test_error_500(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), _patch_get_db(), \
                patch.object(gapi_gui.database, 'clear_search_history',
                             side_effect=RuntimeError('boom')):
            resp = self.client.delete('/api/search/history')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


if __name__ == '__main__':
    unittest.main()
