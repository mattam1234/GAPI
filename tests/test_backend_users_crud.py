#!/usr/bin/env python3
"""Tests for the migrated core user-management routes (users domain chunk 5):

  * POST   /api/users/add | /update | /remove   (multi-user picker, admin)
  * POST   /api/users/role | /roles             (user_manager, admin)
  * DELETE /api/users/delete/{username}          (user_manager, admin)
  * GET    /api/roles                            (admin)
  * GET    /api/users/list                       (login; real pick/vote stats)
  * GET    /api/users/{username}/profile         (login; 404 / real stats)
  * POST   /api/user/profile                     (login)

Run with:
    python -m pytest tests/test_backend_users_crud.py
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


class _AuthedCase(unittest.TestCase):
    """Logged-in, admin-by-default client."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(gapi_gui.user_manager, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_admin_route_requires_login(self):
        # No session cookie -> 401 from require_login.
        resp = self.client.post('/api/users/role', json={'username': 'x', 'role': 'y'})
        self.assertEqual(resp.status_code, 401)

    def test_admin_route_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.post('/api/users/role',
                                    json={'username': 'x', 'role': 'y'})
        self.assertEqual(resp.status_code, 403)

    def test_login_route_requires_login(self):
        resp = self.client.get('/api/users/list')
        self.assertEqual(resp.status_code, 401)


# ── Multi-user picker CRUD (add / update / remove) ──────────────────────────

class MultiPickerCrudTest(_AuthedCase):
    def test_add_user_success(self):
        picker = MagicMock()
        picker.add_user.return_value = True
        picker.users = [{'name': 'Bob', 'platforms': {'steam': '123'}}]
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/add',
                                    json={'name': 'Bob', 'steam_id': '123'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['user']['name'], 'Bob')
        picker.load_users.assert_called_once()

    def test_add_user_requires_steam_id(self):
        with patch.object(gapi_gui, 'multi_picker', MagicMock()):
            resp = self.client.post('/api/users/add', json={'name': 'Bob'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Steam ID', resp.json()['error'])

    def test_add_user_already_exists(self):
        picker = MagicMock()
        picker.add_user.return_value = False
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/add',
                                    json={'name': 'Bob', 'steam_id': '123'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'User already exists')

    def test_add_user_no_picker_400(self):
        with patch.object(gapi_gui, 'multi_picker', None):
            resp = self.client.post('/api/users/add',
                                    json={'name': 'Bob', 'steam_id': '123'})
        self.assertEqual(resp.status_code, 400)

    def test_update_user_success(self):
        picker = MagicMock()
        picker.update_user.return_value = True
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/update',
                                    json={'identifier': 'Bob',
                                          'updates': {'email': 'b@x.com'}})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_update_user_not_found_404(self):
        picker = MagicMock()
        picker.update_user.return_value = False
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/update',
                                    json={'identifier': 'Bob',
                                          'updates': {'email': 'b@x.com'}})
        self.assertEqual(resp.status_code, 404)

    def test_update_user_requires_updates(self):
        with patch.object(gapi_gui, 'multi_picker', MagicMock()):
            resp = self.client.post('/api/users/update', json={'identifier': 'Bob'})
        self.assertEqual(resp.status_code, 400)

    def test_remove_user_success(self):
        picker = MagicMock()
        picker.remove_user.return_value = True
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/remove', json={'name': 'Bob'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_remove_user_not_found_404(self):
        picker = MagicMock()
        picker.remove_user.return_value = False
        with patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post('/api/users/remove', json={'name': 'Bob'})
        self.assertEqual(resp.status_code, 404)


# ── Role management (user_manager) ──────────────────────────────────────────

