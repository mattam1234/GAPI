#!/usr/bin/env python3
"""Tests for the migrated "remainder" routes (library / users / multiuser):

  * GET  /api/library                     (cached library + demo fallback)
  * POST /api/library/sync                (manual sync trigger)
  * GET  /api/library/sync/settings       (admin)
  * POST /api/library/sync/settings       (admin)
  * GET  /api/library/sync/status         (per-user status; 503 no-DB)
  * GET  /api/users                       (multi-user picker list, scope filter)
  * GET  /api/users/all                   (admin)
  * GET  /api/users/online                (login)
  * GET  /api/multiuser/common            (login)
  * GET  /api/multiuser/stats             (login)

Run with:
    python -m pytest tests/test_backend_remainders.py
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
    """Logged-in, admin-by-default client (user 'admin')."""

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

    def test_library_requires_login(self):
        self.assertEqual(self.client.get('/api/library').status_code, 401)

    def test_library_sync_requires_login(self):
        self.assertEqual(self.client.post('/api/library/sync').status_code, 401)

    def test_sync_settings_requires_login(self):
        self.assertEqual(self.client.get('/api/library/sync/settings').status_code, 401)

    def test_sync_status_requires_login(self):
        self.assertEqual(self.client.get('/api/library/sync/status').status_code, 401)

    def test_users_requires_login(self):
        self.assertEqual(self.client.get('/api/users').status_code, 401)

    def test_users_all_requires_login(self):
        self.assertEqual(self.client.get('/api/users/all').status_code, 401)

    def test_users_online_requires_login(self):
        self.assertEqual(self.client.get('/api/users/online').status_code, 401)

    def test_multiuser_common_requires_login(self):
        self.assertEqual(self.client.get('/api/multiuser/common').status_code, 401)

    def test_multiuser_stats_requires_login(self):
        self.assertEqual(self.client.get('/api/multiuser/stats').status_code, 401)

    def test_users_all_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.get('/api/users/all')
        self.assertEqual(resp.status_code, 403)

    def test_sync_settings_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.get('/api/library/sync/settings')
        self.assertEqual(resp.status_code, 403)


# ── GET /api/library ────────────────────────────────────────────────────────

class LibraryListTest(_AuthedCase):
    def test_db_unavailable_returns_demo_games(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/library')
        self.assertEqual(resp.status_code, 200)
        games = resp.json()['games']
        self.assertTrue(games)
        # Demo payload shape.
        self.assertIn('game_id', games[0])
        self.assertIn('playtime_hours', games[0])

    def test_empty_cache_triggers_background_sync(self):
        db = MagicMock()
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_library_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_cached_library', return_value=[]), \
             patch.object(gapi_gui, 'sync_library_to_db', return_value=(True, 'ok')):
            resp = self.client.get('/api/library')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['games'], [])
        self.assertIn('message', body)

    def test_cached_library_formats_and_filters(self):
        db = MagicMock()
        cached = [
            {'app_id': 620, 'name': 'Portal 2', 'playtime_hours': 12.34,
             'platform': 'steam'},
            {'app_id': 440, 'name': 'Team Fortress 2', 'playtime_hours': 3.0,
             'platform': 'steam'},
        ]
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_library_service', None), \
             patch.object(gapi_gui, '_db_favorites_service', None), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_cached_library', return_value=cached), \
             patch.object(gapi_gui.database, 'get_library_cache_age', return_value=100), \
             patch.object(gapi_gui.database, 'get_user_favorites', return_value=[620]):
            resp = self.client.get('/api/library?search=portal')
        self.assertEqual(resp.status_code, 200)
        games = resp.json()['games']
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['name'], 'Portal 2')
        self.assertTrue(games[0]['is_favorite'])
        self.assertEqual(games[0]['game_id'], 'steam:620')

    def test_db_error_falls_back_to_demo(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/library')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['games'])


# ── POST /api/library/sync ──────────────────────────────────────────────────

class LibrarySyncTriggerTest(_AuthedCase):
    def test_sync_success(self):
        sched = MagicMock()
        sched.trigger_sync.return_value = (True, 'Sync started')
        with patch.object(gapi_gui, 'sync_scheduler', sched):
            resp = self.client.post('/api/library/sync')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Sync started')

    def test_sync_failure_400(self):
        sched = MagicMock()
        sched.trigger_sync.return_value = (False, 'Already syncing')
        with patch.object(gapi_gui, 'sync_scheduler', sched):
            resp = self.client.post('/api/library/sync')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Already syncing')

    def test_sync_exception_500(self):
        sched = MagicMock()
        sched.trigger_sync.side_effect = RuntimeError('explode')
        with patch.object(gapi_gui, 'sync_scheduler', sched):
            resp = self.client.post('/api/library/sync')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('explode', resp.json()['error'])


# ── GET/POST /api/library/sync/settings (admin) ─────────────────────────────

class LibrarySyncSettingsTest(_AuthedCase):
    def test_get_settings(self):
        sched = MagicMock()
        sched.get_interval.return_value = 24
        sched.last_sync_times = {}
        with patch.object(gapi_gui, 'sync_scheduler', sched):
            resp = self.client.get('/api/library/sync/settings')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['sync_interval_hours'], 24)

    def test_update_settings_requires_interval(self):
        with patch.object(gapi_gui, 'sync_scheduler', MagicMock()):
            resp = self.client.post('/api/library/sync/settings', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('required', resp.json()['error'])

    def test_update_settings_out_of_range(self):
        with patch.object(gapi_gui, 'sync_scheduler', MagicMock()):
            resp = self.client.post('/api/library/sync/settings',
                                    json={'sync_interval_hours': 999})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('between 1 and 168', resp.json()['error'])

    def test_update_settings_invalid_value(self):
        with patch.object(gapi_gui, 'sync_scheduler', MagicMock()):
            resp = self.client.post('/api/library/sync/settings',
                                    json={'sync_interval_hours': 'abc'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid interval value')

    def test_update_settings_success(self):
        sched = MagicMock()
        sched.get_interval.return_value = 12.0
        with patch.object(gapi_gui, 'sync_scheduler', sched):
            resp = self.client.post('/api/library/sync/settings',
                                    json={'sync_interval_hours': 12})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['sync_interval_hours'], 12.0)
        sched.set_interval.assert_called_once_with(12.0)


# ── GET /api/library/sync/status ────────────────────────────────────────────

class LibrarySyncStatusTest(_AuthedCase):
    def test_status_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/library/sync/status')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Database not available')

    def test_status_success(self):
        db = MagicMock()
        sched = MagicMock()
        sched.get_interval.return_value = 24
        sched.should_sync.return_value = False
        sched.in_progress = set()
        sched.last_sync_times = {}
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, '_library_service', None), \
             patch.object(gapi_gui, 'sync_scheduler', sched), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
             patch.object(gapi_gui.database, 'get_library_cache_age', return_value=3600), \
             patch.object(gapi_gui.database, 'get_cached_library', return_value=[{'x': 1}]):
            resp = self.client.get('/api/library/sync/status')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['games_cached'], 1)
        self.assertEqual(body['cache_age_hours'], 1.0)


# ── GET /api/users (scope filter) ───────────────────────────────────────────

class UsersListTest(_AuthedCase):
    def test_default_scope_keeps_only_platform_users(self):
        users = [
            {'username': 'alice', 'steam_id': '', 'epic_id': '', 'gog_id': ''},
            {'username': 'bob', 'steam_id': '123', 'epic_id': '', 'gog_id': ''},
        ]
        with patch.object(gapi_gui.user_manager, 'get_all_users', return_value=users):
            resp = self.client.get('/api/users')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([u['username'] for u in resp.json()['users']], ['bob'])

    def test_scope_me_and_friends(self):
        users = [
            {'username': 'admin', 'steam_id': '', 'epic_id': '', 'gog_id': ''},
            {'username': 'bob', 'steam_id': '123', 'epic_id': '', 'gog_id': ''},
            {'username': 'eve', 'steam_id': '9', 'epic_id': '', 'gog_id': ''},
        ]
        with patch.object(gapi_gui.user_manager, 'get_all_users', return_value=users), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=MagicMock()), \
             patch.object(gapi_gui.database, 'get_app_friends_with_platforms',
                          return_value={'friends': [{'username': 'bob'}]}):
            resp = self.client.get('/api/users?scope=me_and_friends')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sorted(u['username'] for u in resp.json()['users']),
                         ['admin', 'bob'])


# ── GET /api/users/all (admin) ──────────────────────────────────────────────

class UsersAllTest(_AuthedCase):
    def test_returns_all_users(self):
        with patch.object(gapi_gui.user_manager, 'get_all_users',
                          return_value=[{'username': 'a'}, {'username': 'b'}]):
            resp = self.client.get('/api/users/all')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['users']), 2)


# ── GET /api/users/online ───────────────────────────────────────────────────

class UsersOnlineTest(_AuthedCase):
    def test_db_unavailable_empty(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/users/online')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['users'], [])

    def test_online_users(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_online_users',
                          return_value=[{'username': 'alice'}]):
            resp = self.client.get('/api/users/online')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['users'], [{'username': 'alice'}])


# ── GET /api/multiuser/common & /stats ──────────────────────────────────────

class MultiuserReadTest(_AuthedCase):
    def test_common_no_picker_400(self):
        with patch.object(gapi_gui, '_ensure_multi_picker', MagicMock()), \
             patch.object(gapi_gui, 'multi_picker', None):
            resp = self.client.get('/api/multiuser/common')
        self.assertEqual(resp.status_code, 400)

    def test_common_success(self):
        mp = MagicMock()
        mp.find_common_games.return_value = [
            {'appid': 620, 'name': 'Portal 2', 'playtime_forever': 120,
             'owners': ['a', 'b']},
        ]
        with patch.object(gapi_gui, '_ensure_multi_picker', MagicMock()), \
             patch.object(gapi_gui, 'multi_picker', mp), \
             patch.object(gapi_gui, 'multi_picker_lock', MagicMock()):
            resp = self.client.get('/api/multiuser/common?users=a,b')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_common'], 1)
        self.assertEqual(body['games'][0]['playtime_hours'], 2.0)
        mp.find_common_games.assert_called_once_with(['a', 'b'])

    def test_stats_no_picker_400(self):
        with patch.object(gapi_gui, '_ensure_multi_picker', MagicMock()), \
             patch.object(gapi_gui, 'multi_picker', None):
            resp = self.client.get('/api/multiuser/stats')
        self.assertEqual(resp.status_code, 400)

    def test_stats_success(self):
        mp = MagicMock()
        mp.get_library_stats.return_value = {'total_games': 5, 'users': 2}
        with patch.object(gapi_gui, '_ensure_multi_picker', MagicMock()), \
             patch.object(gapi_gui, 'multi_picker', mp), \
             patch.object(gapi_gui, 'multi_picker_lock', MagicMock()):
            resp = self.client.get('/api/multiuser/stats')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'total_games': 5, 'users': 2})
        mp.get_library_stats.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()
