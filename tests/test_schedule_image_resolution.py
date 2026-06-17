#!/usr/bin/env python3
"""Validate schedule game-image resolution across all supported platforms.

Each platform client shapes its game dict differently (Steam uses
header/capsule images or a numeric appid resolvable via the Steam CDN; PSN
carries an ``image_url``; Nintendo carries ``boxart``; GOG/Epic carry no image
and use non-Steam ids). These tests pin that ``_resolve_schedule_game_image_url``
returns a usable URL where one exists and never misattributes a non-Steam id to
the Steam CDN.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gapi_gui import _resolve_schedule_game_image_url

STEAM_CDN = 'https://cdn.akamai.steamstatic.com/steam/apps/'


class TestScheduleImageResolution(unittest.TestCase):
    # --- precedence ------------------------------------------------------
    def test_existing_url_takes_precedence(self):
        url = _resolve_schedule_game_image_url(
            game={'platform': 'steam', 'header_image': 'http://h'},
            existing_url='  http://explicit  ',
        )
        self.assertEqual(url, 'http://explicit')

    # --- steam -----------------------------------------------------------
    def test_steam_uses_header_image(self):
        game = {'platform': 'steam', 'appid': '620', 'header_image': 'http://steam/h.jpg'}
        self.assertEqual(_resolve_schedule_game_image_url(game=game), 'http://steam/h.jpg')

    def test_steam_falls_back_to_cdn_by_appid(self):
        game = {'platform': 'steam', 'appid': '620'}
        self.assertEqual(
            _resolve_schedule_game_image_url(game=game),
            f'{STEAM_CDN}620/header.jpg',
        )

    def test_unknown_platform_numeric_appid_allows_cdn(self):
        # Schedule events store game_appid without a platform; preserve the
        # Steam-CDN default for that path.
        self.assertEqual(
            _resolve_schedule_game_image_url(game_appid='620'),
            f'{STEAM_CDN}620/header.jpg',
        )

    # --- gog (regression: numeric id must NOT become a Steam URL) ---------
    def test_gog_numeric_id_does_not_become_steam_url(self):
        game = {'platform': 'gog', 'appid': '1207658924'}
        url = _resolve_schedule_game_image_url(game=game)
        self.assertNotIn(STEAM_CDN, url)
        self.assertEqual(url, '')

    def test_gog_uses_its_own_image_when_present(self):
        game = {'platform': 'gog', 'appid': '1207658924', 'image_url': 'http://gog/i.jpg'}
        self.assertEqual(_resolve_schedule_game_image_url(game=game), 'http://gog/i.jpg')

    # --- epic ------------------------------------------------------------
    def test_epic_alphanumeric_id_returns_empty(self):
        game = {'platform': 'epic', 'appid': 'a1b2c3catalog'}
        self.assertEqual(_resolve_schedule_game_image_url(game=game), '')

    # --- psn -------------------------------------------------------------
    def test_psn_uses_image_url(self):
        game = {'platform': 'psn', 'image_url': 'http://psn/cover.png'}
        self.assertEqual(_resolve_schedule_game_image_url(game=game), 'http://psn/cover.png')

    # --- nintendo (regression: boxart must be honored) -------------------
    def test_nintendo_uses_boxart(self):
        game = {'platform': 'Nintendo Switch', 'boxart': 'http://nintendo/box.jpg'}
        self.assertEqual(_resolve_schedule_game_image_url(game=game), 'http://nintendo/box.jpg')

    # --- empty / missing -------------------------------------------------
    def test_no_image_no_appid_returns_empty(self):
        self.assertEqual(_resolve_schedule_game_image_url(game={'platform': 'gog'}), '')

    def test_none_game_returns_empty(self):
        self.assertEqual(_resolve_schedule_game_image_url(), '')


if __name__ == '__main__':
    unittest.main()
