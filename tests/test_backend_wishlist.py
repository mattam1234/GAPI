#!/usr/bin/env python3
"""
Tests for the migrated wishlist domain (backend/routers/wishlist.py).

Covers list/add/remove, the 201 on create, validation parity, the path-style
game_id in DELETE, and the sales endpoint branches (empty wishlist, missing
Steam client, and a live check with a fake Steam client).

Run with:
    python -m pytest tests/test_backend_wishlist.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi
import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _MemoryWishlistService:
    """In-memory stand-in mirroring app.services.wishlist_service.WishlistService."""
    def __init__(self):
        self._data = {}

    def add(self, game_id, name, platform='steam', target_price=None, notes=''):
        if target_price is not None and target_price < 0:
            return False
        self._data[game_id] = {
            'game_id': game_id, 'name': name, 'platform': platform,
            'added_date': '2026-06-18', 'target_price': target_price, 'notes': notes,
        }
        return True

    def remove(self, game_id):
        return self._data.pop(game_id, None) is not None

    def get_all(self):
        return self._data

    def check_sales(self, steam_client):
        # One synthetic sale, regardless of client, for the live-check branch.
        return [{'game_id': gid, 'sale_reason': 'on_sale'} for gid in self._data]


class _FakePicker:
    def __init__(self, steam_client=None):
        self.wishlist_service = _MemoryWishlistService()
        self.steam_client = steam_client


class BackendWishlistTest(unittest.TestCase):
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
        self.assertEqual(TestClient(app).get('/api/wishlist').status_code, 401)

    # --- list / add / remove --------------------------------------------

    def test_empty_initially(self):
        resp = self.client.get('/api/wishlist')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'entries': [], 'count': 0})

    def test_add_returns_201_and_lists(self):
        resp = self.client.post('/api/wishlist',
                                json={'game_id': 'steam:620', 'name': 'Portal 2',
                                      'target_price': 4.99})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {'success': True, 'game_id': 'steam:620'})

        listed = self.client.get('/api/wishlist').json()
        self.assertEqual(listed['count'], 1)
        self.assertEqual(listed['entries'][0]['name'], 'Portal 2')
        self.assertEqual(listed['entries'][0]['target_price'], 4.99)

    def test_remove_path_style_id_then_404(self):
        self.client.post('/api/wishlist',
                         json={'game_id': 'steam:620', 'name': 'Portal 2'})
        ok = self.client.delete('/api/wishlist/steam:620')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), {'success': True})
        self.assertEqual(self.client.delete('/api/wishlist/steam:620').status_code, 404)

    # --- validation parity ----------------------------------------------

    def test_missing_game_id_is_400(self):
        resp = self.client.post('/api/wishlist', json={'name': 'X'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('game_id is required', resp.json()['detail'])

    def test_missing_name_is_400(self):
        resp = self.client.post('/api/wishlist', json={'game_id': 'steam:1'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name is required', resp.json()['detail'])

    def test_non_numeric_target_price_is_400(self):
        resp = self.client.post('/api/wishlist',
                                json={'game_id': 'g', 'name': 'n',
                                      'target_price': 'cheap'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('target_price must be a number', resp.json()['detail'])

    def test_negative_target_price_is_400(self):
        resp = self.client.post('/api/wishlist',
                                json={'game_id': 'g', 'name': 'n',
                                      'target_price': -1})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('must not be negative', resp.json()['detail'])

    # --- sales -----------------------------------------------------------

    def test_sales_empty_wishlist(self):
        resp = self.client.get('/api/wishlist/sales')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['checked'], 0)
        self.assertEqual(resp.json()['sales'], [])

    def test_sales_without_steam_client_is_503(self):
        self.client.post('/api/wishlist',
                         json={'game_id': 'steam:620', 'name': 'Portal 2'})
        resp = self.client.get('/api/wishlist/sales')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Steam client not available', resp.json()['detail'])

    def test_sales_with_steam_client(self):
        # A real SteamAPIClient instance passes the isinstance() gate.
        self.picker.steam_client = gapi.SteamAPIClient.__new__(gapi.SteamAPIClient)
        self.client.post('/api/wishlist',
                         json={'game_id': 'steam:620', 'name': 'Portal 2'})
        resp = self.client.get('/api/wishlist/sales')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['on_sale_count'], 1)
        self.assertEqual(body['checked'], 1)


if __name__ == '__main__':
    unittest.main()
