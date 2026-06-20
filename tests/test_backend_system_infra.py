#!/usr/bin/env python3
"""Tests for the migrated INFRA/SYSTEM single-route endpoints (FastAPI).

Covers the ~11 cross-cutting routes now served by
``backend/routers/system_infra.py``:

  GET  /api/health                    (unauth, cacheable)
  GET  /api/status                    (unauth)
  GET  /api/changelog                 (unauth, cacheable)
  GET  /api/csrf-token                (unauth, sets cookie)
  POST /api/errors/report             (unauth, ring buffer, 201)
  GET  /api/history                   (require_login)
  POST /api/moderation/report         (require_login)
  POST /api/password-reset-request    (unauth)
  GET  /api/platform/status           (require_login)
  GET  /api/user/{username}/card      (require_login)
  GET  /api/user-profile/{username}   (require_login)

No real DB / network: services and DB are patched on ``gapi_gui.*``.

Run with:
    python -m pytest tests/test_backend_system_infra.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app

_CACHEABLE = 'public, max-age=60, stale-while-revalidate=120'


def _session_cookie(username):
    ser = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return ser.dumps({'username': username})


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


class _AnonCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous


# ── health (unauth, cacheable) ──────────────────────────────────────────────

class HealthTest(_AnonCase):
    def test_anonymous(self):
        resp = self.client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['status'], 'healthy')
        self.assertFalse(body['authenticated'])
        self.assertIsNone(body['current_user'])

    def test_cache_header(self):
        resp = self.client.get('/api/health')
        self.assertEqual(resp.headers['cache-control'], _CACHEABLE)

    def test_authenticated(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('bob'))
        body = client.get('/api/health').json()
        self.assertTrue(body['authenticated'])
        self.assertEqual(body['current_user'], 'bob')


# ── status (unauth) ─────────────────────────────────────────────────────────

class StatusTest(unittest.TestCase):
    def test_not_logged_in(self):
        client = TestClient(app)
        resp = client.get('/api/status')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'ready': False, 'logged_in': False, 'message': 'Please log in'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_logged_in_picker_loading(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('alice'))
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = client.get('/api/status')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'ready': False, 'logged_in': True, 'message': 'Loading games...'})

    def test_logged_in_ready(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('alice'))
        picker = SimpleNamespace(games=[1, 2, 3], favorites=[1])
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker), \
                patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            resp = client.get('/api/status')
        body = resp.json()
        self.assertTrue(body['ready'])
        self.assertTrue(body['logged_in'])
        self.assertEqual(body['current_user'], 'alice')
        self.assertTrue(body['is_admin'])
        self.assertEqual(body['total_games'], 3)
        self.assertEqual(body['favorites'], 1)


# ── changelog (unauth, cacheable) ───────────────────────────────────────────

class ChangelogTest(_AnonCase):
    def test_default_returns_all(self):
        resp = self.client.get('/api/changelog')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_versions'], len(gapi_gui._API_CHANGELOG))
        self.assertEqual(len(body['changelog']), len(gapi_gui._API_CHANGELOG))

    def test_cache_header(self):
        resp = self.client.get('/api/changelog')
        self.assertEqual(resp.headers['cache-control'], _CACHEABLE)

    def test_limit(self):
        resp = self.client.get('/api/changelog?limit=1')
        self.assertEqual(len(resp.json()['changelog']), 1)

    def test_invalid_limit_returns_all(self):
        resp = self.client.get('/api/changelog?limit=abc')
        body = resp.json()
        self.assertEqual(len(body['changelog']), body['total_versions'])

    def test_most_recent_first(self):
        resp = self.client.get('/api/changelog')
        versions = [e['version'] for e in resp.json()['changelog']]
        self.assertEqual(versions[0], gapi_gui._API_CHANGELOG[0]['version'])


# ── csrf token (unauth, sets cookie) ────────────────────────────────────────

class CsrfTokenTest(_AnonCase):
    def test_returns_token(self):
        resp = self.client.get('/api/csrf-token')
        self.assertEqual(resp.status_code, 200)
        token = resp.json()['token']
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_sets_cookie_matching_body(self):
        resp = self.client.get('/api/csrf-token')
        token = resp.json()['token']
        set_cookie = resp.headers.get('set-cookie', '')
        self.assertIn('csrf_token=', set_cookie)
        self.assertIn(token, set_cookie)

    def test_tokens_unique(self):
        t1 = self.client.get('/api/csrf-token').json()['token']
        t2 = self.client.get('/api/csrf-token').json()['token']
        self.assertNotEqual(t1, t2)


# ── client error reporting (unauth, 201, ring buffer) ───────────────────────

class ErrorsReportTest(_AnonCase):
    def setUp(self):
        super().setUp()
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.clear()

    def test_report_201(self):
        resp = self.client.post('/api/errors/report',
                                json={'message': 'Boom', 'url': 'http://x/'})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()['recorded'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_stored_in_buffer(self):
        self.client.post('/api/errors/report', json={'message': 'StoredErr'})
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 1)
            self.assertEqual(gapi_gui._client_errors[0]['message'], 'StoredErr')

    def test_truncates_long_message(self):
        self.client.post('/api/errors/report', json={'message': 'x' * 1000})
        with gapi_gui._client_errors_lock:
            self.assertLessEqual(len(gapi_gui._client_errors[-1]['message']), 500)

    def test_empty_body_201(self):
        resp = self.client.post('/api/errors/report')
        self.assertEqual(resp.status_code, 201)

    def test_records_username_when_authed(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('carol'))
        client.post('/api/errors/report', json={'message': 'WithUser'})
        with gapi_gui._client_errors_lock:
            self.assertEqual(gapi_gui._client_errors[-1]['username'], 'carol')


# ── history (require_login) ─────────────────────────────────────────────────

class HistoryTest(_AuthedCase):
    def test_requires_login(self):
        anon = TestClient(app)
        self.assertEqual(anon.get('/api/history').status_code, 401)

    def test_no_picker_empty(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/history')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'history': []})

    def test_recent_entries(self):
        picker = SimpleNamespace(
            history=['steam:20', 'steam:10'],
            games=[
                {'game_id': 'steam:10', 'appid': 10, 'name': 'Demo A',
                 'platform': 'steam', 'playtime_forever': 60},
                {'game_id': 'steam:20', 'appid': 20, 'name': 'Demo B',
                 'platform': 'steam', 'playtime_forever': 120},
            ],
        )
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.get('/api/history')
        self.assertEqual(resp.status_code, 200)
        history = resp.json()['history']
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['game_id'], 'steam:10')
        self.assertEqual(history[0]['game_name'], 'Demo A')


# ── moderation report (require_login) ───────────────────────────────────────

class ModerationReportTest(_AuthedCase):
    def test_requires_login(self):
        anon = TestClient(app)
        self.assertEqual(
            anon.post('/api/moderation/report', json={}).status_code, 401)

    def test_service_unavailable_503(self):
        with patch.object(gapi_gui, '_moderation_service', None):
            resp = self.client.post('/api/moderation/report', json={'reason': 'x'})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Moderation service not available')

    def test_missing_reason_400(self):
        svc = MagicMock()
        db = MagicMock()
        with patch.object(gapi_gui, '_moderation_service', svc), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])):
            resp = self.client.post('/api/moderation/report', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Reason required')

    def test_success(self):
        svc = MagicMock()
        svc.report_user_content.return_value = 77
        db = MagicMock()
        with patch.object(gapi_gui, '_moderation_service', svc), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])):
            resp = self.client.post('/api/moderation/report',
                                    json={'reason': 'spam', 'type': 'chat'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'report_id': 77})
        db.close.assert_called_once()

    def test_exception_500(self):
        svc = MagicMock()
        svc.report_user_content.side_effect = RuntimeError('boom')
        db = MagicMock()
        with patch.object(gapi_gui, '_moderation_service', svc), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])):
            resp = self.client.post('/api/moderation/report',
                                    json={'reason': 'spam'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


# ── password reset request (unauth) ─────────────────────────────────────────

class PasswordResetRequestTest(_AnonCase):
    def test_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/password-reset-request',
                                    json={'username': 'x'})
        self.assertEqual(resp.status_code, 503)

    def test_missing_username_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/password-reset-request', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Username is required')

    def test_unknown_user_generic_message(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui.database, 'SessionLocal', return_value=db):
            resp = self.client.post('/api/password-reset-request',
                                    json={'username': 'ghost'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('If that username exists', resp.json()['message'])

    def test_known_user_recorded(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                patch.object(gapi_gui.database, 'SessionLocal', return_value=db), \
                patch.object(gapi_gui.database, 'PasswordResetRequest', MagicMock()):
            resp = self.client.post('/api/password-reset-request',
                                    json={'username': 'real'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('submitted', resp.json()['message'])
        db.commit.assert_called_once()


# ── platform status (require_login) ─────────────────────────────────────────

class PlatformStatusTest(_AuthedCase):
    def test_requires_login(self):
        anon = TestClient(app)
        self.assertEqual(anon.get('/api/platform/status').status_code, 401)

    def test_empty_clients(self):
        fake_picker = MagicMock()
        fake_picker.clients = {}
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/platform/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['platforms']
        for plat in ('steam', 'epic', 'gog', 'xbox', 'psn', 'nintendo'):
            self.assertIn(plat, data)
        self.assertIn('note', data['nintendo'])

    def test_picker_none_ok(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/platform/status')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['platforms']['steam']['configured'])


# ── user card (require_login) ───────────────────────────────────────────────

class UserCardTest(_AuthedCase):
    def test_requires_login(self):
        anon = TestClient(app)
        self.assertEqual(anon.get('/api/user/bob/card').status_code, 401)

    def test_found_via_leaderboard_service(self):
        svc = MagicMock()
        svc.get_user_card.return_value = {'username': 'bob', 'bio': 'hi'}
        db = MagicMock()
        with patch.object(gapi_gui, '_leaderboard_service', svc), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])):
            resp = self.client.get('/api/user/bob/card')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'bob')
        db.close.assert_called_once()

    def test_not_found_404(self):
        svc = MagicMock()
        svc.get_user_card.return_value = None
        db = MagicMock()
        with patch.object(gapi_gui, '_leaderboard_service', svc), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])):
            resp = self.client.get('/api/user/ghost/card')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'User not found')

    def test_falls_back_to_database(self):
        db = MagicMock()
        with patch.object(gapi_gui, '_leaderboard_service', None), \
                patch.object(gapi_gui.database, 'get_db', return_value=iter([db])), \
                patch.object(gapi_gui.database, 'get_user_card',
                             return_value={'username': 'bob'}):
            resp = self.client.get('/api/user/bob/card')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'bob')


# ── user profile card (require_login) ───────────────────────────────────────

class UserProfileCardTest(_AuthedCase):
    def test_requires_login(self):
        anon = TestClient(app)
        self.assertEqual(anon.get('/api/user-profile/bob').status_code, 401)

    def test_found(self):
        db = MagicMock()
        with patch.object(gapi_gui.database, 'get_db', return_value=iter([db])), \
                patch.object(gapi_gui.database, 'get_user_card',
                             return_value={'username': 'bob', 'roles': []}):
            resp = self.client.get('/api/user-profile/bob')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'bob')
        db.close.assert_called_once()

    def test_not_found_404(self):
        db = MagicMock()
        with patch.object(gapi_gui.database, 'get_db', return_value=iter([db])), \
                patch.object(gapi_gui.database, 'get_user_card', return_value=None):
            resp = self.client.get('/api/user-profile/ghost')
        self.assertEqual(resp.status_code, 404)
        self.assertIn('not found', resp.json()['error'])


if __name__ == '__main__':
    unittest.main()
