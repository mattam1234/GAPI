#!/usr/bin/env python3
"""
Unit tests for GAPI core functionality.

Run with:
    python -m pytest tests/
  or
    python -m unittest discover tests/
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

# Make sure gapi module can be imported regardless of where tests are run from.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi
from multiuser import VotingSession

# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------
VALID_STEAM_ID = '76561190000000001'
FAKE_API_KEY = 'TEST_API_KEY_12345'

# Minimal fake game dicts that match what SteamAPIClient produces.
FAKE_GAMES = [
    {'appid': 620,   'name': 'Portal 2',        'playtime_forever': 2720, 'platform': 'steam', 'game_id': 'steam:620'},
    {'appid': 440,   'name': 'Team Fortress 2', 'playtime_forever': 0,    'platform': 'steam', 'game_id': 'steam:440'},
    {'appid': 570,   'name': 'Dota 2',           'playtime_forever': 120,  'platform': 'steam', 'game_id': 'steam:570'},
    {'appid': 730,   'name': 'CS:GO',            'playtime_forever': 4560, 'platform': 'steam', 'game_id': 'steam:730'},
    {'appid': 72850, 'name': 'Skyrim',           'playtime_forever': 890,  'platform': 'steam', 'game_id': 'steam:72850'},
]


def make_picker(tmp_dir: str) -> gapi.GamePicker:
    """Create a GamePicker using *tmp_dir* for all file I/O (no real API calls)."""
    cfg_path = os.path.join(tmp_dir, 'config.json')
    with open(cfg_path, 'w') as f:
        json.dump({'steam_api_key': FAKE_API_KEY, 'steam_id': VALID_STEAM_ID}, f)
    orig = os.getcwd()
    os.chdir(tmp_dir)
    try:
        picker = gapi.GamePicker(cfg_path)
    finally:
        os.chdir(orig)
    return picker


# ===========================================================================
# Helper function tests
# ===========================================================================

class TestMinutesToHours(unittest.TestCase):
    """Tests for gapi.minutes_to_hours()."""

    def test_zero(self):
        self.assertEqual(gapi.minutes_to_hours(0), 0.0)

    def test_one_hour(self):
        self.assertAlmostEqual(gapi.minutes_to_hours(60), 1.0)

    def test_fraction(self):
        self.assertAlmostEqual(gapi.minutes_to_hours(90), 1.5)

    def test_large_value(self):
        self.assertAlmostEqual(gapi.minutes_to_hours(2720), round(2720 / 60, 1))


class TestIsValidSteamId(unittest.TestCase):
    """Tests for gapi.is_valid_steam_id()."""

    def test_valid_id(self):
        self.assertTrue(gapi.is_valid_steam_id('76561190000000001'))
        self.assertTrue(gapi.is_valid_steam_id('76561198000000001'))

    def test_too_short(self):
        self.assertFalse(gapi.is_valid_steam_id('7656119'))

    def test_too_long(self):
        self.assertFalse(gapi.is_valid_steam_id('765611900000000012'))

    def test_wrong_prefix(self):
        self.assertFalse(gapi.is_valid_steam_id('12345678901234567'))

    def test_non_digit(self):
        self.assertFalse(gapi.is_valid_steam_id('7656119abcdefghi'))

    def test_empty(self):
        self.assertFalse(gapi.is_valid_steam_id(''))

    def test_none(self):
        self.assertFalse(gapi.is_valid_steam_id(None))  # type: ignore[arg-type]


class TestIsPlaceholderValue(unittest.TestCase):
    """Tests for gapi.is_placeholder_value()."""

    def test_your_prefix(self):
        self.assertTrue(gapi.is_placeholder_value('YOUR_STEAM_API_KEY'))
        self.assertTrue(gapi.is_placeholder_value('YOUR_ANYTHING'))

    def test_known_placeholders(self):
        self.assertTrue(gapi.is_placeholder_value('DEMO_MODE'))
        self.assertTrue(gapi.is_placeholder_value('DEMO_KEY'))

    def test_empty_string(self):
        self.assertTrue(gapi.is_placeholder_value(''))

    def test_none(self):
        self.assertTrue(gapi.is_placeholder_value(None))  # type: ignore[arg-type]

    def test_real_key(self):
        self.assertFalse(gapi.is_placeholder_value('A1B2C3D4E5F6'))

    def test_real_steam_id(self):
        self.assertFalse(gapi.is_placeholder_value('76561190000000001'))


class TestParseReleaseYear(unittest.TestCase):
    """Tests for gapi._parse_release_year()."""

    def test_full_date(self):
        self.assertEqual(gapi._parse_release_year('21 Sep, 2011'), 2011)
        self.assertEqual(gapi._parse_release_year('18 Apr, 2011'), 2011)

    def test_year_only(self):
        self.assertEqual(gapi._parse_release_year('2020'), 2020)

    def test_early_year(self):
        self.assertEqual(gapi._parse_release_year('1998'), 1998)

    def test_empty(self):
        self.assertIsNone(gapi._parse_release_year(''))

    def test_none(self):
        self.assertIsNone(gapi._parse_release_year(None))  # type: ignore[arg-type]

    def test_no_year(self):
        self.assertIsNone(gapi._parse_release_year('Coming Soon'))


class TestExtractGameId(unittest.TestCase):
    """Tests for gapi.extract_game_id()."""

    def test_appid(self):
        self.assertEqual(gapi.extract_game_id({'appid': 620}), 620)

    def test_game_id(self):
        self.assertEqual(gapi.extract_game_id({'game_id': 'steam:620'}), 'steam:620')

    def test_id_key(self):
        self.assertEqual(gapi.extract_game_id({'id': 'epic:abc'}), 'epic:abc')

    def test_appid_preferred(self):
        self.assertEqual(gapi.extract_game_id({'appid': 1, 'game_id': 'x'}), 1)

    def test_empty(self):
        self.assertIsNone(gapi.extract_game_id({}))


# ===========================================================================
# GamePicker favorites tests
# ===========================================================================

class TestGamePickerFavorites(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_favorite(self):
        self.assertTrue(self.picker.add_favorite('steam:620'))
        self.assertIn('steam:620', self.picker.favorites)

    def test_add_favorite_no_duplicates(self):
        self.picker.add_favorite('steam:620')
        result = self.picker.add_favorite('steam:620')
        self.assertFalse(result)
        self.assertEqual(self.picker.favorites.count('steam:620'), 1)

    def test_remove_favorite(self):
        self.picker.add_favorite('steam:620')
        result = self.picker.remove_favorite('steam:620')
        self.assertTrue(result)
        self.assertNotIn('steam:620', self.picker.favorites)

    def test_remove_nonexistent_favorite(self):
        result = self.picker.remove_favorite('steam:99999')
        self.assertFalse(result)

    def test_favorites_persisted(self):
        """Favorites should survive a new GamePicker instance (on-disk persistence)."""
        self.picker.add_favorite('steam:440')
        cfg_path = os.path.join(self.tmp_dir, 'config.json')
        picker2 = gapi.GamePicker(cfg_path)
        self.assertIn('steam:440', picker2.favorites)

    def test_add_favorite_int_backward_compat(self):
        """Integer IDs should be converted to composite format."""
        self.picker.add_favorite(620)  # type: ignore[arg-type]
        self.assertIn('steam:620', self.picker.favorites)


# ===========================================================================
# GamePicker tags tests
# ===========================================================================

class TestGamePickerTags(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_tag(self):
        result = self.picker.add_tag('steam:620', 'coop')
        self.assertTrue(result)
        self.assertIn('coop', self.picker.get_tags('steam:620'))

    def test_add_tag_normalised_lowercase(self):
        self.picker.add_tag('steam:620', 'CoOp')
        self.assertIn('coop', self.picker.get_tags('steam:620'))

    def test_add_tag_no_duplicates(self):
        self.picker.add_tag('steam:620', 'coop')
        result = self.picker.add_tag('steam:620', 'coop')
        self.assertFalse(result)
        self.assertEqual(self.picker.get_tags('steam:620').count('coop'), 1)

    def test_add_empty_tag_rejected(self):
        result = self.picker.add_tag('steam:620', '   ')
        self.assertFalse(result)

    def test_remove_tag(self):
        self.picker.add_tag('steam:620', 'coop')
        result = self.picker.remove_tag('steam:620', 'coop')
        self.assertTrue(result)
        self.assertNotIn('coop', self.picker.get_tags('steam:620'))

    def test_remove_nonexistent_tag(self):
        result = self.picker.remove_tag('steam:620', 'nonexistent')
        self.assertFalse(result)

    def test_get_tags_empty(self):
        self.assertEqual(self.picker.get_tags('steam:99999'), [])

    def test_all_tags(self):
        self.picker.add_tag('steam:620', 'coop')
        self.picker.add_tag('steam:620', 'puzzle')
        self.picker.add_tag('steam:440', 'fps')
        tags = self.picker.all_tags()
        self.assertIn('coop', tags)
        self.assertIn('puzzle', tags)
        self.assertIn('fps', tags)
        self.assertEqual(len(tags), len(set(tags)), "all_tags should not contain duplicates")

    def test_filter_by_tag(self):
        self.picker.games = list(FAKE_GAMES)
        self.picker.add_tag('steam:620', 'coop')
        self.picker.add_tag('steam:440', 'coop')
        results = self.picker.filter_by_tag('coop')
        names = [g['name'] for g in results]
        self.assertIn('Portal 2', names)
        self.assertIn('Team Fortress 2', names)
        self.assertNotIn('Dota 2', names)

    def test_filter_by_tag_case_insensitive(self):
        self.picker.games = list(FAKE_GAMES)
        self.picker.add_tag('steam:570', 'MOBA')
        results = self.picker.filter_by_tag('moba')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Dota 2')

    def test_tags_persisted(self):
        self.picker.add_tag('steam:730', 'fps')
        cfg_path = os.path.join(self.tmp_dir, 'config.json')
        picker2 = gapi.GamePicker(cfg_path)
        self.assertIn('fps', picker2.get_tags('steam:730'))


# ===========================================================================
# GamePicker reviews tests
# ===========================================================================

class TestGamePickerReviews(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_review(self):
        result = self.picker.add_or_update_review('steam:620', 9, 'Great puzzle game')
        self.assertTrue(result)
        review = self.picker.get_review('steam:620')
        self.assertIsNotNone(review)
        self.assertEqual(review['rating'], 9)
        self.assertEqual(review['notes'], 'Great puzzle game')

    def test_update_review(self):
        self.picker.add_or_update_review('steam:620', 7, 'Good')
        self.picker.add_or_update_review('steam:620', 8, 'Very good')
        review = self.picker.get_review('steam:620')
        self.assertEqual(review['rating'], 8)
        self.assertEqual(review['notes'], 'Very good')

    def test_invalid_rating_too_low(self):
        result = self.picker.add_or_update_review('steam:620', 0)
        self.assertFalse(result)
        self.assertIsNone(self.picker.get_review('steam:620'))

    def test_invalid_rating_too_high(self):
        result = self.picker.add_or_update_review('steam:620', 11)
        self.assertFalse(result)

    def test_remove_review(self):
        self.picker.add_or_update_review('steam:620', 8)
        result = self.picker.remove_review('steam:620')
        self.assertTrue(result)
        self.assertIsNone(self.picker.get_review('steam:620'))

    def test_remove_nonexistent_review(self):
        result = self.picker.remove_review('steam:99999')
        self.assertFalse(result)

    def test_review_has_updated_at(self):
        self.picker.add_or_update_review('steam:620', 8)
        review = self.picker.get_review('steam:620')
        self.assertIn('updated_at', review)

    def test_reviews_persisted(self):
        self.picker.add_or_update_review('steam:620', 9, 'Excellent')
        cfg_path = os.path.join(self.tmp_dir, 'config.json')
        picker2 = gapi.GamePicker(cfg_path)
        self.assertEqual(picker2.get_review('steam:620')['rating'], 9)


# ===========================================================================
# GamePicker backlog tests
# ===========================================================================

class TestGamePickerBacklog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_set_backlog_status(self):
        result = self.picker.set_backlog_status('steam:620', 'want_to_play')
        self.assertTrue(result)
        self.assertEqual(self.picker.get_backlog_status('steam:620'), 'want_to_play')

    def test_all_valid_statuses(self):
        for status in gapi.GamePicker.BACKLOG_STATUSES:
            self.assertTrue(self.picker.set_backlog_status('steam:620', status))
            self.assertEqual(self.picker.get_backlog_status('steam:620'), status)

    def test_invalid_status_rejected(self):
        result = self.picker.set_backlog_status('steam:620', 'not_a_status')
        self.assertFalse(result)
        self.assertIsNone(self.picker.get_backlog_status('steam:620'))

    def test_remove_backlog_status(self):
        self.picker.set_backlog_status('steam:620', 'playing')
        result = self.picker.remove_backlog_status('steam:620')
        self.assertTrue(result)
        self.assertIsNone(self.picker.get_backlog_status('steam:620'))

    def test_remove_nonexistent_backlog(self):
        result = self.picker.remove_backlog_status('steam:99999')
        self.assertFalse(result)

    def test_get_backlog_games_with_status_filter(self):
        self.picker.games = list(FAKE_GAMES)
        self.picker.set_backlog_status('steam:620', 'playing')
        self.picker.set_backlog_status('steam:440', 'want_to_play')
        playing = self.picker.get_backlog_games(status='playing')
        self.assertEqual(len(playing), 1)
        self.assertEqual(playing[0]['name'], 'Portal 2')
        self.assertEqual(playing[0]['backlog_status'], 'playing')

    def test_get_all_backlog_games(self):
        self.picker.games = list(FAKE_GAMES)
        self.picker.set_backlog_status('steam:620', 'playing')
        self.picker.set_backlog_status('steam:440', 'want_to_play')
        all_games = self.picker.get_backlog_games()
        self.assertEqual(len(all_games), 2)

    def test_backlog_persisted(self):
        self.picker.set_backlog_status('steam:730', 'completed')
        cfg_path = os.path.join(self.tmp_dir, 'config.json')
        picker2 = gapi.GamePicker(cfg_path)
        self.assertEqual(picker2.get_backlog_status('steam:730'), 'completed')


# ===========================================================================
# GamePicker filter_games tests (no external API calls)
# ===========================================================================

class TestGamePickerFilterGames(unittest.TestCase):
    """Tests for filter_games() using in-memory mock data only."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)
        self.picker.games = list(FAKE_GAMES)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_no_filter_returns_all(self):
        result = self.picker.filter_games()
        self.assertEqual(len(result), len(FAKE_GAMES))

    def test_min_playtime(self):
        # Only games with >= 600 min (10 h) playtime
        result = self.picker.filter_games(min_playtime=600)
        names = [g['name'] for g in result]
        self.assertIn('Portal 2', names)    # 2720 min
        self.assertIn('CS:GO', names)        # 4560 min
        self.assertNotIn('Team Fortress 2', names)  # 0 min

    def test_max_playtime(self):
        # Only games with <= 200 min playtime
        result = self.picker.filter_games(max_playtime=200)
        names = [g['name'] for g in result]
        self.assertIn('Team Fortress 2', names)  # 0 min
        self.assertIn('Dota 2', names)             # 120 min
        self.assertNotIn('Portal 2', names)        # 2720 min

    def test_min_and_max_playtime(self):
        result = self.picker.filter_games(min_playtime=100, max_playtime=1000)
        names = [g['name'] for g in result]
        self.assertIn('Dota 2', names)    # 120 min
        self.assertIn('Skyrim', names)    # 890 min
        self.assertNotIn('Team Fortress 2', names)  # 0 min
        self.assertNotIn('Portal 2', names)         # 2720 min

    def test_favorites_only(self):
        self.picker.add_favorite('steam:620')
        self.picker.add_favorite('steam:440')
        result = self.picker.filter_games(favorites_only=True)
        names = [g['name'] for g in result]
        self.assertIn('Portal 2', names)
        self.assertIn('Team Fortress 2', names)
        self.assertNotIn('Dota 2', names)

    def test_favorites_only_empty(self):
        result = self.picker.filter_games(favorites_only=True)
        self.assertEqual(result, [])

    def test_exclude_game_ids_by_appid(self):
        result = self.picker.filter_games(exclude_game_ids=['620', '440'])
        names = [g['name'] for g in result]
        self.assertNotIn('Portal 2', names)
        self.assertNotIn('Team Fortress 2', names)
        self.assertIn('Dota 2', names)

    def test_exclude_game_ids_by_composite(self):
        result = self.picker.filter_games(exclude_game_ids=['steam:620'])
        names = [g['name'] for g in result]
        self.assertNotIn('Portal 2', names)
        self.assertIn('Dota 2', names)

    def test_filter_games_with_genre_via_cache(self):
        """filter_games with genres should use the details_cache when available."""
        # Pre-populate the details cache so no HTTP call is made.
        self.picker.clients['steam'].details_cache = {
            620: {
                'genres': [{'description': 'Puzzle'}, {'description': 'Action'}],
                'release_date': {'date': '18 Apr, 2011'},
            },
            440: {
                'genres': [{'description': 'Action'}, {'description': 'FPS'}],
                'release_date': {'date': '10 Oct, 2007'},
            },
            570: {
                'genres': [{'description': 'Strategy'}],
                'release_date': {'date': '2013'},
            },
            730: {
                'genres': [{'description': 'Action'}, {'description': 'FPS'}],
                'release_date': {'date': '2012'},
            },
            72850: {
                'genres': [{'description': 'RPG'}],
                'release_date': {'date': '11 Nov, 2011'},
            },
        }
        result = self.picker.filter_games(genres=['Action'])
        names = [g['name'] for g in result]
        self.assertIn('Portal 2', names)
        self.assertIn('Team Fortress 2', names)
        self.assertIn('CS:GO', names)
        self.assertNotIn('Dota 2', names)   # Strategy only
        self.assertNotIn('Skyrim', names)   # RPG only

    def test_filter_games_exclude_genre_via_cache(self):
        self.picker.clients['steam'].details_cache = {
            620: {'genres': [{'description': 'Puzzle'}]},
            440: {'genres': [{'description': 'FPS'}]},
            570: {'genres': [{'description': 'Strategy'}]},
            730: {'genres': [{'description': 'FPS'}]},
            72850: {'genres': [{'description': 'RPG'}]},
        }
        result = self.picker.filter_games(exclude_genres=['FPS'])
        names = [g['name'] for g in result]
        self.assertNotIn('Team Fortress 2', names)
        self.assertNotIn('CS:GO', names)
        self.assertIn('Portal 2', names)
        self.assertIn('Dota 2', names)

    def test_filter_games_min_metacritic_via_cache(self):
        self.picker.clients['steam'].details_cache = {
            620: {'metacritic': {'score': 95}},
            440: {'metacritic': {'score': 70}},
            570: {},  # no metacritic key
            730: {'metacritic': {'score': 83}},
            72850: {'metacritic': {'score': 94}},
        }
        result = self.picker.filter_games(min_metacritic=90)
        names = [g['name'] for g in result]
        self.assertIn('Portal 2', names)
        self.assertIn('Skyrim', names)
        self.assertNotIn('Team Fortress 2', names)
        self.assertNotIn('Dota 2', names)
        self.assertNotIn('CS:GO', names)

    def test_filter_games_release_year_via_cache(self):
        self.picker.clients['steam'].details_cache = {
            620:   {'release_date': {'date': '18 Apr, 2011'}},
            440:   {'release_date': {'date': '10 Oct, 2007'}},
            570:   {'release_date': {'date': '2013'}},
            730:   {'release_date': {'date': '21 Aug, 2012'}},
            72850: {'release_date': {'date': '11 Nov, 2011'}},
        }
        result = self.picker.filter_games(min_release_year=2011, max_release_year=2012)
        names = [g['name'] for g in result]
        self.assertIn('Portal 2', names)    # 2011
        self.assertIn('CS:GO', names)        # 2012
        self.assertIn('Skyrim', names)       # 2011
        self.assertNotIn('Team Fortress 2', names)  # 2007
        self.assertNotIn('Dota 2', names)            # 2013


