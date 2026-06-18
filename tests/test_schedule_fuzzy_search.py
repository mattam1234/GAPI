#!/usr/bin/env python3
"""Validate schedule fuzzy search for games and attendees.

Covers the matchers (``_fuzzy_search_games`` / ``_fuzzy_search_users``) and the
request-input helpers (``_parse_search_limit`` / ``_safe_playtime_hours``) that
back the /api/schedule/search-* endpoints.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gapi_gui import (
    _fuzzy_search_games,
    _fuzzy_search_users,
    _parse_search_limit,
    _safe_playtime_hours,
)


def _names(results):
    return [r.get('name') for r in results]


class TestParseSearchLimit(unittest.TestCase):
    def test_defaults_on_invalid(self):
        self.assertEqual(_parse_search_limit(None), 10)
        self.assertEqual(_parse_search_limit('abc'), 10)
        self.assertEqual(_parse_search_limit(''), 10)

    def test_parses_numeric_string(self):
        self.assertEqual(_parse_search_limit('5'), 5)

    def test_non_positive_falls_back_to_default(self):
        self.assertEqual(_parse_search_limit(0), 10)
        self.assertEqual(_parse_search_limit(-3), 10)

    def test_clamped_to_maximum(self):
        self.assertEqual(_parse_search_limit(999999), 50)


class TestSafePlaytimeHours(unittest.TestCase):
    def test_uses_explicit_hours(self):
        self.assertEqual(_safe_playtime_hours({'playtime_hours': 3.25}), 3.2)

    def test_falls_back_to_minutes(self):
        self.assertEqual(_safe_playtime_hours({'playtime_forever': 600}), 10.0)

    def test_string_minutes_tolerated(self):
        self.assertEqual(_safe_playtime_hours({'playtime_forever': '600'}), 10.0)

    def test_missing_returns_zero(self):
        self.assertEqual(_safe_playtime_hours({}), 0.0)

    def test_garbage_returns_zero(self):
        self.assertEqual(_safe_playtime_hours({'playtime_forever': 'oops'}), 0.0)


class TestFuzzySearchGames(unittest.TestCase):
    def setUp(self):
        self.games = [
            {'name': 'Portal 2', 'appid': '620'},
            {'name': 'Portal', 'appid': '400'},
            {'name': 'Teleport Masters', 'appid': '999'},
            {'name': 'DOOM Eternal', 'appid': '782330'},
        ]

    def test_empty_query_returns_empty(self):
        self.assertEqual(_fuzzy_search_games('', self.games), [])

    def test_empty_games_returns_empty(self):
        self.assertEqual(_fuzzy_search_games('portal', []), [])

    def test_exact_appid_match_ranks_first(self):
        results = _fuzzy_search_games('620', self.games)
        self.assertEqual(results[0]['name'], 'Portal 2')

    def test_appid_substring_match(self):
        # '78233' is contained in DOOM's appid 782330
        results = _fuzzy_search_games('78233', self.games)
        self.assertIn('DOOM Eternal', _names(results))

    def test_prefix_matches_returned_internal_substring_excluded(self):
        # The matcher uses prefix-boost + sequence ratio, NOT internal substring
        # matching: 'Portal'/'Portal 2' start with 'port' (high score), while
        # 'Teleport Masters' only contains it internally and falls below the
        # 0.6 threshold, so it is excluded.
        names = _names(_fuzzy_search_games('port', self.games))
        self.assertIn('Portal', names)
        self.assertIn('Portal 2', names)
        self.assertNotIn('Teleport Masters', names)

    def test_dissimilar_excluded_by_threshold(self):
        results = _fuzzy_search_games('portal', self.games)
        self.assertNotIn('DOOM Eternal', _names(results))

    def test_case_insensitive(self):
        self.assertTrue(_fuzzy_search_games('PORTAL', self.games))

    def test_limit_respected(self):
        many = [{'name': f'Portal {i}', 'appid': str(i)} for i in range(20)]
        self.assertLessEqual(len(_fuzzy_search_games('portal', many, limit=5)), 5)

    def test_app_id_alternate_key(self):
        games = [{'name': 'Half-Life', 'app_id': '70'}]
        results = _fuzzy_search_games('70', games)
        self.assertEqual(results[0]['name'], 'Half-Life')

    def test_ties_sorted_by_name(self):
        games = [
            {'name': 'Zeta', 'appid': '620'},
            {'name': 'Alpha', 'appid': '620'},
        ]
        # Both are exact appid matches (score 1.0); name breaks the tie.
        self.assertEqual(_names(_fuzzy_search_games('620', games)), ['Alpha', 'Zeta'])


class TestFuzzySearchUsers(unittest.TestCase):
    def setUp(self):
        self.users = [
            {'name': 'Alice'},
            {'name': 'Alicia'},
            {'name': 'Bob'},
            {'name': 'Charlie'},
        ]

    def test_empty_query_returns_empty(self):
        self.assertEqual(_fuzzy_search_users('', self.users), [])

    def test_empty_users_returns_empty(self):
        self.assertEqual(_fuzzy_search_users('alice', []), [])

    def test_exact_match_ranks_first(self):
        self.assertEqual(_fuzzy_search_users('alice', self.users)[0]['name'], 'Alice')

    def test_prefix_match_included(self):
        names = _names(_fuzzy_search_users('ali', self.users))
        self.assertIn('Alice', names)
        self.assertIn('Alicia', names)

    def test_dissimilar_excluded(self):
        self.assertNotIn('Bob', _names(_fuzzy_search_users('alice', self.users)))

    def test_case_insensitive(self):
        self.assertTrue(_fuzzy_search_users('ALICE', self.users))

    def test_limit_respected(self):
        users = [{'name': f'Alice{i}'} for i in range(20)]
        self.assertLessEqual(len(_fuzzy_search_users('alice', users, limit=5)), 5)


if __name__ == '__main__':
    unittest.main()
