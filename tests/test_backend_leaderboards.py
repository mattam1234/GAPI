#!/usr/bin/env python3
"""
Tests for the migrated leaderboards domain (backend/routers/leaderboards.py).

The raw-SQL routes' db_service is stubbed with a fake cursor; the service-backed
route stubs _leaderboard_service.

Run with:
    python -m pytest tests/test_backend_leaderboards.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _db_service(rows):
    cursor = SimpleNamespace(fetchall=lambda: rows)
    db = SimpleNamespace(execute=lambda query, params=None: cursor)
    return SimpleNamespace(get_db=lambda: db)


class BackendLeaderboardsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/leaderboards').status_code, 401)

    # --- /api/leaderboards (category, raw SQL) --------------------------

    def test_category_default_picks(self):
        with patch.object(gapi_gui, 'db_service',
                          _db_service([('alice', 42), ('bob', 10)]), create=True):
            resp = self.client.get('/api/leaderboards')
        self.assertEqual(resp.status_code, 200)
        lb = resp.json()['leaderboard']
        self.assertEqual(lb[0], {'username': 'alice', 'value': 42})

    def test_invalid_category_coerced(self):
        with patch.object(gapi_gui, 'db_service', _db_service([]), create=True):
            resp = self.client.get('/api/leaderboards?category=bogus&limit=5')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['leaderboard'], [])

    def test_error_is_500(self):
        bad = SimpleNamespace(get_db=lambda: (_ for _ in ()).throw(RuntimeError('db')))
        with patch.object(gapi_gui, 'db_service', bad, create=True):
            resp = self.client.get('/api/leaderboards')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to get leaderboards', resp.json()['error'])

    # --- /api/leaderboards/seasonal -------------------------------------

    def test_seasonal_weekly(self):
        rows = [('alice', 5, '🔥 Weekly Star')]
        with patch.object(gapi_gui, 'db_service', _db_service(rows), create=True):
            resp = self.client.get('/api/leaderboards/seasonal?period=weekly')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['period_info'], "This Week's Top Performers")
        self.assertEqual(body['leaderboard'][0]['seasonal_title'], '🔥 Weekly Star')

    def test_seasonal_invalid_period_defaults_alltime(self):
        with patch.object(gapi_gui, 'db_service', _db_service([]), create=True):
            resp = self.client.get('/api/leaderboards/seasonal?period=decade')
        self.assertEqual(resp.json()['period_info'], 'All-Time Rankings')

    # --- /api/leaderboard (service) -------------------------------------

    def test_singular_service_rankings(self):
        svc = SimpleNamespace(
            get_rankings=lambda db, metric='playtime', limit=20: [
                {'username': 'alice', 'value': 999}])
        with patch.object(gapi_gui, '_leaderboard_service', svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])):
            resp = self.client.get('/api/leaderboard?metric=games&limit=5')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['metric'], 'games')
        self.assertEqual(body['entries'][0]['username'], 'alice')


if __name__ == '__main__':
    unittest.main()
