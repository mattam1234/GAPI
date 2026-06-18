#!/usr/bin/env python3
"""Tests for POST /api/schedule/<event_id>/create-discord-event.

Exercises the endpoint with the Discord REST layer mocked: happy path,
validation errors, missing token, missing event, and Discord API failures.
No network calls are made.
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


class FakeResponse:
    def __init__(self, status_code, payload=None, content_type='application/json'):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {'content-type': content_type}
        self.content = b'x' * 100

    def json(self):
        return self._payload


class TestCreateDiscordEventEndpoint(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

        # Point the endpoint's config loader at a temp config with a token.
        self._cfg = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        )
        json.dump({'discord_bot_token': 'test-token'}, self._cfg)
        self._cfg.close()
        self._env = patch.dict(os.environ, {'GAPI_DISCORD_CONFIG': self._cfg.name})
        self._env.start()

        self.event = {
            'id': 'ev1',
            'title': 'Game Night',
            'date': '2026-03-15',
            'time': '20:00',
            'attendees': ['alice'],
            'game_name': 'Portal 2',
            'notes': 'Bring snacks',
            # No game image fields -> resolver returns '' -> no image fetch.
        }
        self.recorded = {}

    def tearDown(self):
        self._env.stop()
        os.unlink(self._cfg.name)

    def _picker(self, event=None):
        ev = self.event if event is None else event

        def get_event(eid):
            return ev if (ev and eid == ev['id']) else None

        def set_info(event_id, discord_event_id, guild_id):
            self.recorded['set_info'] = (event_id, discord_event_id, guild_id)

        return SimpleNamespace(
            schedule_service=SimpleNamespace(
                get_event=get_event,
                set_discord_event_info=set_info,
            )
        )

    def _post(self, body, event=None):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._picker(event)):
            return self.client.post('/api/schedule/ev1/create-discord-event', json=body)

    # --- happy path ------------------------------------------------------
    def test_creates_event_and_records_id(self):
        with patch('requests.post', return_value=FakeResponse(201, {'id': '12345'})) as mock_post:
            resp = self._post({'guild_id': '987654321'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['discord_event_id'], '12345')
        self.assertIn('discord.com/events/987654321/12345', data['discord_event_url'])
        # Endpoint persisted the Discord event id back onto the schedule event.
        self.assertEqual(self.recorded['set_info'], ('ev1', '12345', '987654321'))
        # Sanity: the Discord REST endpoint was called with a Bot auth header.
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['Authorization'], 'Bot test-token')

    # --- validation ------------------------------------------------------
    def test_missing_guild_id_returns_400(self):
        with patch('requests.post') as mock_post:
            resp = self._post({})
        self.assertEqual(resp.status_code, 400)
        mock_post.assert_not_called()

    def test_unknown_event_returns_404(self):
        with patch('requests.post') as mock_post:
            resp = self._post({'guild_id': '1'}, event={'id': 'other', 'title': 'x'})
        self.assertEqual(resp.status_code, 404)
        mock_post.assert_not_called()

    # --- config ----------------------------------------------------------
    def test_missing_token_returns_500(self):
        # Point config at a file without a token.
        empty = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        )
        json.dump({}, empty)
        empty.close()
        try:
            with patch.dict(os.environ, {'GAPI_DISCORD_CONFIG': empty.name}):
                with patch('requests.post') as mock_post:
                    resp = self._post({'guild_id': '1'})
            self.assertEqual(resp.status_code, 500)
            mock_post.assert_not_called()
        finally:
            os.unlink(empty.name)

    # --- discord API failure --------------------------------------------
    def test_discord_api_error_is_propagated(self):
        err = FakeResponse(403, {'message': 'Missing Access'})
        with patch('requests.post', return_value=err):
            resp = self._post({'guild_id': '987654321'})
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertIn('Missing Access', data['error'])
        self.assertNotIn('set_info', self.recorded)


if __name__ == '__main__':
    unittest.main()
