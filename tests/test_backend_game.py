#!/usr/bin/env python3
"""
Tests for the migrated game-details domain (backend/routers/game.py).

Run with:
    python -m pytest tests/test_backend_game.py
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


class _LibSvc:
    def __init__(self, platform='steam', cached=None, stale=None):
        self._platform = platform
        self._cached = cached
        self._stale = stale
        self.updated = None

    def get_game_platform(self, db, username, app_id):
        return self._platform

    def get_game_details(self, db, app_id, platform, max_age_hours=1):
        return self._cached

    def get_stale_game_details(self, db, app_id, platform):
        return self._stale

    def update_game_details(self, db, app_id, platform, response):
        self.updated = dict(response)


class BackendGameDetailsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._db = patch.object(gapi_gui.database, 'SessionLocal',
                                return_value=MagicMock())
        self._dbavail = patch.object(gapi_gui, 'ensure_db_available', return_value=True)
        self._db.start()
        self._dbavail.start()

    def tearDown(self):
        self._db.stop()
        self._dbavail.stop()

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).get('/api/game/620/details').status_code, 401)

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            self.assertEqual(
                self.client.get('/api/game/620/details').status_code, 503)

    def test_non_integer_app_id_falls_through(self):
        # {app_id:int} should not match a non-integer segment.
        resp = self.client.get('/api/game/abc/details')
        self.assertNotEqual(resp.status_code, 200)

    def test_fresh_cache_hit(self):
        lib = _LibSvc(platform='steam', cached={'name': 'Portal 2', 'header_image': 'x'})
        with patch.object(gapi_gui, '_library_service', lib):
            resp = self.client.get('/api/game/620/details')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['source'], 'cache')
        self.assertEqual(body['app_id'], 620)
        self.assertEqual(body['name'], 'Portal 2')

    def test_api_fetch_when_cache_miss(self):
        import gapi
        lib = _LibSvc(platform='steam', cached=None)
        steam = gapi.SteamAPIClient.__new__(gapi.SteamAPIClient)
        steam.get_game_details = lambda aid: {'short_description': 'Great game',
                                              'header_image': 'h'}
        steam.get_protondb_rating = lambda aid: 'gold'
        picker = SimpleNamespace(steam_client=steam)
        with patch.object(gapi_gui, '_library_service', lib), \
             patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/game/620/details')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['source'], 'api')
        self.assertEqual(body['description'], 'Great game')
        self.assertEqual(body['protondb'], 'gold')
        self.assertIsNotNone(lib.updated)  # cache updated

    def test_no_api_falls_back_to_stale(self):
        lib = _LibSvc(platform='steam', cached=None, stale={'name': 'Old'})
        picker = SimpleNamespace(steam_client=None)
        with patch.object(gapi_gui, '_library_service', lib), \
             patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/game/620/details')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['source'], 'cache_stale')

    def test_no_data_minimal_response(self):
        lib = _LibSvc(platform='steam', cached=None, stale=None)
        picker = SimpleNamespace(steam_client=None)
        with patch.object(gapi_gui, '_library_service', lib), \
             patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/game/620/details')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['source'], 'none')
        self.assertFalse(body['steam_integration'])


if __name__ == '__main__':
    unittest.main()
