#!/usr/bin/env python3
"""
Tests for:
  - Fine-grained Permission System (Tier 2, item 5)
  - Notification Preferences (Tier 2, item 6)
  - Error Rate Dashboard (Tier 3, item 12)

Endpoints tested:
  GET  /api/permissions
  GET  /api/users/<username>/permissions
  POST /api/admin/users/<username>/permissions
  POST /api/admin/roles/bulk-assign
  GET  /api/notifications/preferences
  PUT  /api/notifications/preferences
  GET  /api/notifications/history
  POST /api/admin/notifications/broadcast
  GET  /api/admin/errors/rate

Run with:
    python -m pytest tests/test_permissions_notifprefs.py
"""
import collections
import json
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui
import database


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _set_user_session(client, username='bob'):
    with client.session_transaction() as sess:
        sess['username'] = username


# ---------------------------------------------------------------------------
# GET /api/permissions
# ---------------------------------------------------------------------------

class TestPermissionsList(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_public_endpoint_returns_200(self):
        resp = self.client.get('/api/permissions')
        self.assertEqual(resp.status_code, 200)

    def test_response_contains_permissions_list(self):
        resp = self.client.get('/api/permissions')
        data = json.loads(resp.data)
        self.assertIn('permissions', data)
        self.assertIsInstance(data['permissions'], list)

    def test_response_contains_role_matrix(self):
        resp = self.client.get('/api/permissions')
        data = json.loads(resp.data)
        self.assertIn('role_matrix', data)
        self.assertIsInstance(data['role_matrix'], dict)

    def test_admin_role_has_wildcard(self):
        resp = self.client.get('/api/permissions')
        data = json.loads(resp.data)
        # role_matrix is only populated when DB_AVAILABLE is True
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp2 = self.client.get('/api/permissions')
        data2 = json.loads(resp2.data)
        self.assertIn('admin', data2['role_matrix'])
        self.assertIn('*', data2['role_matrix']['admin'])

    def test_all_permissions_non_empty_when_db_available(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.get('/api/permissions')
        data = json.loads(resp.data)
        self.assertGreater(len(data['permissions']), 0)


# ---------------------------------------------------------------------------
# GET /api/users/<username>/permissions
# ---------------------------------------------------------------------------

class TestGetUserPermissions(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.get('/api/users/alice/permissions')
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/users/alice/permissions')
        self.assertEqual(resp.status_code, 503)

    def test_returns_permission_shape(self):
        fake_perms = {
            'effective': ['analytics_read'],
            'from_roles': ['analytics_read'],
            'granted': [],
            'denied': [],
            'is_admin': False,
        }
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_user_permissions', return_value=fake_perms), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/users/alice/permissions')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        for key in ('effective', 'from_roles', 'granted', 'denied', 'is_admin'):
            self.assertIn(key, data)

    def test_admin_is_admin_flag(self):
        fake_perms = {
            'effective': database.ALL_PERMISSIONS[:],
            'from_roles': database.ALL_PERMISSIONS[:],
            'granted': [],
            'denied': [],
            'is_admin': True,
        }
        mock_db = MagicMock()
        _set_user_session(self.client, 'admin')
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_user_permissions', return_value=fake_perms), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/users/admin/permissions')
        data = json.loads(resp.data)
        self.assertTrue(data['is_admin'])


# ---------------------------------------------------------------------------
# POST /api/admin/users/<username>/permissions
# ---------------------------------------------------------------------------

class TestSetUserPermissions(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/users/alice/permissions',
                                json={'permission': 'analytics_read', 'action': 'grant'})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/users/alice/permissions',
                                        json={'permission': 'analytics_read', 'action': 'grant'})
        self.assertEqual(resp.status_code, 503)

    def test_missing_fields_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/users/alice/permissions', json={})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_action_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post(
                    '/api/admin/users/alice/permissions',
                    json={'permission': 'analytics_read', 'action': 'delete'},
                )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_permission_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post(
                    '/api/admin/users/alice/permissions',
                    json={'permission': 'fly_to_mars', 'action': 'grant'},
                )
        self.assertEqual(resp.status_code, 400)

    def test_grant_succeeds(self):
        mock_db = MagicMock()
        fake_perms = {'effective': ['analytics_read'], 'from_roles': [],
                      'granted': ['analytics_read'], 'denied': [], 'is_admin': False}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.set_user_permission_override', return_value=True), \
                 patch('database.get_user_permissions', return_value=fake_perms), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post(
                    '/api/admin/users/alice/permissions',
                    json={'permission': 'analytics_read', 'action': 'grant'},
                )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['ok'])
        self.assertIn('permissions', data)

    def test_remove_action(self):
        mock_db = MagicMock()
        fake_perms = {'effective': [], 'from_roles': [], 'granted': [], 'denied': [], 'is_admin': False}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.remove_user_permission_override', return_value=True) as mock_fn, \
                 patch('database.get_user_permissions', return_value=fake_perms), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post(
                    '/api/admin/users/alice/permissions',
                    json={'permission': 'analytics_read', 'action': 'remove'},
                )
                mock_fn.assert_called_once()
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# POST /api/admin/roles/bulk-assign
# ---------------------------------------------------------------------------

