#!/usr/bin/env python3
"""Tests for the schedule iCalendar (.ics) export — RFC 5545 TEXT escaping.

Unescaped commas/semicolons/backslashes/newlines in a title or notes produce a
malformed .ics that calendar clients reject. These tests pin the escaping and
basic VCALENDAR/VEVENT structure.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


class TestScheduleIcalExport(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def _picker(self, events):
        return SimpleNamespace(
            schedule_service=SimpleNamespace(get_events=lambda username=None: events)
        )

    def _export(self, events):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._picker(events)):
            resp = self.client.get('/api/schedule/export.ics?download=0')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def test_basic_structure(self):
        body = self._export([
            {'id': 'ev1', 'title': 'Game Night', 'date': '2026-07-15', 'time': '20:00'}
        ])
        self.assertIn('BEGIN:VCALENDAR', body)
        self.assertIn('BEGIN:VEVENT', body)
        self.assertIn('UID:ev1@gapi', body)
        self.assertIn('DTSTART:20260715T200000', body)
        self.assertTrue(body.endswith('END:VCALENDAR\r\n'))

    def test_summary_special_chars_escaped(self):
        body = self._export([
            {'id': 'e', 'title': 'Co-op, FPS; round 2\\3', 'date': '2026-07-15', 'time': '20:00'}
        ])
        self.assertIn(r'SUMMARY:Co-op\, FPS\; round 2\\3', body)
        # No raw unescaped comma/semicolon survives in the summary line.
        summary_line = [ln for ln in body.split('\r\n') if ln.startswith('SUMMARY:')][0]
        self.assertNotIn('Co-op,', summary_line)

    def test_notes_newline_does_not_break_file(self):
        body = self._export([
            {'id': 'e', 'title': 'GN', 'date': '2026-07-15', 'time': '20:00',
             'notes': 'line one\nline two'}
        ])
        desc_lines = [ln for ln in body.split('\r\n') if ln.startswith('DESCRIPTION:')]
        self.assertEqual(len(desc_lines), 1)
        # Embedded newline became the literal \n sequence, not a real break.
        self.assertIn(r'line one\nline two', desc_lines[0])

    def test_description_includes_escaped_game_and_attendees(self):
        body = self._export([
            {'id': 'e', 'title': 'GN', 'date': '2026-07-15', 'time': '20:00',
             'game_name': 'Portal 2', 'attendees': ['alice', 'bob']}
        ])
        desc_line = [ln for ln in body.split('\r\n') if ln.startswith('DESCRIPTION:')][0]
        self.assertIn('Game: Portal 2', desc_line)
        # The attendees comma is escaped per RFC 5545.
        self.assertIn(r'Attendees: alice\, bob', desc_line)

    def test_event_without_date_omits_dtstart(self):
        body = self._export([{'id': 'e', 'title': 'TBD', 'date': '', 'time': '20:00'}])
        self.assertIn('BEGIN:VEVENT', body)
        self.assertNotIn('DTSTART:', body)


if __name__ == '__main__':
    unittest.main()
