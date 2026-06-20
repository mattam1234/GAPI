#!/usr/bin/env python3
"""
Tests for the Discord bot admin management API endpoints.

The HTTP routes were migrated from Flask to FastAPI
(backend/routers/admin_console.py); these route-hitting tests have been
repointed to the FastAPI ``TestClient`` accordingly. Auth is now a signed
session cookie (decoded by the FastAPI dependency from the same Flask secret)
plus a patched ``user_manager.is_admin`` (the ``@require_admin`` equivalent).

The helper-level tests (autostart, env-var contract) call ``gapi_gui`` helpers /
read ``discord_bot.py`` directly and are unaffected by the migration.

Run with:
    python -m pytest tests/test_discord_bot_admin.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _RouteCase(unittest.TestCase):
    """FastAPI TestClient logged in as admin (user_manager.is_admin patched)."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(gapi_gui.user_manager, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()

    def _anon(self):
        c = TestClient(app)
        return c


class TestDiscordBotStatus(_RouteCase):

    def test_status_requires_admin(self):
        resp = self._anon().get('/api/admin/discord-bot/status')
        self.assertIn(resp.status_code, (401, 403))

    def test_status_returns_not_running_when_no_process(self):
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=False), \
             patch.object(gapi_gui, '_discord_bot_process', None):
            resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['running'])
        self.assertIsNone(data['pid'])
        self.assertIsInstance(data['log'], list)

    def test_status_reports_running_when_process_alive(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 12345
        with patch.object(gapi_gui, '_discord_bot_is_running', return_value=True), \
             patch.object(gapi_gui, '_discord_bot_process', fake_proc):
            resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['running'])
        self.assertEqual(data['pid'], 12345)


class TestDiscordBotStart(_RouteCase):

    def test_start_requires_admin(self):
        resp = self._anon().post('/api/admin/discord-bot/start', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_start_returns_error_when_already_running(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 9999
        with patch.object(gapi_gui, '_discord_bot_process', fake_proc):
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 409)
        self.assertIn('error', resp.json())

    def test_start_rejects_path_traversal_config(self):
        with patch.object(gapi_gui, '_discord_bot_process', None):
            resp = self.client.post('/api/admin/discord-bot/start',
                                    json={'config_path': '../../../../etc/passwd'})
        self.assertEqual(resp.status_code, 400)

    def test_start_returns_error_when_script_missing(self):
        with patch.object(gapi_gui, '_discord_bot_process', None), \
             patch('os.path.exists', return_value=False):
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertIn(resp.status_code, (400, 500))

    def test_start_launches_process(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 5555
        fake_proc.stdout = iter([])
        with patch.object(gapi_gui, '_discord_bot_process', None), \
             patch('os.path.exists', return_value=True), \
             patch('subprocess.Popen', return_value=fake_proc) as mock_popen:
            resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('started'))
        mock_popen.assert_called_once()
        _, kwargs = mock_popen.call_args
        self.assertEqual(kwargs.get('cwd'),
                         os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertTrue(os.path.isabs(kwargs['env']['GAPI_DISCORD_CONFIG']))


class TestDiscordBotAutostart(unittest.TestCase):

    def test_token_configured_reads_env_override(self):
        with patch.dict(os.environ, {'DISCORD_BOT_TOKEN': 'secret-token'}, clear=False):
            self.assertTrue(gapi_gui._discord_bot_token_configured('/does/not/matter.json'))

    def test_autostart_uses_config_token(self):
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.json') as fh:
            json.dump({'discord_bot_token': 'configured-token'}, fh)
            config_path = fh.name
        try:
            with patch.object(gapi_gui, '_start_managed_discord_bot',
                              return_value=(True, MagicMock(pid=1234), '')) as mock_start:
                gapi_gui._auto_start_discord_bot_if_configured(config_path)
            mock_start.assert_called_once_with(config_path)
        finally:
            os.unlink(config_path)


class TestDiscordBotStop(_RouteCase):

    def test_stop_requires_admin(self):
        resp = self._anon().post('/api/admin/discord-bot/stop')
        self.assertIn(resp.status_code, (401, 403))

    def test_stop_returns_error_when_not_running(self):
        with patch.object(gapi_gui, '_discord_bot_process', None):
            resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 409)

    def test_stop_terminates_process(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 7777
        with patch.object(gapi_gui, '_discord_bot_process', fake_proc):
            resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('stopped'))
        fake_proc.terminate.assert_called_once()


class TestDiscordBotStats(_RouteCase):

    def test_stats_requires_admin(self):
        resp = self._anon().get('/api/admin/discord-bot/stats')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_returns_zero_linked_users_when_no_db_links(self):
        with patch.object(gapi_gui, '_get_discord_linked_users_from_db', return_value=[]), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=False), \
             patch.object(gapi_gui, '_discord_bot_process', None):
            resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['linked_users'], 0)
        self.assertFalse(data['config_exists'])

    def test_stats_counts_linked_users_from_db(self):
        with patch.object(gapi_gui, '_discord_bot_process', None), \
             patch.object(gapi_gui, '_get_discord_linked_users_from_db', return_value=[
                 {'discord_id': '111', 'steam_id': 'steam1', 'username': 'alice'},
                 {'discord_id': '222', 'steam_id': 'steam2', 'username': 'bob'},
             ]), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True):
            resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['linked_users'], 2)


