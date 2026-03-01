#!/usr/bin/env python3
"""
Tests for:
  - SteamAPIClient.get_player_achievements()
  - SteamAPIClient.get_schema_for_game()
  - database.sync_steam_achievements()
  - POST /api/achievements/sync endpoint (Flask test client)
  - OpenAPI spec: /api/achievements/sync path
  - requirements.txt: all expected packages listed

Run with:
    python -m pytest tests/test_steam_sync.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import gapi
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# In-memory DB helper (shared with test_challenges_graphql.py pattern)
# ---------------------------------------------------------------------------

def _make_session():
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _create_user(db, username='alice', steam_id='76561198000000001'):
    user = database.User(username=username, password='hash', steam_id=steam_id)
    db.add(user)
    db.commit()
    return db.query(database.User).filter_by(username=username).first()


# ===========================================================================
# SteamAPIClient.get_player_achievements
# ===========================================================================

class TestGetPlayerAchievements(unittest.TestCase):

    def _client(self):
        return gapi.SteamAPIClient('FAKE_KEY')

    def test_returns_empty_on_bad_app_id(self):
        client = self._client()
        result = client.get_player_achievements('12345', 'not_an_int')
        self.assertEqual(result, [])

    def test_returns_empty_on_http_error(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch.object(client.session, 'get', return_value=mock_resp):
            result = client.get_player_achievements('12345', '620')
        self.assertEqual(result, [])

    def test_parses_achievements_correctly(self):
        client = self._client()
        payload = {
            'playerstats': {
                'achievements': [
                    {'apiname': 'ACH1', 'achieved': 1, 'unlocktime': 1700000000},
                    {'apiname': 'ACH2', 'achieved': 0, 'unlocktime': 0},
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        with patch.object(client.session, 'get', return_value=mock_resp):
            result = client.get_player_achievements('12345', '620')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['apiname'], 'ACH1')
        self.assertEqual(result[0]['achieved'], 1)

    def test_returns_empty_list_if_no_achievements_key(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'playerstats': {}}
        with patch.object(client.session, 'get', return_value=mock_resp):
            result = client.get_player_achievements('12345', '620')
        self.assertEqual(result, [])

    def test_network_error_returns_empty(self):
        import requests as _requests
        client = self._client()
        with patch.object(client.session, 'get',
                          side_effect=_requests.RequestException("timeout")):
            result = client.get_player_achievements('12345', '620')
        self.assertEqual(result, [])


# ===========================================================================
# SteamAPIClient.get_schema_for_game
# ===========================================================================

class TestGetSchemaForGame(unittest.TestCase):

    def _client(self):
        return gapi.SteamAPIClient('FAKE_KEY')

    def test_returns_empty_on_bad_app_id(self):
        self.assertEqual(self._client().get_schema_for_game('not_int'), {})

    def test_returns_empty_on_http_error(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(client.session, 'get', return_value=mock_resp):
            self.assertEqual(client.get_schema_for_game('620'), {})

    def test_parses_schema_correctly(self):
        client = self._client()
        payload = {
            'game': {
                'availableGameStats': {
                    'achievements': [
                        {'name': 'ACH1', 'displayName': 'Finish Game',
                         'description': 'Complete the game', 'icon': 'x.jpg', 'icongray': 'y.jpg'},
                        {'name': 'ACH2', 'displayName': 'Speed Run',
                         'description': '', 'icon': '', 'icongray': ''},
                    ]
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        with patch.object(client.session, 'get', return_value=mock_resp):
            result = client.get_schema_for_game('620')
        self.assertIn('ACH1', result)
        self.assertEqual(result['ACH1']['name'], 'Finish Game')
        self.assertEqual(result['ACH1']['description'], 'Complete the game')
        self.assertIn('ACH2', result)

    def test_returns_empty_dict_if_no_achievements(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'game': {'availableGameStats': {'achievements': []}}}
        with patch.object(client.session, 'get', return_value=mock_resp):
            self.assertEqual(client.get_schema_for_game('620'), {})

    def test_result_maps_apiname_to_dict(self):
        client = self._client()
        payload = {'game': {'availableGameStats': {'achievements': [
            {'name': 'X', 'displayName': 'XX', 'description': 'DD'}
        ]}}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        with patch.object(client.session, 'get', return_value=mock_resp):
            result = client.get_schema_for_game('1')
        self.assertIsInstance(result, dict)
        self.assertIn('name', result['X'])
        self.assertIn('description', result['X'])


# ===========================================================================
# database.sync_steam_achievements
# ===========================================================================

_PLAYER_ACHIEVEMENTS = [
    {'apiname': 'ACH1', 'achieved': 1, 'unlocktime': 1700000000},
    {'apiname': 'ACH2', 'achieved': 0, 'unlocktime': 0},
]

_SCHEMA = {
    'ACH1': {'name': 'Finish Game', 'description': 'Complete the game'},
    'ACH2': {'name': 'Speed Run',   'description': 'Finish in under 2 hours'},
}


class TestSyncSteamAchievements(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_zeros(self):
        result = database.sync_steam_achievements(
            None, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        self.assertEqual(result['added'], 0)
        self.assertEqual(result['updated'], 0)

    def test_unknown_user_returns_zeros(self):
        result = database.sync_steam_achievements(
            self.db, 'nobody', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        self.assertEqual(result['added'], 0)

    def test_adds_new_achievements(self):
        result = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        self.assertEqual(result['added'], 2)
        self.assertEqual(result['updated'], 0)

    def test_correct_unlock_state_stored(self):
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        ach1 = self.db.query(database.Achievement).filter_by(achievement_id='ACH1').first()
        ach2 = self.db.query(database.Achievement).filter_by(achievement_id='ACH2').first()
        self.assertTrue(ach1.unlocked)
        self.assertFalse(ach2.unlocked)

    def test_display_name_from_schema(self):
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        ach1 = self.db.query(database.Achievement).filter_by(achievement_id='ACH1').first()
        self.assertEqual(ach1.achievement_name, 'Finish Game')

    def test_description_from_schema(self):
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        ach = self.db.query(database.Achievement).filter_by(achievement_id='ACH1').first()
        self.assertEqual(ach.achievement_description, 'Complete the game')

    def test_idempotent_no_duplicate_on_second_sync(self):
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        result2 = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        self.assertEqual(result2['added'], 0)
        count = self.db.query(database.Achievement).filter_by(app_id='620').count()
        self.assertEqual(count, 2)

    def test_updates_unlock_state_on_second_sync(self):
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        # Now ACH2 gets unlocked
        updated_achievements = [
            {'apiname': 'ACH1', 'achieved': 1, 'unlocktime': 1700000000},
            {'apiname': 'ACH2', 'achieved': 1, 'unlocktime': 1700001000},
        ]
        result2 = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            updated_achievements, _SCHEMA)
        self.assertEqual(result2['updated'], 1)
        ach2 = self.db.query(database.Achievement).filter_by(achievement_id='ACH2').first()
        self.assertTrue(ach2.unlocked)

    def test_empty_player_achievements_returns_zeros(self):
        result = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2', [], _SCHEMA)
        self.assertEqual(result['added'], 0)
        self.assertEqual(result['updated'], 0)

    def test_result_is_json_serialisable(self):
        result = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        json.dumps(result)

    def test_unlock_time_stored(self):
        import datetime as _dt
        database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, _SCHEMA)
        ach = self.db.query(database.Achievement).filter_by(achievement_id='ACH1').first()
        self.assertIsNotNone(ach.unlock_time)
        self.assertIsInstance(ach.unlock_time, _dt.datetime)

    def test_missing_schema_falls_back_to_apiname(self):
        result = database.sync_steam_achievements(
            self.db, 'alice', '76561198000000001', '620', 'Portal 2',
            _PLAYER_ACHIEVEMENTS, {})  # empty schema
        self.assertEqual(result['added'], 2)
        ach = self.db.query(database.Achievement).filter_by(achievement_id='ACH1').first()
        self.assertEqual(ach.achievement_name, 'ACH1')


# ===========================================================================
# OpenAPI spec: /api/achievements/sync
# ===========================================================================

class TestOpenAPISyncPath(unittest.TestCase):

    def setUp(self):
        from openapi_spec import build_spec
        self.spec = build_spec()
        self.paths = self.spec['paths']

    def test_sync_path_present(self):
        self.assertIn('/api/achievements/sync', self.paths)

    def test_sync_is_post(self):
        self.assertIn('post', self.paths['/api/achievements/sync'])

    def test_sync_response_200_present(self):
        responses = self.paths['/api/achievements/sync']['post']['responses']
        self.assertIn('200', responses)

    def test_sync_400_and_503_present(self):
        responses = self.paths['/api/achievements/sync']['post']['responses']
        self.assertIn('400', responses)
        self.assertIn('503', responses)

    def test_sync_tagged_achievements(self):
        tags = self.paths['/api/achievements/sync']['post']['tags']
        self.assertIn('achievements', tags)

    def test_spec_json_serialisable(self):
        json.dumps(self.spec)


# ===========================================================================
# requirements.txt: all expected packages present
# ===========================================================================

class TestRequirementsTxt(unittest.TestCase):

    def setUp(self):
        req_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'requirements.txt'
        )
        with open(req_path) as f:
            self._content = f.read()

    def _assert_pkg(self, pkg):
        self.assertIn(pkg, self._content,
                      f"'{pkg}' not found in requirements.txt")

    def test_requests_present(self):
        self._assert_pkg('requests')

    def test_flask_present(self):
        self._assert_pkg('flask')

    def test_sqlalchemy_present(self):
        self._assert_pkg('sqlalchemy')

    def test_psycopg2_present(self):
        self._assert_pkg('psycopg2')

    def test_python_dotenv_present(self):
        self._assert_pkg('python-dotenv')

    def test_colorama_present(self):
        self._assert_pkg('colorama')

    def test_discordpy_present(self):
        self._assert_pkg('discord')

    def test_howlongtobeatpy_present(self):
        self._assert_pkg('howlongtobeatpy')

    def test_pypresence_present(self):
        self._assert_pkg('pypresence')

    def test_graphene_present(self):
        self._assert_pkg('graphene')

    def test_epicstore_api_present(self):
        self._assert_pkg('epicstore')

    def test_no_duplicate_package_entries(self):
        packages = []
        for line in self._content.splitlines():
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-'):
                pkg = line.split('>=')[0].split('==')[0].split(',')[0].lower().strip()
                packages.append(pkg)
        self.assertEqual(len(packages), len(set(packages)),
                         f"Duplicate entries in requirements.txt: {packages}")


if __name__ == '__main__':
    unittest.main()
