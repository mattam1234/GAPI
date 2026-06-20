#!/usr/bin/env python3
"""Tests for the tournaments domain (FastAPI) — now a REAL persistent feature.

Tournaments are backed by the database (models in ``backend/models/tournaments``
and logic in ``app/services/tournament_service``). These tests run against an
isolated in-memory SQLite engine (StaticPool) that replaces
``database.SessionLocal`` for the duration of each test, so they never touch the
real app database and start from a clean slate.

Covers the 3 live routes under /api/tournaments:
  * GET   /api/tournaments                        (list + ?status= filter)
  * GET   /api/tournaments/{tournament_id}        (detail incl. participants)
  * POST  /api/tournaments/register/{tournament_id}

Status lifecycle: upcoming -> open -> active -> completed. Registration is only
allowed while a tournament is ``open``; not-open / full -> 409; double-register
is idempotent; missing -> 404; all routes require login (401 otherwise).

Run with:
    python -m pytest tests/test_backend_tournaments.py
"""
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import gapi_gui
import database
from backend.main import app
from app.services import tournament_service
# Import the models so their tables are registered on database.Base.metadata.
from backend.models import tournaments as tournament_models  # noqa: F401


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


def _make_inmemory_sessionmaker():
    """Build a fresh in-memory SQLite sessionmaker with all tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class _DBCase(unittest.TestCase):
    """Base case: isolated in-memory DB patched over database.SessionLocal."""

    def setUp(self):
        self._SessionLocal = _make_inmemory_sessionmaker()
        self._patcher = patch.object(database, "SessionLocal", self._SessionLocal)
        self._patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._patcher.stop()

    def _login(self, username='alice'):
        self.client.cookies.set('session', _session_cookie(username))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(_DBCase):
    def setUp(self):
        super().setUp()
        # No cookie -> anonymous.

    def test_list_requires_login(self):
        self.assertEqual(self.client.get('/api/tournaments').status_code, 401)

    def test_detail_requires_login(self):
        self.assertEqual(self.client.get('/api/tournaments/1').status_code, 401)

    def test_register_requires_login(self):
        self.assertEqual(
            self.client.post('/api/tournaments/register/1', json={}).status_code, 401)


# ── Service layer ───────────────────────────────────────────────────────────

class ServiceTest(_DBCase):
    def test_create_and_get_roundtrip(self):
        created = tournament_service.create_tournament(
            name='Spring Showdown', game='Chess', status='open', max_players=8,
            created_by='admin')
        self.assertEqual(created['name'], 'Spring Showdown')
        self.assertEqual(created['status'], 'open')
        self.assertEqual(created['participants'], 0)

        detail = tournament_service.get_tournament(int(created['id']))
        self.assertEqual(detail['tournament']['name'], 'Spring Showdown')
        self.assertEqual(detail['tournament']['participants'], [])

    def test_create_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            tournament_service.create_tournament(name='   ')

    def test_create_rejects_bad_status(self):
        with self.assertRaises(ValueError):
            tournament_service.create_tournament(name='X', status='bogus')

    def test_get_missing_raises_404(self):
        with self.assertRaises(tournament_service.LookupError404):
            tournament_service.get_tournament(99999)

    def test_register_when_not_open_raises_conflict(self):
        t = tournament_service.create_tournament(name='Upcoming Cup', status='upcoming')
        with self.assertRaises(tournament_service.ConflictError):
            tournament_service.register(int(t['id']), 'alice')

    def test_register_when_full_raises_conflict(self):
        t = tournament_service.create_tournament(
            name='Tiny', status='open', max_players=1)
        tournament_service.register(int(t['id']), 'alice')
        with self.assertRaises(tournament_service.ConflictError):
            tournament_service.register(int(t['id']), 'bob')

    def test_double_register_is_idempotent(self):
        t = tournament_service.create_tournament(name='Dup', status='open')
        first = tournament_service.register(int(t['id']), 'alice')
        second = tournament_service.register(int(t['id']), 'alice')
        self.assertFalse(first['already_registered'])
        self.assertTrue(second['already_registered'])
        self.assertTrue(second['success'])
        # Only one registration row persisted.
        self.assertEqual(second['participants'], 1)

    def test_active_tournament_has_bracket(self):
        t = tournament_service.create_tournament(name='Active', status='open')
        for name in ('a', 'b', 'c'):
            tournament_service.register(int(t['id']), name)
        # Flip to active and confirm bracket pairings appear.
        db = database.SessionLocal()
        try:
            row = db.query(tournament_models.FeatureTournament).first()
            row.status = 'active'
            db.commit()
        finally:
            db.close()
        detail = tournament_service.get_tournament(int(t['id']))
        self.assertIn('bracket', detail)
        # 3 players -> 2 matches, last is a bye.
        self.assertEqual(len(detail['bracket']), 2)
        self.assertIsNone(detail['bracket'][1]['player_two'])


# ── GET /api/tournaments ────────────────────────────────────────────────────

class ListTournamentsTest(_DBCase):
    def setUp(self):
        super().setUp()
        self._login('alice')
        tournament_service.create_tournament(name='Open One', status='open')
        tournament_service.create_tournament(name='Active One', status='active')
        tournament_service.create_tournament(name='Upcoming One', status='upcoming')
        tournament_service.create_tournament(name='Done One', status='completed')

    def test_list_all_when_no_filter(self):
        resp = self.client.get('/api/tournaments')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        self.assertEqual(len(resp.json()['tournaments']), 4)

    def test_status_filter(self):
        resp = self.client.get('/api/tournaments?status=open')
        body = resp.json()['tournaments']
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['name'], 'Open One')

    def test_status_filter_case_insensitive(self):
        resp = self.client.get('/api/tournaments?status=ACTIVE')
        self.assertEqual(len(resp.json()['tournaments']), 1)

    def test_status_all_returns_everything(self):
        resp = self.client.get('/api/tournaments?status=all')
        self.assertEqual(len(resp.json()['tournaments']), 4)

    def test_unknown_status_yields_empty(self):
        resp = self.client.get('/api/tournaments?status=nonexistent')
        self.assertEqual(resp.json()['tournaments'], [])

    def test_list_items_have_expected_keys(self):
        resp = self.client.get('/api/tournaments?status=open')
        item = resp.json()['tournaments'][0]
        for key in ('id', 'name', 'game', 'status', 'participants', 'max_players'):
            self.assertIn(key, item)


# ── GET /api/tournaments/{tournament_id} ────────────────────────────────────

class GetTournamentTest(_DBCase):
    def setUp(self):
        super().setUp()
        self._login('alice')
        self.t = tournament_service.create_tournament(
            name='Detail Cup', game='Pong', status='open')

    def test_detail_includes_participants(self):
        tournament_service.register(int(self.t['id']), 'alice')
        resp = self.client.get(f"/api/tournaments/{self.t['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        body = resp.json()['tournament']
        self.assertEqual(body['name'], 'Detail Cup')
        usernames = [p['username'] for p in body['participants']]
        self.assertIn('alice', usernames)

    def test_missing_returns_404(self):
        resp = self.client.get('/api/tournaments/99999')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Tournament not found'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_non_int_id_returns_404(self):
        resp = self.client.get('/api/tournaments/notanint')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Tournament not found'})


# ── POST /api/tournaments/register/{tournament_id} ──────────────────────────

class RegisterTournamentTest(_DBCase):
    def setUp(self):
        super().setUp()
        self._login('alice')

    def test_register_persists_and_appears_in_participants(self):
        t = tournament_service.create_tournament(name='Reg Cup', status='open')
        resp = self.client.post(f"/api/tournaments/register/{t['id']}", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        self.assertTrue(resp.json()['success'])
        self.assertEqual(resp.json()['participants'], 1)

        detail = self.client.get(f"/api/tournaments/{t['id']}").json()
        usernames = [p['username'] for p in detail['tournament']['participants']]
        self.assertEqual(usernames, ['alice'])

    def test_register_without_body(self):
        t = tournament_service.create_tournament(name='NoBody Cup', status='open')
        resp = self.client.post(f"/api/tournaments/register/{t['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_register_not_open_returns_409(self):
        t = tournament_service.create_tournament(name='Upcoming', status='upcoming')
        resp = self.client.post(f"/api/tournaments/register/{t['id']}", json={})
        self.assertEqual(resp.status_code, 409)
        self.assertIn('error', resp.json())

    def test_register_full_returns_409(self):
        t = tournament_service.create_tournament(
            name='Full Cup', status='open', max_players=1)
        tournament_service.register(int(t['id']), 'bob')
        resp = self.client.post(f"/api/tournaments/register/{t['id']}", json={})
        self.assertEqual(resp.status_code, 409)

    def test_double_register_idempotent_via_route(self):
        t = tournament_service.create_tournament(name='Dup Cup', status='open')
        first = self.client.post(f"/api/tournaments/register/{t['id']}", json={})
        second = self.client.post(f"/api/tournaments/register/{t['id']}", json={})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()['already_registered'])
        # Still exactly one participant.
        detail = self.client.get(f"/api/tournaments/{t['id']}").json()
        self.assertEqual(len(detail['tournament']['participants']), 1)

    def test_register_missing_returns_404(self):
        resp = self.client.post('/api/tournaments/register/99999', json={})
        self.assertEqual(resp.status_code, 404)

    def test_register_non_int_returns_404(self):
        resp = self.client.post('/api/tournaments/register/abc', json={})
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