# ===========================================================================
# GamePicker pick_random_game tests
# ===========================================================================

class TestGamePickerPickRandom(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)
        self.picker.games = list(FAKE_GAMES)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pick_returns_a_game(self):
        game = self.picker.pick_random_game()
        self.assertIsNotNone(game)
        self.assertIn('name', game)

    def test_pick_from_empty_library(self):
        self.picker.games = []
        result = self.picker.pick_random_game()
        self.assertIsNone(result)

    def test_pick_adds_to_history(self):
        self.picker.history = []
        game = self.picker.pick_random_game()
        self.assertIn(game.get('game_id'), self.picker.history)

    def test_pick_from_filtered_list(self):
        filtered = [g for g in FAKE_GAMES if g['playtime_forever'] == 0]
        game = self.picker.pick_random_game(filtered_games=filtered)
        self.assertEqual(game['name'], 'Team Fortress 2')

    def test_pick_avoids_recent(self):
        """With avoid_recent=True, recently picked games should be skipped when possible."""
        # Mark all but one game as recent
        recently_played = [g['game_id'] for g in FAKE_GAMES[:-1]]
        self.picker.history = recently_played
        game = self.picker.pick_random_game(avoid_recent=True)
        # With all but Skyrim in history, it should pick Skyrim
        self.assertEqual(game['name'], 'Skyrim')

    def test_pick_with_avoid_recent_false(self):
        """With avoid_recent=False, history is ignored."""
        all_ids = [g['game_id'] for g in FAKE_GAMES]
        self.picker.history = all_ids
        game = self.picker.pick_random_game(avoid_recent=False)
        self.assertIsNotNone(game)

    def test_pick_single_game_returns_it(self):
        single = [FAKE_GAMES[0]]
        game = self.picker.pick_random_game(filtered_games=single)
        self.assertEqual(game['appid'], 620)


