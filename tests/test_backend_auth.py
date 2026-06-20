#!/usr/bin/env python3
"""Tests for the migrated auth + setup domain (backend/routers/auth.py).

The headline test is the **session seam**: POST /api/auth/login must set a Flask
session cookie that authenticates a follow-up request via require_login.

Run with:
    python -m pytest tests/test_backend_auth.py
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
    return gapi_gui.app.session_interface.get_signing_serializer(
        gapi_gui.app).dumps({'username': username})


class AuthCurrentTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_anon_401(self):
        resp = self.client.get('/api/auth/current')
        self.assertEqual(resp.status_code, 401)
        self.assertIsNone(resp.json()['username'])

    def test_logged_in(self):
        self.client.cookies.set('session', _session_cookie('alice'))
        with patch.object(gapi_gui.user_manager, 'get_user_role', return_value='admin'):
            resp = self.client.get('/api/auth/current')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['username'], 'alice')
        self.assertEqual(body['role'], 'admin')
        self.assertEqual(body['roles'], ['admin'])


class LoginSessionSeamTest(unittest.TestCase):
    """The critical seam: a login here must authenticate FastAPI require_login."""

    def setUp(self):
        self.client = TestClient(app)

    def test_login_missing_fields_400(self):
        resp = self.client.post('/api/auth/login', json={'username': 'a'})
        self.assertEqual(resp.status_code, 400)

    def test_login_bad_credentials_401(self):
        with patch.object(gapi_gui.user_manager, 'login',
                          return_value=(False, 'Invalid credentials')), \
             patch.object(gapi_gui, '_audit', lambda *a, **k: None):
            resp = self.client.post('/api/auth/login',
                                    json={'username': 'a', 'password': 'x'})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error'], 'Invalid credentials')

    def test_login_sets_cookie_that_authenticates(self):
        with patch.object(gapi_gui.user_manager, 'login', return_value=(True, 'ok')), \
             patch.object(gapi_gui.user_manager, 'get_user_ids', return_value={}), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False), \
             patch.object(gapi_gui, '_audit', lambda *a, **k: None):
            resp = self.client.post('/api/auth/login',
                                    json={'username': 'bob', 'password': 'pw'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'bob')
        self.assertIn('session', resp.cookies)  # Set-Cookie present

        # The TestClient now holds the cookie; a require_login route must accept it.
        with patch.object(gapi_gui.user_manager, 'get_user_role', return_value='user'):
            who = self.client.get('/api/auth/current')
        self.assertEqual(who.status_code, 200)
        self.assertEqual(who.json()['username'], 'bob')

    def test_login_no_steam_id_skips_sync_thread(self):
        with patch.object(gapi_gui.user_manager, 'login', return_value=(True, 'ok')), \
             patch.object(gapi_gui.user_manager, 'get_user_ids', return_value={}), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False), \
             patch.object(gapi_gui, '_audit', lambda *a, **k: None), \
             patch('backend.routers.auth.threading.Thread') as thread:
            self.client.post('/api/auth/login', json={'username': 'b', 'password': 'p'})
        thread.assert_not_called()


class LogoutTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_logout_clears_cookie_and_resets_pickers(self):
        with patch.object(gapi_gui, '_audit', lambda *a, **k: None):
            resp = self.client.post('/api/auth/logout')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(gapi_gui.picker)
        self.assertIsNone(gapi_gui.multi_picker)


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_missing_fields_400(self):
        resp = self.client.post('/api/auth/register', json={'username': 'a'})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_email_400(self):
        with patch.object(gapi_gui, '_is_valid_email_address', return_value=False):
            resp = self.client.post('/api/auth/register',
                                    json={'username': 'a', 'password': 'pw',
                                          'email': 'bad'})
        self.assertEqual(resp.status_code, 400)

    def test_register_success(self):
        with patch.object(gapi_gui.user_manager, 'register', return_value=(True, 'Registered')), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/auth/register',
                                    json={'username': 'a', 'password': 'pw'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Registered')

    def test_register_failure_400(self):
        with patch.object(gapi_gui.user_manager, 'register',
                          return_value=(False, 'Username taken')):
            resp = self.client.post('/api/auth/register',
                                    json={'username': 'a', 'password': 'pw'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Username taken')


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_status_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/setup/status')
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.json()['needs_setup'])

    def test_status_needs_setup_true_when_no_users(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_user_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_user_count', return_value=0):
            resp = self.client.get('/api/setup/status')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['needs_setup'])

    def test_initial_admin_conflict_when_users_exist(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_user_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_user_count', return_value=3):
            resp = self.client.post('/api/setup/initial-admin',
                                    json={'username': 'admin', 'password': 'pw'})
        self.assertEqual(resp.status_code, 409)

    def test_initial_admin_created_201(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_user_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_user_count', return_value=0), \
             patch.object(gapi_gui.database, 'create_or_update_user',
                          return_value=MagicMock()):
            resp = self.client.post('/api/setup/initial-admin',
                                    json={'username': 'admin', 'password': 'pw'})
        self.assertEqual(resp.status_code, 201)


class UpdateAndGetIdsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_update_ids_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/auth/update-ids', json={'steam_id': '1'})
        self.assertEqual(resp.status_code, 401)

    def test_update_ids_failure_400(self):
        with patch.object(gapi_gui.user_manager, 'update_user_ids', return_value=False):
            resp = self.client.post('/api/auth/update-ids', json={'steam_id': '1'})
        self.assertEqual(resp.status_code, 400)

    def test_update_ids_discord_non_numeric_400(self):
        with patch.object(gapi_gui.user_manager, 'update_user_ids', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/auth/update-ids',
                                    json={'discord_id': 'abc'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('numeric', resp.json()['error'])

    def test_update_ids_success(self):
        with patch.object(gapi_gui.user_manager, 'update_user_ids', return_value=True), \
             patch.object(gapi_gui.user_manager, 'get_user_ids', return_value={}), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/auth/update-ids', json={'epic_id': 'e1'})
        self.assertEqual(resp.status_code, 200)

    def test_get_ids_requires_login(self):
        client = TestClient(app)
        resp = client.get('/api/auth/get-ids')
        self.assertEqual(resp.status_code, 401)

    def test_get_ids_success(self):
        with patch.object(gapi_gui.user_manager, 'get_user_ids',
                          return_value={'steam_id': 's1', 'discord_id': ''}), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/auth/get-ids')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['steam_id'], 's1')


class ChangePasswordTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/auth/change-password',
                           json={'current_password': 'a', 'new_password': 'bbbbbb'})
        self.assertEqual(resp.status_code, 401)

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/auth/change-password',
                                    json={'current_password': 'a',
                                          'new_password': 'bbbbbb'})
        self.assertEqual(resp.status_code, 503)

    def test_short_new_password_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/auth/change-password',
                                    json={'current_password': 'a', 'new_password': '123'})
        self.assertEqual(resp.status_code, 400)

    def test_wrong_current_password_401(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'verify_user_password', return_value=False):
            resp = self.client.post('/api/auth/change-password',
                                    json={'current_password': 'wrong',
                                          'new_password': 'bbbbbb'})
        self.assertEqual(resp.status_code, 401)

    def test_change_password_success(self):
        user = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'verify_user_password', return_value=True), \
             patch.object(gapi_gui.database, 'get_user_by_username', return_value=user), \
             patch.object(gapi_gui.database, 'hash_password', return_value='hashed'):
            resp = self.client.post('/api/auth/change-password',
                                    json={'current_password': 'old',
                                          'new_password': 'bbbbbb'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Password changed successfully')


if __name__ == '__main__':
    unittest.main()
