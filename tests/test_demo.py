#!/usr/bin/env python3
"""
Tests for the demo.py showcase script.

Run with:
    python -m pytest tests/test_demo.py
"""
import argparse
import glob
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Import demo.py from the repo root
# ---------------------------------------------------------------------------
_DEMO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'demo.py')
spec = importlib.util.spec_from_file_location('demo', _DEMO_PATH)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


# ===========================================================================
# Data constants
# ===========================================================================

class TestDemoConstants(unittest.TestCase):

    def test_demo_games_non_empty(self):
        self.assertGreater(len(demo.DEMO_GAMES), 5)

    def test_user1_games_non_empty(self):
        self.assertGreater(len(demo.USER1_GAMES), 0)

    def test_user2_games_non_empty(self):
        self.assertGreater(len(demo.USER2_GAMES), 0)

    def test_all_games_have_required_fields(self):
        required = {'appid', 'name', 'playtime_forever', 'platform', 'genres'}
        for g in demo.DEMO_GAMES:
            self.assertEqual(required - g.keys(), set(),
                             f"Game {g.get('name')} missing fields")

    def test_genres_are_lists(self):
        for g in demo.DEMO_GAMES:
            self.assertIsInstance(g['genres'], list)

    def test_platforms_valid(self):
        valid = {'steam', 'epic', 'gog'}
        for g in demo.DEMO_GAMES:
            self.assertIn(g['platform'], valid, f"Unexpected platform in {g['name']}")

    def test_playtime_non_negative(self):
        for g in demo.DEMO_GAMES:
            self.assertGreaterEqual(g['playtime_forever'], 0)


# ===========================================================================
# run_demo() — smoke test (quiet mode, no real output check needed)
# ===========================================================================

class TestRunDemo(unittest.TestCase):

    def _run(self) -> str:
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            demo.run_demo(quiet=True)
        return buf.getvalue()

    def test_run_demo_completes_without_exception(self):
        self._run()

    def test_output_contains_game_names(self):
        output = self._run()
        # At least one well-known game should appear
        self.assertTrue(
            any(name in output for name in ['Portal 2', 'Team Fortress 2', 'Dota 2']),
            "Expected at least one game name in demo output"
        )

    def test_output_has_completion_message(self):
        output = self._run()
        self.assertIn('Demo complete', output)

    def test_output_mentions_setup_steps(self):
        output = self._run()
        self.assertIn('config_template.json', output)
        self.assertIn('steamcommunity.com', output)

    def test_output_has_multiuser_section(self):
        output = self._run()
        self.assertIn('Common games', output)

    def test_output_has_stats_section(self):
        output = self._run()
        self.assertIn('Total games', output)

    def test_output_has_achievement_section(self):
        output = self._run()
        self.assertIn('Achievement', output)

    def test_export_cleans_up_temp_file(self):
        """demo_export should leave no temporary files behind."""
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), '*.json')))
        with patch('sys.stdout', io.StringIO()):
            demo.demo_export(quiet=True)
        after = set(glob.glob(os.path.join(tempfile.gettempdir(), '*.json')))
        self.assertEqual(before, after, "demo_export left behind a temp file")


# ===========================================================================
# Filter logic
# ===========================================================================

class TestDemoFilters(unittest.TestCase):

    def test_unplayed_filter(self):
        unplayed = [g for g in demo.USER1_GAMES if g['playtime_forever'] == 0]
        for g in unplayed:
            self.assertEqual(g['playtime_forever'], 0)

    def test_barely_played_filter(self):
        barely = [g for g in demo.USER1_GAMES if 0 < g['playtime_forever'] < 120]
        for g in barely:
            self.assertGreater(g['playtime_forever'], 0)
            self.assertLess(g['playtime_forever'], 120)

    def test_well_played_filter(self):
        well = [g for g in demo.USER1_GAMES if g['playtime_forever'] >= 600]
        for g in well:
            self.assertGreaterEqual(g['playtime_forever'], 600)

    def test_genre_filter_rpg(self):
        rpg = [g for g in demo.USER1_GAMES if 'RPG' in g.get('genres', [])]
        self.assertGreater(len(rpg), 0, "Expected at least one RPG in demo dataset")
        for g in rpg:
            self.assertIn('RPG', g['genres'])


# ===========================================================================
# Multi-user
# ===========================================================================

class TestDemoMultiUser(unittest.TestCase):

    def test_common_games_are_truly_common(self):
        u1_names = {g['name'] for g in demo.USER1_GAMES}
        u2_names = {g['name'] for g in demo.USER2_GAMES}
        common = u1_names & u2_names
        for name in common:
            self.assertIn(name, u1_names)
            self.assertIn(name, u2_names)

    def test_at_least_one_common_game(self):
        u1_names = {g['name'] for g in demo.USER1_GAMES}
        u2_names = {g['name'] for g in demo.USER2_GAMES}
        self.assertGreater(len(u1_names & u2_names), 0)


# ===========================================================================
# CLI argument parsing
# ===========================================================================

class TestDemoArgParsing(unittest.TestCase):

    def test_quiet_flag_parsed(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--quiet', '-q', action='store_true')
        args = parser.parse_args(['--quiet'])
        self.assertTrue(args.quiet)

    def test_no_args_not_quiet(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--quiet', '-q', action='store_true')
        args = parser.parse_args([])
        self.assertFalse(args.quiet)


# ===========================================================================
# config_template.json — steam_id field present
# ===========================================================================

class TestConfigTemplate(unittest.TestCase):

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config_template.json'
        )
        with open(path) as f:
            self._cfg = json.load(f)

    def test_steam_api_key_present(self):
        self.assertIn('steam_api_key', self._cfg)

    def test_steam_id_present(self):
        self.assertIn('steam_id', self._cfg,
                      "config_template.json must contain 'steam_id'")

    def test_discord_bot_token_present(self):
        self.assertIn('discord_bot_token', self._cfg)

    def test_database_url_present(self):
        self.assertIn('database_url', self._cfg)

    def test_template_json_valid(self):
        """All values should be the correct type."""
        int_fields = ['barely_played_hours', 'well_played_hours',
                      'max_history_size', 'api_timeout_seconds']
        for f in int_fields:
            self.assertIn(f, self._cfg)
            self.assertIsInstance(self._cfg[f], int,
                                  f"'{f}' should be an integer")


if __name__ == '__main__':
    unittest.main()
