#!/usr/bin/env python3
"""
Tests for the migrated reviews domain (backend/routers/reviews.py).

Exercises the full CRUD surface through the FastAPI app, with auth bridged via
the Flask session cookie and the per-user picker stubbed so storage behavior is
deterministic and isolated.

Run with:
    python -m pytest tests/test_backend_reviews.py
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


class _MemoryReviewService:
    """In-memory stand-in mirroring app.services.review_service.ReviewService."""
    def __init__(self):
        self._data = {}

    def get_all(self):
        return self._data

    def get(self, game_id):
        return self._data.get(str(game_id))

    def add_or_update(self, game_id, rating, notes=''):
        if not 1 <= int(rating) <= 10:
            return False
        self._data[str(game_id)] = {
            'rating': int(rating), 'notes': notes, 'updated_at': '2026-06-18T00:00:00'
        }
        return True

    def remove(self, game_id):
        return self._data.pop(str(game_id), None) is not None


class _FakePicker:
    def __init__(self):
        self.review_service = _MemoryReviewService()


class BackendReviewsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.picker = _FakePicker()
        # Reuse one picker so writes persist across requests within a test.
        self._patches = [
            patch.object(gapi_gui, 'ensure_picker_initialized',
                         return_value=self.picker),
        ]
        for p in self._patches:
            p.start()
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        for p in self._patches:
            p.stop()
        app.dependency_overrides.clear()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        c = TestClient(app)  # no cookie
        self.assertEqual(c.get('/api/reviews').status_code, 401)

    # --- CRUD lifecycle --------------------------------------------------

    def test_empty_list_initially(self):
        resp = self.client.get('/api/reviews')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {})

    def test_create_then_get_and_list(self):
        resp = self.client.post('/api/reviews/steam:570',
                                json={'rating': 9, 'notes': 'great'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'game_id': 'steam:570',
                          'rating': 9, 'notes': 'great'})

        got = self.client.get('/api/reviews/steam:570')
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()['rating'], 9)
        self.assertEqual(got.json()['notes'], 'great')

        listed = self.client.get('/api/reviews')
        self.assertIn('steam:570', listed.json())

    def test_put_upserts(self):
        self.client.post('/api/reviews/g1', json={'rating': 3})
        resp = self.client.put('/api/reviews/g1', json={'rating': 7, 'notes': 'better'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get('/api/reviews/g1').json()['rating'], 7)

    def test_get_missing_is_404(self):
        self.assertEqual(self.client.get('/api/reviews/nope').status_code, 404)

    def test_delete_then_missing(self):
        self.client.post('/api/reviews/g2', json={'rating': 5})
        self.assertEqual(self.client.delete('/api/reviews/g2').status_code, 200)
        self.assertEqual(self.client.delete('/api/reviews/g2').status_code, 404)

    # --- validation parity with the legacy endpoint ----------------------

    def test_missing_rating_is_400(self):
        resp = self.client.post('/api/reviews/g3', json={'notes': 'x'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('rating is required', resp.json()['detail'])

    def test_non_integer_rating_is_400(self):
        resp = self.client.post('/api/reviews/g4', json={'rating': 'abc'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('must be an integer', resp.json()['detail'])

    def test_out_of_range_rating_is_400(self):
        resp = self.client.post('/api/reviews/g5', json={'rating': 99})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('between 1 and 10', resp.json()['detail'])


if __name__ == '__main__':
    unittest.main()