class TestBulkAssignRole(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/roles/bulk-assign',
                                json={'role': 'vip', 'usernames': ['alice']})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/roles/bulk-assign',
                                        json={'role': 'vip', 'usernames': ['alice']})
        self.assertEqual(resp.status_code, 503)

    def test_missing_role_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/roles/bulk-assign',
                                        json={'usernames': ['alice']})
        self.assertEqual(resp.status_code, 400)

    def test_empty_usernames_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/roles/bulk-assign',
                                        json={'role': 'vip', 'usernames': []})
        self.assertEqual(resp.status_code, 400)

    def test_over_limit_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post(
                    '/api/admin/roles/bulk-assign',
                    json={'role': 'vip', 'usernames': [f'u{i}' for i in range(201)]},
                )
        self.assertEqual(resp.status_code, 400)

    def test_successful_bulk_assign_returns_assigned_list(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui.user_manager, 'update_user_roles', return_value=(True, 'ok')):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/roles/bulk-assign',
                                        json={'role': 'vip', 'usernames': ['alice', 'bob']})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('assigned', data)
        self.assertIn('skipped', data)
        self.assertIn('errors', data)
        self.assertEqual(sorted(data['assigned']), ['alice', 'bob'])

    def test_skipped_when_update_fails(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui.user_manager, 'update_user_roles', return_value=(False, 'not found')):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/roles/bulk-assign',
                                        json={'role': 'vip', 'usernames': ['ghost']})
        data = json.loads(resp.data)
        self.assertEqual(data['assigned'], [])
        self.assertIn('ghost', data['skipped'])


# ---------------------------------------------------------------------------
# GET /api/notifications/preferences
# ---------------------------------------------------------------------------

