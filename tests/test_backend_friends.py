#!/usr/bin/env python3
"""
Tests for the migrated friends domain (backend/routers/friends.py).

Run with:
    python -m pytest tests/test_backend_friends.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi
import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class BackendFriendsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/friends').status_code, 401)

    # --- Steam GET -------------------------------------------------------

    def test_no_steam_id_503(self):
        with patch.object(gapi_gui.user_manager, 'get_user_ids', return_value={}):
            resp = self.client.get('/api/friends')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Steam ID', resp.json()['error'])

    def test_no_steam_client_503(self):
        with patch.object(gapi_gui.user_manager, 'get_user_ids',
                          return_value={'steam_id': '765'}), \
             patch.object(gapi, 'is_placeholder_value', return_value=False), \
             patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=SimpleNamespace(steam_client=None)):
            resp = self.client.get('/api/friends')
        self.assertEqual(resp.status_code, 503)

    def test_friends_list_sorted(self):
        steam = gapi.SteamAPIClient.__new__(gapi.SteamAPIClient)
        steam.get_friend_list = lambda sid: [{'steamid': '1'}, {'steamid': '2'}]
        steam.get_player_summaries = lambda ids: [
            {'steamid': '1', 'personaname': 'Offline', 'personastate': 0},
            {'steamid': '2', 'personaname': 'InGame', 'personastate': 1,
             'gameextrainfo': 'Portal 2', 'gameid': '620'},
        ]
        steam.get_recently_played = lambda fid, count=5: []
        picker = SimpleNamespace(steam_client=steam)
        with patch.object(gapi_gui.user_manager, 'get_user_ids',
                          return_value={'steam_id': '765'}), \
             patch.object(gapi, 'is_placeholder_value', return_value=False), \
             patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/friends')
        self.assertEqual(resp.status_code, 200)
        friends = resp.json()['friends']
        # in-game sorts first
        self.assertEqual(friends[0]['personaname'], 'InGame')
        self.assertEqual(friends[0]['current_game'], 'Portal 2')

    # --- placeholder add/remove/follow ----------------------------------

    def test_add_requires_username(self):
        resp = self.client.post('/api/friends/add', json={})
        self.assertEqual(resp.status_code, 400)

    def test_add_self_rejected(self):
        resp = self.client.post('/api/friends/add', json={'username': 'alice'})
        self.assertEqual(resp.status_code, 400)

    def test_add_success(self):
        resp = self.client.post('/api/friends/add', json={'username': 'bob'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('bob', resp.json()['message'])

    def test_remove(self):
        resp = self.client.delete('/api/friends/bob')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Removed bob', resp.json()['message'])

    def test_unfollow(self):
        resp = self.client.delete('/api/friends/follow/bob')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Unfollowed bob', resp.json()['message'])


if __name__ == '__main__':
    unittest.main()
