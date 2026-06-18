#!/usr/bin/env python3
"""
Tests for GET /api/schedule/discord-guilds (backend/routers/schedule.py).

Run with:
    python -m pytest tests/test_backend_discord_guilds.py
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


class BackendDiscordGuildsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).get('/api/schedule/discord-guilds').status_code, 401)

    def test_no_discord_id_returns_hint(self):
        with patch.object(gapi_gui, '_get_current_user_record', return_value={}):
            resp = self.client.get('/api/schedule/discord-guilds')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['guilds'], [])
        self.assertIn('Link your Discord ID', body['error'])

    def test_db_unavailable(self):
        with patch.object(gapi_gui, '_get_current_user_record',
                          return_value={'discord_id': '42'}), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/schedule/discord-guilds')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['error'], 'Database unavailable')

    def test_lists_guilds(self):
        guilds = [{'guild_id': 'g1', 'guild_name': 'My Server', 'icon_url': 'u'}]
        with patch.object(gapi_gui, '_get_current_user_record',
                          return_value={'discord_id': '42'}), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'list_discord_locations_for_user',
                          return_value=guilds):
            resp = self.client.get('/api/schedule/discord-guilds')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['discord_id'], '42')
        self.assertEqual(body['guilds'][0]['guild_name'], 'My Server')


if __name__ == '__main__':
    unittest.main()