class TestGetNotificationPrefs(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.get('/api/notifications/preferences')
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/notifications/preferences')
        self.assertEqual(resp.status_code, 503)

    def _fake_prefs(self):
        return {
            'email_enabled': False, 'push_enabled': True,
            'friend_requests': True, 'challenge_updates': True,
            'trade_offers': True, 'team_events': True,
            'system_announcements': True,
            'digest_frequency': 'never',
            'updated_at': '2026-01-01T00:00:00',
        }

    def test_returns_200_with_pref_fields(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notification_prefs', return_value=self._fake_prefs()), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/notifications/preferences')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        for f in ('email_enabled', 'push_enabled', 'digest_frequency'):
            self.assertIn(f, data)

    def test_digest_frequency_default_never(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notification_prefs', return_value=self._fake_prefs()), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/notifications/preferences')
        data = json.loads(resp.data)
        self.assertEqual(data['digest_frequency'], 'never')


# ---------------------------------------------------------------------------
# PUT /api/notifications/preferences
# ---------------------------------------------------------------------------

class TestSetNotificationPrefs(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.put('/api/notifications/preferences', json={'push_enabled': False})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.put('/api/notifications/preferences', json={})
        self.assertEqual(resp.status_code, 503)

    def test_updates_and_returns_prefs(self):
        mock_db = MagicMock()
        updated = {
            'email_enabled': True, 'push_enabled': False,
            'friend_requests': True, 'challenge_updates': True,
            'trade_offers': True, 'team_events': True,
            'system_announcements': True,
            'digest_frequency': 'weekly',
            'updated_at': '2026-03-01T12:00:00',
        }
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.set_notification_prefs', return_value=updated) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.put(
                '/api/notifications/preferences',
                json={'email_enabled': True, 'digest_frequency': 'weekly'},
            )
            args, kwargs = mock_fn.call_args
            # verify the update dict was forwarded
            self.assertIn('email_enabled', args[2] if len(args) > 2 else kwargs.get('updates', {}))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['digest_frequency'], 'weekly')

    def test_db_failure_returns_500(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.set_notification_prefs', return_value={}), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.put('/api/notifications/preferences', json={})
        self.assertEqual(resp.status_code, 500)


# ---------------------------------------------------------------------------
# GET /api/notifications/history
# ---------------------------------------------------------------------------

class TestNotificationHistory(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_login(self):
        resp = self.client.get('/api/notifications/history')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_empty_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/notifications/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['notifications'], [])
        self.assertEqual(data['total'], 0)

    def test_returns_notifications_list_shape(self):
        mock_db = MagicMock()
        fake_notifs = [
            {'id': 1, 'title': 'Hello', 'message': 'World', 'read': False,
             'type': 'info', 'created_at': '2026-01-01T00:00:00'},
        ]
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notifications', return_value=fake_notifs), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/notifications/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('notifications', data)
        self.assertIn('total', data)
        self.assertEqual(data['total'], 1)

    def test_pagination_offset_and_limit(self):
        mock_db = MagicMock()
        fake_notifs = [{'id': i, 'title': f'N{i}', 'message': '',
                        'read': False, 'type': 'info', 'created_at': ''}
                       for i in range(10)]
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notifications', return_value=fake_notifs), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/notifications/history?limit=3&offset=2')
        data = json.loads(resp.data)
        self.assertEqual(data['total'], 10)
        self.assertEqual(len(data['notifications']), 3)

    def test_unread_filter_passed_through(self):
        mock_db = MagicMock()
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_notifications', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/notifications/history?unread=true')
            _, kwargs = mock_fn.call_args
            self.assertTrue(kwargs.get('unread_only', False))


# ---------------------------------------------------------------------------
# POST /api/admin/notifications/broadcast
# ---------------------------------------------------------------------------

class TestBroadcastNotification(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/notifications/broadcast',
                                json={'title': 'hi', 'message': 'there'})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/notifications/broadcast',
                                        json={'title': 'hi', 'message': 'there'})
        self.assertEqual(resp.status_code, 503)

    def test_missing_title_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/notifications/broadcast',
                                        json={'message': 'there'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_message_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/notifications/broadcast',
                                        json={'title': 'hi'})
        self.assertEqual(resp.status_code, 400)

    def test_broadcast_to_all_users(self):
        mock_db = MagicMock()
        mock_user1 = MagicMock(); mock_user1.username = 'alice'
        mock_user2 = MagicMock(); mock_user2.username = 'bob'
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_all_users', return_value=[mock_user1, mock_user2]), \
                 patch('database.create_notification', return_value=True), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/notifications/broadcast',
                                        json={'title': 'hi', 'message': 'there'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['sent'], 2)
        self.assertEqual(data['skipped'], 0)

    def test_broadcast_to_specific_users(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_notification', return_value=True), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post(
                    '/api/admin/notifications/broadcast',
                    json={'title': 'hi', 'message': 'there', 'usernames': ['carol']},
                )
        data = json.loads(resp.data)
        self.assertEqual(data['sent'], 1)

    def test_invalid_type_defaults_to_info(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_notification', return_value=True) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.post(
                    '/api/admin/notifications/broadcast',
                    json={'title': 'hi', 'message': 'there',
                          'type': 'BAD_TYPE', 'usernames': ['x']},
                )
                call_args, call_kwargs = mock_fn.call_args
                # The type argument is positional (index 4) or keyword
                actual_type = (
                    call_kwargs.get('type')
                    or (call_args[4] if len(call_args) > 4 else None)
                    or 'info'
                )
                self.assertEqual(actual_type, 'info')


