#!/usr/bin/env python3
"""
Tests for the FastAPI modernization foundation (backend/).

Covers:
  - Auth dependency bridging the Flask session cookie (anonymous / non-admin /
    admin) on the migrated analytics endpoints.
  - Analytics dashboard + export served natively by FastAPI, reusing the
    existing AnalyticsService (via dependency override for determinism).
  - The strangler-fig mount: unmigrated paths fall through to the legacy Flask
    app (GET /api/health).

Run with:
    python -m pytest tests/test_backend_foundation.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app
from backend.dependencies import get_db
from backend.routers.analytics import get_analytics_service


def _session_cookie(username):
    """Forge a valid Flask session cookie the way the real login endpoint does."""
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _FakeAnalytics:
    """Deterministic stand-in so tests don't depend on live DB contents."""
    def get_dashboard_summary(self, db):
        return {'total_users': 3, 'total_picks': 4, 'total_reviews': 2}

    def get_pick_trends(self, db, days=7):
        return [{'date': '2026-06-18', 'picks': 4}]

    def get_active_users(self, db, days=7):
        return [{'date': '2026-06-18', 'active_users': 3}]

    def get_top_games(self, db, limit=10):
        return [{'game_id': 'steam:570', 'game_name': 'Portal', 'pick_count': 3}]

    def get_platform_stats(self, db):
        return {'steam': 5}

    def get_engagement_metrics(self, db):
        return {'total_users': 3, 'engagement_rate': '66.7%', 'users_picked': 3}

    def get_chat_stats(self, db, days=7):
        return {'messages_7d': 10, 'active_chatters': 2, 'avg_msg_per_user': 5}

    def get_review_stats(self, db):
        return {'total': 2, 'average_rating': 4.5, 'distribution': {'star_5': 1}}

    def get_export_data(self, db):
        return {
            'timestamp': '2026-06-18T00:00:00',
            'summary': self.get_dashboard_summary(db),
            'pick_trends_7d': self.get_pick_trends(db),
            'active_users_7d': self.get_active_users(db),
            'top_games': self.get_top_games(db, 20),
            'platform_stats': self.get_platform_stats(db),
            'engagement': self.get_engagement_metrics(db),
            'chat_stats': self.get_chat_stats(db),
            'review_stats': self.get_review_stats(db),
        }


class BackendFoundationTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Reuse a dummy DB session and the fake service so the slice is tested
        # in isolation from real DB contents. Auth is exercised for real.
        app.dependency_overrides[get_db] = lambda: iter([object()])
        app.dependency_overrides[get_analytics_service] = lambda: _FakeAnalytics()

    def tearDown(self):
        app.dependency_overrides.clear()

    # --- auth on a migrated endpoint ------------------------------------

    def test_dashboard_requires_login(self):
        resp = self.client.get('/api/analytics/dashboard')
        self.assertEqual(resp.status_code, 401)

    def test_dashboard_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui._app_settings_service, 'is_admin',
                          return_value=False):
            resp = self.client.get('/api/analytics/dashboard')
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_ok_for_admin(self):
        self.client.cookies.set('session', _session_cookie('admin'))
        with patch.object(gapi_gui._app_settings_service, 'is_admin',
                          return_value=True):
            resp = self.client.get('/api/analytics/dashboard')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['summary']['total_picks'], 4)
        self.assertEqual(body['top_games'][0]['game_name'], 'Portal')
        self.assertEqual(body['review_stats']['average_rating'], 4.5)
        # Response is shaped by the Pydantic model (defaults filled in).
        self.assertIn('timestamp', body)
        self.assertIn('active_users_7d', body)

    def test_export_ok_for_admin(self):
        self.client.cookies.set('session', _session_cookie('admin'))
        with patch.object(gapi_gui._app_settings_service, 'is_admin',
                          return_value=True):
            resp = self.client.get('/api/analytics/export')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['top_games'][0]['pick_count'], 3)

    def test_tampered_cookie_is_anonymous(self):
        self.client.cookies.set('session', 'not-a-valid-signed-cookie')
        resp = self.client.get('/api/analytics/dashboard')
        self.assertEqual(resp.status_code, 401)

    # --- strangler fallback to legacy Flask -----------------------------

    def test_unmigrated_path_falls_through_to_flask(self):
        # /api/health is only defined in the legacy Flask app; reaching it
        # proves the WSGI fallback mount works.
        resp = self.client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'healthy')

    def test_openapi_schema_generated(self):
        # FastAPI auto-generates the spec that will retire openapi_spec.py.
        resp = self.client.get('/openapi.json')
        self.assertEqual(resp.status_code, 200)
        paths = resp.json().get('paths', {})
        self.assertIn('/api/analytics/dashboard', paths)


if __name__ == '__main__':
    unittest.main()
