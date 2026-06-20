#!/usr/bin/env python3
"""Tests for the migrated admin-console routes (admin domain subset):

Discord bot management (@require_admin -> user_manager.is_admin):
  * GET  /api/admin/discord-bot/status | /stats | /config | /users | /diagnostics
  * POST /api/admin/discord-bot/start | /stop | /config | /restart | /users
  * DEL  /api/admin/discord-bot/users/{discord_id}

Moderation + profanity (@require_login + inline _app_settings_service.is_admin):
  * GET  /api/admin/moderation/reports | /profanity-filter
  * POST /api/admin/moderation/action | /profanity-filter

App settings + password reset:
  * GET  /api/admin/settings              (admin)
  * POST /api/admin/settings              (admin)
  * GET  /api/admin/settings/public       (PUBLIC — no auth)
  * GET  /api/admin/password-reset-requests           (admin)
  * POST /api/admin/password-reset-requests/{id}/dismiss (admin)

The discord-bot manager / moderation / settings services are mocked via
patch.object on gapi_gui.* — no real subprocess, no real DB writes.

Run with:
    python -m pytest tests/test_backend_admin_console.py
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


class _AdminUmCase(unittest.TestCase):
    """Logged-in admin via user_manager.is_admin (discord-bot / password-reset)."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(gapi_gui.user_manager, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()


# ───────────────────────────────────────────────────────────────────────────
# Auth gating
# ───────────────────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_discord_status_requires_login(self):
        resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 401)

    def test_discord_status_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 403)

    def test_password_reset_requests_requires_login(self):
        resp = self.client.get('/api/admin/password-reset-requests')
        self.assertEqual(resp.status_code, 401)

    def test_moderation_reports_requires_login(self):
        resp = self.client.get('/api/admin/moderation/reports')
        self.assertEqual(resp.status_code, 401)

    def test_settings_requires_login(self):
        resp = self.client.get('/api/admin/settings')
        self.assertEqual(resp.status_code, 401)

    def test_public_settings_is_unauthenticated(self):
        # PUBLIC route: no cookie, but must NOT 401/403.
        svc = MagicMock()
        svc.get.return_value = 'true'
        with patch.object(gapi_gui, '_app_settings_service', svc):
            resp = self.client.get('/api/admin/settings/public')
        self.assertEqual(resp.status_code, 200)


# ───────────────────────────────────────────────────────────────────────────
# Discord bot management
# ───────────────────────────────────────────────────────────────────────────

