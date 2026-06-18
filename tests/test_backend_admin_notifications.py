#!/usr/bin/env python3
"""
Tests for the migrated admin send-digests route
(backend/routers/admin_notifications.py). Broadcast is covered by the ported
TestBroadcastNotification in test_permissions_notifprefs.py.

Run with:
    python -m pytest tests/test_backend_admin_notifications.py
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


class BackendSendDigestsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(gapi_gui.user_manager, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()

    def test_requires_admin(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertEqual(resp.status_code, 403)

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertEqual(resp.status_code, 503)

    def test_email_service_not_loaded_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_email_service', None):
            resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertEqual(resp.status_code, 503)

    def test_dry_run_counts_opted_in(self):
        email_svc = SimpleNamespace(is_configured=lambda: True,
                                    send_digest_email=lambda *a, **k: True)
        users = [SimpleNamespace(username='alice'), SimpleNamespace(username='bob')]
        prefs = {'alice': {'email_enabled': True, 'digest_frequency': 'daily'},
                 'bob': {'email_enabled': False, 'digest_frequency': 'never'}}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_email_service', email_svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_all_users', return_value=users), \
             patch.object(gapi_gui.database, 'get_notification_prefs',
                          side_effect=lambda db, u: prefs[u]), \
             patch.object(gapi_gui.database, 'get_user_email',
                          return_value='alice@example.com'), \
             patch.object(gapi_gui, '_is_valid_email_address', return_value=True), \
             patch.object(gapi_gui.database, 'get_notifications',
                          return_value=[{'id': 1}]):
            resp = self.client.post('/api/admin/notifications/send-digests',
                                    json={'period': 'daily', 'dry_run': True})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['dry_run'])
        self.assertEqual(body['sent'], 1)   # alice (opted in)
        self.assertEqual(body['skipped'], 1)  # bob (not opted in)


if __name__ == '__main__':
    unittest.main()
