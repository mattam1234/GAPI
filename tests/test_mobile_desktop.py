#!/usr/bin/env python3
"""
Tests for:
* mobile-app/ structure and content (React Native)
* desktop-app/ structure and content (Electron with system tray)
* ROADMAP — Mobile App and Desktop Application marked complete
* FEATURES_SUMMARY — entries exist for both

Run with:
    python -m pytest tests/test_mobile_desktop.py
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(ROOT, *parts)


def _read(*parts):
    with open(_path(*parts)) as f:
        return f.read()


def _json(*parts):
    with open(_path(*parts)) as f:
        return json.load(f)


# ===========================================================================
# Mobile App (React Native)
# ===========================================================================

class TestMobileAppStructure(unittest.TestCase):

    def test_package_json_exists(self):
        self.assertTrue(os.path.exists(_path('mobile-app', 'package.json')))

    def test_package_json_valid_json(self):
        pkg = _json('mobile-app', 'package.json')
        self.assertEqual(pkg['name'], 'GAPIApp')
        self.assertIn('react-native', pkg['dependencies'])
        self.assertIn('@react-navigation/native', pkg['dependencies'])
        self.assertIn('@react-native-async-storage/async-storage', pkg['dependencies'])

    def test_app_tsx_exists(self):
        self.assertTrue(os.path.exists(_path('mobile-app', 'App.tsx')))

    def test_app_navigator_exists(self):
        self.assertTrue(os.path.exists(_path('mobile-app', 'src', 'AppNavigator.tsx')))

    def test_all_four_screens_exist(self):
        for screen in ('PickScreen', 'LibraryScreen', 'HistoryScreen', 'SettingsScreen'):
            p = _path('mobile-app', 'src', 'screens', f'{screen}.tsx')
            self.assertTrue(os.path.exists(p), f'Missing {screen}.tsx')

    def test_context_exists(self):
        p = _path('mobile-app', 'src', 'context', 'ServerConfigContext.tsx')
        self.assertTrue(os.path.exists(p))

    def test_hook_exists(self):
        p = _path('mobile-app', 'src', 'hooks', 'useGapiApi.ts')
        self.assertTrue(os.path.exists(p))

    def test_components_exist(self):
        for comp in ('GameCard', 'PlatformBadge'):
            p = _path('mobile-app', 'src', 'components', f'{comp}.tsx')
            self.assertTrue(os.path.exists(p), f'Missing {comp}.tsx')

    def test_formatters_exists(self):
        self.assertTrue(os.path.exists(_path('mobile-app', 'src', 'utils', 'formatters.ts')))

    def test_readme_exists(self):
        self.assertTrue(os.path.exists(_path('mobile-app', 'README.md')))

    def test_tests_exist(self):
        self.assertTrue(
            os.path.exists(_path('mobile-app', '__tests__', 'formatters.test.ts'))
        )

    # ── Content checks ──────────────────────────────────────────────────────

    def test_app_tsx_uses_navigation_container(self):
        content = _read('mobile-app', 'App.tsx')
        self.assertIn('NavigationContainer', content)
        self.assertIn('ServerConfigProvider', content)

    def test_app_navigator_has_four_tabs(self):
        content = _read('mobile-app', 'src', 'AppNavigator.tsx')
        for tab in ('Pick', 'Library', 'History', 'Settings'):
            self.assertIn(tab, content)

    def test_server_config_context_has_async_storage(self):
        content = _read('mobile-app', 'src', 'context', 'ServerConfigContext.tsx')
        self.assertIn('AsyncStorage', content)
        self.assertIn('DEFAULT_URL', content)

    def test_hook_exposes_pick_library_history(self):
        content = _read('mobile-app', 'src', 'hooks', 'useGapiApi.ts')
        self.assertIn('pickGame', content)
        self.assertIn('getLibrary', content)
        self.assertIn('getHistory', content)
        self.assertIn('/api/pick', content)
        self.assertIn('/api/library', content)
        self.assertIn('/api/history', content)

    def test_pick_screen_has_three_modes(self):
        content = _read('mobile-app', 'src', 'screens', 'PickScreen.tsx')
        self.assertIn('random', content)
        self.assertIn('unplayed', content)
        self.assertIn('barely_played', content)

    def test_library_screen_has_platform_filter(self):
        content = _read('mobile-app', 'src', 'screens', 'LibraryScreen.tsx')
        self.assertIn('steam', content)
        self.assertIn('epic', content)
        self.assertIn('nintendo', content)

    def test_platform_badge_covers_all_platforms(self):
        content = _read('mobile-app', 'src', 'components', 'PlatformBadge.tsx')
        for platform in ('steam', 'epic', 'gog', 'xbox', 'psn', 'nintendo'):
            self.assertIn(platform, content.lower())

    def test_formatters_ts_has_two_functions(self):
        content = _read('mobile-app', 'src', 'utils', 'formatters.ts')
        self.assertIn('formatPlaytime', content)
        self.assertIn('formatRelativeTime', content)

    def test_readme_covers_ios_android_and_setup(self):
        content = _read('mobile-app', 'README.md')
        for keyword in ('iOS', 'Android', 'React Native', 'npm install', 'npm start'):
            self.assertIn(keyword, content, f"README missing: {keyword}")

    def test_formatter_tests_cover_edge_cases(self):
        content = _read('mobile-app', '__tests__', 'formatters.test.ts')
        self.assertIn('0h played', content)
        self.assertIn('just now', content)
        self.assertIn('ago', content)


# ===========================================================================
# Desktop App (Electron)
# ===========================================================================

class TestDesktopAppStructure(unittest.TestCase):

    def test_package_json_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'package.json')))

    def test_package_json_valid_json(self):
        pkg = _json('desktop-app', 'package.json')
        self.assertEqual(pkg['name'], 'gapi-desktop')
        self.assertIn('electron', pkg['devDependencies'])
        self.assertEqual(pkg['main'], 'src/main.js')

    def test_main_js_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'src', 'main.js')))

    def test_preload_js_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'src', 'preload.js')))

    def test_renderer_html_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'renderer', 'index.html')))

    def test_renderer_js_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'renderer', 'renderer.js')))

    def test_readme_exists(self):
        self.assertTrue(os.path.exists(_path('desktop-app', 'README.md')))

    def test_tests_exist(self):
        self.assertTrue(
            os.path.exists(_path('desktop-app', '__tests__', 'formatters.test.js'))
        )

    # ── Content checks ──────────────────────────────────────────────────────

    def test_main_js_creates_tray(self):
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn('Tray', content)
        self.assertIn('createTray', content)

    def test_main_js_has_health_check(self):
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn('checkHealth', content)
        self.assertIn('setInterval', content)

    def test_main_js_sends_desktop_notification(self):
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn('Notification', content)

    def test_main_js_has_tray_context_menu(self):
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn('buildFromTemplate', content)
        self.assertIn('Pick a Game', content)
        self.assertIn('Open GAPI Window', content)
        self.assertIn('Settings', content)
        self.assertIn('Quit', content)

    def test_main_js_has_ipc_handlers(self):
        content = _read('desktop-app', 'src', 'main.js')
        for handler in ('set-server-url', 'get-server-url', 'quick-pick',
                        'get-library', 'get-history', 'open-external',
                        'get-connection-status'):
            self.assertIn(handler, content, f"Missing IPC handler: {handler}")

    def test_main_js_uses_electron_store(self):
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn('electron-store', content)
        self.assertIn('serverUrl', content)

    def test_main_js_has_non_darwin_quit(self):
        """Windows/Linux: app quits when all windows are closed."""
        content = _read('desktop-app', 'src', 'main.js')
        self.assertIn("process.platform !== 'darwin'", content)

    def test_preload_exposes_context_bridge(self):
        content = _read('desktop-app', 'src', 'preload.js')
        self.assertIn('contextBridge', content)
        self.assertIn('exposeInMainWorld', content)
        self.assertIn('gapiAPI', content)

    def test_preload_exposes_all_api_methods(self):
        content = _read('desktop-app', 'src', 'preload.js')
        for method in ('getServerUrl', 'setServerUrl', 'quickPick',
                       'getLibrary', 'getHistory', 'openExternal',
                       'onConnectionStatus', 'onGamePicked', 'onOpenSettings'):
            self.assertIn(method, content, f"Missing preload API: {method}")

    def test_renderer_html_has_four_panels(self):
        content = _read('desktop-app', 'renderer', 'index.html')
        for panel in ('pick', 'library', 'history', 'settings'):
            self.assertIn(f'panel-{panel}', content, f"Missing panel: {panel}")

    def test_renderer_html_has_tray_nav_items(self):
        content = _read('desktop-app', 'renderer', 'index.html')
        for label in ('Pick a Game', 'Library', 'History', 'Settings'):
            self.assertIn(label, content)

    def test_renderer_js_uses_gapi_api(self):
        content = _read('desktop-app', 'renderer', 'renderer.js')
        self.assertIn('window.gapiAPI', content)
        self.assertIn('quickPick', content)
        self.assertIn('getLibrary', content)
        self.assertIn('getHistory', content)

    def test_renderer_js_has_pick_modes(self):
        # Pick mode values are set in the HTML data attributes, not renderer.js literals
        html_content = _read('desktop-app', 'renderer', 'index.html')
        for mode in ('random', 'unplayed', 'barely_played'):
            self.assertIn(mode, html_content, f"Pick mode '{mode}' missing from index.html")

    def test_renderer_html_has_csp(self):
        content = _read('desktop-app', 'renderer', 'index.html')
        self.assertIn('Content-Security-Policy', content)

    def test_readme_covers_tray_and_platforms(self):
        content = _read('desktop-app', 'README.md')
        for keyword in ('Tray', 'macOS', 'Windows', 'Linux', 'Electron',
                        'npm install', 'Notification'):
            self.assertIn(keyword, content, f"README missing: {keyword}")

    def test_package_json_has_build_config_all_platforms(self):
        pkg = _json('desktop-app', 'package.json')
        build = pkg.get('build', {})
        self.assertIn('mac',   build)
        self.assertIn('win',   build)
        self.assertIn('linux', build)

    def test_desktop_formatter_tests_cover_edge_cases(self):
        content = _read('desktop-app', '__tests__', 'formatters.test.js')
        self.assertIn('0h played', content)
        self.assertIn('just now', content)


# ===========================================================================
# ROADMAP
# ===========================================================================

class TestROADMAP(unittest.TestCase):

    def setUp(self):
        self._content = _read('ROADMAP.md')

    def test_mobile_app_not_unchecked(self):
        """Mobile App should no longer be an unchecked item."""
        lines = [l for l in self._content.splitlines()
                 if 'Mobile App' in l and l.strip().startswith('- [ ]')]
        self.assertEqual(lines, [], f"Mobile App still unchecked: {lines}")

    def test_desktop_app_not_unchecked(self):
        """Desktop Application should no longer be an unchecked item."""
        lines = [l for l in self._content.splitlines()
                 if 'Desktop Application' in l and l.strip().startswith('- [ ]')]
        self.assertEqual(lines, [], f"Desktop Application still unchecked: {lines}")

    def test_no_remaining_unchecked_items(self):
        """All ROADMAP items should be completed."""
        unchecked = [l.strip() for l in self._content.splitlines()
                     if l.strip().startswith('- [ ]')]
        self.assertEqual(unchecked, [],
                         f"Remaining unchecked ROADMAP items: {unchecked}")


# ===========================================================================
# FEATURES_SUMMARY
# ===========================================================================

class TestFeaturesSummary(unittest.TestCase):

    def setUp(self):
        self._content = _read('FEATURES_SUMMARY.md')

    def test_mobile_app_mentioned(self):
        self.assertIn('Mobile App', self._content)
        self.assertIn('React Native', self._content)

    def test_desktop_app_mentioned(self):
        self.assertIn('Desktop', self._content)
        self.assertIn('Electron', self._content)
        self.assertIn('system tray', self._content.lower())


if __name__ == '__main__':
    unittest.main()
