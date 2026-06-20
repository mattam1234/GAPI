#!/usr/bin/env python3
"""Tests for the migrated batch-operations domain (backend/routers/batch.py):

  * POST /api/batch/tag-games
  * POST /api/batch/change-status
  * POST /api/batch/add-to-playlist
  * POST /api/batch/delete
  * POST /api/batch/export

Faithful port of the legacy Flask routes: per-item success counts, swallowed
per-item errors, exact JSON shapes and status codes, ``Cache-Control: no-store``.

Run with:
    python -m pytest tests/test_backend_batch.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _db_gen(db):
    """Mimic database.get_db(): a generator next() can pull one session from."""
    def _gen():
        yield db
    return _gen


class _AuthedCase(unittest.TestCase):
    """Logged-in client with a patched DB session generator."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self.db = MagicMock()
        self._db = patch.object(gapi_gui.database, 'get_db', _db_gen(self.db))
        self._db.start()

    def tearDown(self):
        self._db.stop()


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_tag_games_requires_login(self):
        resp = self.client.post('/api/batch/tag-games',
                                json={'game_ids': [1], 'tags': ['a']})
        self.assertEqual(resp.status_code, 401)

    def test_export_requires_login(self):
        resp = self.client.post('/api/batch/export', json={'game_ids': [1]})
        self.assertEqual(resp.status_code, 401)


# ── tag-games ───────────────────────────────────────────────────────────────

class TagGamesTest(_AuthedCase):
    def test_success_counts_each_item(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_db_favorites_service', svc):
            resp = self.client.post(
                '/api/batch/tag-games',
                json={'game_ids': ['1', '2', '3'], 'tags': ['fun']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'tagged': 3})
        self.assertEqual(svc.add_tags.call_count, 3)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_per_item_error_swallowed_still_counts(self):
        svc = MagicMock()
        svc.add_tags.side_effect = [None, RuntimeError('boom'), None]
        with patch.object(gapi_gui, '_db_favorites_service', svc):
            resp = self.client.post(
                '/api/batch/tag-games',
                json={'game_ids': ['1', '2', '3'], 'tags': ['fun']})
        self.assertEqual(resp.status_code, 200)
        # The id whose add_tags raised is not counted (count incremented after).
        self.assertEqual(resp.json(), {'success': True, 'tagged': 2})

    def test_missing_tags_400(self):
        resp = self.client.post('/api/batch/tag-games',
                                json={'game_ids': ['1'], 'tags': []})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'game_ids and tags required')

    def test_missing_game_ids_400(self):
        resp = self.client.post('/api/batch/tag-games',
                                json={'game_ids': [], 'tags': ['fun']})
        self.assertEqual(resp.status_code, 400)


# ── change-status ───────────────────────────────────────────────────────────

class ChangeStatusTest(_AuthedCase):
    def test_success(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_db_favorites_service', svc):
            resp = self.client.post(
                '/api/batch/change-status',
                json={'game_ids': ['1', '2'], 'status': 'completed'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'updated': 2})
        self.assertEqual(svc.add_to_backlog.call_count, 2)

    def test_missing_status_400(self):
        resp = self.client.post('/api/batch/change-status',
                                json={'game_ids': ['1'], 'status': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'game_ids and status required')


# ── add-to-playlist ─────────────────────────────────────────────────────────

class AddToPlaylistTest(_AuthedCase):
    def test_success_count_only(self):
        resp = self.client.post(
            '/api/batch/add-to-playlist',
            json={'game_ids': ['1', '2', '3'], 'playlist_name': 'Faves'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'added': 3})

    def test_missing_playlist_name_400(self):
        resp = self.client.post('/api/batch/add-to-playlist',
                                json={'game_ids': ['1'], 'playlist_name': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'],
                         'game_ids and playlist_name required')


# ── delete ──────────────────────────────────────────────────────────────────

class DeleteTest(_AuthedCase):
    def test_success_count_only(self):
        with patch.object(gapi_gui, '_db_favorites_service', MagicMock()):
            resp = self.client.post(
                '/api/batch/delete',
                json={'game_ids': ['1', '2'], 'source': 'wishlist'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'deleted': 2})

    def test_default_source_wishlist(self):
        with patch.object(gapi_gui, '_db_favorites_service', MagicMock()):
            resp = self.client.post('/api/batch/delete',
                                    json={'game_ids': ['1']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'deleted': 1})

    def test_missing_game_ids_400(self):
        resp = self.client.post('/api/batch/delete', json={'game_ids': []})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'game_ids required')


# ── export ──────────────────────────────────────────────────────────────────

GAMES = [
    {'app_id': '620', 'name': 'Portal 2',
     'release_date': '2011', 'price': '9.99'},
    {'app_id': '570', 'name': 'Dota 2',
     'release_date': '2013', 'price': '0'},
]


class ExportTest(_AuthedCase):
    def test_csv_export(self):
        picker = SimpleNamespace(games=GAMES)
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=picker):
            resp = self.client.post('/api/batch/export',
                                    json={'game_ids': ['620'], 'format': 'csv'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['content-type'].split(';')[0], 'text/csv')
        self.assertIn('attachment; filename=games_export.csv',
                      resp.headers['content-disposition'])
        body = resp.text
        self.assertIn('App ID,Name,Release Date,Price', body)
        self.assertIn('620,"Portal 2",2011,9.99', body)
        self.assertNotIn('Dota 2', body)

    def test_json_export(self):
        picker = SimpleNamespace(games=GAMES)
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=picker):
            resp = self.client.post(
                '/api/batch/export',
                json={'game_ids': ['620', '570'], 'format': 'json'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual({g['app_id'] for g in data}, {'620', '570'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_no_games_400(self):
        picker = SimpleNamespace(games=[])
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=picker):
            resp = self.client.post('/api/batch/export', json={'game_ids': ['1']})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'No games available')

    def test_no_picker_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=None):
            resp = self.client.post('/api/batch/export', json={'game_ids': ['1']})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'No games available')


if __name__ == '__main__':
    unittest.main()