class DiscordBotTest(_AdminUmCase):
    def test_status_running(self):
        proc = MagicMock()
        proc.pid = 4321
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=True), \
             patch.object(gapi_gui, '_discord_bot_process', proc), \
             patch.object(gapi_gui, '_discord_bot_log_lines', ['line1', 'line2']):
            resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['running'])
        self.assertEqual(body['pid'], 4321)
        self.assertEqual(body['log'], ['line1', 'line2'])
        self.assertEqual(resp.headers.get('cache-control'), 'no-store')

    def test_status_not_running(self):
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=False):
            resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['running'])
        self.assertIsNone(body['pid'])

    def test_start_success(self):
        proc = MagicMock()
        proc.pid = 999
        with patch.object(gapi_gui, '_validate_repo_config_path', return_value='config.json'), \
             patch.object(gapi_gui, '_start_managed_discord_bot',
                          return_value=(True, proc, '')):
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'started': True, 'pid': 999})

    def test_start_already_running_409(self):
        with patch.object(gapi_gui, '_validate_repo_config_path', return_value='config.json'), \
             patch.object(gapi_gui, '_start_managed_discord_bot',
                          return_value=(False, None, 'Discord bot is already running')):
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'Discord bot is already running')

    def test_start_invalid_config_path_400(self):
        with patch.object(gapi_gui, '_validate_repo_config_path',
                          side_effect=ValueError('Invalid config_path')):
            resp = self.client.post('/api/admin/discord-bot/start',
                                    json={'config_path': '../escape'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid config_path')

    def test_start_failure_500(self):
        with patch.object(gapi_gui, '_validate_repo_config_path', return_value='config.json'), \
             patch.object(gapi_gui, '_start_managed_discord_bot',
                          return_value=(False, None, 'Failed to start bot')):
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 500)

    def test_stop_success(self):
        proc = MagicMock()
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=True), \
             patch.object(gapi_gui, '_discord_bot_process', proc):
            resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'stopped': True})
        proc.terminate.assert_called_once()

    def test_stop_not_running_409(self):
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=False):
            resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'Discord bot is not running')

    def test_stats(self):
        with patch.object(gapi_gui, '_get_discord_linked_users_from_db',
                          return_value=[{'discord_id': '1'}, {'discord_id': '2'}]), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_discord_bot_is_running', return_value=False):
            resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['linked_users'], 2)
        self.assertTrue(body['config_exists'])
        self.assertFalse(body['running'])

    def test_get_config_missing_file(self):
        with patch.object(gapi_gui.os.path, 'exists', return_value=False):
            resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['config_exists'])
        self.assertFalse(body['discord_token_set'])

    def test_get_config_present(self):
        cfg = {'discord_bot_token': 'tok', 'steam_api_key': 'key'}
        m = unittest.mock.mock_open(read_data='{}')
        with patch.object(gapi_gui.os.path, 'exists', return_value=True), \
             patch('builtins.open', m), \
             patch.object(gapi_gui.json, 'load', return_value=cfg):
            resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['config_exists'])
        self.assertTrue(body['discord_token_set'])
        self.assertTrue(body['steam_api_key_set'])

    def test_save_config_requires_a_value(self):
        resp = self.client.post('/api/admin/discord-bot/config', json={})
        self.assertEqual(resp.status_code, 400)

    def test_save_config_success(self):
        m = unittest.mock.mock_open(read_data='{}')
        with patch.object(gapi_gui.os.path, 'exists', return_value=False), \
             patch('builtins.open', m), \
             patch.object(gapi_gui.gapi, '_atomic_write_json') as wj:
            resp = self.client.post('/api/admin/discord-bot/config',
                                    json={'discord_bot_token': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'saved': True})
        wj.assert_called_once()

    def test_restart_success(self):
        proc = MagicMock()
        proc.pid = 77
        with patch.object(gapi_gui, '_validate_repo_config_path', return_value='config.json'), \
             patch.object(gapi_gui, '_discord_bot_is_running', return_value=False), \
             patch.object(gapi_gui, '_start_managed_discord_bot',
                          return_value=(True, proc, '')):
            resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'restarted': True, 'pid': 77})

    def test_restart_invalid_config_400(self):
        with patch.object(gapi_gui, '_validate_repo_config_path',
                          side_effect=ValueError('Invalid config_path')):
            resp = self.client.post('/api/admin/discord-bot/restart',
                                    json={'config_path': '../x'})
        self.assertEqual(resp.status_code, 400)

    def test_restart_start_failure_500(self):
        with patch.object(gapi_gui, '_validate_repo_config_path', return_value='config.json'), \
             patch.object(gapi_gui, '_discord_bot_is_running', return_value=False), \
             patch.object(gapi_gui, '_start_managed_discord_bot',
                          return_value=(False, None, 'boom')):
            resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 500)

    def test_list_users(self):
        users = [{'discord_id': '1', 'steam_id': '2', 'username': 'u'}]
        with patch.object(gapi_gui, '_get_discord_linked_users_from_db',
                          return_value=users):
            resp = self.client.get('/api/admin/discord-bot/users')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'users': users})

    def test_add_user_validation(self):
        resp = self.client.post('/api/admin/discord-bot/users',
                                json={'discord_id': '', 'steam_id': ''})
        self.assertEqual(resp.status_code, 400)
        resp2 = self.client.post('/api/admin/discord-bot/users',
                                 json={'discord_id': 'abc', 'steam_id': '123'})
        self.assertEqual(resp2.status_code, 400)
        self.assertIn('numeric', resp2.json()['error'])

    def test_add_user_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/discord-bot/users',
                                    json={'discord_id': '123', 'steam_id': '456'})
        self.assertEqual(resp.status_code, 503)

    def test_add_user_success(self):
        db = MagicMock()
        user = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db):
            resp = self.client.post('/api/admin/discord-bot/users',
                                    json={'discord_id': '123', 'steam_id': '456'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['saved'])
        self.assertEqual(user.discord_id, '123')

    def test_add_user_not_found_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_user_by_username', return_value=None):
            resp = self.client.post('/api/admin/discord-bot/users',
                                    json={'discord_id': '123', 'steam_id': '456',
                                          'username': 'nope'})
        self.assertEqual(resp.status_code, 404)

    def test_remove_user_success(self):
        db = MagicMock()
        user = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_user_by_discord_id', return_value=user):
            resp = self.client.delete('/api/admin/discord-bot/users/123')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'removed': True})
        self.assertIsNone(user.discord_id)

    def test_remove_user_not_found_404(self):
        db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_user_by_discord_id', return_value=None):
            resp = self.client.delete('/api/admin/discord-bot/users/999')
        self.assertEqual(resp.status_code, 404)

    def test_remove_user_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.delete('/api/admin/discord-bot/users/123')
        self.assertEqual(resp.status_code, 503)

    def test_diagnostics(self):
        with patch.object(gapi_gui.os, 'getenv', return_value=None), \
             patch.object(gapi_gui.os.path, 'exists', return_value=False), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True):
            resp = self.client.get('/api/admin/discord-bot/diagnostics')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['steam_api_key_source'], 'missing')
        self.assertFalse(body['config_file_exists'])
        self.assertIn('python_version', body)


