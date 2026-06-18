#!/usr/bin/env python3
"""
Tests for the migrated data-export domain (backend/routers/export.py):
  * GET /api/export/library    (CSV)
  * GET /api/export/favorites  (CSV)
  * GET /api/export/user-data  (JSON backup)

Run with:
    python -m pytest tests/test_backend_export.py
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


class _Fav:
    def __init__(self, favs):
        self._favs = set(favs)

    def contains(self, game_id):
        return game_id in self._favs


class _Reviews:
    def get(self, game_id):
        return {'rating': 9, 'notes': 'great'} if game_id == 'steam:620' else None


class _Tags:
    def get(self, game_id):
        return ['coop'] if game_id == 'steam:620' else []


def _picker(games, favs=()):
    return SimpleNamespace(
        games=games, favorites_service=_Fav(favs),
        review_service=_Reviews(), tag_service=_Tags())


GAMES = [
    {'appid': 620, 'game_id': 'steam:620', 'name': 'Portal 2',
     'platform': 'steam', 'playtime_forever': 120},
    {'appid': 570, 'game_id': 'steam:570', 'name': 'Dota 2',
     'platform': 'steam', 'playtime_forever': 60},
]


class BackendExportTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._bk = patch.object(
            gapi_gui, '_get_shared_backlog_service',
            return_value=SimpleNamespace(get_status=lambda gid, username=None: ''))
        self._bk.start()

    def tearDown(self):
        self._bk.stop()

    # --- auth / preconditions -------------------------------------------

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).get('/api/export/library').status_code, 401)

    def test_library_not_loaded_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/export/library')
        self.assertEqual(resp.status_code, 400)

    # --- library CSV -----------------------------------------------------

    def test_library_csv(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=_picker(GAMES, favs={'steam:620'})):
            resp = self.client.get('/api/export/library')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers['content-type'].startswith('text/csv'))
        self.assertIn('gapi_library.csv', resp.headers['content-disposition'])
        body = resp.text
        self.assertIn('app_id,name,platform,playtime_hours,is_favorite', body)
        # Sorted by name -> Dota 2 before Portal 2
        lines = [ln for ln in body.splitlines() if ln]
        self.assertTrue(lines[1].startswith('570,Dota 2'))
        self.assertIn('620,Portal 2,steam,2.0,yes', body)

    # --- favorites CSV ---------------------------------------------------

    def test_favorites_only_favorited(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=_picker(GAMES, favs={'steam:620'})):
            resp = self.client.get('/api/export/favorites')
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn('Portal 2', body)
        self.assertNotIn('Dota 2', body)
        self.assertIn('gapi_favorites.csv', resp.headers['content-disposition'])

    # --- user-data JSON --------------------------------------------------

    def test_user_data_404_when_empty(self):
        with patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_user_data_export', return_value=None):
            resp = self.client.get('/api/export/user-data')
        self.assertEqual(resp.status_code, 404)

    def test_user_data_json_attachment(self):
        export = {'username': 'alice', 'favorites': ['steam:620']}
        with patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_user_data_export', return_value=export):
            resp = self.client.get('/api/export/user-data')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers['content-type'].startswith('application/json'))
        self.assertIn('gapi_alice_backup.json', resp.headers['content-disposition'])
        self.assertEqual(resp.json()['username'], 'alice')


if __name__ == '__main__':
    unittest.main()
