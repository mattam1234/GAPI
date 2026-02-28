#!/usr/bin/env python3
"""
Tests for Discord Rich Presence and Localization (i18n) features.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord_presence as dp
from discord_presence import DiscordPresence


# ===========================================================================
# DiscordPresence unit tests
# ===========================================================================

class TestDiscordPresenceDisabled(unittest.TestCase):
    """DiscordPresence is disabled when no client_id is supplied."""

    def setUp(self):
        # Make sure environment variable is absent
        self._orig = os.environ.pop('DISCORD_CLIENT_ID', None)

    def tearDown(self):
        if self._orig is not None:
            os.environ['DISCORD_CLIENT_ID'] = self._orig

    def test_disabled_when_no_client_id(self):
        rpc = DiscordPresence(client_id=None)
        self.assertFalse(rpc.enabled)

    def test_update_returns_false_when_disabled(self):
        rpc = DiscordPresence(client_id=None)
        self.assertFalse(rpc.update('Portal 2'))

    def test_clear_returns_false_when_disabled(self):
        rpc = DiscordPresence(client_id=None)
        self.assertFalse(rpc.clear())

    def test_close_does_not_raise_when_disabled(self):
        rpc = DiscordPresence(client_id=None)
        rpc.close()  # should not raise


class TestDiscordPresenceNoPypresence(unittest.TestCase):
    """DiscordPresence warns gracefully when pypresence is not installed."""

    def test_disabled_without_pypresence(self):
        # Simulate pypresence not importable
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', False):
            rpc = DiscordPresence(client_id='123456789')
            self.assertFalse(rpc.enabled)

    def test_update_false_without_pypresence(self):
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', False):
            rpc = DiscordPresence(client_id='123456789')
            self.assertFalse(rpc.update('Skyrim'))


class TestDiscordPresenceEnabled(unittest.TestCase):
    """DiscordPresence is enabled when client_id + pypresence are available."""

    def _make_mock_presence_class(self):
        mock_instance = MagicMock()
        mock_class = MagicMock(return_value=mock_instance)
        return mock_class, mock_instance

    def test_enabled_flag(self):
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', MagicMock()):
            rpc = DiscordPresence(client_id='123456789')
            self.assertTrue(rpc.enabled)

    def test_update_calls_connect_and_update(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc._connected = False
            result = rpc.update('Portal 2', playtime_hours=45.3)
            self.assertTrue(result)
            # Give the daemon thread time to run
            time.sleep(0.2)
            mock_instance.connect.assert_called_once()
            mock_instance.update.assert_called_once()
            call_kwargs = mock_instance.update.call_args.kwargs
            self.assertIn('Portal 2', call_kwargs.get('details', ''))
            self.assertIn('45.3h', call_kwargs.get('state', ''))

    def test_clear_calls_rpc_clear(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc._connected = False
            result = rpc.clear()
            self.assertTrue(result)
            time.sleep(0.2)
            mock_instance.clear.assert_called_once()

    def test_connect_failure_does_not_raise(self):
        mock_class = MagicMock(side_effect=Exception('Discord not running'))
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            # Should not raise — errors are swallowed
            rpc.update('Dota 2')
            time.sleep(0.2)

    def test_update_failure_after_connect_does_not_raise(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        mock_instance.update.side_effect = Exception('RPC error')
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc.update('CS:GO')
            time.sleep(0.2)
            # Should have disconnected after failure
            # (no assert needed — just must not raise)

    def test_client_id_from_environment(self):
        os.environ['DISCORD_CLIENT_ID'] = '987654321'
        try:
            with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
                 patch.object(dp, 'Presence', MagicMock()):
                rpc = DiscordPresence()
                self.assertTrue(rpc.enabled)
                self.assertEqual(rpc._client_id, '987654321')
        finally:
            del os.environ['DISCORD_CLIENT_ID']

    def test_close_disconnects(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc._connect()
            rpc.close()
            mock_instance.close.assert_called()
            self.assertFalse(rpc._connected)

    def test_update_without_playtime(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc.update('Team Fortress 2')
            time.sleep(0.2)
            call_kwargs = mock_instance.update.call_args.kwargs
            self.assertEqual(call_kwargs.get('state'), dp._RP_DEFAULT_STATE)

    def test_update_with_custom_details(self):
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            rpc.update('Skyrim', details='Currently playing via GAPI')
            time.sleep(0.2)
            call_kwargs = mock_instance.update.call_args.kwargs
            self.assertEqual(call_kwargs.get('details'), 'Currently playing via GAPI')

    def test_thread_safety(self):
        """Multiple concurrent update calls must not raise."""
        mock_class, mock_instance = self._make_mock_presence_class()
        with patch.object(dp, '_PYPRESENCE_AVAILABLE', True), \
             patch.object(dp, 'Presence', mock_class):
            rpc = DiscordPresence(client_id='123456789')
            threads = [
                threading.Thread(target=rpc.update, args=(f'Game {i}',), kwargs={'playtime_hours': float(i)})
                for i in range(10)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=2)
            # All threads must finish — just assert no exceptions occurred


# ===========================================================================
# i18n / locales endpoint tests
# ===========================================================================

class TestI18nEndpoints(unittest.TestCase):
    """Integration tests for GET /api/i18n and GET /api/i18n/<lang>."""

    def setUp(self):
        # Import the Flask app in test mode
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    def test_list_locales_returns_200(self):
        resp = self.client.get('/api/i18n')
        self.assertEqual(resp.status_code, 200)

    def test_list_locales_contains_en_and_es(self):
        resp = self.client.get('/api/i18n')
        data = json.loads(resp.data)
        langs = [item['lang'] for item in data['locales']]
        self.assertIn('en', langs)
        self.assertIn('es', langs)

    def test_list_locales_has_lang_name(self):
        resp = self.client.get('/api/i18n')
        data = json.loads(resp.data)
        by_lang = {item['lang']: item for item in data['locales']}
        self.assertEqual(by_lang['en']['lang_name'], 'English')
        self.assertEqual(by_lang['es']['lang_name'], 'Español')

    def test_get_english_locale(self):
        resp = self.client.get('/api/i18n/en')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['lang'], 'en')
        self.assertIn('nav', data)
        self.assertIn('pick', data)
        self.assertIn('common', data)

    def test_get_spanish_locale(self):
        resp = self.client.get('/api/i18n/es')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['lang'], 'es')
        self.assertEqual(data['lang_name'], 'Español')

    def test_missing_locale_returns_404(self):
        resp = self.client.get('/api/i18n/zz')
        self.assertEqual(resp.status_code, 404)
        data = json.loads(resp.data)
        self.assertIn('error', data)

    def test_path_traversal_rejected(self):
        """Requesting ../../etc/passwd must not succeed."""
        resp = self.client.get('/api/i18n/../../etc/passwd')
        # Flask routing treats extra slashes as different URLs, so either
        # a 404 (not found) or 400 (bad request) is acceptable.
        self.assertIn(resp.status_code, (400, 404))

    def test_english_locale_has_expected_keys(self):
        resp = self.client.get('/api/i18n/en')
        data = json.loads(resp.data)
        expected_sections = ['nav', 'pick', 'library', 'reviews', 'tags',
                              'backlog', 'playlists', 'schedule', 'budget',
                              'wishlist', 'stats', 'auth', 'common']
        for section in expected_sections:
            self.assertIn(section, data, f"Missing section: {section}")

    def test_spanish_locale_has_same_structure_as_english(self):
        en_resp = self.client.get('/api/i18n/en')
        es_resp = self.client.get('/api/i18n/es')
        en = json.loads(en_resp.data)
        es = json.loads(es_resp.data)
        for section in en:
            if section in ('lang', 'lang_name'):
                continue
            self.assertIn(section, es, f"Spanish locale missing section: {section}")
            if isinstance(en[section], dict):
                for key in en[section]:
                    self.assertIn(key, es[section],
                                  f"Spanish locale missing key '{key}' in section '{section}'")


# ===========================================================================
# _load_locale helper tests
# ===========================================================================

class TestLoadLocale(unittest.TestCase):
    """Unit tests for the _load_locale helper imported via gapi_gui."""

    def setUp(self):
        import gapi_gui
        self._load_locale = gapi_gui._load_locale

    def test_loads_en(self):
        data = self._load_locale('en')
        self.assertIsNotNone(data)
        self.assertEqual(data['lang'], 'en')

    def test_loads_es(self):
        data = self._load_locale('es')
        self.assertIsNotNone(data)
        self.assertEqual(data['lang'], 'es')

    def test_returns_none_for_unknown(self):
        data = self._load_locale('xx_NONEXISTENT')
        self.assertIsNone(data)

    def test_path_traversal_sanitised(self):
        # Attempting ../../etc/passwd-style lang names must return None
        data = self._load_locale('../../etc/passwd')
        self.assertIsNone(data)


if __name__ == '__main__':
    unittest.main()
