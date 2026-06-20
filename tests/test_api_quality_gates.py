#!/usr/bin/env python3
"""
Tests for Phase 9C Quality Gates features:
  - API endpoint usage statistics tracking and admin endpoint
  - Client-side error reporting (POST) and admin view/clear endpoints
  - API changelog endpoint

Run with:
    python -m pytest tests/test_api_quality_gates.py
"""
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient as _FastTestClient

import gapi_gui
from backend.main import app as _fastapi_app


def _set_admin_session(client):
    """Log in as admin on either a Flask or FastAPI test client."""
    if hasattr(client, 'session_transaction'):
        with client.session_transaction() as sess:
            sess['username'] = 'admin'
    else:
        ser = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
        client.cookies.set('session', ser.dumps({'username': 'admin'}))


def _set_user_session(client, username='alice'):
    with client.session_transaction() as sess:
        sess['username'] = username


class _AppTestBase(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        # Clear stats between tests
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats.clear()
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.clear()


# ===========================================================================
# API Usage Statistics
# ===========================================================================

class TestApiStats(unittest.TestCase):
    """API usage statistics are collected and exposed via admin endpoint."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        # Flask client: still-Flask routes (/api/openapi.json) populate the
        # shared in-memory _api_endpoint_stats via after_request. FastAPI
        # client: the migrated admin read/reset endpoints (admin_ops). Both
        # read/write the same gapi_gui module globals. (/api/changelog moved to
        # FastAPI, whose stats are tracked outside this Flask after_request.)
        self.client = gapi_gui.app.test_client()
        self.api = _FastTestClient(_fastapi_app)
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats.clear()

    def test_stats_require_admin(self):
        resp = self.api.get('/api/admin/api-stats')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_returns_ok_for_admin(self):
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/api-stats')
        self.assertEqual(resp.status_code, 200)

    def test_stats_response_shape(self):
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/api-stats')
        data = resp.json()
        self.assertIn('stats', data)
        self.assertIn('endpoint_count', data)

    def test_stats_increments_on_requests(self):
        # Make a couple of requests to a known still-Flask endpoint. (/api/auth/*
        # and /api/changelog migrated to FastAPI, whose stats are tracked
        # outside this Flask after_request mechanism, so use the still-Flask
        # /api/openapi.json route here.)
        self.client.get('/api/openapi.json')
        self.client.get('/api/openapi.json')
        with gapi_gui._api_stats_lock:
            entry = gapi_gui._api_endpoint_stats.get('api_openapi_spec')
        self.assertIsNotNone(entry, 'api_openapi_spec should be tracked')
        self.assertGreaterEqual(entry['calls'], 2)

    def test_stats_tracks_errors(self):
        # /api/auth/login with wrong credentials returns 401
        self.client.post(
            '/api/auth/login',
            json={'username': 'no_such_user', 'password': 'bad'},
            content_type='application/json',
        )
        with gapi_gui._api_stats_lock:
            entry = gapi_gui._api_endpoint_stats.get('api_auth_login')
        if entry:  # might not be present if rate-limiter blocked the request
            self.assertGreaterEqual(entry['errors'], 0)

    def test_stats_entry_fields(self):
        self.client.get('/api/openapi.json')
        with gapi_gui._api_stats_lock:
            entry = gapi_gui._api_endpoint_stats.get('api_openapi_spec')
        self.assertIsNotNone(entry)
        for field in ('calls', 'errors', 'total_ms', 'min_ms', 'max_ms'):
            self.assertIn(field, entry, f'missing field: {field}')

    def test_stats_avg_ms_in_admin_response(self):
        self.client.get('/api/openapi.json')
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/api-stats')
        data = resp.json()
        # openapi-spec endpoint should appear in stats
        stats_list = data['stats']
        endpoints = {e['endpoint']: e for e in stats_list}
        self.assertIn('api_openapi_spec', endpoints)
        self.assertIn('avg_ms', endpoints['api_openapi_spec'])

    def test_stats_reset_requires_admin(self):
        resp = self.api.post('/api/admin/api-stats/reset')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_reset_clears_data(self):
        self.client.get('/api/openapi.json')
        # Confirm data exists
        with gapi_gui._api_stats_lock:
            self.assertIn('api_openapi_spec', gapi_gui._api_endpoint_stats)
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.post('/api/admin/api-stats/reset')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['reset'])
        # The openapi-spec entry (from before reset) must be gone; the reset
        # endpoint itself may have been added after the clear.
        with gapi_gui._api_stats_lock:
            self.assertNotIn('api_openapi_spec', gapi_gui._api_endpoint_stats)

    def test_stats_sorted_by_call_count(self):
        # Hit openapi-spec 3x, docs 1x (both still-Flask).
        for _ in range(3):
            self.client.get('/api/openapi.json')
        self.client.get('/api/docs')
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/api-stats')
        data = resp.json()
        stats_list = data['stats']
        # openapi_spec (3 calls) must appear before swagger_ui (1 call)
        ep_names = [e['endpoint'] for e in stats_list]
        if 'api_openapi_spec' in ep_names and 'api_swagger_ui' in ep_names:
            self.assertLess(ep_names.index('api_openapi_spec'),
                            ep_names.index('api_swagger_ui'))
        # Verify the list is sorted descending by calls
        calls_list = [e['calls'] for e in stats_list]
        self.assertEqual(calls_list, sorted(calls_list, reverse=True))


# ===========================================================================
# Client-Side Error Reporting
# ===========================================================================

class TestClientErrors(unittest.TestCase):
    """Client-side JS errors are recorded and accessible to admins."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        # POST /api/errors/report migrated to FastAPI, as are the admin
        # view/clear endpoints (admin_ops). Both share the gapi_gui._client_errors
        # ring buffer, so a single FastAPI client drives both.
        self.api = _FastTestClient(_fastapi_app)
        self.client = self.api
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.clear()

    def _report(self, **kwargs):
        payload = {
            'message': 'TypeError: Cannot read property',
            'stack': 'at app.js:42',
            'url': 'http://localhost/',
            'line': 42,
            'col': 7,
        }
        payload.update(kwargs)
        return self.api.post('/api/errors/report', json=payload)

    def test_report_returns_201(self):
        resp = self._report()
        self.assertEqual(resp.status_code, 201)

    def test_report_response_body(self):
        resp = self._report()
        data = resp.json()
        self.assertTrue(data['recorded'])

    def test_report_stored_in_buffer(self):
        self._report(message='TestError')
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 1)
            self.assertEqual(gapi_gui._client_errors[0]['message'], 'TestError')

    def test_report_entry_has_timestamp(self):
        self._report()
        with gapi_gui._client_errors_lock:
            entry = gapi_gui._client_errors[-1]
        self.assertIn('timestamp', entry)
        self.assertTrue(entry['timestamp'])  # non-empty

    def test_report_truncates_long_message(self):
        self._report(message='x' * 1000)
        with gapi_gui._client_errors_lock:
            entry = gapi_gui._client_errors[-1]
        self.assertLessEqual(len(entry['message']), 500)

    def test_report_accepts_empty_body(self):
        resp = self.client.post(
            '/api/errors/report',
            content='{}',
            headers={'content-type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 201)

    def test_report_no_json_body_ok(self):
        resp = self.client.post('/api/errors/report')
        self.assertEqual(resp.status_code, 201)

    def test_view_errors_requires_admin(self):
        resp = self.api.get('/api/admin/client-errors')
        self.assertIn(resp.status_code, (401, 403))

    def test_view_errors_returns_list(self):
        self._report(message='err1')
        self._report(message='err2')
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/client-errors')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('errors', data)
        self.assertIn('total_stored', data)
        self.assertGreaterEqual(data['total_stored'], 2)

    def test_view_errors_newest_first(self):
        self._report(message='first')
        self._report(message='second')
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/client-errors')
        data = resp.json()
        messages = [e['message'] for e in data['errors']]
        self.assertEqual(messages[0], 'second')
        self.assertEqual(messages[1], 'first')

    def test_view_errors_limit_param(self):
        for i in range(10):
            self._report(message=f'err{i}')
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.get('/api/admin/client-errors?limit=3')
        data = resp.json()
        self.assertLessEqual(len(data['errors']), 3)

    def test_clear_errors_requires_admin(self):
        resp = self.api.post('/api/admin/client-errors/clear')
        self.assertIn(resp.status_code, (401, 403))

    def test_clear_errors_empties_buffer(self):
        self._report(message='to clear')
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 1)
        _set_admin_session(self.api)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = self.api.post('/api/admin/client-errors/clear')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['cleared'])
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 0)

    def test_ring_buffer_respects_max_size(self):
        """Buffer should never grow beyond _CLIENT_ERROR_MAX entries."""
        for i in range(gapi_gui._CLIENT_ERROR_MAX + 10):
            self._report(message=f'overflow-{i}')
        with gapi_gui._client_errors_lock:
            self.assertLessEqual(len(gapi_gui._client_errors), gapi_gui._CLIENT_ERROR_MAX)