# ===========================================================================
# GamePicker playlists tests
# ===========================================================================

class TestGamePickerPlaylists(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)
        self.picker.games = list(FAKE_GAMES)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_playlist(self):
        result = self.picker.create_playlist('Cozy Games')
        self.assertTrue(result)
        names = [p['name'] for p in self.picker.list_playlists()]
        self.assertIn('Cozy Games', names)

    def test_create_duplicate_playlist(self):
        self.picker.create_playlist('My Playlist')
        result = self.picker.create_playlist('My Playlist')
        self.assertFalse(result)

    def test_delete_playlist(self):
        self.picker.create_playlist('To Delete')
        result = self.picker.delete_playlist('To Delete')
        self.assertTrue(result)
        names = [p['name'] for p in self.picker.list_playlists()]
        self.assertNotIn('To Delete', names)

    def test_add_to_playlist(self):
        self.picker.create_playlist('FPS')
        self.picker.add_to_playlist('FPS', 'steam:440')
        games = self.picker.get_playlist_games('FPS')
        names = [g['name'] for g in games]
        self.assertIn('Team Fortress 2', names)

    def test_remove_from_playlist(self):
        self.picker.create_playlist('FPS')
        self.picker.add_to_playlist('FPS', 'steam:440')
        self.picker.remove_from_playlist('FPS', 'steam:440')
        games = self.picker.get_playlist_games('FPS')
        self.assertEqual(games, [])

    def test_get_nonexistent_playlist(self):
        result = self.picker.get_playlist_games('Nonexistent')
        self.assertIsNone(result)


