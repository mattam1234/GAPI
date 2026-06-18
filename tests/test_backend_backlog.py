#!/usr/bin/env python3
"""
Error/validation-branch tests for the migrated backlog domain
(backend/routers/backlog.py).

The happy-path and multi-user permission flows are covered by the integration
tests in test_backlog_collections.py (now driven through the FastAPI app). This
file pins the auth, validation, and not-found branches.

Run with:
    python -m pytest tests/test_backend_backlog.py
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from app.repositories.backlog_repository import BacklogRepository
from app.services.backlog_service import BacklogService
from backend.main import app as fastapi_app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _fake_picker():
    return SimpleNamespace(games=[
        {'game_id': 'steam:620', 'name': 'Portal 2', 'platform': 'steam'},
    ])


class BackendBacklogTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(fastapi_app)
        self.client.cookies.set('session', _session_cookie('alice'))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.service = BacklogService(
            BacklogRepository(os.path.join(tmp.name, 'shared-backlogs.json')))
        self._patches = [
            patch.object(gapi_gui, '_shared_backlog_service', self.service),
            patch.object(gapi_gui, 'ensure_picker_initialized',
                         return_value=_fake_picker()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth ------------------------------------------------------------

    def test_collections_require_login(self):
        self.assertEqual(TestClient(fastapi_app).get('/api/backlogs').status_code, 401)

    def test_status_list_requires_login(self):
        self.assertEqual(TestClient(fastapi_app).get('/api/backlog').status_code, 401)

    # --- collection validation ------------------------------------------

    def test_create_requires_name(self):
        resp = self.client.post('/api/backlogs', json={'name': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name is required', resp.json()['detail'])

    def test_update_unknown_collection_is_404(self):
        resp = self.client.put('/api/backlogs/does-not-exist',
                               json={'name': 'New name'})
        self.assertEqual(resp.status_code, 404)

    def test_delete_unknown_collection_is_404(self):
        resp = self.client.delete('/api/backlogs/does-not-exist')
        self.assertEqual(resp.status_code, 404)

    # --- per-game status validation -------------------------------------

    def test_list_not_initialized_is_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/backlog')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Not initialized', resp.json()['detail'])

    def test_list_invalid_status_is_400(self):
        resp = self.client.get('/api/backlog?status=bogus')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Invalid status', resp.json()['detail'])

    def test_set_status_requires_status(self):
        resp = self.client.post('/api/backlog/steam:620', json={'notes': 'x'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('status is required', resp.json()['detail'])

    def test_set_invalid_status_is_400(self):
        resp = self.client.post('/api/backlog/steam:620', json={'status': 'bogus'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Invalid status', resp.json()['detail'])

    def test_get_status_of_unknown_game_is_null(self):
        resp = self.client.get('/api/backlog/steam:999')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'game_id': 'steam:999', 'status': None, 'notes': ''})

    def test_delete_unknown_game_is_404(self):
        resp = self.client.delete('/api/backlog/steam:999')
        self.assertEqual(resp.status_code, 404)

    # --- a small happy-path round-trip (PUT upsert) ----------------------

    def test_put_set_then_get_status(self):
        put = self.client.put('/api/backlog/steam:620', json={'status': 'playing'})
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json()['status'], 'playing')
        got = self.client.get('/api/backlog/steam:620')
        self.assertEqual(got.json()['status'], 'playing')


if __name__ == '__main__':
    unittest.main()
