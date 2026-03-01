#!/usr/bin/env python3
"""
Tests for plugin deletion, user-data backup/restore, and updated OpenAPI spec.

Run with:
    python -m pytest tests/test_plugin_export.py
"""
import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from openapi_spec import build_spec


# ---------------------------------------------------------------------------
# Helpers – lightweight in-memory SQLite DB via SQLAlchemy
# ---------------------------------------------------------------------------

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_session():
    """Return a fresh in-memory SQLAlchemy session with all tables created."""
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _create_user(db, username='alice'):
    user = database.User(username=username, password='hash')
    db.add(user)
    db.commit()
    return db.query(database.User).filter_by(username=username).first()


# ---------------------------------------------------------------------------
# delete_plugin tests
# ---------------------------------------------------------------------------

class TestDeletePlugin(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        _create_user(self.db)
        # Register a plugin to use in tests
        database.register_plugin(self.db, name='TestPlugin', description='A test', version='1.0.0')
        plugin = self.db.query(database.Plugin).filter_by(name='TestPlugin').first()
        self.plugin_id = plugin.id

    def tearDown(self):
        self.db.close()

    def test_delete_existing_plugin_returns_true(self):
        result = database.delete_plugin(self.db, self.plugin_id)
        self.assertTrue(result)

    def test_delete_existing_plugin_removes_from_db(self):
        database.delete_plugin(self.db, self.plugin_id)
        plugin = self.db.query(database.Plugin).filter_by(id=self.plugin_id).first()
        self.assertIsNone(plugin)

    def test_delete_nonexistent_plugin_returns_false(self):
        result = database.delete_plugin(self.db, 99999)
        self.assertFalse(result)

    def test_delete_with_none_db_returns_false(self):
        result = database.delete_plugin(None, 1)
        self.assertFalse(result)

    def test_delete_does_not_affect_other_plugins(self):
        database.register_plugin(self.db, name='OtherPlugin')
        database.delete_plugin(self.db, self.plugin_id)
        remaining = database.get_plugins(self.db)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['name'], 'OtherPlugin')


# ---------------------------------------------------------------------------
# get_user_data_export tests
# ---------------------------------------------------------------------------

class TestGetUserDataExport(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db, 'bob')

    def tearDown(self):
        self.db.close()

    def test_export_unknown_user_returns_empty(self):
        result = database.get_user_data_export(self.db, 'nobody')
        self.assertEqual(result, {})

    def test_export_with_none_db_returns_empty(self):
        result = database.get_user_data_export(None, 'bob')
        self.assertEqual(result, {})

    def test_export_contains_required_keys(self):
        result = database.get_user_data_export(self.db, 'bob')
        for key in ('version', 'exported_at', 'username', 'profile',
                    'ignored_games', 'favorites', 'achievements'):
            self.assertIn(key, result)

    def test_export_username_matches(self):
        result = database.get_user_data_export(self.db, 'bob')
        self.assertEqual(result['username'], 'bob')

    def test_export_includes_ignored_game(self):
        self.db.add(database.IgnoredGame(
            user_id=self.user.id, app_id='620',
            game_name='Portal 2', reason='Already played'))
        self.db.commit()
        result = database.get_user_data_export(self.db, 'bob')
        self.assertEqual(len(result['ignored_games']), 1)
        self.assertEqual(result['ignored_games'][0]['app_id'], '620')

    def test_export_includes_favorite(self):
        self.db.add(database.FavoriteGame(user_id=self.user.id, app_id='440', platform='steam'))
        self.db.commit()
        result = database.get_user_data_export(self.db, 'bob')
        self.assertEqual(len(result['favorites']), 1)
        self.assertEqual(result['favorites'][0]['app_id'], '440')

    def test_export_includes_achievement(self):
        self.db.add(database.Achievement(
            user_id=self.user.id, app_id='620', game_name='Portal 2',
            achievement_id='ACH_WIN', achievement_name='Win',
            unlocked=True))
        self.db.commit()
        result = database.get_user_data_export(self.db, 'bob')
        self.assertEqual(len(result['achievements']), 1)
        self.assertEqual(result['achievements'][0]['achievement_id'], 'ACH_WIN')
        self.assertTrue(result['achievements'][0]['unlocked'])

    def test_export_is_json_serialisable(self):
        result = database.get_user_data_export(self.db, 'bob')
        serialised = json.dumps(result)  # must not raise
        self.assertIsInstance(serialised, str)


# ---------------------------------------------------------------------------
# import_user_data tests
# ---------------------------------------------------------------------------

