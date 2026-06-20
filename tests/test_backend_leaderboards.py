#!/usr/bin/env python3
"""
Tests for the migrated leaderboards domain (backend/routers/leaderboards.py).

The plural category/seasonal routes now compute real rankings via the
SQLAlchemy-layer helpers ``database.get_category_leaderboard`` /
``get_seasonal_leaderboard`` (patched here); the service-backed singular route
stubs ``_leaderboard_service``.

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


def _session_local():
    """Patch database.SessionLocal so the route's session usage is a no-op."""
    return patch.object(gapi_gui.database, 'SessionLocal',
                        return_value=MagicMock())


class BackendLeaderboardsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/leaderboards').status_code, 401)

    # --- /api/leaderboards (category) -----------------------------------

    def test_category_default_picks(self):
        rows = [{'username': 'alice', 'value': 42}, {'username': 'bob', 'value': 10}]
        with _session_local(), \
             patch.object(gapi_gui.database, 'get_category_leaderboard',
                          return_value=rows) as m:
            resp = self.client.get('/api/leaderboards')
        self.assertEqual(resp.status_code, 200)
        lb = resp.json()['leaderboard']
        self.assertEqual(lb[0], {'username': 'alice', 'value': 42})
        # default category is 'picks'
        self.assertEqual(m.call_args.kwargs['category'], 'picks')

    def test_invalid_category_passed_through(self):
        # The helper coerces unknown categories to 'picks'; the route forwards
        # whatever was requested and trusts the helper.
        with _session_local(), \
             patch.object(gapi_gui.database, 'get_category_leaderboard',
                          return_value=[]) as m:
            resp = self.client.get('/api/leaderboards?category=bogus&limit=5')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['leaderboard'], [])
        self.assertEqual(m.call_args.kwargs['limit'], 5)

    def test_error_is_500(self):
        with _session_local(), \
             patch.object(gapi_gui.database, 'get_category_leaderboard',
                          side_effect=RuntimeError('db')):
            resp = self.client.get('/api/leaderboards')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to get leaderboards', resp.json()['error'])

    # --- /api/leaderboards/seasonal -------------------------------------

    def test_seasonal_weekly(self):
        result = {'leaderboard': [{'username': 'alice', 'value': 5,
                                   'seasonal_title': '🔥 Weekly Star'}],
                  'period_info': "This Week's Top Performers"}
        with _session_local(), \
             patch.object(gapi_gui.database, 'get_seasonal_leaderboard',
                          return_value=result) as m:
            resp = self.client.get('/api/leaderboards/seasonal?period=weekly')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['period_info'], "This Week's Top Performers")
        self.assertEqual(body['leaderboard'][0]['seasonal_title'], '🔥 Weekly Star')
        self.assertEqual(m.call_args.kwargs['period'], 'weekly')

    def test_seasonal_invalid_period_defaults_alltime(self):
        # The helper maps unknown periods to 'alltime'.
        result = {'leaderboard': [], 'period_info': 'All-Time Rankings'}
        with _session_local(), \
             patch.object(gapi_gui.database, 'get_seasonal_leaderboard',
                          return_value=result):
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