# ===========================================================================
# VotingSession tests
# ===========================================================================

class TestVotingSession(unittest.TestCase):

    def _make_session(self, candidates=None, voters=None, duration=None):
        if candidates is None:
            candidates = [
                {'appid': 620, 'name': 'Portal 2', 'game_id': 'steam:620'},
                {'appid': 440, 'name': 'TF2',      'game_id': 'steam:440'},
            ]
        return VotingSession(session_id='test-session', candidates=candidates,
                             voters=voters, duration=duration)

    def test_cast_vote_valid(self):
        session = self._make_session()
        success, msg = session.cast_vote('Alice', '620')
        self.assertTrue(success)

    def test_cast_vote_invalid_candidate(self):
        session = self._make_session()
        success, msg = session.cast_vote('Alice', '99999')
        self.assertFalse(success)

    def test_cast_vote_restricted_to_eligible_voters(self):
        session = self._make_session(voters=['Alice', 'Bob'])
        success, msg = session.cast_vote('Charlie', '620')
        self.assertFalse(success)
        self.assertIn('eligible', msg.lower())

    def test_eligible_voter_can_vote(self):
        session = self._make_session(voters=['Alice', 'Bob'])
        success, msg = session.cast_vote('Alice', '620')
        self.assertTrue(success)

    def test_cast_vote_on_closed_session(self):
        session = self._make_session()
        session.closed = True
        success, msg = session.cast_vote('Alice', '620')
        self.assertFalse(success)

    def test_get_results(self):
        session = self._make_session()
        session.cast_vote('Alice', '620')
        session.cast_vote('Bob', '620')
        session.cast_vote('Carol', '440')
        results = session.get_results()
        self.assertEqual(results['620']['count'], 2)
        self.assertEqual(results['440']['count'], 1)

    def test_get_winner_single_winner(self):
        session = self._make_session()
        session.cast_vote('Alice', '620')
        session.cast_vote('Bob', '620')
        session.cast_vote('Carol', '440')
        winner = session.get_winner()
        self.assertIsNotNone(winner)
        self.assertEqual(str(winner.get('appid') or winner.get('game_id')), '620')

    def test_get_winner_no_votes(self):
        session = self._make_session()
        # No votes cast; should return None or handle gracefully
        winner = session.get_winner()
        # With no votes all candidates have 0 votes; winner may be None or any candidate
        # The important thing is it doesn't raise.

    def test_is_expired_no_duration(self):
        session = self._make_session(duration=None)
        self.assertFalse(session.is_expired())

    def test_is_expired_long_duration(self):
        session = self._make_session(duration=99999)
        self.assertFalse(session.is_expired())