class TestDiscordBotConfig(_RouteCase):

    def test_get_config_requires_admin(self):
        resp = self._anon().get('/api/admin/discord-bot/config')
        self.assertIn(resp.status_code, (401, 403))

    def test_post_config_requires_admin(self):
        resp = self._anon().post('/api/admin/discord-bot/config', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_get_config_no_file(self):
        with patch('os.path.exists', return_value=False):
            resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['config_exists'])
        self.assertFalse(data['discord_token_set'])

    def test_get_config_masks_secrets(self):
        fake_cfg = json.dumps({'discord_bot_token': 'secret', 'steam_api_key': 'key'})
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data=fake_cfg)):
            resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn('secret', str(data))
        self.assertNotIn('key', str(data.get('steam_api_key', '')))
        self.assertTrue(data['discord_token_set'])
        self.assertTrue(data['steam_api_key_set'])

    def test_post_config_rejects_empty(self):
        resp = self.client.post('/api/admin/discord-bot/config', json={})
        self.assertEqual(resp.status_code, 400)

    def test_post_config_saves_token(self):
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data='{}')), \
             patch.object(gapi_gui.gapi, '_atomic_write_json') as mock_write:
            resp = self.client.post('/api/admin/discord-bot/config',
                                    json={'discord_bot_token': 'mytoken'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('saved'))
        mock_write.assert_called_once()
        _, written_data = mock_write.call_args[0]
        self.assertEqual(written_data.get('discord_bot_token'), 'mytoken')


class TestDiscordBotRestart(_RouteCase):

    def test_restart_requires_admin(self):
        resp = self._anon().post('/api/admin/discord-bot/restart', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_restart_rejects_path_traversal(self):
        with patch.object(gapi_gui, '_discord_bot_process', None):
            resp = self.client.post('/api/admin/discord-bot/restart',
                                    json={'config_path': '../../../../etc/passwd'})
        self.assertEqual(resp.status_code, 400)

    def test_restart_stops_existing_and_starts_new(self):
        old_proc = MagicMock()
        old_proc.poll.return_value = None
        old_proc.pid = 1111

        new_proc = MagicMock()
        new_proc.poll.return_value = None
        new_proc.pid = 2222
        new_proc.stdout = iter([])

        with patch.object(gapi_gui, '_discord_bot_process', old_proc), \
             patch('os.path.exists', return_value=True), \
             patch('subprocess.Popen', return_value=new_proc):
            resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('restarted'))
        self.assertEqual(data['pid'], 2222)
        old_proc.terminate.assert_called_once()

    def test_restart_when_not_running_still_starts(self):
        new_proc = MagicMock()
        new_proc.poll.return_value = None
        new_proc.pid = 3333
        new_proc.stdout = iter([])

        with patch.object(gapi_gui, '_discord_bot_process', None), \
             patch('os.path.exists', return_value=True), \
             patch('subprocess.Popen', return_value=new_proc):
            resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('restarted'))


class TestDiscordBotUserManagement(_RouteCase):

    def test_list_users_requires_admin(self):
        resp = self._anon().get('/api/admin/discord-bot/users')
        self.assertIn(resp.status_code, (401, 403))

    def test_remove_user_requires_admin(self):
        resp = self._anon().delete('/api/admin/discord-bot/users/12345')
        self.assertIn(resp.status_code, (401, 403))

    def test_list_users_empty_when_no_db_rows(self):
        with patch.object(gapi_gui, '_get_discord_linked_users_from_db', return_value=[]):
            resp = self.client.get('/api/admin/discord-bot/users')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['users'], [])

    def test_list_users_returns_all_db_links(self):
        with patch.object(gapi_gui, '_get_discord_linked_users_from_db', return_value=[
            {'discord_id': '111', 'steam_id': 'steam_aaa', 'username': 'alice'},
            {'discord_id': '222', 'steam_id': 'steam_bbb', 'username': 'bob'},
        ]):
            resp = self.client.get('/api/admin/discord-bot/users')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['users']), 2)
        ids = {u['discord_id'] for u in data['users']}
        self.assertIn('111', ids)
        self.assertIn('222', ids)

    def test_remove_user_not_found(self):
        fake_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=fake_db), \
             patch.object(gapi_gui.database, 'get_user_by_discord_id', return_value=None):
            resp = self.client.delete('/api/admin/discord-bot/users/999')
        self.assertEqual(resp.status_code, 404)

    def test_remove_user_success(self):
        fake_db = MagicMock()
        fake_user = MagicMock()
        fake_user.discord_id = '111'
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=fake_db), \
             patch.object(gapi_gui.database, 'get_user_by_discord_id', return_value=fake_user):
            resp = self.client.delete('/api/admin/discord-bot/users/111')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('removed'))
        self.assertIsNone(fake_user.discord_id)
        fake_db.commit.assert_called_once()


class TestDiscordBotEnvVar(unittest.TestCase):
    """Verify that discord_bot.py honours the GAPI_DISCORD_CONFIG env var."""

    def test_env_var_used_as_config_path(self):
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'discord_bot.py',
        )
        with open(bot_path, 'r', encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('GAPI_DISCORD_CONFIG', src,
                      'discord_bot.py should read the GAPI_DISCORD_CONFIG env var')

    def test_env_var_used_as_discord_token(self):
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'discord_bot.py',
        )
        with open(bot_path, 'r', encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('DISCORD_BOT_TOKEN', src,
                      'discord_bot.py should read the DISCORD_BOT_TOKEN env var')


if __name__ == '__main__':
    unittest.main()
