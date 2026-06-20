#!/usr/bin/env python3
"""Tests for the migrated live-session domain (FastAPI).

Covers the in-memory live pick session routes (the DB-linked path is bypassed by
forcing ``DB_AVAILABLE`` / ``ensure_db_available`` off so the in-memory branch
runs, mirroring how the legacy fixtures exercised these handlers):

  * GET    /api/live-session/discord-locations
  * POST   /api/live-session/create                       (201)
  * GET    /api/live-session/active
  * POST   /api/live-session/{session_id}/join
  * POST   /api/live-session/{session_id}/leave
  * POST   /api/live-session/{session_id}/disband
  * POST   /api/live-session/{session_id}/pick
  * GET    /api/live-session/{session_id}
  * POST   /api/live-session/{session_id}/vote
  * POST   /api/live-session/{session_id}/invite

Run with:
    python -m pytest tests/test_backend_live_session.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _LiveSessionCase(unittest.TestCase):
    """Logged-in client with the DB-linked path disabled (in-memory branch)."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        # Force the in-memory branch: DB_AVAILABLE False -> ensure_db_available
        # short-circuits, so DB-linked code never runs.
        self._db = patch.object(gapi_gui, 'DB_AVAILABLE', False)
        self._db.start()
        # Start from a clean session store each test.
        with gapi_gui.live_sessions_lock:
            gapi_gui.live_sessions.clear()

    def tearDown(self):
        self._db.stop()
        with gapi_gui.live_sessions_lock:
            gapi_gui.live_sessions.clear()

    def _create(self, name='Game Night', user='alice'):
        self.client.cookies.set('session', _session_cookie(user))
        resp = self.client.post('/api/live-session/create', json={'name': name})
        self.assertEqual(resp.status_code, 201)
        return resp.json()['session_id']


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_create_requires_login(self):
        resp = self.client.post('/api/live-session/create', json={})
        self.assertEqual(resp.status_code, 401)

    def test_active_requires_login(self):
        resp = self.client.get('/api/live-session/active')
        self.assertEqual(resp.status_code, 401)

    def test_get_requires_login(self):
        resp = self.client.get('/api/live-session/abc')
        self.assertEqual(resp.status_code, 401)


# ── create / active / get ───────────────────────────────────────────────────

