#!/usr/bin/env python3
"""
Tests for the migrated achievement-challenges domain (backend/routers/challenges.py).

DB-backed: the legacy database challenge helpers and DB-availability flag are
stubbed.

Run with:
    python -m pytest tests/test_backend_challenges.py
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


class BackendChallengesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._patches = [
            patch.object(gapi_gui, 'ensure_db_available', return_value=True),
            patch.object(gapi_gui.database, 'get_db',
                         side_effect=lambda: iter([MagicMock()])),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth / db -------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).get('/api/achievement-challenges').status_code, 401)

    def test_db_unavailable_is_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/achievement-challenges')
        self.assertEqual(resp.status_code, 503)

    # --- create ----------------------------------------------------------

    def test_create_validation(self):
        resp = self.client.post('/api/achievement-challenges',
                                json={'title': 'T'})  # missing app_id/game_name
        self.assertEqual(resp.status_code, 400)

    def test_create_success_201(self):
        ch = {'id': 'c1', 'title': 'Race', 'app_id': '620'}
        with patch.object(gapi_gui.database, 'create_achievement_challenge',
                          return_value=ch):
            resp = self.client.post('/api/achievement-challenges', json={
                'title': 'Race', 'app_id': '620', 'game_name': 'Portal 2',
                'target_achievement_ids': ['A', 'B']})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['id'], 'c1')

    def test_create_failure_500(self):
        with patch.object(gapi_gui.database, 'create_achievement_challenge',
                          return_value=None):
            resp = self.client.post('/api/achievement-challenges', json={
                'title': 'Race', 'app_id': '620', 'game_name': 'Portal 2'})
        self.assertEqual(resp.status_code, 500)

    # --- list / get ------------------------------------------------------

    def test_list(self):
        with patch.object(gapi_gui.database, 'get_achievement_challenges',
                          return_value=[{'id': 'c1'}]):
            resp = self.client.get('/api/achievement-challenges')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['challenges'][0]['id'], 'c1')

    def test_get_one_404(self):
        with patch.object(gapi_gui.database, 'get_achievement_challenge',
                          return_value=None):
            resp = self.client.get('/api/achievement-challenges/ghost')
        self.assertEqual(resp.status_code, 404)

    def test_get_one_ok(self):
        with patch.object(gapi_gui.database, 'get_achievement_challenge',
                          return_value={'id': 'c1'}):
            resp = self.client.get('/api/achievement-challenges/c1')
        self.assertEqual(resp.status_code, 200)

    # --- join / progress / cancel ---------------------------------------

    def test_join_ok(self):
        with patch.object(gapi_gui.database, 'join_achievement_challenge',
                          return_value={'id': 'c1', 'joined': True}):
            resp = self.client.post('/api/achievement-challenges/c1/join')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['joined'])

    def test_join_404(self):
        with patch.object(gapi_gui.database, 'join_achievement_challenge',
                          return_value=None):
            resp = self.client.post('/api/achievement-challenges/c1/join')
        self.assertEqual(resp.status_code, 404)

    def test_progress_non_integer_400(self):
        resp = self.client.put('/api/achievement-challenges/c1/progress',
                               json={'unlocked_count': 'lots'})
        self.assertEqual(resp.status_code, 400)

    def test_progress_ok(self):
        with patch.object(gapi_gui.database, 'record_challenge_unlock',
                          return_value={'id': 'c1', 'unlocked': 3}):
            resp = self.client.put('/api/achievement-challenges/c1/progress',
                                   json={'unlocked_count': 3})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unlocked'], 3)

    def test_cancel_ok(self):
        with patch.object(gapi_gui.database, 'cancel_achievement_challenge',
                          return_value=True):
            resp = self.client.delete('/api/achievement-challenges/c1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'id': 'c1'})

    def test_cancel_denied_404(self):
        with patch.object(gapi_gui.database, 'cancel_achievement_challenge',
                          return_value=False):
            resp = self.client.delete('/api/achievement-challenges/c1')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
