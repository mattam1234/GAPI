#!/usr/bin/env python3
"""
Tests for the migrated multi-user pick route (backend/routers/multiuser.py).

Run with:
    python -m pytest tests/test_backend_multiuser.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class BackendMultiuserPickTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._patches = [
            patch.object(gapi_gui, '_ensure_multi_picker', lambda: None),
            patch.object(gapi_gui, '_audit'),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).post('/api/multiuser/pick', json={}).status_code, 401)

    def test_not_initialized_400(self):
        with patch.object(gapi_gui, 'multi_picker', None):
            resp = self.client.post('/api/multiuser/pick', json={})
        self.assertEqual(resp.status_code, 400)

    def test_no_common_games_404(self):
        mp = SimpleNamespace(pick_common_game=lambda *a, **k: None)
        with patch.object(gapi_gui, 'multi_picker', mp):
            resp = self.client.post('/api/multiuser/pick',
                                    json={'users': ['alice', 'bob']})
        self.assertEqual(resp.status_code, 404)

    def test_pick_success_and_audits(self):
        game = {'appid': 620, 'name': 'Portal 2', 'playtime_forever': 120,
                'owners': ['alice', 'bob'], 'is_coop': True}
        captured = {}

        def _pick(users, **kwargs):
            captured['users'] = users
            captured['coop_only'] = kwargs.get('coop_only')
            captured['genres'] = kwargs.get('genres')
            return game

        mp = SimpleNamespace(pick_common_game=_pick)
        with patch.object(gapi_gui, 'multi_picker', mp), \
             patch.object(gapi_gui, '_audit') as audit:
            resp = self.client.post('/api/multiuser/pick', json={
                'users': ['alice', 'bob'], 'coop_only': True,
                'genres': 'action, co-op'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['name'], 'Portal 2')
        self.assertEqual(body['playtime_hours'], 2.0)
        self.assertTrue(body['is_coop'])
        self.assertIn('store.steampowered.com/app/620', body['steam_url'])
        # filters parsed through
        self.assertEqual(captured['users'], ['alice', 'bob'])
        self.assertTrue(captured['coop_only'])
        self.assertEqual(captured['genres'], ['action', 'co-op'])
        # pick recorded for analytics
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], 'pick')


if __name__ == '__main__':
    unittest.main()