class CreateActiveGetTest(_LiveSessionCase):
    def test_create_session(self):
        resp = self.client.post('/api/live-session/create', json={'name': 'My Night'})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['host'], 'alice')
        self.assertEqual(body['name'], 'My Night')
        self.assertEqual(body['participants'], ['alice'])
        self.assertEqual(body['status'], 'waiting')

    def test_create_discord_linked_requires_both_ids(self):
        # Only guild id supplied -> 400 with explicit message.
        resp = self.client.post('/api/live-session/create',
                                json={'discord_guild_id': 'g1'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('discord_guild_id', resp.json()['error'])

    def test_active_lists_created_session(self):
        sid = self._create('Nighty')
        resp = self.client.get('/api/live-session/active')
        self.assertEqual(resp.status_code, 200)
        ids = [s['session_id'] for s in resp.json()['sessions']]
        self.assertIn(sid, ids)

    def test_active_not_shadowed_by_param_route(self):
        # /active must hit the literal route, not /{session_id}. A param route
        # would 404 ("Session not found"); the literal returns {"sessions": [...]}.
        resp = self.client.get('/api/live-session/active')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('sessions', resp.json())
        self.assertNotIn('error', resp.json())

    def test_discord_locations_not_shadowed(self):
        # Literal /discord-locations must not be captured by /{session_id}.
        resp = self.client.get('/api/live-session/discord-locations')
        self.assertEqual(resp.status_code, 200)
        # alice has no DB-linked discord id (DB off) -> guilds empty + error hint.
        self.assertIn('guilds', resp.json())

    def test_get_session(self):
        sid = self._create()
        resp = self.client.get(f'/api/live-session/{sid}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['session_id'], sid)

    def test_get_session_not_found(self):
        resp = self.client.get('/api/live-session/does-not-exist')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Session not found')


# ── join / leave ────────────────────────────────────────────────────────────

class JoinLeaveTest(_LiveSessionCase):
    def test_join_session(self):
        sid = self._create(user='alice')
        self.client.cookies.set('session', _session_cookie('bob'))
        resp = self.client.post(f'/api/live-session/{sid}/join')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('bob', resp.json()['participants'])

    def test_join_not_found(self):
        resp = self.client.post('/api/live-session/nope/join')
        self.assertEqual(resp.status_code, 404)

    def test_leave_hands_off_host(self):
        sid = self._create(user='alice')
        self.client.cookies.set('session', _session_cookie('bob'))
        self.client.post(f'/api/live-session/{sid}/join')
        # alice (host) leaves -> bob becomes host.
        self.client.cookies.set('session', _session_cookie('alice'))
        resp = self.client.post(f'/api/live-session/{sid}/leave')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['session']['host'], 'bob')

    def test_leave_last_participant_closes(self):
        sid = self._create(user='alice')
        resp = self.client.post(f'/api/live-session/{sid}/leave')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('no participants left', resp.json()['message'])
        # Session removed.
        self.assertNotIn(sid, gapi_gui.live_sessions)


# ── disband ─────────────────────────────────────────────────────────────────

class DisbandTest(_LiveSessionCase):
    def test_disband_by_host(self):
        sid = self._create(user='alice')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.post(f'/api/live-session/{sid}/disband')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertNotIn(sid, gapi_gui.live_sessions)

    def test_disband_forbidden_for_non_host_non_admin(self):
        sid = self._create(user='alice')
        self.client.cookies.set('session', _session_cookie('bob'))
        self.client.post(f'/api/live-session/{sid}/join')
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.post(f'/api/live-session/{sid}/disband')
        self.assertEqual(resp.status_code, 403)

    def test_disband_not_found(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.post('/api/live-session/nope/disband')
        self.assertEqual(resp.status_code, 404)


# ── pick ────────────────────────────────────────────────────────────────────

class PickTest(_LiveSessionCase):
    def test_pick_requires_host(self):
        sid = self._create(user='alice')
        self.client.cookies.set('session', _session_cookie('bob'))
        self.client.post(f'/api/live-session/{sid}/join')
        resp = self.client.post(f'/api/live-session/{sid}/pick', json={})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('host', resp.json()['error'])

    def test_pick_not_found(self):
        resp = self.client.post('/api/live-session/nope/pick', json={})
        self.assertEqual(resp.status_code, 404)

    def test_pick_no_common_game(self):
        sid = self._create(user='alice')
        picker = MagicMock()
        picker.pick_common_game.return_value = None
        with patch.object(gapi_gui, '_ensure_multi_picker'), \
                patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post(f'/api/live-session/{sid}/pick', json={})
        self.assertEqual(resp.status_code, 404)
        self.assertIn('No common game', resp.json()['error'])

    def test_pick_success(self):
        sid = self._create(user='alice')
        picker = MagicMock()
        picker.pick_common_game.return_value = {'appid': '440', 'name': 'TF2'}
        with patch.object(gapi_gui, '_ensure_multi_picker'), \
                patch.object(gapi_gui, 'multi_picker', picker):
            resp = self.client.post(f'/api/live-session/{sid}/pick', json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['picked_game']['name'], 'TF2')
        self.assertEqual(body['session']['status'], 'awaiting_vote')


# ── vote ────────────────────────────────────────────────────────────────────

class VoteTest(_LiveSessionCase):
    def _create_and_pick(self):
        sid = self._create(user='alice')
        picker = MagicMock()
        picker.pick_common_game.return_value = {'appid': '440', 'name': 'TF2'}
        with patch.object(gapi_gui, '_ensure_multi_picker'), \
                patch.object(gapi_gui, 'multi_picker', picker):
            self.client.post(f'/api/live-session/{sid}/pick', json={})
        return sid

    def test_vote_requires_accept_field(self):
        sid = self._create_and_pick()
        resp = self.client.post(f'/api/live-session/{sid}/vote', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('accept', resp.json()['error'])

    def test_vote_not_found(self):
        resp = self.client.post('/api/live-session/nope/vote', json={'accept': True})
        self.assertEqual(resp.status_code, 404)

    def test_vote_only_participants(self):
        sid = self._create_and_pick()
        self.client.cookies.set('session', _session_cookie('carol'))
        resp = self.client.post(f'/api/live-session/{sid}/vote', json={'accept': True})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('participants', resp.json()['error'])

    def test_vote_accept_completes(self):
        sid = self._create_and_pick()  # single participant alice, majority = 1
        resp = self.client.post(f'/api/live-session/{sid}/vote', json={'accept': True})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['result'], 'accepted')
        self.assertEqual(body['session']['status'], 'completed')

    def test_vote_no_active_game(self):
        sid = self._create(user='alice')  # status waiting, no picked_game
        resp = self.client.post(f'/api/live-session/{sid}/vote', json={'accept': True})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('No active game vote', resp.json()['error'])


# ── invite ──────────────────────────────────────────────────────────────────

class InviteTest(_LiveSessionCase):
    def test_invite_requires_host(self):
        sid = self._create(user='alice')
        self.client.cookies.set('session', _session_cookie('bob'))
        self.client.post(f'/api/live-session/{sid}/join')
        resp = self.client.post(f'/api/live-session/{sid}/invite',
                                json={'usernames': ['carol']})
        self.assertEqual(resp.status_code, 403)

    def test_invite_not_found(self):
        resp = self.client.post('/api/live-session/nope/invite',
                                json={'usernames': ['carol']})
        self.assertEqual(resp.status_code, 404)

    def test_invite_requires_usernames_list(self):
        sid = self._create(user='alice')
        resp = self.client.post(f'/api/live-session/{sid}/invite', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('usernames', resp.json()['error'])

    def test_invite_db_unavailable(self):
        # In-memory path with DB off -> 503 "Database not available for notifications".
        sid = self._create(user='alice')
        resp = self.client.post(f'/api/live-session/{sid}/invite',
                                json={'usernames': ['carol']})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Database not available', resp.json()['error'])


if __name__ == '__main__':
    unittest.main()
