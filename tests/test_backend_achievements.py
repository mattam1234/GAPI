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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi
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


class BackendAchievementStatsTest(unittest.TestCase):
    """GET /api/achievements/stats and GET /api/achievements/{app_id}."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    # --- /stats ----------------------------------------------------------

    def test_stats_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            self.assertEqual(
                self.client.get('/api/achievements/stats').status_code, 503)

    def test_stats_empty_default(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'get_db', side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_achievement_stats', return_value=None), \
             patch.object(gapi_gui.database, 'get_achievement_stats_by_platform', return_value=[]):
            resp = self.client.get('/api/achievements/stats')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total_tracked'], 0)

    def test_stats_populated_includes_by_platform(self):
        stats = {'total_tracked': 10, 'total_unlocked': 4, 'games': []}
        by_plat = [{'platform': 'steam', 'game_count': 2}]
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'get_db', side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_achievement_stats', return_value=stats), \
             patch.object(gapi_gui.database, 'get_achievement_stats_by_platform', return_value=by_plat):
            resp = self.client.get('/api/achievements/stats')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['by_platform'], by_plat)

    # --- /{app_id} (Steam) ----------------------------------------------

    def _picker(self, steam_client=None, steam_id='765'):
        return SimpleNamespace(steam_client=steam_client, config={'steam_id': steam_id})

    def test_app_id_not_initialized_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            self.assertEqual(self.client.get('/api/achievements/620').status_code, 400)

    def test_app_id_no_steam_client_503(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=self._picker(steam_client=None)):
            self.assertEqual(self.client.get('/api/achievements/620').status_code, 503)

    def test_app_id_success(self):
        client = gapi.SteamAPIClient.__new__(gapi.SteamAPIClient)
        with patch.object(gapi, 'is_placeholder_value', return_value=False), \
             patch.object(type(client), 'get_player_achievements',
                          return_value={'unlocked': 5, 'total': 10}, create=True), \
             patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=self._picker(steam_client=client)):
            resp = self.client.get('/api/achievements/620')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['app_id'], 620)
        self.assertEqual(body['unlocked'], 5)

    def test_app_id_unavailable_404(self):
        client = gapi.SteamAPIClient.__new__(gapi.SteamAPIClient)
        with patch.object(gapi, 'is_placeholder_value', return_value=False), \
             patch.object(type(client), 'get_player_achievements',
                          return_value=None, create=True), \
             patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=self._picker(steam_client=client)):
            resp = self.client.get('/api/achievements/620')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
