#!/usr/bin/env python3
"""Tests for the migrated extensibility domains (FastAPI): push + plugins.

Covers all routes:
  push:
    * GET    /api/push/vapid-public-key   (no auth)
    * POST   /api/push/subscribe
    * DELETE /api/push/unsubscribe
    * GET    /api/push/subscriptions
  plugins:
    * GET    /api/plugins
    * POST   /api/plugins
    * PUT    /api/plugins/{plugin_id}
    * DELETE /api/plugins/{plugin_id}

Services (``_push_service``, ``_plugin_service``) and ``database`` helpers are
patched via ``patch.object`` on ``gapi_gui`` — no real DB or network is touched.

Run with:
    python -m pytest tests/test_backend_extensibility.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _fake_db_gen():
    """Return a generator yielding a MagicMock db (mimics database.get_db())."""
    def gen():
        yield MagicMock()
    return gen


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_push_subscribe_requires_login(self):
        self.assertEqual(
            self.client.post('/api/push/subscribe', json={}).status_code, 401)

    def test_push_unsubscribe_requires_login(self):
        self.assertEqual(
            self.client.request('DELETE', '/api/push/unsubscribe',
                                json={}).status_code, 401)

    def test_push_subscriptions_requires_login(self):
        self.assertEqual(
            self.client.get('/api/push/subscriptions').status_code, 401)

    def test_plugins_list_requires_login(self):
        self.assertEqual(self.client.get('/api/plugins').status_code, 401)

    def test_plugins_register_requires_login(self):
        self.assertEqual(
            self.client.post('/api/plugins', json={}).status_code, 401)

    def test_plugins_toggle_requires_login(self):
        self.assertEqual(
            self.client.put('/api/plugins/1', json={}).status_code, 401)

    def test_plugins_delete_requires_login(self):
        self.assertEqual(
            self.client.delete('/api/plugins/1').status_code, 401)

    def test_vapid_key_no_auth_required(self):
        # No auth on this route; should not be 401.
        with patch.object(gapi_gui, '_push_service', None):
            resp = self.client.get('/api/push/vapid-public-key')
        self.assertEqual(resp.status_code, 200)


# ── GET /api/push/vapid-public-key ──────────────────────────────────────────

class VapidKeyTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_configured(self):
        svc = MagicMock()
        svc.get_public_key.return_value = 'PUBKEY'
        svc.is_configured.return_value = True
        with patch.object(gapi_gui, '_push_service', svc):
            resp = self.client.get('/api/push/vapid-public-key')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'public_key': 'PUBKEY', 'configured': True})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_no_service(self):
        with patch.object(gapi_gui, '_push_service', None):
            resp = self.client.get('/api/push/vapid-public-key')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'public_key': '', 'configured': False})


# ── POST /api/push/subscribe ────────────────────────────────────────────────

class PushSubscribeTest(_AuthedCase):
    _GOOD = {'endpoint': 'https://x', 'keys': {'p256dh': 'a', 'auth': 'b'}}

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/push/subscribe', json=self._GOOD)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json(), {'error': 'Database not available'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_missing_fields_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/push/subscribe',
                                    json={'endpoint': 'https://x', 'keys': {}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json(),
            {'error': "'endpoint', 'keys.p256dh', and 'keys.auth' are required"})

    def test_success_201(self):
        db = MagicMock()
        db.add_push_subscription.return_value = True
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/push/subscribe', json=self._GOOD)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {'subscribed': True})

    def test_save_failure_500(self):
        db = MagicMock()
        db.add_push_subscription.return_value = False
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/push/subscribe', json=self._GOOD)
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {'error': 'Failed to save subscription'})

    def test_db_exception_500(self):
        db = MagicMock()
        db.add_push_subscription.side_effect = RuntimeError('boom')
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/push/subscribe', json=self._GOOD)
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {'error': 'Internal server error'})


# ── DELETE /api/push/unsubscribe ────────────────────────────────────────────

class PushUnsubscribeTest(_AuthedCase):
    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://x'})
        self.assertEqual(resp.status_code, 503)

    def test_missing_endpoint_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {'error': "'endpoint' is required"})

    def test_success(self):
        db = MagicMock()
        db.remove_push_subscription.return_value = True
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://x'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'unsubscribed': True})

    def test_not_found_404(self):
        db = MagicMock()
        db.remove_push_subscription.return_value = False
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://x'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Subscription not found'})

    def test_db_exception_500(self):
        db = MagicMock()
        db.remove_push_subscription.side_effect = RuntimeError('boom')
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://x'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {'error': 'Internal server error'})


# ── GET /api/push/subscriptions ─────────────────────────────────────────────

class PushSubscriptionsTest(_AuthedCase):
    def test_db_unavailable_empty(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/push/subscriptions')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'subscriptions': [], 'count': 0})

    def test_success_omits_keys(self):
        db = MagicMock()
        db.get_user_push_subscriptions.return_value = [
            {'id': 1, 'endpoint': 'https://x', 'user_agent': 'UA',
             'created_at': 't', 'p256dh': 'secret', 'auth': 'secret'},
        ]
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.get('/api/push/subscriptions')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            'subscriptions': [
                {'id': 1, 'endpoint': 'https://x', 'user_agent': 'UA',
                 'created_at': 't'},
            ],
            'count': 1,
        })

    def test_db_exception_500(self):
        db = MagicMock()
        db.get_user_push_subscriptions.side_effect = RuntimeError('boom')
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.get('/api/push/subscriptions')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {'error': 'Internal server error'})


# ── GET /api/plugins ────────────────────────────────────────────────────────

class GetPluginsTest(_AuthedCase):
    def test_via_service(self):
        svc = MagicMock()
        svc.get_all.return_value = [{'name': 'p1'}]
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.get('/api/plugins')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'plugins': [{'name': 'p1'}]})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_fallback_to_database(self):
        db = MagicMock()
        db.get_plugins.return_value = [{'name': 'p2'}]
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', None), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.get('/api/plugins')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'plugins': [{'name': 'p2'}]})


# ── POST /api/plugins ───────────────────────────────────────────────────────

class RegisterPluginTest(_AuthedCase):
    def test_not_admin_403(self):
        svc = MagicMock()
        svc.is_admin.return_value = False
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/plugins', json={'name': 'p'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json(), {'error': 'Admin access required'})

    def test_missing_name_400(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/plugins', json={'name': '   '})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {'error': 'name is required'})

    def test_success_201(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.register.return_value = True
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/plugins', json={'name': 'cool'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {'success': True})

    def test_register_failure_500(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.register.return_value = False
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/plugins', json={'name': 'cool'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {'error': 'Failed to register plugin'})

    def test_admin_via_database_roles(self):
        db = MagicMock()
        db.get_user_roles.return_value = ['admin']
        db.register_plugin.return_value = True
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', None), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.post('/api/plugins', json={'name': 'cool'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {'success': True})


# ── PUT /api/plugins/{plugin_id} ────────────────────────────────────────────

class TogglePluginTest(_AuthedCase):
    def test_not_admin_403(self):
        svc = MagicMock()
        svc.is_admin.return_value = False
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.put('/api/plugins/5', json={'enabled': True})
        self.assertEqual(resp.status_code, 403)

    def test_success(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.toggle.return_value = True
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.put('/api/plugins/5', json={'enabled': False})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})
        svc.toggle.assert_called_once_with(unittest.mock.ANY, 5, False)

    def test_not_found_404(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.toggle.return_value = False
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.put('/api/plugins/5', json={'enabled': True})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Plugin not found'})


# ── DELETE /api/plugins/{plugin_id} ─────────────────────────────────────────

class DeletePluginTest(_AuthedCase):
    def test_not_admin_403(self):
        svc = MagicMock()
        svc.is_admin.return_value = False
        db = MagicMock()
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.delete('/api/plugins/5')
        self.assertEqual(resp.status_code, 403)

    def test_success(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        db = MagicMock()
        db.delete_plugin.return_value = True
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.delete('/api/plugins/5')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})
        db.delete_plugin.assert_called_once_with(unittest.mock.ANY, 5)

    def test_not_found_404(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        db = MagicMock()
        db.delete_plugin.return_value = False
        db.get_db = _fake_db_gen()
        with patch.object(gapi_gui, '_plugin_service', svc), \
                patch.object(gapi_gui, 'database', db):
            resp = self.client.delete('/api/plugins/5')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Plugin not found'})


if __name__ == '__main__':
    unittest.main()
