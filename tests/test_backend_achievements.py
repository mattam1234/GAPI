#!/usr/bin/env python3
"""
Tests for the migrated achievement-hunt domain (backend/routers/achievements.py).

DB-backed: the legacy _achievement_service singleton, DB-availability flags, and
DB session are stubbed.

Run with:
    python -m pytest tests/test_backend_achievements.py
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


class _FakeAchSvc:
    def __init__(self, all_by_user=None, start=None, update=None):
        self._all = all_by_user if all_by_user is not None else []
        self._start = start
        self._update = update

    def get_all_by_user(self, db, username):
        return self._all

    def start_hunt(self, db, username, app_id, game_name, difficulty='medium',
                   target_achievements=0):
        return self._start

    def update_hunt(self, db, hunt_id, unlocked_achievements=None, status=None):
        return self._update


class BackendAchievementsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._patches = [
            patch.object(gapi_gui, 'DB_AVAILABLE', True),
            patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/achievements').status_code, 401)

    # --- GET /api/achievements ------------------------------------------

    def test_get_db_unavailable_empty(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/achievements')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'achievements': []})

    def test_get_returns_service_data(self):
        data = [{'app_id': 620, 'game_name': 'Portal 2', 'achievements': []}]
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc(all_by_user=data)):
            resp = self.client.get('/api/achievements')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['achievements'][0]['game_name'], 'Portal 2')

    # --- POST /api/achievement-hunt -------------------------------------

    def test_start_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/achievement-hunt',
                                    json={'app_id': 620, 'game_name': 'Portal 2'})
        self.assertEqual(resp.status_code, 503)

    def test_start_requires_fields(self):
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc()):
            resp = self.client.post('/api/achievement-hunt', json={'app_id': 620})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('required', resp.json()['detail'])

    def test_start_app_id_must_be_int(self):
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc()):
            resp = self.client.post('/api/achievement-hunt',
                                    json={'app_id': 'abc', 'game_name': 'P2'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('integer', resp.json()['detail'])

    def test_start_success_201(self):
        hunt = {'hunt_id': 1, 'app_id': 620, 'game_name': 'Portal 2',
                'status': 'active'}
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc(start=hunt)):
            resp = self.client.post('/api/achievement-hunt',
                                    json={'app_id': 620, 'game_name': 'Portal 2'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['hunt_id'], 1)

    def test_start_user_not_found_404(self):
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc(start=None)):
            resp = self.client.post('/api/achievement-hunt',
                                    json={'app_id': 620, 'game_name': 'P2'})
        self.assertEqual(resp.status_code, 404)

    # --- PUT /api/achievement-hunt/{id} ---------------------------------

    def test_update_success(self):
        updated = {'hunt_id': 1, 'status': 'completed'}
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc(update=updated)):
            resp = self.client.put('/api/achievement-hunt/1',
                                   json={'status': 'completed'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'completed')

    def test_update_not_found_404(self):
        with patch.object(gapi_gui, '_achievement_service', _FakeAchSvc(update=None)):
            resp = self.client.put('/api/achievement-hunt/999',
                                   json={'status': 'completed'})
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
