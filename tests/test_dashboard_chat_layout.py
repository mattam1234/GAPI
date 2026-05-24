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
        self.assertNotIn('<p style="color: var(--text-secondary); margin-bottom: 12px;">Real-time chat with other users.</p>', template)
        self.assertIn('id="schedule-agenda"', template)
        self.assertIn('id="agenda-quick-title"', template)
        self.assertIn('id="sch-duration"', template)
        self.assertIn('id="sch-attendee-values"', template)

    def test_main_js_supports_dashboard_leaderboard_and_room_sidebar(self):
        script = (REPO_ROOT / 'static' / 'main.js').read_text(encoding='utf-8')
        self.assertIn("loadLeaderboard({ listId: 'dash-leaderboard-list'", script)
        self.assertIn('function renderChatRoomList()', script)
        self.assertIn('function updateChatRoomHeader()', script)
        self.assertNotIn("if (tabName === 'leaderboard') loadLeaderboard();", script)
        self.assertIn('function renderScheduleAgenda(', script)
        self.assertIn('function createAgendaEvent()', script)
        self.assertIn('function handleScheduleAgendaDrop(', script)
        self.assertIn('function focusScheduleInviteField(', script)

    def test_styles_include_chat_layout_and_dashboard_controls(self):
        styles = (REPO_ROOT / 'static' / 'style.css').read_text(encoding='utf-8')
        self.assertIn('.chat-layout {', styles)
        self.assertIn('.chat-room-sidebar {', styles)
        self.assertIn('.dash-leaderboard-controls {', styles)
        self.assertIn('grid-auto-rows: 1fr;', styles)
        self.assertIn('-webkit-line-clamp: 2;', styles)
        self.assertIn('.schedule-agenda-board {', styles)
        self.assertIn('.schedule-agenda-item {', styles)


if __name__ == '__main__':
    unittest.main()
