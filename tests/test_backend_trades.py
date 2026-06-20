#!/usr/bin/env python3
"""Tests for the migrated trades domain (FastAPI).

Covers all 4 routes under /api/trades:
  * GET    /api/trades
  * POST   /api/trades/create
  * POST   /api/trades/{trade_id}/accept
  * POST   /api/trades/{trade_id}/decline

The legacy handlers all reference a module-global ``db_service`` that is never
defined on ``gapi_gui``; the resulting ``AttributeError`` is caught and the
handler returns a success-faking mock response. That latent behaviour is
preserved and exercised here (the "mock fallback" tests). The success/persist
path is exercised by patching ``gapi_gui.db_service`` to a MagicMock — no real
database is ever touched.

Run with:
    python -m pytest tests/test_backend_trades.py
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


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_get_requires_login(self):
        self.assertEqual(self.client.get('/api/trades').status_code, 401)

    def test_create_requires_login(self):
        self.assertEqual(
            self.client.post('/api/trades/create', json={}).status_code, 401)

    def test_accept_requires_login(self):
        self.assertEqual(
            self.client.post('/api/trades/5/accept').status_code, 401)

    def test_decline_requires_login(self):
        self.assertEqual(
            self.client.post('/api/trades/5/decline').status_code, 401)


# ── GET /api/trades ─────────────────────────────────────────────────────────

class GetTradesTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            (7, 'bob', 'Doom for Quake'),
        ]
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/trades')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'trades': [{'id': '7', 'from_user': 'bob',
                                      'offer': 'Doom for Quake'}]})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        # db_service is not defined on gapi_gui -> AttributeError -> mock branch.
        resp = self.client.get('/api/trades')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'trades': [{'id': '1', 'from_user': 'gamer123',
                         'offer': 'Portal 2 for Elden Ring'}]})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_on_db_error(self):
        svc = MagicMock()
        svc.get_db.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/trades')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['trades'][0]['from_user'], 'gamer123')


# ── POST /api/trades/create ─────────────────────────────────────────────────

class CreateTradeTest(_AuthedCase):
    def test_missing_fields_400(self):
        resp = self.client.post('/api/trades/create', json={'username': 'bob'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'All fields required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_empty_body_400(self):
        resp = self.client.post('/api/trades/create', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'All fields required')

    def test_user_not_found_404(self):
        svc = MagicMock()
        svc.get_db.return_value = MagicMock()
        svc.get_current_user.return_value = MagicMock(id=1)
        svc.get_user_by_username.return_value = None
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.post('/api/trades/create',
                                    json={'username': 'ghost', 'offer': 'X'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'User not found')

    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.lastrowid = 99
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        svc.get_user_by_username.return_value = MagicMock(id=2)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/trades/create',
                                    json={'username': 'bob', 'offer': 'Doom'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade offer sent to bob'})

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/trades/create',
                                json={'username': 'bob', 'offer': 'Doom'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade offer sent (mock)'})


# ── POST /api/trades/{trade_id}/accept ──────────────────────────────────────

class AcceptTradeTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/trades/42/accept')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade accepted'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/trades/42/accept')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade accepted (mock)'})


# ── POST /api/trades/{trade_id}/decline ─────────────────────────────────────

class DeclineTradeTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/trades/42/decline')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade declined'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/trades/42/decline')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'message': 'Trade declined (mock)'})


if __name__ == '__main__':
    unittest.main()