class TestImportUserData(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db, 'carol')

    def tearDown(self):
        self.db.close()

    def _basic_export(self):
        return {
            'version': '1',
            'username': 'carol',
            'profile': {},
            'ignored_games': [
                {'app_id': '620', 'game_name': 'Portal 2', 'reason': 'Played'},
            ],
            'favorites': [
                {'app_id': '440', 'platform': 'steam'},
            ],
            'achievements': [
                {
                    'app_id': '620', 'game_name': 'Portal 2',
                    'achievement_id': 'ACH_WIN', 'name': 'Win',
                    'unlocked': True, 'unlock_time': None, 'rarity': 5.0,
                },
            ],
        }

    def test_import_none_db_returns_empty(self):
        result = database.import_user_data(None, 'carol', self._basic_export())
        self.assertEqual(result, {})

    def test_import_unknown_user_returns_empty(self):
        result = database.import_user_data(self.db, 'nobody', self._basic_export())
        self.assertEqual(result, {})

    def test_import_adds_ignored_game(self):
        counts = database.import_user_data(self.db, 'carol', self._basic_export())
        self.assertEqual(counts['ignored_added'], 1)
        ignored = self.db.query(database.IgnoredGame).filter_by(user_id=self.user.id).all()
        self.assertEqual(len(ignored), 1)
        self.assertEqual(ignored[0].app_id, '620')

    def test_import_adds_favorite(self):
        counts = database.import_user_data(self.db, 'carol', self._basic_export())
        self.assertEqual(counts['favorites_added'], 1)
        favs = self.db.query(database.FavoriteGame).filter_by(user_id=self.user.id).all()
        self.assertEqual(len(favs), 1)

    def test_import_adds_achievement(self):
        counts = database.import_user_data(self.db, 'carol', self._basic_export())
        self.assertEqual(counts['achievements_added'], 1)
        achs = self.db.query(database.Achievement).filter_by(user_id=self.user.id).all()
        self.assertEqual(len(achs), 1)
        self.assertEqual(achs[0].achievement_id, 'ACH_WIN')

    def test_import_is_idempotent(self):
        """Importing the same export twice must not duplicate records."""
        database.import_user_data(self.db, 'carol', self._basic_export())
        counts2 = database.import_user_data(self.db, 'carol', self._basic_export())
        self.assertEqual(counts2['ignored_added'], 0)
        self.assertEqual(counts2['favorites_added'], 0)
        self.assertEqual(counts2['achievements_added'], 0)

    def test_import_empty_sections_adds_nothing(self):
        empty = {'profile': {}, 'ignored_games': [], 'favorites': [], 'achievements': []}
        counts = database.import_user_data(self.db, 'carol', empty)
        self.assertEqual(counts['ignored_added'], 0)
        self.assertEqual(counts['favorites_added'], 0)
        self.assertEqual(counts['achievements_added'], 0)

    def test_roundtrip_export_import(self):
        """Export then import into a fresh user should reproduce the data."""
        # Seed carol with some data
        self.db.add(database.IgnoredGame(user_id=self.user.id, app_id='730',
                                          game_name='CSGO'))
        self.db.add(database.FavoriteGame(user_id=self.user.id, app_id='570',
                                           platform='steam'))
        self.db.commit()

        exported = database.get_user_data_export(self.db, 'carol')

        # Import into a second user in the same DB
        dave = database.User(username='dave', password='hash')
        self.db.add(dave)
        self.db.commit()

        counts = database.import_user_data(self.db, 'dave', exported)
        self.assertEqual(counts['ignored_added'], 1)
        self.assertEqual(counts['favorites_added'], 1)


# ---------------------------------------------------------------------------
# OpenAPI spec coverage tests
# ---------------------------------------------------------------------------

class TestOpenAPISpecCoverage(unittest.TestCase):

    def setUp(self):
        self.spec = build_spec()
        self.paths = self.spec['paths']

    def test_live_session_create_present(self):
        self.assertIn('/api/live-session/create', self.paths)

    def test_live_session_active_present(self):
        self.assertIn('/api/live-session/active', self.paths)

    def test_live_session_events_sse_present(self):
        self.assertIn('/api/live-session/{session_id}/events', self.paths)

    def test_live_session_join_leave_pick_invite_present(self):
        for suffix in ('join', 'leave', 'pick', 'invite'):
            self.assertIn(f'/api/live-session/{{session_id}}/{suffix}', self.paths,
                          msg=f'Missing /api/live-session/{{session_id}}/{suffix}')

    def test_presence_endpoints_present(self):
        self.assertIn('/api/presence', self.paths)
        self.assertIn('/api/users/online', self.paths)

    def test_app_friends_endpoints_present(self):
        for path in ('/api/app-friends', '/api/app-friends/request',
                     '/api/app-friends/respond', '/api/app-friends/remove'):
            self.assertIn(path, self.paths, msg=f'Missing {path}')

    def test_chat_endpoints_present(self):
        self.assertIn('/api/chat/messages', self.paths)
        self.assertIn('/api/chat/send', self.paths)

    def test_notification_endpoints_present(self):
        for path in ('/api/notifications', '/api/notifications/read',
                     '/api/notifications/send'):
            self.assertIn(path, self.paths, msg=f'Missing {path}')

    def test_leaderboard_present(self):
        self.assertIn('/api/leaderboard', self.paths)

    def test_plugin_delete_documented(self):
        self.assertIn('/api/plugins/{plugin_id}', self.paths)
        self.assertIn('delete', self.paths['/api/plugins/{plugin_id}'])

    def test_admin_settings_present(self):
        self.assertIn('/api/admin/settings', self.paths)
        self.assertIn('/api/admin/settings/public', self.paths)

    def test_i18n_endpoints_present(self):
        self.assertIn('/api/i18n', self.paths)
        self.assertIn('/api/i18n/{lang}', self.paths)

    def test_user_profile_and_card_present(self):
        self.assertIn('/api/user/{username}/card', self.paths)
        self.assertIn('/api/user/profile', self.paths)

    def test_user_data_export_import_present(self):
        self.assertIn('/api/export/user-data', self.paths)
        self.assertIn('/api/import/user-data', self.paths)

    def test_spec_is_json_serialisable(self):
        serialised = json.dumps(self.spec)
        self.assertIsInstance(serialised, str)

    def test_all_paths_have_at_least_one_method(self):
        http_methods = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}
        for path, item in self.paths.items():
            self.assertTrue(
                any(m in item for m in http_methods),
                msg=f'Path {path!r} has no HTTP method entries',
            )


if __name__ == '__main__':
    unittest.main()
