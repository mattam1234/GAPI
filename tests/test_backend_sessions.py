#!/usr/bin/env python3
"""
Tests for the migrated session-history domain (backend/routers/sessions.py).

Run with:
    python -m pytest tests/test_backend_sessions.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class BackendSessionsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(
            TestClient(app).get('/api/sessions/history').status_code, 401)

    def test_history_shape(self):
        resp = self.client.get('/api/sessions/history')
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()['sessions']
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]['winning_pick'], 'Portal 2')
        for s in sessions:
            self.assertEqual(
                set(s),
                {'name', 'played_at', 'winning_pick', 'player_count',
                 'your_vote', 'you_picked'})


if __name__ == '__main__':
    unittest.main()
