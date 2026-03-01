#!/usr/bin/env python3
"""
Tests for:
  * VR game filtering in gapi.GamePicker.filter_games()
  * VR filter wired into the Web API (gapi_gui.py)
  * Voice command JS in the Web GUI HTML
  * Controller / gamepad JS in desktop-app/renderer/renderer.js
  * ROADMAP Under Consideration entries updated

Run with:
    python -m pytest tests/test_vr_controller_voice.py
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch, call

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(ROOT, *parts)


def _read(*parts):
    with open(_path(*parts)) as f:
        return f.read()


# ===========================================================================
# VR filter — gapi.py logic
# ===========================================================================

class TestVRFilterLogic(unittest.TestCase):

    def _make_picker(self, games):
        """Return a minimal GamePicker with the given games list."""
        import sys
        sys.path.insert(0, ROOT)
        import gapi
        picker = gapi.GamePicker.__new__(gapi.GamePicker)
        import logging
        picker._log = logging.getLogger('test')
        picker.config = {}
        picker.MAX_HISTORY = 20
        picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        picker.API_TIMEOUT = 10
        picker.clients = {}
        picker.steam_client = None
        picker.games = games
        picker.history = []
        picker.favorites = []
        picker.reviews = {}
        picker.tags = {}
        # attach a minimal tag_service stub
        ts = MagicMock()
        ts.filter_by_tag.side_effect = lambda tag, games: games
        picker.tag_service = ts
        return picker

    def _make_game(self, name, appid, categories=None):
        return {
            'name': name,
            'appid': appid,
            'game_id': str(appid),
            'platform': 'steam',
            'playtime_forever': 0,
        }, categories or []

    def _patch_clients(self, picker, game_details_map):
        """Patch picker.clients so get_game_details returns the given details."""
        client = MagicMock()

        def _get_details(game_id):
            return game_details_map.get(str(game_id), {})

        client.get_game_details.side_effect = _get_details
        picker.clients = {'steam': client}

    def test_vr_filter_none_returns_all(self):
        """With vr_filter=None, all games should be returned."""
        game_a = {'name': 'A', 'appid': 1, 'game_id': '1', 'platform': 'steam', 'playtime_forever': 0}
        game_b = {'name': 'B', 'appid': 2, 'game_id': '2', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game_a, game_b])
        result = picker.filter_games(vr_filter=None)
        self.assertEqual(len(result), 2)

    def test_vr_supported_filter_includes_vr_supported_game(self):
        """vr_supported filter should include games with 'VR Supported' category."""
        game = {'name': 'VR Game', 'appid': 10, 'game_id': '10', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Supported'}]}
        self._patch_clients(picker, {'10': details})
        result = picker.filter_games(vr_filter='vr_supported')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'VR Game')

    def test_vr_supported_filter_includes_vr_only_game(self):
        """vr_supported should also include 'VR Only' games (they are VR capable)."""
        game = {'name': 'VR Only Game', 'appid': 11, 'game_id': '11', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Only'}]}
        self._patch_clients(picker, {'11': details})
        result = picker.filter_games(vr_filter='vr_supported')
        self.assertEqual(len(result), 1)

    def test_vr_supported_filter_excludes_non_vr_game(self):
        """vr_supported should exclude games without any VR category."""
        game = {'name': 'Normal Game', 'appid': 12, 'game_id': '12', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'Single-player'}]}
        self._patch_clients(picker, {'12': details})
        result = picker.filter_games(vr_filter='vr_supported')
        self.assertEqual(len(result), 0)

    def test_vr_only_filter_includes_vr_only_game(self):
        """vr_only should include games that require a VR headset."""
        game = {'name': 'VR Req', 'appid': 20, 'game_id': '20', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Only'}]}
        self._patch_clients(picker, {'20': details})
        result = picker.filter_games(vr_filter='vr_only')
        self.assertEqual(len(result), 1)

    def test_vr_only_filter_excludes_vr_supported_but_not_required(self):
        """vr_only should exclude 'VR Supported' (optional VR) games."""
        game = {'name': 'VR Opt', 'appid': 21, 'game_id': '21', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Supported'}]}
        self._patch_clients(picker, {'21': details})
        result = picker.filter_games(vr_filter='vr_only')
        self.assertEqual(len(result), 0)

    def test_no_vr_filter_excludes_vr_supported(self):
        """no_vr should exclude VR Supported games."""
        game = {'name': 'VR Game', 'appid': 30, 'game_id': '30', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Supported'}]}
        self._patch_clients(picker, {'30': details})
        result = picker.filter_games(vr_filter='no_vr')
        self.assertEqual(len(result), 0)

    def test_no_vr_filter_excludes_vr_only(self):
        """no_vr should also exclude VR Only games."""
        game = {'name': 'VR Only', 'appid': 31, 'game_id': '31', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'VR Only'}]}
        self._patch_clients(picker, {'31': details})
        result = picker.filter_games(vr_filter='no_vr')
        self.assertEqual(len(result), 0)

    def test_no_vr_filter_includes_non_vr_game(self):
        """no_vr should keep games without VR categories."""
        game = {'name': 'Normal', 'appid': 32, 'game_id': '32', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        details = {'categories': [{'description': 'Single-player'}]}
        self._patch_clients(picker, {'32': details})
        result = picker.filter_games(vr_filter='no_vr')
        self.assertEqual(len(result), 1)

    def test_vr_supported_filter_excludes_games_without_details(self):
        """Games without detail data should be excluded for positive VR filters."""
        game = {'name': 'No Details', 'appid': 40, 'game_id': '40', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        self._patch_clients(picker, {})  # no details available
        result = picker.filter_games(vr_filter='vr_supported')
        self.assertEqual(len(result), 0)

    def test_no_vr_filter_includes_games_without_details(self):
        """Games without detail data should be kept for no_vr (benefit of doubt)."""
        game = {'name': 'No Details', 'appid': 41, 'game_id': '41', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([game])
        # When client returns empty dict (falsy), game has no known VR categories
        # so it should be included by no_vr (we can't confirm it's VR)
        self._patch_clients(picker, {})
        result = picker.filter_games(vr_filter='no_vr')
        # Empty dict → falsy → falls into "details unavailable" branch → kept for no_vr
        self.assertEqual(len(result), 1)

    def test_filter_games_signature_has_vr_filter_param(self):
        """filter_games must accept vr_filter keyword argument."""
        import inspect
        import sys
        sys.path.insert(0, ROOT)
        import gapi
        sig = inspect.signature(gapi.GamePicker.filter_games)
        self.assertIn('vr_filter', sig.parameters)

    def test_vr_filter_default_is_none(self):
        """vr_filter parameter default should be None."""
        import inspect
        import sys
        sys.path.insert(0, ROOT)
        import gapi
        sig = inspect.signature(gapi.GamePicker.filter_games)
        default = sig.parameters['vr_filter'].default
        self.assertIsNone(default)

    def test_mixed_vr_no_vr_list(self):
        """no_vr should return only the non-VR game from a mixed list."""
        g_vr  = {'name': 'VR', 'appid': 50, 'game_id': '50', 'platform': 'steam', 'playtime_forever': 0}
        g_std = {'name': 'STD', 'appid': 51, 'game_id': '51', 'platform': 'steam', 'playtime_forever': 0}
        picker = self._make_picker([g_vr, g_std])
        self._patch_clients(picker, {
            '50': {'categories': [{'description': 'VR Supported'}]},
            '51': {'categories': [{'description': 'Single-player'}]},
        })
        result = picker.filter_games(vr_filter='no_vr')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'STD')


# ===========================================================================
# VR filter — CLI argument exists in gapi.py
# ===========================================================================

class TestVRFilterCLI(unittest.TestCase):

    def test_vr_filter_cli_arg_exists(self):
        """gapi.py source must define --vr-filter CLI argument."""
        content = _read('gapi.py')
        self.assertIn('--vr-filter', content)

    def test_vr_filter_cli_choices_present(self):
        """--vr-filter must list vr_supported, vr_only, no_vr as choices."""
        content = _read('gapi.py')
        for choice in ('vr_supported', 'vr_only', 'no_vr'):
            self.assertIn(choice, content, f"Missing CLI choice: {choice}")

    def test_vr_filter_wired_into_adv_kwargs(self):
        """CLI picks must pass vr_filter to filter_games via adv_kwargs."""
        content = _read('gapi.py')
        self.assertIn("'vr_filter': args.vr_filter", content)

    def test_vr_filter_counted_in_needs_details(self):
        """needs_details must include vr_filter check in CLI section."""
        content = _read('gapi.py')
        # The needs_details check in the CLI must reference vr_filter
        self.assertIn('args.vr_filter is not None', content)


# ===========================================================================
# VR filter — Web API (gapi_gui.py)
# ===========================================================================

class TestVRFilterWebAPI(unittest.TestCase):

    def test_vr_filter_parsed_from_request(self):
        content = _read('gapi_gui.py')
        self.assertIn("data.get('vr_filter'", content)

    def test_vr_filter_validated_values(self):
        content = _read('gapi_gui.py')
        for v in ('vr_supported', 'vr_only', 'no_vr'):
            self.assertIn(v, content, f"API missing vr_filter value: {v}")

    def test_vr_filter_passed_to_adv_dict(self):
        content = _read('gapi_gui.py')
        self.assertIn("'vr_filter': vr_filter", content)

    def test_vr_filter_dropdown_in_html(self):
        content = _read('gapi_gui.py')
        self.assertIn('id="vr-filter"', content)
        self.assertIn('vr_supported', content)
        self.assertIn('vr_only', content)
        self.assertIn('no_vr', content)

    def test_pick_game_js_sends_vr_filter(self):
        """The pickGame() JS function must send vr_filter in its POST body."""
        content = _read('gapi_gui.py')
        self.assertIn('vr_filter: vrFilter', content)
        self.assertIn("getElementById('vr-filter')", content)


# ===========================================================================
# Voice commands — gapi_gui.py Web GUI
# ===========================================================================

class TestVoiceCommands(unittest.TestCase):

    def setUp(self):
        self._content = _read('gapi_gui.py')

    def test_voice_pick_button_exists(self):
        self.assertIn('voice-pick-btn', self._content)

    def test_toggle_voice_pick_function_exists(self):
        self.assertIn('toggleVoicePick', self._content)

    def test_speech_recognition_api_used(self):
        self.assertIn('SpeechRecognition', self._content)

    def test_voice_start_stop_functions(self):
        self.assertIn('_startVoice', self._content)
        self.assertIn('_stopVoice', self._content)

    def test_voice_commands_pick_and_reroll(self):
        """Voice commands for pick/choose/random and reroll/again/another must exist."""
        for cmd in ("'pick'", "'choose'", "'random'", "'reroll'", "'again'", "'another'"):
            self.assertIn(cmd, self._content, f"Missing voice command: {cmd}")

    def test_voice_stop_command(self):
        """'stop' voice command must halt recognition."""
        self.assertIn("'stop'", self._content)

    def test_voice_status_div_exists(self):
        self.assertIn('voice-status', self._content)

    def test_voice_uses_continuous_mode(self):
        self.assertIn('continuous = true', self._content)

    def test_voice_browser_compatibility_check(self):
        """Must check for both SpeechRecognition and webkitSpeechRecognition."""
        self.assertIn('webkitSpeechRecognition', self._content)

    def test_voice_auto_restart(self):
        """Voice recognition must restart after it ends to stay active."""
        self.assertIn('_voiceRecognition.start()', self._content)


# ===========================================================================
# Controller support — desktop-app/renderer/renderer.js
# ===========================================================================

class TestControllerSupport(unittest.TestCase):

    def setUp(self):
        self._content = _read('desktop-app', 'renderer', 'renderer.js')

    def test_gamepad_api_used(self):
        self.assertIn('getGamepads', self._content)

    def test_gamepadconnected_listener(self):
        self.assertIn('gamepadconnected', self._content)

    def test_gamepaddisconnected_listener(self):
        self.assertIn('gamepaddisconnected', self._content)

    def test_pick_on_a_button(self):
        """A/Cross button (0) should trigger pick."""
        self.assertIn('doPick', self._content)
        # Button 0 triggers doPick
        self.assertIn('justPressed(0)', self._content)

    def test_panel_navigation_buttons(self):
        """D-pad buttons should navigate panels."""
        self.assertIn('justPressed(14)', self._content)  # D-pad left
        self.assertIn('justPressed(15)', self._content)  # D-pad right

    def test_pick_mode_buttons(self):
        """LB/RB (4/5) should cycle pick modes."""
        self.assertIn('justPressed(4)', self._content)
        self.assertIn('justPressed(5)', self._content)

    def test_hud_overlay_exists(self):
        self.assertIn('gamepad-hud', self._content)

    def test_request_animation_frame_used(self):
        self.assertIn('requestAnimationFrame', self._content)

    def test_controller_panel_navigation_function(self):
        self.assertIn('_gotoPanel', self._content)

    def test_controller_set_pick_mode_function(self):
        self.assertIn('_setPickMode', self._content)

    def test_controller_scroll_support(self):
        self.assertIn('_scroll', self._content)
        self.assertIn('scrollBy', self._content)

    def test_controller_vr_filter_cycling(self):
        """LT/L2 should cycle through VR filter options."""
        self.assertIn('_cycleVrFilter', self._content)

    def test_controller_readme_updated(self):
        """desktop-app/README.md must mention controller/gamepad support."""
        readme = _read('desktop-app', 'README.md')
        self.assertTrue(
            any(kw.lower() in readme.lower() for kw in
                ('controller', 'gamepad', 'Gamepad API')),
            "README does not mention controller/gamepad support"
        )

    def test_desktop_test_file_covers_controller(self):
        """The desktop formatter test file should exist (already verified in previous tests)."""
        self.assertTrue(
            os.path.exists(_path('desktop-app', '__tests__', 'formatters.test.js'))
        )


# ===========================================================================
# ROADMAP Under Consideration updates
# ===========================================================================

class TestROADMAPUnderConsideration(unittest.TestCase):

    def setUp(self):
        self._content = _read('ROADMAP.md')

    def test_vr_filtering_marked_done(self):
        """VR game filtering should be ~~struck~~ as done."""
        self.assertIn('~~VR game filtering~~', self._content)

    def test_controller_support_marked_done(self):
        self.assertIn('~~Controller support for desktop app~~', self._content)

    def test_voice_commands_marked_done(self):
        self.assertIn('~~Voice commands for game picking~~', self._content)


if __name__ == '__main__':
    unittest.main()
