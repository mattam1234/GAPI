#!/usr/bin/env python3
"""
Tests for the migrated user-profile domain (backend/routers/profile.py).

Run with:
    python -m pytest tests/test_backend_profile.py
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


class BackendProfileTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_me_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/profile/me').status_code, 401)

    def test_update_requires_login(self):
        self.assertEqual(
            TestClient(app).post('/api/profile/update').status_code, 401)

    def test_get_my_profile(self):
        resp = self.client.get('/api/profile/me')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['username'], 'alice')
        self.assertEqual(body['favorite_game'], 'Portal 2')
        self.assertFalse(body['is_private'])

    def test_update_profile(self):
        resp = self.client.post('/api/profile/update', json={'bio': 'new bio'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'message': 'Profile updated'})


if __name__ == '__main__':
    unittest.main()