# ---------------------------------------------------------------------------
# GET /api/admin/errors/rate
# ---------------------------------------------------------------------------

class TestErrorRate(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/errors/rate')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_24_buckets(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/errors/rate')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('buckets', data)
        self.assertEqual(len(data['buckets']), 24)

    def test_buckets_have_hour_and_count(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/errors/rate')
        data = json.loads(resp.data)
        for b in data['buckets']:
            self.assertIn('hour', b)
            self.assertIn('count', b)

    def test_total_keys_present(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/errors/rate')
        data = json.loads(resp.data)
        self.assertIn('total_24h', data)
        self.assertIn('total_all', data)

    def test_recent_errors_counted_in_24h(self):
        recent_ts = datetime.utcnow().isoformat()
        old_ts = (datetime.utcnow() - timedelta(hours=30)).isoformat()
        fake_errors = collections.deque([
            {'timestamp': recent_ts, 'message': 'err1'},
            {'timestamp': recent_ts, 'message': 'err2'},
            {'timestamp': old_ts, 'message': 'old err'},
        ], maxlen=200)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, '_client_errors', fake_errors), \
                 patch.object(gapi_gui, '_client_errors_lock', threading.Lock()):
                resp = self.client.get('/api/admin/errors/rate')
        data = json.loads(resp.data)
        self.assertEqual(data['total_24h'], 2)
        self.assertEqual(data['total_all'], 3)

    def test_empty_buffer_returns_zeros(self):
        fake_errors = collections.deque([], maxlen=200)
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, '_client_errors', fake_errors), \
                 patch.object(gapi_gui, '_client_errors_lock', threading.Lock()):
                resp = self.client.get('/api/admin/errors/rate')
        data = json.loads(resp.data)
        self.assertEqual(data['total_24h'], 0)
        self.assertEqual(data['total_all'], 0)
        self.assertTrue(all(b['count'] == 0 for b in data['buckets']))


# ---------------------------------------------------------------------------
# Unit tests for database helpers
# ---------------------------------------------------------------------------