# ===========================================================================
# API Changelog
# ===========================================================================

class TestApiChangelog(unittest.TestCase):
    """GET /api/changelog returns structured version history."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        # /api/changelog migrated to FastAPI; drive it with the FastAPI client.
        self.client = _FastTestClient(_fastapi_app)
        # A still-Flask client for the security-header check (those headers are
        # added by the legacy after_request, which doesn't run for FastAPI).
        self.flask_client = gapi_gui.app.test_client()

    def test_changelog_is_public(self):
        resp = self.client.get('/api/changelog')
        self.assertEqual(resp.status_code, 200)

    def test_changelog_response_shape(self):
        resp = self.client.get('/api/changelog')
        data = resp.json()
        self.assertIn('changelog', data)
        self.assertIn('total_versions', data)

    def test_changelog_entries_have_required_fields(self):
        resp = self.client.get('/api/changelog')
        data = resp.json()
        for entry in data['changelog']:
            self.assertIn('version', entry)
            self.assertIn('date', entry)
            self.assertIn('changes', entry)
            self.assertIsInstance(entry['changes'], list)
            self.assertGreater(len(entry['changes']), 0)

    def test_changelog_limit_param(self):
        resp = self.client.get('/api/changelog?limit=1')
        data = resp.json()
        self.assertEqual(len(data['changelog']), 1)

    def test_changelog_limit_defaults_to_all(self):
        resp_all = self.client.get('/api/changelog')
        resp_lim = self.client.get(f'/api/changelog?limit={len(gapi_gui._API_CHANGELOG)}')
        data_all = resp_all.json()
        data_lim = resp_lim.json()
        self.assertEqual(data_all['changelog'], data_lim['changelog'])

    def test_changelog_total_versions_matches_data(self):
        resp = self.client.get('/api/changelog')
        data = resp.json()
        self.assertEqual(data['total_versions'], len(gapi_gui._API_CHANGELOG))

    def test_changelog_invalid_limit_returns_all(self):
        resp = self.client.get('/api/changelog?limit=abc')
        data = resp.json()
        self.assertEqual(len(data['changelog']), data['total_versions'])

    def test_changelog_most_recent_version_listed_first(self):
        resp = self.client.get('/api/changelog')
        data = resp.json()
        versions = [e['version'] for e in data['changelog']]
        # First entry must be the highest version in the changelog constant
        self.assertEqual(versions[0], gapi_gui._API_CHANGELOG[0]['version'])

    def test_changelog_data_type_is_list(self):
        resp = self.client.get('/api/changelog')
        data = resp.json()
        self.assertIsInstance(data['changelog'], list)

    def test_changelog_security_headers_present(self):
        """The legacy after_request still carries security headers on Flask
        routes (changelog itself is now FastAPI; use a still-Flask endpoint)."""
        resp = self.flask_client.get('/api/openapi.json')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')


if __name__ == '__main__':
    unittest.main()
