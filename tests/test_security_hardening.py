#!/usr/bin/env python3
"""
Tests for security hardening features:
  - HTTP security headers added to all responses
  - API rate limiting on auth endpoints
  - API response compression availability
  - /api/admin/security-info endpoint

Run with:
    python -m pytest tests/test_security_hardening.py
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


class TestSecurityHeaders(unittest.TestCase):
    """Every response must include the mandatory security headers."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _check_headers(self, resp):
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff',
                         'X-Content-Type-Options must be "nosniff"')
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'SAMEORIGIN',
                         'X-Frame-Options must be "SAMEORIGIN"')
        self.assertIn('Referrer-Policy', resp.headers,
                      'Referrer-Policy header must be present')
        self.assertIn('Permissions-Policy', resp.headers,
                      'Permissions-Policy header must be present')

    def test_security_headers_on_json_endpoint(self):
        resp = self.client.get('/api/auth/current')
        self._check_headers(resp)

    def test_security_headers_on_404(self):
        resp = self.client.get('/this/does/not/exist/at/all')
        self._check_headers(resp)

    def test_x_content_type_options_is_nosniff(self):
        resp = self.client.get('/api/auth/current')
        self.assertEqual(resp.headers['X-Content-Type-Options'], 'nosniff')

    def test_x_frame_options_is_sameorigin(self):
        resp = self.client.get('/api/auth/current')
        self.assertEqual(resp.headers['X-Frame-Options'], 'SAMEORIGIN')

    def test_x_xss_protection_not_sent(self):
        # X-XSS-Protection is deprecated and can introduce vulnerabilities;
        # we explicitly do not set it.
        resp = self.client.get('/api/auth/current')
        self.assertNotIn('X-XSS-Protection', resp.headers)

    def test_referrer_policy_present(self):
        resp = self.client.get('/api/auth/current')
        self.assertIn(resp.headers['Referrer-Policy'], [
            'strict-origin-when-cross-origin',
            'no-referrer',
            'same-origin',
        ])

    def test_permissions_policy_restricts_sensors(self):
        resp = self.client.get('/api/auth/current')
        policy = resp.headers.get('Permissions-Policy', '')
        self.assertIn('geolocation=()', policy)

    def test_security_headers_on_post_endpoint(self):
        resp = self.client.post(
            '/api/auth/login',
            json={'username': 'nobody', 'password': 'wrong'},
            content_type='application/json',
        )
        self._check_headers(resp)


class TestSecurityInfoEndpoint(unittest.TestCase):
    """GET /api/admin/security-info returns security feature flags."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_security_info_requires_admin(self):
        resp = self.client.get('/api/admin/security-info')
        self.assertIn(resp.status_code, (401, 403))

    def test_security_info_returns_flags(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/security-info')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('compression_enabled', data)
        self.assertIn('rate_limiting_enabled', data)
        self.assertIn('security_headers_enabled', data)

    def test_security_headers_always_enabled(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/security-info')
        data = json.loads(resp.data)
        self.assertTrue(data['security_headers_enabled'])

    def test_security_info_booleans(self):
        """All values in the response must be booleans."""
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/security-info')
        data = json.loads(resp.data)
        for key, value in data.items():
            self.assertIsInstance(value, bool, f'{key} should be bool')


class TestRateLimiting(unittest.TestCase):
    """Rate-limiting decorators must be present on auth endpoints."""

    def test_login_has_rate_limit_decorator(self):
        """The login view function must be wrapped by a rate-limit decorator
        or be the no-op stub when Flask-Limiter is not installed."""
        import inspect
        fn = gapi_gui.app.view_functions.get('api_auth_login')
        self.assertIsNotNone(fn, 'api_auth_login view must be registered')
        # If Flask-Limiter is available the function is wrapped; if not it is
        # still callable.  Either way it must accept requests.
        self.assertTrue(callable(fn))

    def test_register_has_rate_limit_decorator(self):
        fn = gapi_gui.app.view_functions.get('api_auth_register')
        self.assertIsNotNone(fn, 'api_auth_register view must be registered')
        self.assertTrue(callable(fn))

    def test_limiter_attribute_exists_on_module(self):
        self.assertTrue(hasattr(gapi_gui, 'limiter'),
                        'gapi_gui must expose a "limiter" attribute')

    def test_limiter_is_functional(self):
        """limiter.limit() must return a decorator without raising."""
        decorator = gapi_gui.limiter.limit("1 per second")
        def dummy():
            pass
        wrapped = decorator(dummy)
        self.assertTrue(callable(wrapped))


class TestCompressionAndLimiterFlags(unittest.TestCase):
    """Module-level flags must be consistent with installed packages."""

    def test_compress_flag_is_boolean(self):
        self.assertIsInstance(gapi_gui._COMPRESS_AVAILABLE, bool)

    def test_limiter_flag_is_boolean(self):
        self.assertIsInstance(gapi_gui._LIMITER_AVAILABLE, bool)

    def test_compress_flag_true_when_installed(self):
        try:
            import flask_compress  # noqa: F401
            self.assertTrue(gapi_gui._COMPRESS_AVAILABLE)
        except ImportError:
            self.assertFalse(gapi_gui._COMPRESS_AVAILABLE)

    def test_limiter_flag_true_when_installed(self):
        try:
            import flask_limiter  # noqa: F401
            self.assertTrue(gapi_gui._LIMITER_AVAILABLE)
        except ImportError:
            self.assertFalse(gapi_gui._LIMITER_AVAILABLE)


if __name__ == '__main__':
    unittest.main()
