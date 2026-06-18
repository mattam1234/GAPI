#!/usr/bin/env python3
"""
Tests for the migrated tags domain (backend/routers/tags.py).

Exercises tag CRUD and the by-tag library filter through the FastAPI app, with
auth bridged via the Flask session cookie and the per-user picker stubbed.

Run with:
    python -m pytest tests/test_backend_tags.py
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


class _MemoryTagService:
    """In-memory stand-in mirroring app.services.tag_service.TagService."""
    def __init__(self):
        self._data = {}

    def add(self, game_id, tag):
        tags = self._data.setdefault(str(game_id), [])
        if tag in tags:
            return False
        tags.append(tag)
        return True

    def remove(self, game_id, tag):
        tags = self._data.get(str(game_id), [])
        if tag in tags:
            tags.remove(tag)
            return True
        return False

    def get(self, game_id):
        return list(self._data.get(str(game_id), []))

    def get_all(self):
        return {k: list(v) for k, v in self._data.items()}

    def all_tag_names(self):
        return sorted({t for v in self._data.values() for t in v})

    def filter_by_tag(self, tag, games):
        return [
            g for g in games
            if tag in self.get(g.get('game_id', str(g.get('appid', ''))))
        ]


class _FakePicker:
    def __init__(self):
        self.tag_service = _MemoryTagService()
        self.games = [
            {'appid': 570, 'game_id': 'steam:570', 'name': 'Portal',
             'playtime_forever': 120},
        ]


class BackendTagsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.picker = _FakePicker()
        self._patch = patch.object(gapi_gui, 'ensure_picker_initialized',
                                   return_value=self.picker)
        self._patch.start()
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        self._patch.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/tags').status_code, 401)

    # --- CRUD ------------------------------------------------------------

    def test_empty_initially(self):
        resp = self.client.get('/api/tags')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'tags': [], 'game_tags': {}})

    def test_add_tag(self):
        resp = self.client.post('/api/tags/steam:570', json={'tag': 'cozy'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['added'])
        self.assertEqual(body['tags'], ['cozy'])

        # Reflected in the global tag list + per-game tags
        self.assertEqual(self.client.get('/api/tags').json()['tags'], ['cozy'])
        self.assertEqual(
            self.client.get('/api/tags/steam:570').json()['tags'], ['cozy'])

    def test_add_duplicate_tag_reports_not_added(self):
        self.client.post('/api/tags/steam:570', json={'tag': 'cozy'})
        resp = self.client.post('/api/tags/steam:570', json={'tag': 'cozy'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['added'])

    def test_add_empty_tag_is_400(self):
        resp = self.client.post('/api/tags/steam:570', json={'tag': '   '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('tag is required', resp.json()['detail'])

    def test_remove_tag_then_404(self):
        self.client.post('/api/tags/steam:570', json={'tag': 'cozy'})
        ok = self.client.delete('/api/tags/steam:570/cozy')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['tags'], [])
        missing = self.client.delete('/api/tags/steam:570/cozy')
        self.assertEqual(missing.status_code, 404)

    # --- by-tag library filter ------------------------------------------

    def test_library_by_tag(self):
        self.client.post('/api/tags/steam:570', json={'tag': 'cozy'})
        resp = self.client.get('/api/library/by-tag/cozy')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['tag'], 'cozy')
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['games'][0]['name'], 'Portal')
        self.assertEqual(body['games'][0]['tags'], ['cozy'])

    def test_library_by_tag_no_matches(self):
        resp = self.client.get('/api/library/by-tag/nonexistent')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)


if __name__ == '__main__':
    unittest.main()
