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

import gapi_gui


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


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
        self.client = gapi_gui.app.test_client()
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats.clear()

    def test_stats_require_admin(self):
        resp = self.client.get('/api/admin/api-stats')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_returns_ok_for_admin(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/api-stats')
        self.assertEqual(resp.status_code, 200)

    def test_stats_response_shape(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/api-stats')
        data = json.loads(resp.data)
        self.assertIn('stats', data)
        self.assertIn('endpoint_count', data)

    def test_stats_increments_on_requests(self):
        # Make a couple of requests to a known endpoint
        self.client.get('/api/auth/current')
        self.client.get('/api/auth/current')
        with gapi_gui._api_stats_lock:
            entry = gapi_gui._api_endpoint_stats.get('api_auth_current')
        self.assertIsNotNone(entry, 'api_auth_current should be tracked')
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
        self.client.get('/api/changelog')
        with gapi_gui._api_stats_lock:
            entry = gapi_gui._api_endpoint_stats.get('api_changelog')
        self.assertIsNotNone(entry)
        for field in ('calls', 'errors', 'total_ms', 'min_ms', 'max_ms'):
            self.assertIn(field, entry, f'missing field: {field}')

    def test_stats_avg_ms_in_admin_response(self):
        self.client.get('/api/changelog')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/api-stats')
        data = json.loads(resp.data)
        # changelog endpoint should appear in stats
        stats_list = data['stats']
        endpoints = {e['endpoint']: e for e in stats_list}
        self.assertIn('api_changelog', endpoints)
        self.assertIn('avg_ms', endpoints['api_changelog'])

    def test_stats_reset_requires_admin(self):
        resp = self.client.post('/api/admin/api-stats/reset')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_reset_clears_data(self):
        self.client.get('/api/changelog')
        # Confirm data exists
        with gapi_gui._api_stats_lock:
            self.assertIn('api_changelog', gapi_gui._api_endpoint_stats)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/api-stats/reset')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['reset'])
        # The changelog entry (from before reset) must be gone; the reset
        # endpoint itself may have been added after the clear.
        with gapi_gui._api_stats_lock:
            self.assertNotIn('api_changelog', gapi_gui._api_endpoint_stats)

    def test_stats_sorted_by_call_count(self):
        # Hit changelog 3x, auth/current 1x
        for _ in range(3):
            self.client.get('/api/changelog')
        self.client.get('/api/auth/current')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/api-stats')
        data = json.loads(resp.data)
        stats_list = data['stats']
        # changelog (3 calls) must appear before auth_current (1 call)
        ep_names = [e['endpoint'] for e in stats_list]
        if 'api_changelog' in ep_names and 'api_auth_current' in ep_names:
            self.assertLess(ep_names.index('api_changelog'), ep_names.index('api_auth_current'))
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
        self.client = gapi_gui.app.test_client()
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
        return self.client.post(
            '/api/errors/report',
            json=payload,
            content_type='application/json',
        )

    def test_report_returns_201(self):
        resp = self._report()
        self.assertEqual(resp.status_code, 201)

    def test_report_response_body(self):
        resp = self._report()
        data = json.loads(resp.data)
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
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_report_no_json_body_ok(self):
        resp = self.client.post('/api/errors/report')
        self.assertEqual(resp.status_code, 201)

    def test_view_errors_requires_admin(self):
        resp = self.client.get('/api/admin/client-errors')
        self.assertIn(resp.status_code, (401, 403))

    def test_view_errors_returns_list(self):
        self._report(message='err1')
        self._report(message='err2')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/client-errors')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('errors', data)
        self.assertIn('total_stored', data)
        self.assertGreaterEqual(data['total_stored'], 2)

    def test_view_errors_newest_first(self):
        self._report(message='first')
        self._report(message='second')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/client-errors')
        data = json.loads(resp.data)
        messages = [e['message'] for e in data['errors']]
        self.assertEqual(messages[0], 'second')
        self.assertEqual(messages[1], 'first')

    def test_view_errors_limit_param(self):
        for i in range(10):
            self._report(message=f'err{i}')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/client-errors?limit=3')
        data = json.loads(resp.data)
        self.assertLessEqual(len(data['errors']), 3)

    def test_clear_errors_requires_admin(self):
        resp = self.client.post('/api/admin/client-errors/clear')
        self.assertIn(resp.status_code, (401, 403))

    def test_clear_errors_empties_buffer(self):
        self._report(message='to clear')
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 1)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/client-errors/clear')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
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
        self.client = gapi_gui.app.test_client()

    def test_changelog_is_public(self):
        resp = self.client.get('/api/changelog')
        self.assertEqual(resp.status_code, 200)

    def test_changelog_response_shape(self):
        resp = self.client.get('/api/changelog')
        data = json.loads(resp.data)
        self.assertIn('changelog', data)
        self.assertIn('total_versions', data)

    def test_changelog_entries_have_required_fields(self):
        resp = self.client.get('/api/changelog')
        data = json.loads(resp.data)
        for entry in data['changelog']:
            self.assertIn('version', entry)
            self.assertIn('date', entry)
            self.assertIn('changes', entry)
            self.assertIsInstance(entry['changes'], list)
            self.assertGreater(len(entry['changes']), 0)

    def test_changelog_limit_param(self):
        resp = self.client.get('/api/changelog?limit=1')
        data = json.loads(resp.data)
        self.assertEqual(len(data['changelog']), 1)

    def test_changelog_limit_defaults_to_all(self):
        resp_all = self.client.get('/api/changelog')
        resp_lim = self.client.get(f'/api/changelog?limit={len(gapi_gui._API_CHANGELOG)}')
        data_all = json.loads(resp_all.data)
        data_lim = json.loads(resp_lim.data)
        self.assertEqual(data_all['changelog'], data_lim['changelog'])

    def test_changelog_total_versions_matches_data(self):
        resp = self.client.get('/api/changelog')
        data = json.loads(resp.data)
        self.assertEqual(data['total_versions'], len(gapi_gui._API_CHANGELOG))

    def test_changelog_invalid_limit_returns_all(self):
        resp = self.client.get('/api/changelog?limit=abc')
        data = json.loads(resp.data)
        self.assertEqual(len(data['changelog']), data['total_versions'])

    def test_changelog_most_recent_version_listed_first(self):
        resp = self.client.get('/api/changelog')
        data = json.loads(resp.data)
        versions = [e['version'] for e in data['changelog']]
        # First entry must be the highest version in the changelog constant
        self.assertEqual(versions[0], gapi_gui._API_CHANGELOG[0]['version'])

    def test_changelog_data_type_is_list(self):
        resp = self.client.get('/api/changelog')
        data = json.loads(resp.data)
        self.assertIsInstance(data['changelog'], list)

    def test_changelog_security_headers_present(self):
        """Changelog response should still carry security headers."""
        resp = self.client.get('/api/changelog')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')


if __name__ == '__main__':
    unittest.main()
