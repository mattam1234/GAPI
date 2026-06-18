#!/usr/bin/env python3
"""
Tests for the migrated direct-messaging domain (backend/routers/messages.py).

DB-backed: the legacy database DM helpers and DB-availability flags are stubbed.
Verifies conversations, thread fetch, send (validation + success + failure),
the static-vs-param route ordering, and the DB-unavailable graceful path.

Run with:
    python -m pytest tests/test_backend_messages.py
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


class BackendMessagesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        # DB available by default with a throwaway session.
        self._patches = [
            patch.object(gapi_gui, 'DB_AVAILABLE', True),
            patch.object(gapi_gui, 'ensure_db_available', return_value=True),
            patch.object(gapi_gui.database, 'get_db',
                         return_value=iter([MagicMock()])),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        c = TestClient(app)
        self.assertEqual(c.get('/api/messages/conversations').status_code, 401)

    # --- conversations (static route must not be shadowed) --------------

    def test_conversations(self):
        with patch.object(gapi_gui.database, 'get_dm_conversations',
                          return_value=[{'username': 'bob', 'unread': 2}]):
            resp = self.client.get('/api/messages/conversations')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['conversations'][0]['username'], 'bob')

    # --- thread fetch ----------------------------------------------------

    def test_get_thread(self):
        with patch.object(gapi_gui.database, 'get_direct_messages',
                          return_value=[{'sender': 'bob', 'message': 'hi'}]):
            resp = self.client.get('/api/messages/bob')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['messages'][0]['message'], 'hi')

    # --- send ------------------------------------------------------------

    def test_send_requires_message(self):
        resp = self.client.post('/api/messages/bob', json={'message': '   '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Message required', resp.json()['detail'])

    def test_send_success(self):
        created = {'id': 1, 'sender': 'alice', 'message': 'yo'}
        with patch.object(gapi_gui.database, 'create_direct_message',
                          return_value=created):
            resp = self.client.post('/api/messages/bob', json={'message': 'yo'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'message': created})

    def test_send_failure_is_500(self):
        with patch.object(gapi_gui.database, 'create_direct_message',
                          return_value=None):
            resp = self.client.post('/api/messages/bob', json={'message': 'yo'})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to send message', resp.json()['detail'])

    # --- DB-unavailable graceful degradation ----------------------------

    def test_conversations_db_unavailable_empty(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/messages/conversations')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'conversations': []})

    def test_send_db_unavailable_echoes(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.post('/api/messages/bob', json={'message': 'yo'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True,
                          'message': {'sender': 'alice', 'message': 'yo'}})


if __name__ == '__main__':
    unittest.main()
