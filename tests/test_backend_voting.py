#!/usr/bin/env python3
"""
Tests for the migrated voting domain (backend/routers/voting.py).

Covers create / cast / status / close across plurality and ranked-choice,
plus the auth, not-initialised, not-found, and validation branches. The legacy
multi_picker + voting-session objects are stubbed.

Run with:
    python -m pytest tests/test_backend_voting.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _FakeSession:
    def __init__(self, session_id, voting_method='plurality'):
        self.session_id = session_id
        self.voting_method = voting_method
        self._votes = {}

    def cast_vote(self, user_name, choice):
        if user_name == 'intruder':
            return False, 'Not a registered voter'
        self._votes[user_name] = choice
        return True, 'Vote recorded'

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'voting_method': self.voting_method,
            'vote_counts': {'620': len(self._votes)},
            'total_votes': len(self._votes),
        }


class _FakeMultiPicker:
    def __init__(self, common=None, voting_method='plurality'):
        self.users = [{'name': 'alice'}, {'name': 'bob'}]
        self._common = common if common is not None else [
            {'appid': 620, 'name': 'Portal 2', 'playtime_forever': 120},
            {'appid': 570, 'name': 'Dota 2', 'playtime_forever': 60},
        ]
        self._sessions = {}
        self._method = voting_method
        self.closed = None

    def find_common_games(self, users=None):
        return list(self._common)

    def filter_coop_games(self, games):
        return games

    def create_voting_session(self, candidates, voters=None, duration=None,
                              voting_method='plurality'):
        s = _FakeSession('vote-1', voting_method=voting_method)
        self._sessions['vote-1'] = s
        return s

    def get_voting_session(self, session_id):
        return self._sessions.get(session_id)

    def close_voting_session(self, session_id):
        self.closed = session_id
        return {'appid': 620, 'name': 'Portal 2', 'playtime_forever': 120}


class BackendVotingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self.mp = _FakeMultiPicker()
        self._patches = [
            patch.object(gapi_gui, '_ensure_multi_picker', lambda: None),
            patch.object(gapi_gui, 'multi_picker', self.mp),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # --- auth / init -----------------------------------------------------

    def test_requires_login(self):
        c = TestClient(app)
        self.assertEqual(c.post('/api/voting/create', json={}).status_code, 401)

    def test_not_initialized_is_400(self):
        with patch.object(gapi_gui, 'multi_picker', None):
            resp = self.client.post('/api/voting/create', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not initialized', resp.json()['detail'])

    # --- create ----------------------------------------------------------

    def test_create_returns_session_201(self):
        resp = self.client.post('/api/voting/create',
                                json={'num_candidates': 2})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['session_id'], 'vote-1')

    def test_create_invalid_method_is_400(self):
        resp = self.client.post('/api/voting/create',
                                json={'voting_method': 'dictatorship'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('voting_method', resp.json()['detail'])

    def test_create_no_common_games_is_404(self):
        with patch.object(gapi_gui, 'multi_picker', _FakeMultiPicker(common=[])):
            resp = self.client.post('/api/voting/create', json={})
        self.assertEqual(resp.status_code, 404)

    # --- cast vote -------------------------------------------------------

    def _create(self, **kw):
        return self.client.post('/api/voting/create', json=kw).json()

    def test_cast_vote_plurality(self):
        self._create(num_candidates=2)
        resp = self.client.post('/api/voting/vote-1/vote',
                                json={'user_name': 'alice', 'app_id': '620'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_cast_vote_requires_user_name(self):
        self._create()
        resp = self.client.post('/api/voting/vote-1/vote', json={'app_id': '620'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('user_name is required', resp.json()['detail'])

    def test_cast_vote_unknown_session_404(self):
        resp = self.client.post('/api/voting/ghost/vote',
                                json={'user_name': 'alice', 'app_id': '620'})
        self.assertEqual(resp.status_code, 404)

    def test_cast_vote_plurality_requires_app_id(self):
        self._create()
        resp = self.client.post('/api/voting/vote-1/vote',
                                json={'user_name': 'alice'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('app_id is required', resp.json()['detail'])

    def test_cast_vote_rejected_returns_400(self):
        self._create()
        resp = self.client.post('/api/voting/vote-1/vote',
                                json={'user_name': 'intruder', 'app_id': '620'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Not a registered voter', resp.json()['detail'])

    def test_ranked_choice_requires_ranking_list(self):
        with patch.object(gapi_gui, 'multi_picker',
                          _FakeMultiPicker(voting_method='ranked_choice')):
            self.client.post('/api/voting/create',
                             json={'voting_method': 'ranked_choice'})
            resp = self.client.post('/api/voting/vote-1/vote',
                                    json={'user_name': 'alice', 'app_id': '620'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('ranking', resp.json()['detail'])

    # --- status / close --------------------------------------------------

    def test_status_returns_dict(self):
        self._create()
        resp = self.client.get('/api/voting/vote-1/status')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['session_id'], 'vote-1')

    def test_status_unknown_session_404(self):
        self.assertEqual(self.client.get('/api/voting/ghost/status').status_code, 404)

    def test_close_returns_winner(self):
        self._create()
        resp = self.client.post('/api/voting/vote-1/close')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['winner']['name'], 'Portal 2')
        self.assertEqual(body['winner']['app_id'], 620)
        self.assertEqual(self.mp.closed, 'vote-1')

    def test_close_unknown_session_404(self):
        self.assertEqual(self.client.post('/api/voting/ghost/close').status_code, 404)


if __name__ == '__main__':
    unittest.main()
