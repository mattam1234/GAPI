#!/usr/bin/env python3
"""
Tests for the migrated schedule event create/delete routes (chunk 4c):
  * POST   /api/schedule
  * DELETE /api/schedule/{event_id}

Covers validation, the in-app-notification fan-out, and the inline Discord
event create/cancel integration (Discord REST layer mocked via the global
requests module).

Run with:
    python -m pytest tests/test_backend_schedule_events.py
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class FakeResponse:
    def __init__(self, status_code, payload=None, content_type='application/json'):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {'content-type': content_type}
        self.content = b'x' * 100

    def json(self):
        return self._payload


class _FakeSched:
    def __init__(self):
        self.events = {}
        self.discord_info = None
        self._n = 0

    def add_event(self, title, date, time_str, duration, attendees, game_name,
                  notes, **kw):
        self._n += 1
        eid = f'ev{self._n}'
        ev = {
            'id': eid, 'title': title, 'date': date, 'time': time_str,
            'invited_attendees': attendees,
            'invited_attendee_ids': kw.get('attendee_ids') or attendees,
            'attendees': attendees, 'game_name': game_name, 'notes': notes,
        }
        self.events[eid] = ev
        return dict(ev)

    def get_event(self, eid):
        e = self.events.get(eid)
        return dict(e) if e else None

    def remove_event(self, eid):
        return self.events.pop(eid, None) is not None

    def set_discord_event_info(self, eid, did, gid):
        self.discord_info = (eid, did, gid)


class BackendScheduleEventsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self.sched = _FakeSched()
        self.picker = SimpleNamespace(schedule_service=self.sched, games=[])
        self._patches = [
            patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self.picker),
            patch.object(gapi_gui, '_send_schedule_in_app_notifications'),
        ]
        for p in self._patches:
            p.start()
        # Config with a Discord token for the discord-sync paths.
        self._cfg = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump({'discord_bot_token': 'test-token'}, self._cfg)
        self._cfg.close()
        self._env = patch.dict(os.environ, {'GAPI_DISCORD_CONFIG': self._cfg.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        os.unlink(self._cfg.name)
        for p in self._patches:
            p.stop()

    # --- create ----------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).post('/api/schedule', json={}).status_code, 401)

    def test_not_initialized_is_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.post('/api/schedule', json={'title': 'GN'})
        self.assertEqual(resp.status_code, 400)

    def test_create_requires_title(self):
        resp = self.client.post('/api/schedule', json={'title': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('title is required', resp.json()['detail'])

    def test_create_basic_201(self):
        resp = self.client.post('/api/schedule', json={
            'title': 'Game Night', 'date': '2026-03-15', 'time': '20:00',
            'attendees': ['bob']})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['title'], 'Game Night')
        self.assertNotIn('discord_result', body)

    def test_create_with_discord_event(self):
        with patch('requests.post', return_value=FakeResponse(201, {'id': 'd1'})) as mp:
            resp = self.client.post('/api/schedule', json={
                'title': 'GN', 'date': '2026-03-15', 'time': '20:00',
                'create_discord_event': True, 'discord_guild_id': 'g1',
                'timezone_offset_minutes': 0})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body['discord_result']['success'])
        self.assertEqual(body['discord_event_id'], 'd1')
        self.assertEqual(self.sched.discord_info, ('ev1', 'd1', 'g1'))
        self.assertEqual(mp.call_args.kwargs['headers']['Authorization'], 'Bot test-token')

    # --- delete ----------------------------------------------------------

    def _seed(self, **extra):
        ev = {'id': 'ev1', 'title': 'GN', 'date': '2026-03-15', 'time': '20:00'}
        ev.update(extra)
        self.sched.events['ev1'] = ev

    def test_delete_unknown_404(self):
        self.assertEqual(self.client.delete('/api/schedule/ghost').status_code, 404)

    def test_delete_basic(self):
        self._seed()
        resp = self.client.delete('/api/schedule/ev1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'id': 'ev1', 'discord_cancelled': False})

    def test_delete_linked_requires_guild_id(self):
        self._seed(discord_event_id='d1')  # no guild id anywhere
        resp = self.client.delete('/api/schedule/ev1')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()['requires_guild_id'])

    def test_delete_cancels_discord_event(self):
        self._seed(discord_event_id='d1', discord_guild_id='g1')
        with patch('requests.delete', return_value=FakeResponse(204)) as md:
            resp = self.client.delete('/api/schedule/ev1')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['discord_cancelled'])
        md.assert_called_once()

    def test_delete_discord_cancel_failure_is_502(self):
        self._seed(discord_event_id='d1', discord_guild_id='g1')
        with patch('requests.delete', return_value=FakeResponse(403, {'message': 'Nope'})):
            resp = self.client.delete('/api/schedule/ev1')
        self.assertEqual(resp.status_code, 502)
        self.assertIn('Nope', resp.json()['error'])


if __name__ == '__main__':
    unittest.main()
