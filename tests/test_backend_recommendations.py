#!/usr/bin/env python3
"""
Tests for the migrated base recommendations route
(backend/routers/recommendations.py).

Run with:
    python -m pytest tests/test_backend_recommendations.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class BackendRecommendationsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/recommendations').status_code, 401)

    def test_not_initialized_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/recommendations')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Not initialized', resp.json()['error'])

    def test_success_forwards_filters(self):
        captured = {}

        def _recs(**kwargs):
            captured.update(kwargs)
            return [{'appid': 620, 'name': 'Portal 2', 'recommendation_score': 5.2}]

        picker = SimpleNamespace(get_recommendations=_recs)
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get(
                '/api/recommendations?count=3&platforms=steam,epic'
                '&max_budget=20&include_new=true&refresh_seed=abc')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['recommendations'][0]['name'], 'Portal 2')
        self.assertEqual(captured['count'], 3)
        self.assertEqual(captured['platforms'], ['steam', 'epic'])
        self.assertEqual(captured['max_budget'], 20.0)
        self.assertTrue(captured['include_new_releases'])
        self.assertEqual(captured['refresh_seed'], 'abc')

    def test_typeerror_falls_back_to_count_only(self):
        calls = []

        def _recs(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise TypeError("unexpected kwarg")
            return []

        picker = SimpleNamespace(get_recommendations=_recs)
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/recommendations?count=7')
        self.assertEqual(resp.status_code, 200)
        # second call used count-only
        self.assertEqual(calls[1], {'count': 7})

    def test_error_is_500(self):
        picker = SimpleNamespace(
            get_recommendations=lambda **k: (_ for _ in ()).throw(RuntimeError('boom')))
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/recommendations')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to generate', resp.json()['error'])

    # --- /ai (reads ai_recommendations via the SQLAlchemy layer) --------

    def test_ai_returns_defaults_when_no_cached_recs(self):
        # No cached recommendations -> fall back to the default set.
        from unittest.mock import MagicMock
        with patch.object(gapi_gui.database, 'SessionLocal',
                          return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_ai_recommendations',
                          return_value=[]):
            resp = self.client.get('/api/recommendations/ai')
        self.assertEqual(resp.status_code, 200)
        names = [r['name'] for r in resp.json()['recommendations']]
        self.assertIn('Baldurs Gate 3', names)

    def test_ai_returns_cached_recommendations(self):
        # When the ai_recommendations table has rows for the user, return them.
        from unittest.mock import MagicMock
        recs = [{'id': '1', 'name': 'Hades', 'match_score': 92,
                 'reason': 'Roguelike you might like'}]
        with patch.object(gapi_gui.database, 'SessionLocal',
                          return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_ai_recommendations',
                          return_value=recs):
            resp = self.client.get('/api/recommendations/ai')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['recommendations'][0]['name'], 'Hades')

    def test_ai_returns_defaults_on_db_error(self):
        # A DB error during the lookup still yields the safe default set (200).
        with patch.object(gapi_gui.database, 'SessionLocal',
                          side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/recommendations/ai')
        self.assertEqual(resp.status_code, 200)
        names = [r['name'] for r in resp.json()['recommendations']]
        self.assertIn('Baldurs Gate 3', names)


if __name__ == '__main__':
    unittest.main()
