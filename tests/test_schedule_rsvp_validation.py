#!/usr/bin/env python3
"""Edge-case coverage for POST /api/schedule/<event_id>/rsvp.

Complements the permission/fan-out tests in test_achievement_schedule.py with
status validation, not-found handling, and case-insensitive invitee matching.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


class _FakeSchedule:
    def __init__(self, event):
        self._event = event
        self.rsvp_updates = []

    def get_event(self, event_id):
        if self._event is None:
            return None
        return self._event if event_id == self._event['id'] else None

    def update_event_rsvp(self, event_id, attendee_identity, status):
        self.rsvp_updates.append((attendee_identity, status))
        rsvps = dict(self._event.get('rsvp_statuses') or {})
        rsvps[attendee_identity] = status
        self._event['rsvp_statuses'] = rsvps
        return self._event


class TestRsvpValidation(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        self.event = {
            'id': 'ev1', 'title': 'Game Night', 'created_by': 'host',
            'invited_attendees': ['alice', 'bob'],
            'invited_attendee_ids': ['alice', 'bob'],
            'rsvp_statuses': {'alice': 'pending', 'bob': 'pending'},
        }

    def _login(self, username):
        with self.client.session_transaction() as sess:
            sess['username'] = username

    def _post(self, body, event='__default__'):
        ev = self.event if event == '__default__' else event
        picker = SimpleNamespace(schedule_service=_FakeSchedule(ev))
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            with patch.object(gapi_gui, '_send_schedule_in_app_notifications'):
                with patch.object(gapi_gui, '_send_schedule_discord_dm', return_value=True):
                    return self.client.post('/api/schedule/ev1/rsvp', json=body), picker

    def test_invalid_status_returns_400(self):
        self._login('alice')
        resp, picker = self._post({'status': 'going'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(picker.schedule_service.rsvp_updates, [])

    def test_missing_status_returns_400(self):
        self._login('alice')
        resp, _ = self._post({})
        self.assertEqual(resp.status_code, 400)

    def test_event_not_found_returns_404(self):
        self._login('alice')
        resp, _ = self._post({'status': 'accepted'}, event=None)
        self.assertEqual(resp.status_code, 404)

    def test_valid_statuses_accepted(self):
        for status in ('accepted', 'maybe', 'declined', 'pending'):
            self._login('alice')
            resp, picker = self._post({'status': status})
            self.assertEqual(resp.status_code, 200, status)
            self.assertEqual(picker.schedule_service.rsvp_updates, [('alice', status)])

    def test_invitee_matched_case_insensitively(self):
        # Session username differs in case from the invited name.
        self._login('Alice')
        resp, picker = self._post({'status': 'accepted'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(picker.schedule_service.rsvp_updates, [('alice', 'accepted')])

    def test_status_is_case_normalized(self):
        self._login('alice')
        resp, picker = self._post({'status': 'ACCEPTED'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(picker.schedule_service.rsvp_updates, [('alice', 'accepted')])


if __name__ == '__main__':
    unittest.main()
