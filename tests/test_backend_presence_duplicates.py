#!/usr/bin/env python3
"""
Tests for the migrated presence (backend/routers/presence.py) and
duplicate-detection (backend/routers/duplicates.py) domains.

Run with:
    python -m pytest tests/test_backend_presence_duplicates.py
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


class BackendPresenceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    # --- heartbeat -------------------------------------------------------

    def test_heartbeat_requires_login(self):
        self.assertEqual(TestClient(app).post('/api/presence').status_code, 401)

    def test_heartbeat_db_unavailable_ok(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/presence')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_heartbeat_updates_presence(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'update_user_presence') as mock_fn:
            resp = self.client.post('/api/presence')
        self.assertEqual(resp.status_code, 200)
        mock_fn.assert_called_once()

    # --- Discord RPC update/clear ---------------------------------------

    def test_update_rpc_not_configured(self):
        with patch.object(gapi_gui, '_discord_rpc', None):
            resp = self.client.post('/api/presence/update', json={'game': 'Portal'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['ok'])

    def test_update_requires_game(self):
        rpc = SimpleNamespace(enabled=True, update=lambda *a, **k: True)
        with patch.object(gapi_gui, '_discord_rpc', rpc):
            resp = self.client.post('/api/presence/update', json={'game': '  '})
        self.assertEqual(resp.status_code, 400)

    def test_update_success(self):
        calls = {}
        def _update(game, playtime_hours=None):
            calls['game'] = game
            calls['pt'] = playtime_hours
            return True
        rpc = SimpleNamespace(enabled=True, update=_update)
        with patch.object(gapi_gui, '_discord_rpc', rpc):
            resp = self.client.post('/api/presence/update',
                                    json={'game': 'Portal 2', 'playtime_hours': '3.5'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['updated'])
        self.assertEqual(calls['game'], 'Portal 2')
        self.assertEqual(calls['pt'], 3.5)

    def test_clear_success(self):
        rpc = SimpleNamespace(enabled=True, clear=lambda: True)
        with patch.object(gapi_gui, '_discord_rpc', rpc):
            resp = self.client.post('/api/presence/clear')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['cleared'])


class BackendDuplicatesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/duplicates').status_code, 401)

    def test_empty_when_no_library(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/duplicates')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'duplicates': []})

    def test_returns_sorted_slim_groups(self):
        groups = [
            {'name': 'Portal 2', 'platforms': ['steam', 'epic'], 'games': [
                {'appid': 620, 'game_id': 'steam:620', 'name': 'Portal 2',
                 'platform': 'steam', 'playtime_forever': 120}]},
            {'name': 'Aaa', 'platforms': ['gog', 'steam'], 'games': [
                {'appid': 1, 'game_id': 'gog:1', 'name': 'Aaa',
                 'platform': 'gog', 'playtime_forever': 0}]},
        ]
        picker = SimpleNamespace(games=[{}], find_duplicates=lambda: groups)
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/duplicates')
        self.assertEqual(resp.status_code, 200)
        dups = resp.json()['duplicates']
        # sorted by name -> Aaa first
        self.assertEqual([d['name'] for d in dups], ['Aaa', 'Portal 2'])
        self.assertEqual(dups[1]['games'][0]['playtime_hours'], 2.0)
        self.assertEqual(dups[1]['platforms'], ['steam', 'epic'])


if __name__ == '__main__':
    unittest.main()