class TestDatabasePermissionHelpers(unittest.TestCase):
    """Test permission helpers against an in-memory SQLite DB."""

    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        eng = create_engine('sqlite:///:memory:', echo=False)
        database.Base.metadata.create_all(bind=eng)
        Session = sessionmaker(bind=eng)
        db = Session()
        # Ensure roles exist
        for role_name in ['admin', 'user', 'moderator', 'creator', 'vip']:
            database.ensure_role(db, role_name)
        return eng, db

    def test_get_user_permissions_empty_when_no_user(self):
        _, db = self._make_db()
        result = database.get_user_permissions(db, 'nobody')
        self.assertEqual(result['effective'], [])
        db.close()

    def test_get_user_permissions_returns_dict_when_db_none(self):
        result = database.get_user_permissions(None, 'alice')
        self.assertEqual(result['effective'], [])

    def test_has_permission_false_when_db_none(self):
        self.assertFalse(database.has_permission(None, 'alice', 'analytics_read'))

    def test_admin_user_is_admin_flag(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'admin_u', password='x', role='admin')
        result = database.get_user_permissions(db, 'admin_u')
        self.assertTrue(result['is_admin'])
        db.close()

    def test_regular_user_gets_analytics_read(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'reg_user', password='x', role='user')
        result = database.get_user_permissions(db, 'reg_user')
        self.assertIn('analytics_read', result['effective'])
        db.close()

    def test_set_permission_override_grant(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'plain', password='x', role='user')
        ok = database.set_user_permission_override(db, 'plain', 'stream', granted=True, granted_by='admin')
        self.assertTrue(ok)
        result = database.get_user_permissions(db, 'plain')
        self.assertIn('stream', result['effective'])
        self.assertIn('stream', result['granted'])
        db.close()

    def test_set_permission_override_deny(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'plain2', password='x', role='user')
        ok = database.set_user_permission_override(db, 'plain2', 'analytics_read', granted=False)
        self.assertTrue(ok)
        result = database.get_user_permissions(db, 'plain2')
        self.assertNotIn('analytics_read', result['effective'])
        self.assertIn('analytics_read', result['denied'])
        db.close()

    def test_remove_permission_override(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'plain3', password='x', role='user')
        database.set_user_permission_override(db, 'plain3', 'stream', granted=True)
        database.remove_user_permission_override(db, 'plain3', 'stream')
        result = database.get_user_permissions(db, 'plain3')
        self.assertNotIn('stream', result['granted'])
        db.close()

    def test_has_permission_true_for_granted(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'perm_user', password='x', role='user')
        database.set_user_permission_override(db, 'perm_user', 'stream', granted=True)
        self.assertTrue(database.has_permission(db, 'perm_user', 'stream'))
        db.close()

    def test_has_permission_false_for_denied(self):
        _, db = self._make_db()
        database.create_or_update_user(db, 'deny_user', password='x', role='user')
        database.set_user_permission_override(db, 'deny_user', 'analytics_read', granted=False)
        self.assertFalse(database.has_permission(db, 'deny_user', 'analytics_read'))
        db.close()


class TestDatabaseNotificationPrefHelpers(unittest.TestCase):
    """Test notification preference helpers against an in-memory SQLite DB."""

    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        eng = create_engine('sqlite:///:memory:', echo=False)
        database.Base.metadata.create_all(bind=eng)
        Session = sessionmaker(bind=eng)
        return eng, Session()

    def test_get_prefs_creates_defaults(self):
        _, db = self._make_db()
        prefs = database.get_notification_prefs(db, 'alice')
        self.assertIn('email_enabled', prefs)
        self.assertIn('push_enabled', prefs)
        self.assertEqual(prefs['digest_frequency'], 'never')
        db.close()

    def test_get_prefs_returns_empty_when_db_none(self):
        result = database.get_notification_prefs(None, 'alice')
        self.assertEqual(result, {})

    def test_set_prefs_updates_values(self):
        _, db = self._make_db()
        database.get_notification_prefs(db, 'alice')  # create defaults
        updated = database.set_notification_prefs(
            db, 'alice', {'email_enabled': True, 'digest_frequency': 'daily'}
        )
        self.assertTrue(updated['email_enabled'])
        self.assertEqual(updated['digest_frequency'], 'daily')
        db.close()

    def test_set_prefs_ignores_unknown_fields(self):
        _, db = self._make_db()
        # Should not raise
        updated = database.set_notification_prefs(db, 'alice', {'fly_to_mars': True})
        self.assertIn('email_enabled', updated)
        db.close()

    def test_set_prefs_invalid_digest_frequency_ignored(self):
        _, db = self._make_db()
        updated = database.set_notification_prefs(
            db, 'alice', {'digest_frequency': 'hourly'}
        )
        # Invalid value should be ignored, default remains
        self.assertEqual(updated.get('digest_frequency', 'never'), 'never')
        db.close()

    def test_set_prefs_returns_empty_when_db_none(self):
        result = database.set_notification_prefs(None, 'alice', {})
        self.assertEqual(result, {})

    def test_prefs_persist_across_calls(self):
        _, db = self._make_db()
        database.set_notification_prefs(db, 'alice', {'push_enabled': False})
        prefs = database.get_notification_prefs(db, 'alice')
        self.assertFalse(prefs['push_enabled'])
        db.close()


if __name__ == '__main__':
    unittest.main()