# ───────────────────────────────────────────────────────────────────────────
# Moderation + profanity (login + inline _app_settings_service.is_admin)
# ───────────────────────────────────────────────────────────────────────────

class _ModAdminCase(unittest.TestCase):
    """Logged-in admin via _app_settings_service.is_admin."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self.settings_svc = MagicMock()
        self.settings_svc.is_admin.return_value = True
        self._svc = patch.object(gapi_gui, '_app_settings_service', self.settings_svc)
        self._svc.start()
        # database.get_db yields a closeable mock session.
        self.db = MagicMock()
        self._db = patch.object(gapi_gui.database, 'get_db',
                                return_value=iter([self.db]))

    def tearDown(self):
        self._svc.stop()


class ModerationTest(_ModAdminCase):
    def test_reports_success(self):
        mod = MagicMock()
        mod.get_pending_reports.return_value = {'reports': [], 'total': 0}
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.get('/api/admin/moderation/reports?page=2&limit=5')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['page'], 2)
        mod.get_pending_reports.assert_called_once_with(self.db, 5, 5)

    def test_reports_service_unavailable_503(self):
        with patch.object(gapi_gui, '_moderation_service', None):
            resp = self.client.get('/api/admin/moderation/reports')
        self.assertEqual(resp.status_code, 503)

    def test_reports_forbidden_for_non_admin(self):
        self.settings_svc.is_admin.return_value = False
        mod = MagicMock()
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.get('/api/admin/moderation/reports')
        self.assertEqual(resp.status_code, 403)

    def test_action_success(self):
        mod = MagicMock()
        mod.take_moderation_action.return_value = True
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.post('/api/admin/moderation/action',
                                    json={'report_id': 1, 'action': 'warn'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_action_service_unavailable_503(self):
        with patch.object(gapi_gui, '_moderation_service', None):
            resp = self.client.post('/api/admin/moderation/action', json={})
        self.assertEqual(resp.status_code, 503)


class ProfanityFilterTest(_ModAdminCase):
    def test_get_words(self):
        mod = MagicMock()
        mod.get_profanity_filter.return_value = ['bad']
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.get('/api/admin/profanity-filter')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'words': ['bad']})

    def test_add_word(self):
        mod = MagicMock()
        mod.add_profanity_word.return_value = True
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.post('/api/admin/profanity-filter',
                                    json={'word': 'Bad', 'action': 'add'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        mod.add_profanity_word.assert_called_once()

    def test_remove_word(self):
        mod = MagicMock()
        mod.remove_profanity_word.return_value = True
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.post('/api/admin/profanity-filter',
                                    json={'word': 'bad', 'action': 'remove'})
        self.assertEqual(resp.status_code, 200)
        mod.remove_profanity_word.assert_called_once()

    def test_word_required_400(self):
        mod = MagicMock()
        with patch.object(gapi_gui, '_moderation_service', mod), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.post('/api/admin/profanity-filter', json={'word': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Word required')

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_moderation_service', None):
            resp = self.client.get('/api/admin/profanity-filter')
        self.assertEqual(resp.status_code, 503)


# ───────────────────────────────────────────────────────────────────────────
# App settings + public settings
# ───────────────────────────────────────────────────────────────────────────

class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self.db = MagicMock()

    def test_get_settings_success(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.get_with_meta.return_value = [{'key': 'a', 'value': '1'}]
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db, self.db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.get('/api/admin/settings')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['settings'], [{'key': 'a', 'value': '1'}])

    def test_get_settings_forbidden(self):
        svc = MagicMock()
        svc.is_admin.return_value = False
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='bob'):
            resp = self.client.get('/api/admin/settings')
        self.assertEqual(resp.status_code, 403)

    def test_save_settings_success(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.save.return_value = True
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db, self.db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/settings',
                                    json={'settings': {'announcement': 'hi'}})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_save_settings_validation_400(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/settings', json={'settings': {}})
        self.assertEqual(resp.status_code, 400)

    def test_save_settings_failure_500(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.save.return_value = False
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db, self.db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/settings',
                                    json={'settings': {'a': 'b'}})
        self.assertEqual(resp.status_code, 500)

    def test_public_settings(self):
        svc = MagicMock()
        svc.get.side_effect = lambda db, key, default: {
            'announcement': 'News', 'chat_enabled': 'true',
            'leaderboard_public': 'false', 'plugins_enabled': 'true'}[key]
        with patch.object(gapi_gui, '_app_settings_service', svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([self.db])):
            resp = self.client.get('/api/admin/settings/public')  # no auth
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['announcement'], 'News')
        self.assertTrue(body['chat_enabled'])
        self.assertFalse(body['leaderboard_public'])
        self.assertEqual(resp.headers.get('cache-control'), 'no-store')


# ───────────────────────────────────────────────────────────────────────────
# Password reset requests (@require_admin -> user_manager.is_admin)
# ───────────────────────────────────────────────────────────────────────────

class PasswordResetTest(_AdminUmCase):
    def test_list_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/password-reset-requests')
        self.assertEqual(resp.status_code, 503)

    def test_list_success(self):
        row = MagicMock()
        row.id = 1
        row.username = 'bob'
        row.requested_at = None
        row.status = 'pending'
        row.dismissed_by = None
        row.dismissed_at = None
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [row]
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db):
            resp = self.client.get('/api/admin/password-reset-requests')
        self.assertEqual(resp.status_code, 200)
        reqs = resp.json()['requests']
        self.assertEqual(reqs[0]['id'], 1)
        self.assertEqual(reqs[0]['username'], 'bob')

    def test_dismiss_success(self):
        entry = MagicMock()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = entry
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/password-reset-requests/5/dismiss')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Request dismissed')
        self.assertEqual(entry.status, 'dismissed')

    def test_dismiss_not_found_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/password-reset-requests/99/dismiss')
        self.assertEqual(resp.status_code, 404)

    def test_dismiss_non_int_path_422(self):
        resp = self.client.post('/api/admin/password-reset-requests/abc/dismiss')
        # FastAPI int path validation -> 422 (legacy Flask <int:> -> 404).
        self.assertEqual(resp.status_code, 422)


if __name__ == '__main__':
    unittest.main()
