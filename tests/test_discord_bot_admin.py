#!/usr/bin/env python3
"""
Tests for the Discord bot admin management API endpoints.

Run with:
    python -m pytest tests/test_discord_bot_admin.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


def _make_admin_session(client):
    """Push a fake admin session onto the test client."""
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _patch_admin(monkeypatch=None):
    """Return context patches that grant admin access."""
    return [
        patch.object(gapi_gui.user_manager, 'is_admin', return_value=True),
    ]


class TestDiscordBotStatus(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_status_requires_admin(self):
        """Non-admin users receive 401/403."""
        resp = self.client.get('/api/admin/discord-bot/status')
        self.assertIn(resp.status_code, (401, 403))

    def test_status_returns_not_running_when_no_process(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            # Ensure no process is set
            with patch.object(gapi_gui, '_discord_bot_process', None):
                resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['running'])
        self.assertIsNone(data['pid'])
        self.assertIsInstance(data['log'], list)

    def test_status_reports_running_when_process_alive(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # process still running
        fake_proc.pid = 12345
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', fake_proc):
                resp = self.client.get('/api/admin/discord-bot/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['running'])
        self.assertEqual(data['pid'], 12345)


class TestDiscordBotStart(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_start_requires_admin(self):
        resp = self.client.post('/api/admin/discord-bot/start',
                                json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_start_returns_error_when_already_running(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 9999
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', fake_proc):
                resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 409)
        data = json.loads(resp.data)
        self.assertIn('error', data)

    def test_start_rejects_path_traversal_config(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                resp = self.client.post('/api/admin/discord-bot/start',
                                        json={'config_path': '../../../../etc/passwd'})
        self.assertEqual(resp.status_code, 400)

    def test_start_returns_error_when_script_missing(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                with patch('os.path.exists', return_value=False):
                    resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertIn(resp.status_code, (400, 500))

    def test_start_launches_process(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 5555
        fake_proc.stdout = iter([])
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                with patch('os.path.exists', return_value=True):
                    with patch('subprocess.Popen', return_value=fake_proc) as mock_popen:
                        resp = self.client.post('/api/admin/discord-bot/start', json={})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('started'))
        mock_popen.assert_called_once()


class TestDiscordBotStop(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_stop_requires_admin(self):
        resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertIn(resp.status_code, (401, 403))

    def test_stop_returns_error_when_not_running(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 409)

    def test_stop_terminates_process(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 7777
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', fake_proc):
                resp = self.client.post('/api/admin/discord-bot/stop')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('stopped'))
        fake_proc.terminate.assert_called_once()


class TestDiscordBotStats(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_stats_requires_admin(self):
        resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertIn(resp.status_code, (401, 403))

    def test_stats_returns_zero_linked_users_when_no_config(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=False):
                with patch.object(gapi_gui, '_discord_bot_process', None):
                    resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['linked_users'], 0)
        self.assertFalse(data['config_exists'])

    def test_stats_counts_linked_users_from_config(self):
        fake_config = json.dumps({'user_mappings': {'111': 'steam1', '222': 'steam2'}})
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                with patch('os.path.exists', return_value=True):
                    with patch('builtins.open', unittest.mock.mock_open(read_data=fake_config)):
                        resp = self.client.get('/api/admin/discord-bot/stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['linked_users'], 2)


class TestDiscordBotConfig(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_get_config_requires_admin(self):
        resp = self.client.get('/api/admin/discord-bot/config')
        self.assertIn(resp.status_code, (401, 403))

    def test_post_config_requires_admin(self):
        resp = self.client.post('/api/admin/discord-bot/config', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_get_config_no_file(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=False):
                resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['config_exists'])
        self.assertFalse(data['discord_token_set'])

    def test_get_config_masks_secrets(self):
        fake_cfg = json.dumps({'discord_bot_token': 'secret', 'steam_api_key': 'key'})
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', unittest.mock.mock_open(read_data=fake_cfg)):
                    resp = self.client.get('/api/admin/discord-bot/config')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        # Actual token/key must NOT be exposed
        self.assertNotIn('secret', str(data))
        self.assertNotIn('key', str(data.get('steam_api_key', '')))
        self.assertTrue(data['discord_token_set'])
        self.assertTrue(data['steam_api_key_set'])

    def test_post_config_rejects_empty(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            resp = self.client.post('/api/admin/discord-bot/config', json={})
        self.assertEqual(resp.status_code, 400)

    def test_post_config_saves_token(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', unittest.mock.mock_open(read_data='{}')):
                    with patch.object(gapi_gui.gapi, '_atomic_write_json') as mock_write:
                        resp = self.client.post('/api/admin/discord-bot/config',
                                                json={'discord_bot_token': 'mytoken'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('saved'))
        mock_write.assert_called_once()
        _, written_data = mock_write.call_args[0]
        self.assertEqual(written_data.get('discord_bot_token'), 'mytoken')


if __name__ == '__main__':
    unittest.main()


class TestDiscordBotRestart(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_restart_requires_admin(self):
        resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_restart_rejects_path_traversal(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                resp = self.client.post('/api/admin/discord-bot/restart',
                                        json={'config_path': '../../../../etc/passwd'})
        self.assertEqual(resp.status_code, 400)

    def test_restart_stops_existing_and_starts_new(self):
        old_proc = MagicMock()
        old_proc.poll.return_value = None  # currently running
        old_proc.pid = 1111

        new_proc = MagicMock()
        new_proc.poll.return_value = None
        new_proc.pid = 2222
        new_proc.stdout = iter([])

        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', old_proc):
                with patch('os.path.exists', return_value=True):
                    with patch('subprocess.Popen', return_value=new_proc):
                        resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('restarted'))
        self.assertEqual(data['pid'], 2222)
        old_proc.terminate.assert_called_once()

    def test_restart_when_not_running_still_starts(self):
        new_proc = MagicMock()
        new_proc.poll.return_value = None
        new_proc.pid = 3333
        new_proc.stdout = iter([])

        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch.object(gapi_gui, '_discord_bot_process', None):
                with patch('os.path.exists', return_value=True):
                    with patch('subprocess.Popen', return_value=new_proc):
                        resp = self.client.post('/api/admin/discord-bot/restart', json={})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('restarted'))


class TestDiscordBotUserManagement(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_list_users_requires_admin(self):
        resp = self.client.get('/api/admin/discord-bot/users')
        self.assertIn(resp.status_code, (401, 403))

    def test_remove_user_requires_admin(self):
        resp = self.client.delete('/api/admin/discord-bot/users/12345')
        self.assertIn(resp.status_code, (401, 403))

    def test_list_users_empty_when_no_config(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=False):
                resp = self.client.get('/api/admin/discord-bot/users')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['users'], [])

    def test_list_users_returns_all_mappings(self):
        fake_cfg = json.dumps({'user_mappings': {'111': 'steam_aaa', '222': 'steam_bbb'}})
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', unittest.mock.mock_open(read_data=fake_cfg)):
                    resp = self.client.get('/api/admin/discord-bot/users')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(len(data['users']), 2)
        ids = {u['discord_id'] for u in data['users']}
        self.assertIn('111', ids)
        self.assertIn('222', ids)

    def test_remove_user_not_found(self):
        fake_cfg = json.dumps({'user_mappings': {'111': 'steam_aaa'}})
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', unittest.mock.mock_open(read_data=fake_cfg)):
                    resp = self.client.delete('/api/admin/discord-bot/users/999')
        self.assertEqual(resp.status_code, 404)

    def test_remove_user_success(self):
        fake_cfg = json.dumps({'user_mappings': {'111': 'steam_aaa', '222': 'steam_bbb'}})
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            with self.client.session_transaction() as sess:
                sess['username'] = 'admin'
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', unittest.mock.mock_open(read_data=fake_cfg)):
                    with patch.object(gapi_gui.gapi, '_atomic_write_json') as mock_write:
                        resp = self.client.delete('/api/admin/discord-bot/users/111')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get('removed'))
        mock_write.assert_called_once()
        _, written = mock_write.call_args[0]
        self.assertNotIn('111', written.get('user_mappings', {}))
        self.assertIn('222', written.get('user_mappings', {}))


class TestDiscordBotEnvVar(unittest.TestCase):
    """Verify that discord_bot.py honours the GAPI_DISCORD_CONFIG env var."""

    def test_env_var_used_as_config_path(self):
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'discord_bot.py',
        )
        with open(bot_path, 'r') as fh:
            src = fh.read()
        self.assertIn('GAPI_DISCORD_CONFIG', src,
                      'discord_bot.py should read the GAPI_DISCORD_CONFIG env var')

