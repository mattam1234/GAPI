#!/usr/bin/env python3
"""Regression checks for dashboard leaderboard and chat layout source markup."""

from pathlib import Path
import unittest


REPO_ROOT = Path('/home/runner/work/GAPI/GAPI')


class TestDashboardChatLayout(unittest.TestCase):
    def test_template_moves_leaderboard_to_dashboard_and_chat_sidebar(self):
        template = (REPO_ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="dash-leaderboard-list"', template)
        self.assertIn('id="dash-leaderboard-metric"', template)
        self.assertNotIn('id="leaderboard-tab"', template)
        self.assertNotIn('id="nav-leaderboard"', template)
        self.assertIn('class="chat-room-sidebar"', template)
        self.assertIn('id="chat-room-list"', template)

    def test_main_js_supports_dashboard_leaderboard_and_room_sidebar(self):
        script = (REPO_ROOT / 'static' / 'main.js').read_text(encoding='utf-8')
        self.assertIn("loadLeaderboard({ listId: 'dash-leaderboard-list'", script)
        self.assertIn('function renderChatRoomList()', script)
        self.assertIn('function updateChatRoomHeader()', script)
        self.assertNotIn("if (tabName === 'leaderboard') loadLeaderboard();", script)

    def test_styles_include_chat_layout_and_dashboard_controls(self):
        styles = (REPO_ROOT / 'static' / 'style.css').read_text(encoding='utf-8')
        self.assertIn('.chat-layout {', styles)
        self.assertIn('.chat-room-sidebar {', styles)
        self.assertIn('.dash-leaderboard-controls {', styles)
        self.assertIn('grid-auto-rows: 1fr;', styles)
        self.assertIn('-webkit-line-clamp: 2;', styles)


if __name__ == '__main__':
    unittest.main()