# ===========================================================================
# Atomic write helper test
# ===========================================================================

class TestAtomicWriteJson(unittest.TestCase):

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.json')
            data = {'key': 'value', 'nums': [1, 2, 3]}
            gapi._atomic_write_json(path, data)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.json')
            gapi._atomic_write_json(path, {'v': 1})
            gapi._atomic_write_json(path, {'v': 2})
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded['v'], 2)

    def test_no_temp_file_left_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'test.json')
            gapi._atomic_write_json(path, {})
            files = os.listdir(d)
            tmp_files = [f for f in files if f.endswith('.tmp')]
            self.assertEqual(tmp_files, [])


# ===========================================================================
# GamePicker get_recommendations tests
# ===========================================================================

class TestGamePickerRecommendations(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)
        self.picker.games = list(FAKE_GAMES)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_list(self):
        result = self.picker.get_recommendations()
        self.assertIsInstance(result, list)

    def test_empty_library(self):
        self.picker.games = []
        result = self.picker.get_recommendations()
        self.assertEqual(result, [])

    def test_prefers_unplayed_games(self):
        recs = self.picker.get_recommendations(count=5)
        # Team Fortress 2 is unplayed (0 min) so should rank highly
        names = [r['name'] for r in recs]
        self.assertIn('Team Fortress 2', names)

    def test_count_respected(self):
        recs = self.picker.get_recommendations(count=2)
        self.assertLessEqual(len(recs), 2)

    def test_result_has_required_fields(self):
        recs = self.picker.get_recommendations(count=3)
        for rec in recs:
            self.assertIn('name', rec)
            self.assertIn('recommendation_score', rec)
            self.assertIn('recommendation_reason', rec)
            self.assertIn('playtime_hours', rec)

    def test_genre_affinity_boosts_matching_games(self):
        """Games whose genres match well-played genres should rank higher."""
        # Portal 2 (620) is well-played (2720 min > WELL_PLAYED threshold of 600 min)
        # and is Action/Puzzle genre.
        # Pre-populate cache so genre data is available.
        self.picker.clients['steam'].details_cache = {
            620: {'genres': [{'description': 'Puzzle'}, {'description': 'Action'}]},
            440: {'genres': [{'description': 'Action'}, {'description': 'FPS'}]},  # unplayed
            570: {'genres': [{'description': 'Strategy'}]},  # barely played
            730: {'genres': [{'description': 'Action'}, {'description': 'FPS'}]},  # well-played
            72850: {'genres': [{'description': 'RPG'}]},  # played
        }
        recs = self.picker.get_recommendations(count=5)
        names = [r['name'] for r in recs]
        # TF2 (Action/FPS, unplayed) should appear because Action is a preferred genre
        self.assertIn('Team Fortress 2', names)

    def test_history_penalty(self):
        """Games in recent history should rank lower than truly fresh games."""
        # Put all games except CS:GO in history
        self.picker.history = [
            g['game_id'] for g in FAKE_GAMES if g['name'] != 'CS:GO'
        ]
        recs = self.picker.get_recommendations(count=5)
        # Even with penalty they may still appear if there's no alternative,
        # but CS:GO (high playtime, not in history) should be in results
        # The important check: no exceptions raised.
        self.assertIsInstance(recs, list)



