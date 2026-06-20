#!/usr/bin/env python3
"""Tests for the migrated chat domain (FastAPI).

Covers all 12 routes under /api/chat:
  * GET    /api/chat/messages
  * POST   /api/chat/send
  * GET    /api/chat/online-users
  * POST   /api/chat/typing
  * GET    /api/chat/typing/{room}
  * POST   /api/chat/update-room
  * GET    /api/chat/room-users
  * POST   /api/chat/invite
  * POST   /api/chat/message/{message_id}/react
  * DELETE /api/chat/message/{message_id}/react
  * PATCH  /api/chat/message/{message_id}
  * DELETE /api/chat/message/{message_id}

Chat state and helpers live on gapi_gui; DB and chat service are mocked so the
tests never touch a real database.

Run with:
    python -m pytest tests/test_backend_chat.py
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


def _fake_db():
    """A MagicMock that satisfies ``next(database.get_db())`` + ``.close()``."""
    return MagicMock()


def _patch_get_db():
    """Patch database.get_db to yield a single fake session."""
    return patch.object(gapi_gui.database, 'get_db', side_effect=lambda: iter([_fake_db()]))


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_messages_requires_login(self):
        self.assertEqual(self.client.get('/api/chat/messages').status_code, 401)

    def test_send_requires_login(self):
        self.assertEqual(
            self.client.post('/api/chat/send', json={'message': 'hi'}).status_code, 401)

    def test_typing_requires_login(self):
        self.assertEqual(
            self.client.post('/api/chat/typing', json={'room': 'general'}).status_code, 401)

    def test_react_requires_login(self):
        self.assertEqual(
            self.client.post('/api/chat/message/1/react', json={'emoji': '👍'}).status_code, 401)

    def test_delete_message_requires_login(self):
        self.assertEqual(self.client.delete('/api/chat/message/1').status_code, 401)


# ── GET /api/chat/messages ──────────────────────────────────────────────────

class MessagesTest(_AuthedCase):
    def test_messages_success(self):
        with patch.object(gapi_gui, '_chat_service', None), \
             patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             patch.object(gapi_gui.database, 'get_chat_messages',
                          return_value=[{'id': 1, 'message': 'hi'}]) as gcm, \
             _patch_get_db():
            resp = self.client.get('/api/chat/messages?room=general&since_id=0&limit=10')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['room'], 'general')
        self.assertEqual(body['messages'], [{'id': 1, 'message': 'hi'}])
        gcm.assert_called_once()
        self.assertEqual(resp.headers.get('cache-control'), 'no-store')

    def test_messages_uses_chat_service_when_present(self):
        svc = MagicMock()
        svc.get_messages.return_value = [{'id': 7}]
        with patch.object(gapi_gui, '_chat_service', svc), \
             patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             _patch_get_db():
            resp = self.client.get('/api/chat/messages?room=general')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['messages'], [{'id': 7}])
        svc.get_messages.assert_called_once()

    def test_messages_private_access_denied(self):
        with patch.object(gapi_gui, '_can_access_chat_room', return_value=False):
            resp = self.client.get('/api/chat/messages?room=secret')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Access denied', resp.json()['error'])


# ── POST /api/chat/send ─────────────────────────────────────────────────────

class SendTest(_AuthedCase):
    def test_send_success(self):
        sent = {'id': 5, 'message': 'hello', 'sender': 'alice'}
        with patch.object(gapi_gui, '_chat_service', None), \
             patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             patch.object(gapi_gui.database, 'send_chat_message', return_value=sent), \
             _patch_get_db():
            resp = self.client.post('/api/chat/send', json={'message': 'hello'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['message'], 'hello')

    def test_send_empty_message_400(self):
        resp = self.client.post('/api/chat/send', json={'message': '   '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('message is required', resp.json()['error'])

    def test_send_too_long_400(self):
        resp = self.client.post('/api/chat/send', json={'message': 'x' * 501})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('500 characters', resp.json()['error'])

    def test_send_access_denied_403(self):
        with patch.object(gapi_gui, '_can_access_chat_room', return_value=False), \
             _patch_get_db():
            resp = self.client.post('/api/chat/send',
                                    json={'message': 'hi', 'room': 'secret'})
        self.assertEqual(resp.status_code, 403)

    def test_send_failure_500(self):
        with patch.object(gapi_gui, '_chat_service', None), \
             patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             patch.object(gapi_gui.database, 'send_chat_message', return_value=None), \
             _patch_get_db():
            resp = self.client.post('/api/chat/send', json={'message': 'hi'})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to send message', resp.json()['error'])

    def test_send_command_failure_propagates_status(self):
        with patch.object(gapi_gui, '_chat_service', None), \
             patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             patch.object(gapi_gui.database, 'send_chat_message', return_value={'id': 1}), \
             patch.object(gapi_gui, '_handle_chat_command',
                          return_value={'ok': False, 'text': 'Bad command', 'status': 409}), \
             _patch_get_db():
            resp = self.client.post('/api/chat/send', json={'message': '/bogus'})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'Bad command')


# ── GET /api/chat/online-users ──────────────────────────────────────────────

class OnlineUsersTest(_AuthedCase):
    def test_online_users(self):
        import time
        now = time.time()
        with patch.object(gapi_gui, 'user_current_room', {'alice': 'general'}), \
             patch.object(gapi_gui, 'user_last_activity', {'alice': now}):
            resp = self.client.get('/api/chat/online-users')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['online_users'], {'general': ['alice']})


# ── POST /api/chat/typing & GET /api/chat/typing/{room} ─────────────────────

class TypingTest(_AuthedCase):
    def test_typing_set(self):
        indicators = {}
        with patch.object(gapi_gui, 'user_typing_indicators', indicators):
            resp = self.client.post('/api/chat/typing',
                                    json={'room': 'general', 'typing': True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertIn('general:alice', indicators)

    def test_get_typing_excludes_self(self):
        import time
        now = time.time()
        indicators = {'general:bob': now, 'general:alice': now}
        with patch.object(gapi_gui, 'user_typing_indicators', indicators):
            resp = self.client.get('/api/chat/typing/general')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['typing'], ['bob'])


# ── POST /api/chat/update-room ──────────────────────────────────────────────

class UpdateRoomTest(_AuthedCase):
    def test_update_room(self):
        rooms = {}
        activity = {}
        with patch.object(gapi_gui, 'user_current_room', rooms), \
             patch.object(gapi_gui, 'user_last_activity', activity):
            resp = self.client.post('/api/chat/update-room', json={'room': 'squad'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['room'], 'squad')
        self.assertEqual(rooms['alice'], 'squad')


# ── GET /api/chat/room-users ────────────────────────────────────────────────

class RoomUsersTest(_AuthedCase):
    def test_room_users_success(self):
        state = {'owner': 'alice', 'is_private': False,
                 'members': {'alice'}, 'invites': set()}
        with patch.object(gapi_gui, '_can_access_chat_room', return_value=True), \
             patch.object(gapi_gui, '_ensure_chat_room', return_value=state):
            resp = self.client.get('/api/chat/room-users?room=general')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['owner'], 'alice')
        self.assertEqual(body['members'], ['alice'])
        self.assertEqual(body['invites'], [])

    def test_room_users_access_denied(self):
        with patch.object(gapi_gui, '_can_access_chat_room', return_value=False):
            resp = self.client.get('/api/chat/room-users?room=secret')
        self.assertEqual(resp.status_code, 403)


# ── POST /api/chat/invite ───────────────────────────────────────────────────

class InviteTest(_AuthedCase):
    def test_invite_success(self):
        with patch.object(gapi_gui, '_invite_to_chat_room',
                          return_value=(True, 'Invited @bob', 'squad')):
            resp = self.client.post('/api/chat/invite',
                                    json={'room': 'squad', 'target_username': 'bob'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_invite_missing_target_400(self):
        resp = self.client.post('/api/chat/invite', json={'room': 'squad'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('target_username is required', resp.json()['error'])

    def test_invite_not_allowed_403(self):
        with patch.object(gapi_gui, '_invite_to_chat_room',
                          return_value=(False, 'Not allowed', 'squad')):
            resp = self.client.post('/api/chat/invite',
                                    json={'room': 'squad', 'target_username': 'bob'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()['ok'])


# ── Reactions ───────────────────────────────────────────────────────────────

class ReactionTest(_AuthedCase):
    def test_add_reaction_success(self):
        with patch.object(gapi_gui.database, 'add_message_reaction', return_value=True), \
             _patch_get_db():
            resp = self.client.post('/api/chat/message/3/react', json={'emoji': '👍'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_add_reaction_missing_emoji_400(self):
        resp = self.client.post('/api/chat/message/3/react', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('emoji is required', resp.json()['error'])

    def test_add_reaction_failure_400(self):
        with patch.object(gapi_gui.database, 'add_message_reaction', return_value=False), \
             _patch_get_db():
            resp = self.client.post('/api/chat/message/3/react', json={'emoji': '👍'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Failed to add reaction', resp.json()['error'])

    def test_remove_reaction_success(self):
        with patch.object(gapi_gui.database, 'remove_message_reaction', return_value=True), \
             _patch_get_db():
            resp = self.client.delete('/api/chat/message/3/react?emoji=%F0%9F%91%8D')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_remove_reaction_missing_emoji_400(self):
        resp = self.client.delete('/api/chat/message/3/react')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('emoji is required', resp.json()['error'])


# ── Edit / Delete message ───────────────────────────────────────────────────

class EditDeleteTest(_AuthedCase):
    def test_edit_success(self):
        with patch.object(gapi_gui.database, 'edit_chat_message', return_value=True), \
             _patch_get_db():
            resp = self.client.patch('/api/chat/message/9', json={'message': 'updated'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_edit_missing_message_400(self):
        resp = self.client.patch('/api/chat/message/9', json={'message': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('message is required', resp.json()['error'])

    def test_edit_too_long_400(self):
        resp = self.client.patch('/api/chat/message/9', json={'message': 'x' * 501})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('500 characters', resp.json()['error'])

    def test_edit_not_owner_403(self):
        with patch.object(gapi_gui.database, 'edit_chat_message', return_value=False), \
             _patch_get_db():
            resp = self.client.patch('/api/chat/message/9', json={'message': 'updated'})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('not found or not owner', resp.json()['error'])

    def test_delete_success(self):
        with patch.object(gapi_gui.database, 'delete_chat_message', return_value=True), \
             _patch_get_db():
            resp = self.client.delete('/api/chat/message/9')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_delete_not_owner_403(self):
        with patch.object(gapi_gui.database, 'delete_chat_message', return_value=False), \
             _patch_get_db():
            resp = self.client.delete('/api/chat/message/9')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('not found or not owner', resp.json()['error'])


if __name__ == '__main__':
    unittest.main()
