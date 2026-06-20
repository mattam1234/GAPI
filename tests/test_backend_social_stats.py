#!/usr/bin/env python3
"""Tests for the migrated app-friends + stats domains (FastAPI).

Covers all 7 routes:
  * GET    /api/app-friends
  * POST   /api/app-friends/request
  * POST   /api/app-friends/respond
  * POST   /api/app-friends/remove
  * GET    /api/stats
  * GET    /api/stats/compare/candidates
  * GET    /api/stats/compare

The friend service, library/favourites services and database helpers live on
gapi_gui and are mocked so the tests never touch a real database.

Run with:
    python -m pytest tests/test_backend_social_stats.py
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


def _fake_db():
    """A MagicMock that satisfies ``next(database.get_db())`` + ``.close()``."""
    return MagicMock()


def _patch_get_db():
    """Patch database.get_db to yield a single fake session."""
    return patch.object(gapi_gui.database, 'get_db',
                        side_effect=lambda: iter([_fake_db()]))


def _patch_session_local():
    """Patch database.SessionLocal to return a fake session."""
    return patch.object(gapi_gui.database, 'SessionLocal',
                        side_effect=lambda: _fake_db())


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_app_friends_requires_login(self):
        self.assertEqual(self.client.get('/api/app-friends').status_code, 401)

    def test_request_requires_login(self):
        self.assertEqual(
            self.client.post('/api/app-friends/request', json={}).status_code, 401)

    def test_respond_requires_login(self):
        self.assertEqual(
            self.client.post('/api/app-friends/respond', json={}).status_code, 401)

    def test_remove_requires_login(self):
        self.assertEqual(
            self.client.post('/api/app-friends/remove', json={}).status_code, 401)

    def test_stats_requires_login(self):
        self.assertEqual(self.client.get('/api/stats').status_code, 401)

    def test_compare_candidates_requires_login(self):
        self.assertEqual(
            self.client.get('/api/stats/compare/candidates').status_code, 401)

    def test_compare_requires_login(self):
        self.assertEqual(self.client.get('/api/stats/compare').status_code, 401)


# ── GET /api/app-friends ────────────────────────────────────────────────────

class AppFriendsListTest(_AuthedCase):
    def test_success(self):
        payload = {'friends': [{'username': 'bob', 'is_online': True}],
                   'sent': [], 'received': []}
        with _patch_get_db(), patch.object(
                gapi_gui.database, 'get_app_friends_with_platforms',
                return_value=payload):
            resp = self.client.get('/api/app-friends')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), payload)
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── POST /api/app-friends/request ───────────────────────────────────────────

class SendFriendRequestTest(_AuthedCase):
    def test_success_via_service(self):
        svc = MagicMock()
        svc.send_request.return_value = (True, 'Request sent')
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/request',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'message': 'Request sent'})
        svc.send_request.assert_called_once()

    def test_missing_username_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/request', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'username is required')

    def test_service_failure_400(self):
        svc = MagicMock()
        svc.send_request.return_value = (False, 'Already friends')
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/request',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Already friends')

    def test_fallback_to_database_helper(self):
        with patch.object(gapi_gui, '_friend_service', None), _patch_get_db(), \
                patch.object(gapi_gui.database, 'send_friend_request',
                             return_value=(True, 'ok')) as helper:
            resp = self.client.post('/api/app-friends/request',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 200)
        helper.assert_called_once()


# ── POST /api/app-friends/respond ───────────────────────────────────────────

class RespondFriendRequestTest(_AuthedCase):
    def test_success_accept(self):
        svc = MagicMock()
        svc.respond.return_value = (True, 'Accepted')
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/respond',
                                    json={'username': 'bob', 'accept': True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'message': 'Accepted'})

    def test_missing_accept_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/respond',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'accept is required')

    def test_missing_username_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/respond',
                                    json={'accept': True})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'username is required')

    def test_service_failure_400(self):
        svc = MagicMock()
        svc.respond.return_value = (False, 'No such request')
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/respond',
                                    json={'username': 'bob', 'accept': False})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'No such request')


# ── POST /api/app-friends/remove ────────────────────────────────────────────

class RemoveFriendTest(_AuthedCase):
    def test_success(self):
        svc = MagicMock()
        svc.remove.return_value = True
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/remove',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})

    def test_missing_username_400(self):
        svc = MagicMock()
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/remove', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'username is required')

    def test_failure_500(self):
        svc = MagicMock()
        svc.remove.return_value = False
        with patch.object(gapi_gui, '_friend_service', svc), _patch_get_db():
            resp = self.client.post('/api/app-friends/remove',
                                    json={'username': 'bob'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to remove friend')


# ── GET /api/stats ──────────────────────────────────────────────────────────

class StatsTest(_AuthedCase):
    def test_success_with_games(self):
        games = [
            {'name': 'A', 'playtime_hours': 10},
            {'name': 'B', 'playtime_hours': 0},
        ]
        lib = MagicMock()
        lib.get_cached.return_value = games
        fav = MagicMock()
        fav.get_all.return_value = [1, 2, 3]
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_library_service', lib), \
                patch.object(gapi_gui, '_db_favorites_service', fav):
            resp = self.client.get('/api/stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_games'], 2)
        self.assertEqual(body['unplayed_games'], 1)
        self.assertEqual(body['played_games'], 1)
        self.assertEqual(body['favorite_count'], 3)
        self.assertEqual(len(body['top_games']), 2)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_empty_library(self):
        lib = MagicMock()
        lib.get_cached.return_value = []
        fav = MagicMock()
        fav.get_all.return_value = []
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_library_service', lib), \
                patch.object(gapi_gui, '_db_favorites_service', fav):
            resp = self.client.get('/api/stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_games'], 0)
        self.assertEqual(body['favorite_count'], 0)
        self.assertEqual(body['top_games'], [])

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/stats')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Database not available')

    def test_error_500(self):
        lib = MagicMock()
        lib.get_cached.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_library_service', lib):
            resp = self.client.get('/api/stats')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to load stats')


# ── GET /api/stats/compare/candidates ───────────────────────────────────────

class CompareCandidatesTest(_AuthedCase):
    def test_all_scope(self):
        um = MagicMock()
        um.get_all_users.return_value = [{'username': 'bob'}, {'username': 'carol'}, {}]
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, 'user_manager', um):
            resp = self.client.get('/api/stats/compare/candidates?scope=all')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['current_user'], 'alice')
        self.assertEqual(body['users'], [{'username': 'bob'}, {'username': 'carol'}])

    def test_me_and_friends_scope(self):
        friends_data = {'friends': [{'username': 'bob'}]}
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui.database, 'get_app_friends',
                             return_value=friends_data):
            resp = self.client.get(
                '/api/stats/compare/candidates?scope=me_and_friends')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['users'],
                         [{'username': 'alice'}, {'username': 'bob'}])

    def test_db_unavailable_returns_empty_200(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/stats/compare/candidates')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'users': [], 'current_user': 'alice'})

    def test_error_returns_empty_200(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui.database, 'get_app_friends',
                             side_effect=RuntimeError('boom')):
            resp = self.client.get('/api/stats/compare/candidates?scope=friends')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'users': [], 'current_user': 'alice'})


# ── GET /api/stats/compare ──────────────────────────────────────────────────

class CompareStatsTest(_AuthedCase):
    def test_success(self):
        def _cached(db, uname):
            return [{'name': 'A', 'app_id': '1', 'playtime_hours': 5},
                    {'name': 'B', 'app_id': '2', 'playtime_hours': 0}]
        lib = MagicMock()
        lib.get_cached.side_effect = _cached
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_library_service', lib):
            resp = self.client.get('/api/stats/compare?users=bob,carol')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['users']), 2)
        self.assertEqual(body['comparison_metrics']['shared_game_count'], 2)
        self.assertEqual(body['comparison_metrics']['total_unique_games'], 2)

    def test_no_users_400(self):
        resp = self.client.get('/api/stats/compare')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'No users specified')

    def test_blank_users_400(self):
        resp = self.client.get('/api/stats/compare?users=,,')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid users parameter')

    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.get('/api/stats/compare?users=bob')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Database not available')

    def test_per_user_error_recorded(self):
        lib = MagicMock()
        lib.get_cached.side_effect = RuntimeError('user boom')
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
                _patch_session_local(), \
                patch.object(gapi_gui, '_library_service', lib):
            resp = self.client.get('/api/stats/compare?users=bob')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('error', body['users'][0])
        # No valid users -> empty metrics dict.
        self.assertEqual(body['comparison_metrics'], {})


if __name__ == '__main__':
    unittest.main()