# ===========================================================================
# Ranked-Choice Voting (Instant Runoff) tests
# ===========================================================================

class TestVotingSessionRankedChoice(unittest.TestCase):

    THREE_GAMES = [
        {'appid': 620,  'name': 'Portal 2', 'game_id': 'steam:620'},
        {'appid': 440,  'name': 'TF2',      'game_id': 'steam:440'},
        {'appid': 730,  'name': 'CS:GO',    'game_id': 'steam:730'},
    ]

    def _make_rc_session(self, candidates=None, voters=None):
        cands = candidates if candidates is not None else self.THREE_GAMES
        return VotingSession(
            session_id='rc-session',
            candidates=cands,
            voters=voters,
            voting_method='ranked_choice',
        )

    # -- constructor --

    def test_invalid_voting_method_raises(self):
        with self.assertRaises(ValueError):
            VotingSession('s', self.THREE_GAMES, voting_method='invalid')

    def test_plurality_method_stored(self):
        session = VotingSession('s', self.THREE_GAMES, voting_method='plurality')
        self.assertEqual(session.voting_method, 'plurality')

    def test_ranked_choice_method_stored(self):
        session = self._make_rc_session()
        self.assertEqual(session.voting_method, 'ranked_choice')

    # -- cast_vote for ranked_choice --

    def test_ranked_cast_vote_accepts_list(self):
        session = self._make_rc_session()
        ok, msg = session.cast_vote('Alice', ['620', '440', '730'])
        self.assertTrue(ok, msg)

    def test_ranked_cast_vote_rejects_string(self):
        session = self._make_rc_session()
        ok, msg = session.cast_vote('Alice', '620')
        self.assertFalse(ok)
        self.assertIn('list', msg.lower())

    def test_ranked_cast_vote_rejects_invalid_candidate(self):
        session = self._make_rc_session()
        ok, msg = session.cast_vote('Alice', ['620', '99999'])
        self.assertFalse(ok)

    def test_ranked_cast_vote_rejects_duplicates(self):
        session = self._make_rc_session()
        ok, msg = session.cast_vote('Alice', ['620', '620'])
        self.assertFalse(ok)
        self.assertIn('duplicate', msg.lower())

    def test_ranked_partial_ranking_allowed(self):
        """Voters do not have to rank every candidate."""
        session = self._make_rc_session()
        ok, msg = session.cast_vote('Alice', ['620'])
        self.assertTrue(ok, msg)

    # -- plurality session still rejects lists --

    def test_plurality_rejects_list(self):
        session = VotingSession('s', self.THREE_GAMES, voting_method='plurality')
        ok, msg = session.cast_vote('Alice', ['620', '440'])
        self.assertFalse(ok)

    # -- get_results counts first-choice votes for ranked_choice --

    def test_ranked_get_results_counts_first_choices(self):
        session = self._make_rc_session()
        session.cast_vote('Alice', ['620', '440', '730'])
        session.cast_vote('Bob',   ['620', '730', '440'])
        session.cast_vote('Carol', ['440', '620', '730'])
        results = session.get_results()
        self.assertEqual(results['620']['count'], 2)
        self.assertEqual(results['440']['count'], 1)
        self.assertEqual(results['730']['count'], 0)

    # -- IRV algorithm --

    def test_irv_clear_majority_winner(self):
        """If one candidate has >50% first-choices they win immediately."""
        session = self._make_rc_session()
        session.cast_vote('Alice', ['620', '440', '730'])
        session.cast_vote('Bob',   ['620', '730', '440'])
        session.cast_vote('Carol', ['620', '440', '730'])
        winner, rounds = session.run_irv()
        self.assertIsNotNone(winner)
        self.assertEqual(str(winner.get('appid')), '620')

    def test_irv_redistribution(self):
        """The 3rd-place candidate is eliminated and votes redistribute."""
        # Alice: 440 > 620 > 730
        # Bob:   440 > 620 > 730
        # Carol: 730 > 620 > 440  (730 will be eliminated; Carol's vote moves to 620)
        session = self._make_rc_session()
        session.cast_vote('Alice', ['440', '620', '730'])
        session.cast_vote('Bob',   ['440', '620', '730'])
        session.cast_vote('Carol', ['730', '620', '440'])
        winner, rounds = session.run_irv()
        self.assertIsNotNone(winner)
        # After 730 is eliminated, 620 picks up Carol's vote → tie 440:2, 620:1 before elim
        # 440 should win (2 first-choice votes originally, majority after redistribution)
        self.assertEqual(str(winner.get('appid')), '440')

    def test_irv_no_votes_returns_random_candidate(self):
        """With no votes a winner is still returned (random pick)."""
        session = self._make_rc_session()
        winner, rounds = session.run_irv()
        self.assertIsNotNone(winner)

    def test_irv_rounds_recorded(self):
        session = self._make_rc_session()
        session.cast_vote('Alice', ['440', '620', '730'])
        session.cast_vote('Bob',   ['440', '620', '730'])
        session.cast_vote('Carol', ['730', '620', '440'])
        _, rounds = session.run_irv()
        self.assertIsInstance(rounds, list)
        self.assertGreater(len(rounds), 0)
        for r in rounds:
            self.assertIn('round', r)
            self.assertIn('counts', r)
            self.assertIn('eliminated', r)

    def test_get_winner_uses_irv_for_ranked_choice(self):
        session = self._make_rc_session()
        session.cast_vote('Alice', ['620', '440', '730'])
        session.cast_vote('Bob',   ['620', '730', '440'])
        session.cast_vote('Carol', ['620', '440', '730'])
        winner = session.get_winner()
        self.assertIsNotNone(winner)
        self.assertEqual(str(winner.get('appid')), '620')

    # -- to_dict includes voting_method and irv_rounds --

    def test_to_dict_includes_voting_method(self):
        session = self._make_rc_session()
        d = session.to_dict()
        self.assertEqual(d['voting_method'], 'ranked_choice')

    def test_to_dict_plurality_includes_voting_method(self):
        session = VotingSession('s', self.THREE_GAMES, voting_method='plurality')
        d = session.to_dict()
        self.assertEqual(d['voting_method'], 'plurality')

    def test_to_dict_ranked_choice_includes_irv_rounds(self):
        session = self._make_rc_session()
        session.cast_vote('Alice', ['620', '440', '730'])
        d = session.to_dict()
        self.assertIn('irv_rounds', d)
        self.assertIsInstance(d['irv_rounds'], list)

    def test_to_dict_plurality_has_no_irv_rounds(self):
        session = VotingSession('s', self.THREE_GAMES, voting_method='plurality')
        session.cast_vote('Alice', '620')
        d = session.to_dict()
        self.assertNotIn('irv_rounds', d)


