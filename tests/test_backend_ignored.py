#!/usr/bin/env python3
"""
Tests for the migrated ignored-games domain (backend/routers/ignored.py).

This domain is DB-backed rather than picker-backed, so the legacy
_ignored_games_service / _user_service singletons and the DB session are
stubbed. Verifies the asymmetric DB-availability contract (GET 200-empty vs
POST 503), validation, not-found, and the toggle happy/failure paths.

Run with:
    python -m pytest tests/test_backend_ignored.py
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


class _FakeIgnoredSvc:
    def __init__(self, detailed=None, toggle_result=True):
        self._detailed = detailed if detailed is not None else []
        self._toggle = toggle_result

    def get_detailed(self, db, username):
        return self._detailed

    def toggle(self, db, username, app_id, game_name='', reason=''):
        return self._toggle


class _FakeUserSvc:
    def __init__(self, exists=True):
        self._exists = exists

    def user_exists(self, db, username):
        return self._exists


class BackendIgnoredTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        # DB available + a throwaway session by default.
        self._patches = [
            patch.object(gapi_gui, 'DB_AVAILABLE', True),
            patch.object(gapi_gui.database, 'SessionLocal',
                         return_value=MagicMock()),
            patch.object(gapi_gui, '_user_service', _FakeUserSvc(exists=True)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/ignored-games').status_code, 401)

    # --- GET -------------------------------------------------------------

    def test_get_db_unavailable_returns_empty_200(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/ignored-games')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ignored_games': []})

    def test_get_returns_service_data(self):
        detailed = [{'app_id': '620', 'game_name': 'Portal 2',
                     'reason': 'done', 'created_at': '2026-06-18T00:00:00'}]
        with patch.object(gapi_gui, '_ignored_games_service',
                          _FakeIgnoredSvc(detailed=detailed)):
            resp = self.client.get('/api/ignored-games')
        self.assertEqual(resp.status_code, 200)
        games = resp.json()['ignored_games']
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['game_name'], 'Portal 2')

    # --- POST ------------------------------------------------------------

    def test_post_db_unavailable_is_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/ignored-games', json={'app_id': 620})
        self.assertEqual(resp.status_code, 503)

    def test_post_missing_app_id_is_400(self):
        with patch.object(gapi_gui, '_ignored_games_service', _FakeIgnoredSvc()):
            resp = self.client.post('/api/ignored-games', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('app_id required', resp.json()['detail'])

    def test_post_non_integer_app_id_is_400(self):
        with patch.object(gapi_gui, '_ignored_games_service', _FakeIgnoredSvc()):
            resp = self.client.post('/api/ignored-games', json={'app_id': 'abc'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('app_id must be an integer', resp.json()['detail'])

    def test_post_user_not_found_is_404(self):
        with patch.object(gapi_gui, '_user_service', _FakeUserSvc(exists=False)), \
             patch.object(gapi_gui, '_ignored_games_service', _FakeIgnoredSvc()):
            resp = self.client.post('/api/ignored-games', json={'app_id': 620})
        self.assertEqual(resp.status_code, 404)
        self.assertIn('User not found', resp.json()['detail'])

    def test_post_toggle_success(self):
        with patch.object(gapi_gui, '_ignored_games_service',
                          _FakeIgnoredSvc(toggle_result=True)):
            resp = self.client.post('/api/ignored-games',
                                    json={'app_id': 620, 'game_name': 'Portal 2'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('toggled', resp.json()['message'])

    def test_post_toggle_failure_is_400(self):
        with patch.object(gapi_gui, '_ignored_games_service',
                          _FakeIgnoredSvc(toggle_result=False)):
            resp = self.client.post('/api/ignored-games', json={'app_id': 620})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Failed to toggle ignore', resp.json()['detail'])


if __name__ == '__main__':
    unittest.main()