class RoleManagementTest(_AuthedCase):
    def test_update_role_success_passes_admin(self):
        with patch.object(gapi_gui.user_manager, 'update_user_role',
                          return_value=(True, 'Role updated')) as m:
            resp = self.client.post('/api/users/role',
                                    json={'username': 'bob', 'role': 'moderator'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Role updated')
        m.assert_called_once_with('bob', 'moderator', 'admin')

    def test_update_role_missing_fields_400(self):
        resp = self.client.post('/api/users/role', json={'username': 'bob'})
        self.assertEqual(resp.status_code, 400)

    def test_update_role_service_failure_400(self):
        with patch.object(gapi_gui.user_manager, 'update_user_role',
                          return_value=(False, 'Cannot demote last admin')):
            resp = self.client.post('/api/users/role',
                                    json={'username': 'bob', 'role': 'user'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Cannot demote last admin')

    def test_update_roles_requires_list(self):
        resp = self.client.post('/api/users/roles',
                                json={'username': 'bob', 'roles': 'moderator'})
        self.assertEqual(resp.status_code, 400)

    def test_update_roles_success(self):
        with patch.object(gapi_gui.user_manager, 'update_user_roles',
                          return_value=(True, 'Roles updated')) as m:
            resp = self.client.post('/api/users/roles',
                                    json={'username': 'bob',
                                          'roles': ['moderator', 'vip']})
        self.assertEqual(resp.status_code, 200)
        m.assert_called_once_with('bob', ['moderator', 'vip'], 'admin')

    def test_delete_user_success(self):
        with patch.object(gapi_gui.user_manager, 'delete_user',
                          return_value=(True, 'User deleted')) as m:
            resp = self.client.delete('/api/users/delete/bob')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'User deleted')
        m.assert_called_once_with('bob', 'admin')

    def test_delete_user_failure_400(self):
        with patch.object(gapi_gui.user_manager, 'delete_user',
                          return_value=(False, 'Cannot delete yourself')):
            resp = self.client.delete('/api/users/delete/admin')
        self.assertEqual(resp.status_code, 400)


# ── /api/roles ──────────────────────────────────────────────────────────────

class RolesListTest(_AuthedCase):
    def test_list_roles_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/roles')
        self.assertEqual(resp.status_code, 503)

    def test_list_roles_via_database(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_user_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal',
                          return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_roles',
                          return_value=['admin', 'user']):
            resp = self.client.get('/api/roles')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['roles'], ['admin', 'user'])


# ── /api/users/list and /{username}/profile (real pick/vote/session stats) ────

class UserListAndProfileTest(_AuthedCase):
    def test_list_users_returns_real_counts(self):
        # Counts come from database.get_user_activity_counts via the ORM layer.
        with patch.object(gapi_gui.user_manager, 'get_all_users',
                          return_value=[{'username': 'a', 'created_at': None}]), \
             patch.object(gapi_gui.database, 'SessionLocal',
                          return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_user_activity_counts',
                          return_value={'picks': 4, 'votes': 7, 'sessions': 2}):
            resp = self.client.get('/api/users/list')
        self.assertEqual(resp.status_code, 200)
        users = resp.json()['users']
        self.assertEqual(users[0]['username'], 'a')
        # /list reports picks/votes from the DB; sessions is fixed at 0.
        self.assertEqual(users[0]['stats'],
                         {'picks': 4, 'votes': 7, 'sessions': 0})

    def test_list_users_error_500(self):
        with patch.object(gapi_gui.user_manager, 'get_all_users',
                          return_value=[{'username': 'a', 'created_at': None}]), \
             patch.object(gapi_gui.database, 'SessionLocal',
                          side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/users/list')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Failed to list users', resp.json()['error'])

    def test_profile_missing_user_404(self):
        with patch.object(gapi_gui.user_manager, 'get_all_users', return_value=[]):
            resp = self.client.get('/api/users/ghost/profile')
        self.assertEqual(resp.status_code, 404)

    def test_profile_existing_user_returns_stats(self):
        with patch.object(gapi_gui.user_manager, 'get_all_users',
                          return_value=[{'username': 'bob', 'created_at': None}]), \
             patch.object(gapi_gui.database, 'SessionLocal',
                          return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_user_activity_counts',
                          return_value={'picks': 12, 'votes': 30, 'sessions': 6}), \
             patch.object(gapi_gui.database, 'get_user_vote_accuracy',
                          return_value=85):
            resp = self.client.get('/api/users/bob/profile')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['username'], 'bob')
        self.assertEqual(body['stats'], {
            'sessions_hosted': 6, 'picks': 12, 'votes': 30, 'accuracy': 85})
        # Derived achievements: 10+ picks, 25+ votes, 5+ sessions, 80+ accuracy.
        names = {a['name'] for a in body['achievements']}
        self.assertIn('First 10 Picks', names)
        self.assertIn('Decision Maker', names)
        self.assertIn('Session Host', names)
        self.assertIn('Voting Legend', names)

    def test_profile_error_500(self):
        with patch.object(gapi_gui.user_manager, 'get_all_users',
                          return_value=[{'username': 'bob', 'created_at': None}]), \
             patch.object(gapi_gui.database, 'SessionLocal',
                          side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/users/bob/profile')
        self.assertEqual(resp.status_code, 500)


# ── POST /api/user/profile ──────────────────────────────────────────────────

class UpdateMyProfileTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('bob'))

    def test_update_profile_success(self):
        with patch.object(gapi_gui, '_leaderboard_service', None), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'update_user_profile',
                          return_value=True) as m:
            resp = self.client.post('/api/user/profile',
                                    json={'display_name': 'Bobby', 'bio': 'hi'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        m.assert_called_once()

    def test_update_profile_failure_500(self):
        with patch.object(gapi_gui, '_leaderboard_service', None), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'update_user_profile',
                          return_value=False):
            resp = self.client.post('/api/user/profile', json={'bio': 'x'})
        self.assertEqual(resp.status_code, 500)

    def test_update_profile_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/user/profile', json={'bio': 'x'})
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
