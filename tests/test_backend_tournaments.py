#!/usr/bin/env python3
"""Tests for the migrated tournaments domain (FastAPI).

Covers all 3 live routes under /api/tournaments:
  * GET   /api/tournaments
  * GET   /api/tournaments/{tournament_id}
  * POST  /api/tournaments/register/{tournament_id}

These are mock handlers (no DB/service layer), faithfully ported from the
legacy Flask app. The legacy GET-list behaviour is that of ``api_get_tournaments``
(the first-registered, hence live, of two same-path handlers); the later
``api_list_tournaments`` was unreachable dead code and was dropped.

Run with:
    python -m pytest tests/test_backend_tournaments.py
"""
import os
import sys
import unittest

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

    def test_list_requires_login(self):
        self.assertEqual(self.client.get('/api/tournaments').status_code, 401)

    def test_detail_requires_login(self):
        self.assertEqual(self.client.get('/api/tournaments/1').status_code, 401)

    def test_register_requires_login(self):
        self.assertEqual(
            self.client.post('/api/tournaments/register/1', json={}).status_code, 401)


# ── GET /api/tournaments ────────────────────────────────────────────────────

class ListTournamentsTest(_AuthedCase):
    def test_default_active_filter(self):
        resp = self.client.get('/api/tournaments')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        names = [t['name'] for t in resp.json()['tournaments']]
        self.assertEqual(names, ['Spring Showdown', 'Weekend Bash'])
        self.assertTrue(all(t['status'] == 'active'
                            for t in resp.json()['tournaments']))

    def test_upcoming_filter(self):
        resp = self.client.get('/api/tournaments?status=upcoming')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()['tournaments']
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['name'], 'Summer Championship')

    def test_completed_filter_has_winner(self):
        resp = self.client.get('/api/tournaments?status=completed')
        body = resp.json()['tournaments']
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['winner'], 'ProGamer42')

    def test_status_all_returns_everything(self):
        resp = self.client.get('/api/tournaments?status=all')
        self.assertEqual(len(resp.json()['tournaments']), 4)

    def test_status_case_insensitive(self):
        resp = self.client.get('/api/tournaments?status=ACTIVE')
        self.assertEqual(len(resp.json()['tournaments']), 2)

    def test_unknown_status_yields_empty(self):
        resp = self.client.get('/api/tournaments?status=nonexistent')
        self.assertEqual(resp.json()['tournaments'], [])


# ── GET /api/tournaments/{tournament_id} ────────────────────────────────────

class GetTournamentTest(_AuthedCase):
    def test_success_includes_current_user_in_bracket(self):
        resp = self.client.get('/api/tournaments/5')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        body = resp.json()
        self.assertEqual(body['tournament']['id'], 5)
        self.assertEqual(body['tournament']['name'], 'Spring Championship 2026')
        users = [b['user'] for b in body['bracket']]
        self.assertIn('alice', users)

    def test_non_int_id_returns_404(self):
        # int(tournament_id) raises ValueError inside the try -> 404 (preserved).
        resp = self.client.get('/api/tournaments/notanint')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'error': 'Tournament not found'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── POST /api/tournaments/register/{tournament_id} ──────────────────────────

class RegisterTournamentTest(_AuthedCase):
    def test_success(self):
        resp = self.client.post('/api/tournaments/register/3', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        self.assertEqual(resp.json(), {
            'success': True,
            'message': 'Tournament registration successful',
            'bracket_position': 32,
        })

    def test_success_without_body(self):
        resp = self.client.post('/api/tournaments/register/9')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

    def test_non_int_id_still_registers(self):
        # Path param is a string; the handler never parses it -> success.
        resp = self.client.post('/api/tournaments/register/abc', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])


if __name__ == '__main__':
    unittest.main()
