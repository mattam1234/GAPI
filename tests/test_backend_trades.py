#!/usr/bin/env python3
"""Tests for the trades domain (real, persistent FastAPI feature).

Covers all 4 routes under /api/trades:
  * GET    /api/trades
  * POST   /api/trades/create
  * POST   /api/trades/{trade_id}/accept
  * POST   /api/trades/{trade_id}/decline

These exercise REAL behaviour against an in-memory SQLite database (StaticPool
so every connection shares one schema/data set). ``database.SessionLocal`` is
patched to a session factory bound to that engine, and ``database.user_exists``
is patched to recognise the test users. No mock-success fallbacks remain.

Run with:
    python -m pytest tests/test_backend_trades.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import gapi_gui
import database
from backend.main import app
import backend.models.trades  # noqa: F401  (registers Trade on Base)


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


# Users the tests treat as "existing" for recipient validation.
_KNOWN_USERS = {'alice', 'bob', 'carol'}


def _make_engine_factory():
    """Build an in-memory SQLite engine + session factory with the trades table."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(
        bind=engine, tables=[backend.models.trades.Trade.__table__])
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, Session


class _TradesCase(unittest.TestCase):
    """Base case: a fresh in-memory DB + patched SessionLocal/user_exists."""

    def setUp(self):
        self.engine, self.Session = _make_engine_factory()
        self._patches = [
            patch.object(database, 'SessionLocal', self.Session),
            patch.object(database, 'user_exists',
                         side_effect=lambda db, u: u in _KNOWN_USERS,
                         create=True),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _client_for(self, username):
        c = TestClient(app)
        c.cookies.set('session', _session_cookie(username))
        return c

    def _create(self, client=None, **payload):
        client = client or self.client
        body = {'to_user': 'bob', 'offered_items': ['Portal 2'],
                'requested_items': ['Elden Ring']}
        body.update(payload)
        return client.post('/api/trades/create', json=body)


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


# ── POST /api/trades/create ─────────────────────────────────────────────────

class CreateTradeTest(_TradesCase):
    def test_create_returns_pending_trade(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['from_user'], 'alice')
        self.assertEqual(data['to_user'], 'bob')
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['offered_items'], ['Portal 2'])
        self.assertEqual(data['requested_items'], ['Elden Ring'])
        self.assertIn('id', data)
        self.assertIn('message', data)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_create_persists(self):
        tid = self._create().json()['id']
        # New client / new session: trade must still be there.
        resp = self.client.get('/api/trades')
        ids = [t['id'] for t in resp.json()['trades']]
        self.assertIn(tid, ids)

    def test_trade_with_self_400(self):
        resp = self._create(to_user='alice')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('yourself', resp.json()['error'])

    def test_missing_recipient_400(self):
        resp = self.client.post('/api/trades/create',
                                json={'offered_items': ['X']})
        self.assertEqual(resp.status_code, 400)

    def test_empty_items_400(self):
        resp = self._create(offered_items=[], requested_items=[])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_unknown_recipient_400(self):
        resp = self._create(to_user='ghost')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('exist', resp.json()['error'])

    def test_empty_body_400(self):
        resp = self.client.post('/api/trades/create', json={})
        self.assertEqual(resp.status_code, 400)


# ── GET /api/trades ─────────────────────────────────────────────────────────

class GetTradesTest(_TradesCase):
    def test_shows_in_both_users_lists(self):
        tid = self._create().json()['id']

        sender_ids = [t['id'] for t in self.client.get('/api/trades').json()['trades']]
        self.assertIn(tid, sender_ids)

        bob = self._client_for('bob')
        recip_trades = bob.get('/api/trades').json()['trades']
        recip_ids = [t['id'] for t in recip_trades]
        self.assertIn(tid, recip_ids)
        self.assertEqual(recip_trades[0]['status'], 'pending')

    def test_unrelated_user_sees_nothing(self):
        self._create()
        carol = self._client_for('carol')
        self.assertEqual(carol.get('/api/trades').json()['trades'], [])

    def test_empty_list(self):
        resp = self.client.get('/api/trades')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'trades': []})
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── POST /api/trades/{trade_id}/accept ──────────────────────────────────────

class AcceptTradeTest(_TradesCase):
    def test_recipient_accept_sets_accepted_and_persists(self):
        tid = self._create().json()['id']
        bob = self._client_for('bob')
        resp = bob.post(f'/api/trades/{tid}/accept')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'accepted')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

        # Persisted: GET reflects accepted status.
        trades = bob.get('/api/trades').json()['trades']
        self.assertEqual(
            next(t for t in trades if t['id'] == tid)['status'], 'accepted')

    def test_non_recipient_accept_403(self):
        tid = self._create().json()['id']
        # alice is the sender, not the recipient.
        resp = self.client.post(f'/api/trades/{tid}/accept')
        self.assertEqual(resp.status_code, 403)
        # Unchanged.
        bob = self._client_for('bob')
        trades = bob.get('/api/trades').json()['trades']
        self.assertEqual(
            next(t for t in trades if t['id'] == tid)['status'], 'pending')

    def test_accept_already_accepted_409(self):
        tid = self._create().json()['id']
        bob = self._client_for('bob')
        self.assertEqual(bob.post(f'/api/trades/{tid}/accept').status_code, 200)
        resp = bob.post(f'/api/trades/{tid}/accept')
        self.assertEqual(resp.status_code, 409)

    def test_accept_missing_404(self):
        resp = self.client.post('/api/trades/999999/accept')
        self.assertEqual(resp.status_code, 404)


# ── POST /api/trades/{trade_id}/decline ─────────────────────────────────────

class DeclineTradeTest(_TradesCase):
    def test_recipient_decline_sets_declined(self):
        tid = self._create().json()['id']
        bob = self._client_for('bob')
        resp = bob.post(f'/api/trades/{tid}/decline')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'declined')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_non_recipient_decline_403(self):
        tid = self._create().json()['id']
        resp = self.client.post(f'/api/trades/{tid}/decline')
        self.assertEqual(resp.status_code, 403)

    def test_decline_already_declined_409(self):
        tid = self._create().json()['id']
        bob = self._client_for('bob')
        self.assertEqual(bob.post(f'/api/trades/{tid}/decline').status_code, 200)
        resp = bob.post(f'/api/trades/{tid}/decline')
        self.assertEqual(resp.status_code, 409)

    def test_accept_after_decline_409(self):
        tid = self._create().json()['id']
        bob = self._client_for('bob')
        bob.post(f'/api/trades/{tid}/decline')
        self.assertEqual(bob.post(f'/api/trades/{tid}/accept').status_code, 409)

    def test_decline_missing_404(self):
        resp = self.client.post('/api/trades/999999/decline')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