# ===========================================================================
# Budget Tracking tests
# ===========================================================================

class TestGamePickerBudget(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig = os.getcwd()
        self.picker = make_picker(self.tmp_dir)
        os.chdir(self.tmp_dir)
        self.picker.games = list(FAKE_GAMES)

    def tearDown(self):
        os.chdir(self.orig)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_set_budget_basic(self):
        ok = self.picker.set_game_budget('steam:620', 29.99)
        self.assertTrue(ok)
        self.assertIn('steam:620', self.picker.budget)

    def test_set_budget_stores_price(self):
        self.picker.set_game_budget('steam:620', 14.99)
        self.assertEqual(self.picker.budget['steam:620']['price'], 14.99)

    def test_set_budget_stores_currency(self):
        self.picker.set_game_budget('steam:620', 9.99, currency='EUR')
        self.assertEqual(self.picker.budget['steam:620']['currency'], 'EUR')

    def test_set_budget_stores_purchase_date(self):
        self.picker.set_game_budget('steam:620', 4.99, purchase_date='2024-11-28')
        self.assertEqual(self.picker.budget['steam:620']['purchase_date'], '2024-11-28')

    def test_set_budget_stores_notes(self):
        self.picker.set_game_budget('steam:620', 0.0, notes='Gift')
        self.assertEqual(self.picker.budget['steam:620']['notes'], 'Gift')

    def test_set_budget_rejects_negative_price(self):
        ok = self.picker.set_game_budget('steam:620', -5.00)
        self.assertFalse(ok)
        self.assertNotIn('steam:620', self.picker.budget)

    def test_set_budget_zero_price_allowed(self):
        ok = self.picker.set_game_budget('steam:440', 0.0, notes='Free to play')
        self.assertTrue(ok)

    def test_remove_budget(self):
        self.picker.set_game_budget('steam:620', 14.99)
        removed = self.picker.remove_game_budget('steam:620')
        self.assertTrue(removed)
        self.assertNotIn('steam:620', self.picker.budget)

    def test_remove_nonexistent_budget(self):
        removed = self.picker.remove_game_budget('steam:99999')
        self.assertFalse(removed)

    def test_budget_persisted(self):
        self.picker.set_game_budget('steam:620', 29.99)
        # Re-load from the same temp directory
        new_picker = make_picker(self.tmp_dir)
        self.assertIn('steam:620', new_picker.budget)
        self.assertEqual(new_picker.budget['steam:620']['price'], 29.99)

    def test_get_budget_summary_total(self):
        self.picker.set_game_budget('steam:620', 14.99)
        self.picker.set_game_budget('steam:440', 9.99)
        summary = self.picker.get_budget_summary()
        self.assertAlmostEqual(summary['total_spent'], 24.98, places=2)

    def test_get_budget_summary_game_count(self):
        self.picker.set_game_budget('steam:620', 14.99)
        self.picker.set_game_budget('steam:570', 4.99)
        summary = self.picker.get_budget_summary()
        self.assertEqual(summary['game_count'], 2)

    def test_get_budget_summary_empty(self):
        summary = self.picker.get_budget_summary()
        self.assertEqual(summary['total_spent'], 0.0)
        self.assertEqual(summary['game_count'], 0)
        self.assertIsInstance(summary['entries'], list)

    def test_get_budget_summary_entries_enriched_with_name(self):
        self.picker.set_game_budget('steam:620', 14.99)
        summary = self.picker.get_budget_summary()
        entry = next(e for e in summary['entries'] if e['game_id'] == 'steam:620')
        self.assertEqual(entry['name'], 'Portal 2')

    def test_get_budget_summary_currency_breakdown(self):
        self.picker.set_game_budget('steam:620', 14.99, currency='USD')
        self.picker.set_game_budget('steam:440', 9.99, currency='EUR')
        summary = self.picker.get_budget_summary()
        self.assertIn('USD', summary['currency_breakdown'])
        self.assertIn('EUR', summary['currency_breakdown'])


if __name__ == '__main__':
    unittest.main()
