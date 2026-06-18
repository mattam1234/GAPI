#!/usr/bin/env python3
"""
Tests for the migrated playlists domain (backend/routers/playlists.py).

Covers playlist CRUD and per-playlist game add/list/remove through the FastAPI
app, with auth bridged via the Flask session cookie and the per-user picker
stubbed. Asserts the legacy status-code contract (201 create, 409 conflicts,
404 not-found, 400 validation).

Run with:
    python -m pytest tests/test_backend_playlists.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _MemoryPlaylistService:
    """In-memory stand-in mirroring app.services.playlist_service.PlaylistService."""
    def __init__(self):
        self._pl = {}  # name -> list of game_ids

    def list_all(self):
        return [{'name': n, 'count': len(g)} for n, g in self._pl.items()]

    def create(self, name):
        if name in self._pl:
            return False
        self._pl[name] = []
        return True

    def delete(self, name):
        return self._pl.pop(name, None) is not None

    def add_game(self, name, game_id):
        if name not in self._pl or game_id in self._pl[name]:
            return False
        self._pl[name].append(game_id)
        return True

    def remove_game(self, name, game_id):
        if name not in self._pl or game_id not in self._pl[name]:
            return False
        self._pl[name].remove(game_id)
        return True

    def get_games(self, name, all_games):
        if name not in self._pl:
            return None
        ids = set(self._pl[name])
        return [g for g in all_games if str(g.get('game_id')) in ids]


class _FakePicker:
    def __init__(self):
        self.playlist_service = _MemoryPlaylistService()
        self.games = [
            {'game_id': 'steam:570', 'name': 'Portal'},
            {'game_id': 'steam:620', 'name': 'Portal 2'},
        ]


class BackendPlaylistsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.picker = _FakePicker()
        self._patch = patch.object(gapi_gui, 'ensure_picker_initialized',
                                   return_value=self.picker)
        self._patch.start()
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        self._patch.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/playlists').status_code, 401)

    # --- playlist CRUD ---------------------------------------------------

    def test_create_lists_and_conflict(self):
        resp = self.client.post('/api/playlists', json={'name': 'Co-op night'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {'success': True, 'name': 'Co-op night'})

        listed = self.client.get('/api/playlists').json()['playlists']
        self.assertEqual([p['name'] for p in listed], ['Co-op night'])

        # Duplicate -> 409
        dup = self.client.post('/api/playlists', json={'name': 'Co-op night'})
        self.assertEqual(dup.status_code, 409)

    def test_create_requires_name(self):
        resp = self.client.post('/api/playlists', json={'name': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name is required', resp.json()['detail'])

    def test_delete_then_404(self):
        self.client.post('/api/playlists', json={'name': 'PL'})
        self.assertEqual(self.client.delete('/api/playlists/PL').status_code, 200)
        self.assertEqual(self.client.delete('/api/playlists/PL').status_code, 404)

    # --- games within a playlist ----------------------------------------

    def test_add_list_remove_games(self):
        self.client.post('/api/playlists', json={'name': 'PL'})

        add = self.client.post('/api/playlists/PL/games', json={'game_id': 'steam:570'})
        self.assertEqual(add.status_code, 200)

        games = self.client.get('/api/playlists/PL/games').json()
        self.assertEqual(games['count'], 1)
        self.assertEqual(games['games'][0]['name'], 'Portal')

        rem = self.client.delete('/api/playlists/PL/games/steam:570')
        self.assertEqual(rem.status_code, 200)
        self.assertEqual(self.client.get('/api/playlists/PL/games').json()['count'], 0)

    def test_add_game_requires_game_id(self):
        self.client.post('/api/playlists', json={'name': 'PL'})
        resp = self.client.post('/api/playlists/PL/games', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('game_id is required', resp.json()['detail'])

    def test_add_duplicate_game_is_409(self):
        self.client.post('/api/playlists', json={'name': 'PL'})
        self.client.post('/api/playlists/PL/games', json={'game_id': 'steam:570'})
        dup = self.client.post('/api/playlists/PL/games', json={'game_id': 'steam:570'})
        self.assertEqual(dup.status_code, 409)

    def test_games_of_missing_playlist_is_404(self):
        self.assertEqual(
            self.client.get('/api/playlists/ghost/games').status_code, 404)

    def test_remove_missing_game_is_404(self):
        self.client.post('/api/playlists', json={'name': 'PL'})
        self.assertEqual(
            self.client.delete('/api/playlists/PL/games/steam:999').status_code, 404)


if __name__ == '__main__':
    unittest.main()
