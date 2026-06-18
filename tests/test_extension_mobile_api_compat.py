#!/usr/bin/env python3
"""Compatibility tests for browser-extension/mobile API endpoints."""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient as _FastTestClient

import gapi_gui
from backend.main import app as _fastapi_app


class TestExtensionMobileApiCompat(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_resolve_pick_filter_type_accepts_mode_aliases(self):
        self.assertEqual(gapi_gui._resolve_pick_filter_type({'mode': 'random'}), 'all')
        self.assertEqual(gapi_gui._resolve_pick_filter_type({'mode': 'unplayed'}), 'unplayed')
        self.assertEqual(gapi_gui._resolve_pick_filter_type({'mode': 'barely_played'}), 'barely')
        self.assertEqual(gapi_gui._resolve_pick_filter_type({'filter': 'favorites'}), 'favorites')

    def test_health_endpoint_is_public(self):
        resp = self.client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'healthy')

    def test_random_game_endpoint_supports_public_demo_pick(self):
        demo_games = [
            {'appid': 10, 'game_id': 'steam:10', 'name': 'Demo A', 'platform': 'steam', 'playtime_forever': 0},
            {'appid': 11, 'game_id': 'steam:11', 'name': 'Demo B', 'platform': 'steam', 'playtime_forever': 30},
        ]
        # /api/random-game is migrated to FastAPI (anonymous demo path).
        fast_client = _FastTestClient(_fastapi_app)
        with patch.object(gapi_gui, 'DEMO_GAMES', demo_games):
            resp = fast_client.get('/api/random-game?mode=unplayed')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['name'], 'Demo A')
        self.assertIn('playtime_forever', data)
        self.assertIn('game_id', data)

    def test_history_endpoint_requires_login(self):
        resp = self.client.get('/api/history')
        self.assertEqual(resp.status_code, 401)

    @patch('gapi_gui.current_user', 'testuser')
    def test_history_endpoint_returns_recent_entries(self):
        picker = SimpleNamespace(
            history=['steam:20', 'steam:10'],
            games=[
                {'game_id': 'steam:10', 'appid': 10, 'name': 'Demo A', 'platform': 'steam', 'playtime_forever': 60},
                {'game_id': 'steam:20', 'appid': 20, 'name': 'Demo B', 'platform': 'steam', 'playtime_forever': 120},
            ],
        )
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('history', data)
        self.assertEqual(len(data['history']), 2)
        self.assertEqual(data['history'][0]['game_id'], 'steam:10')
        self.assertEqual(data['history'][0]['game_name'], 'Demo A')


if __name__ == '__main__':
    unittest.main()
