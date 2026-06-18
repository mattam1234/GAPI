#!/usr/bin/env python3
"""
Tests for the migrated single-user pick endpoint (backend/routers/pick.py).

The per-user picker and shared services are stubbed; DB and Discord RPC are
disabled so the handler exercises the in-memory filter/pick path.

Run with:
    python -m pytest tests/test_backend_pick.py
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


class _Svc:
    def get(self, *a, **k):
        return None

    def get_status(self, *a, **k):
        return None

    def filter_by_tag(self, tag, games):
        return games


class _FakePicker:
    BARELY_PLAYED_THRESHOLD_MINUTES = 60
    WELL_PLAYED_THRESHOLD_MINUTES = 600

    def __init__(self, games=None, filtered=None):
        self.games = games if games is not None else [
            {'appid': 570, 'name': 'Portal', 'game_id': 'steam:570',
             'playtime_forever': 120}]
        self._filtered = filtered
        self.favorites = set()
        self.config = {}
        self.steam_client = None
        self.review_service = _Svc()
        self.tag_service = _Svc()
        self.backlog_service = _Svc()

    def filter_games(self, **kwargs):
        return self._filtered if self._filtered is not None else self.games

    def pick_random_game(self, filtered=None):
        pool = filtered if filtered is not None else self.games
        return pool[0] if pool else None


class BackendPickTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._patches = [
            patch.object(gapi_gui, 'DB_AVAILABLE', False),
            patch.object(gapi_gui, '_discord_rpc', None),
            patch.object(gapi_gui, '_get_shared_backlog_service', return_value=_Svc()),
            patch.object(gapi_gui, '_audit'),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _with_picker(self, picker):
        return patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker)

    # --- auth / preconditions -------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).post('/api/pick', json={}).status_code, 401)

    def test_picker_init_failure_500(self):
        with self._with_picker(None):
            resp = self.client.post('/api/pick', json={})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to load games')

    def test_no_games_400(self):
        with self._with_picker(_FakePicker(games=[])):
            resp = self.client.post('/api/pick', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('No games available', resp.json()['error'])

    def test_no_games_match_filters_400(self):
        # A genre filter is set -> filter_games runs and returns [] -> 400.
        with self._with_picker(_FakePicker(filtered=[])):
            resp = self.client.post('/api/pick', json={'genre': 'action'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('No games match', resp.json()['error'])

    # --- happy path ------------------------------------------------------

    def test_pick_success(self):
        picker = _FakePicker()
        with self._with_picker(picker), \
             patch.object(gapi_gui, '_audit') as audit:
            resp = self.client.post('/api/pick', json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['name'], 'Portal')
        self.assertEqual(body['game_id'], 'steam:570')
        self.assertEqual(body['playtime_hours'], 2.0)
        self.assertIn('store.steampowered.com/app/570', body['steam_url'])
        # current_game global updated + pick recorded
        self.assertEqual(gapi_gui.current_game['name'], 'Portal')
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], 'pick')
        self.assertEqual(audit.call_args.kwargs['resource_id'], 'steam:570')


if __name__ == '__main__':
    unittest.main()
