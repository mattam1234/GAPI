#!/usr/bin/env python3
"""Tests for automatic achievement sync after library sync."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gapi_gui


class _FakeSession:
    def close(self):
        return None


class _FakeLibraryService:
    def get_cache_age(self, db, username):
        return None

    def cache(self, db, username, games):
        return len(games)


class TestLibrarySyncQueuesAchievementSync(unittest.TestCase):
    def test_sync_library_queues_achievement_sync_on_success(self):
        steam_client = Mock()
        steam_client.get_owned_games.return_value = [
            {'app_id': 620, 'name': 'Portal 2', 'playtime_forever': 120},
            {'app_id': 440, 'name': 'TF2', 'playtime_forever': 60},
        ]
        fake_user_manager = SimpleNamespace(
            get_user_ids=lambda _username: {'steam_id': '76561198000000001'}
        )

        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui, 'user_manager', fake_user_manager), \
             patch.object(gapi_gui, 'load_base_config', return_value={'steam_api_key': 'test-key'}), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=_FakeSession()), \
             patch.object(gapi_gui, '_library_service', _FakeLibraryService()), \
             patch.object(gapi_gui.gapi, 'SteamAPIClient', return_value=steam_client), \
             patch.object(gapi_gui, '_queue_library_achievement_sync') as queue_mock:
            success, message = gapi_gui.sync_library_to_db('alice', force=True)

        self.assertTrue(success)
        self.assertIn('queued achievement sync', message.lower())
        queue_mock.assert_called_once_with('alice')


if __name__ == '__main__':
    unittest.main()
