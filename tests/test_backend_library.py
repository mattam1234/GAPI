#!/usr/bin/env python3
"""
Tests for the migrated library-comparison domain (backend/routers/library.py).

DB-backed: the cached-library lookups and DB-availability flags are stubbed.
Verifies the shared/exclusive computation, the 503 (DB unavailable) and 500
(error) branches, and auth.

Run with:
    python -m pytest tests/test_backend_library.py
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


class _FakeLibrarySvc:
    def __init__(self, libraries):
        self._libs = libraries  # {username: [game dicts]}

    def get_cached(self, db, username):
        return self._libs.get(username, [])


class BackendLibraryTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self._patches = [
            patch.object(gapi_gui, 'ensure_db_available', return_value=True),
            patch.object(gapi_gui.database, 'SessionLocal',
                         return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        c = TestClient(app)
        self.assertEqual(c.get('/api/library/compare/bob').status_code, 401)

    # --- comparison ------------------------------------------------------

    def test_compare_shared_and_exclusive(self):
        libs = {
            'alice': [
                {'app_id': '620', 'name': 'Portal 2'},
                {'app_id': '570', 'name': 'Dota 2'},
            ],
            'bob': [
                {'app_id': '620', 'name': 'Portal 2'},
                {'app_id': '730', 'name': 'CS'},
            ],
        }
        with patch.object(gapi_gui, '_library_service', _FakeLibrarySvc(libs)):
            resp = self.client.get('/api/library/compare/bob')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['shared_games'], ['Portal 2'])
        self.assertEqual(body['your_only'], ['Dota 2'])
        self.assertEqual(body['their_only'], ['CS'])
        self.assertEqual(body['your_count'], 2)
        self.assertEqual(body['their_count'], 2)
        self.assertEqual(body['shared_count'], 1)

    def test_compare_empty_other(self):
        libs = {'alice': [{'app_id': '620', 'name': 'Portal 2'}], 'bob': []}
        with patch.object(gapi_gui, '_library_service', _FakeLibrarySvc(libs)):
            resp = self.client.get('/api/library/compare/bob')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['their_count'], 0)
        self.assertEqual(body['shared_games'], [])
        self.assertEqual(body['your_only'], ['Portal 2'])

    # --- error branches --------------------------------------------------

    def test_db_unavailable_is_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/library/compare/bob')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Database not available', resp.json()['detail'])

    def test_service_error_is_500(self):
        class _Boom:
            def get_cached(self, db, username):
                raise RuntimeError('boom')
        with patch.object(gapi_gui, '_library_service', _Boom()):
            resp = self.client.get('/api/library/compare/bob')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('boom', resp.json()['detail'])


if __name__ == '__main__':
    unittest.main()
