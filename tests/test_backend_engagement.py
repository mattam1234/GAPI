#!/usr/bin/env python3
"""Tests for the migrated engagement cluster (FastAPI).

Covers all routes across six prefixes:
  creator:      GET /api/creator/dashboard, POST /api/creator/apply
  battlepass:   GET /api/battlepass/current, POST /api/battlepass/claim/{level}
  referral:     GET /api/referral/code, POST /api/referral/use/{code}
  streaming:    GET /api/streaming/vods, POST /api/streaming/start
  progression:  GET /api/progression
  ranked:       GET /api/ranked

The ``/api/streaming`` and ``/api/ranked`` handlers reference a never-defined
``gapi_gui.db_service``; the resulting ``AttributeError`` is caught and a
success-faking mock response is returned. That latent behaviour is preserved
and exercised (the "mock fallback" tests). The persist path is exercised by
patching ``gapi_gui.db_service`` to a MagicMock — no real database is ever
touched. Creator/battlepass/referral/progression are pure stubs.

Run with:
    python -m pytest tests/test_backend_engagement.py
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

    def test_creator_dashboard_requires_login(self):
        self.assertEqual(self.client.get('/api/creator/dashboard').status_code, 401)

    def test_creator_apply_requires_login(self):
        self.assertEqual(
            self.client.post('/api/creator/apply', json={}).status_code, 401)

    def test_battlepass_current_requires_login(self):
        self.assertEqual(self.client.get('/api/battlepass/current').status_code, 401)

    def test_battlepass_claim_requires_login(self):
        self.assertEqual(
            self.client.post('/api/battlepass/claim/10').status_code, 401)

    def test_referral_code_requires_login(self):
        self.assertEqual(self.client.get('/api/referral/code').status_code, 401)

    def test_referral_use_requires_login(self):
        self.assertEqual(
            self.client.post('/api/referral/use/ABC').status_code, 401)

    def test_streaming_vods_requires_login(self):
        self.assertEqual(self.client.get('/api/streaming/vods').status_code, 401)

    def test_streaming_start_requires_login(self):
        self.assertEqual(
            self.client.post('/api/streaming/start', json={}).status_code, 401)

    def test_progression_requires_login(self):
        self.assertEqual(self.client.get('/api/progression').status_code, 401)

    def test_ranked_requires_login(self):
        self.assertEqual(self.client.get('/api/ranked').status_code, 401)


# ── creator ─────────────────────────────────────────────────────────────────

class CreatorTest(_AuthedCase):
    def test_dashboard(self):
        resp = self.client.get('/api/creator/dashboard')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['tier'], 'gold')
        self.assertEqual(body['followers'], 125800)
        self.assertEqual(body['status'], 'verified')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_apply(self):
        resp = self.client.post('/api/creator/apply', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Application submitted for review',
             'status': 'pending'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_apply_no_body(self):
        resp = self.client.post('/api/creator/apply')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'pending')


# ── battlepass ──────────────────────────────────────────────────────────────

class BattlepassTest(_AuthedCase):
    def test_current(self):
        resp = self.client.get('/api/battlepass/current')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['battle_pass']['name'], 'Season 5: Storm Rising')
        self.assertEqual(body['battle_pass']['season'], 5)
        self.assertEqual(len(body['rewards']), 4)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_claim(self):
        resp = self.client.post('/api/battlepass/claim/25')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Reward for level 25 claimed!',
             'item': '[Title] Storm Chaser'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── referral ────────────────────────────────────────────────────────────────

class ReferralTest(_AuthedCase):
    def test_code(self):
        resp = self.client.get('/api/referral/code')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['code'], 'REFERALICE123')
        self.assertEqual(body['reward_per_use'], 500)
        self.assertTrue(body['active'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_use(self):
        resp = self.client.post('/api/referral/use/REFERBOB123')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Gained 500 points from referral!',
             'points_gained': 500})
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── streaming ───────────────────────────────────────────────────────────────

class StreamingVodsTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            (7, 'My VOD', '0:30:00', 99),
        ]
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/streaming/vods')
        self.assertEqual(resp.status_code, 200)
        vod = resp.json()['vods'][0]
        self.assertEqual(vod['id'], '7')
        self.assertEqual(vod['title'], 'My VOD')
        self.assertEqual(vod['views'], 99)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.get('/api/streaming/vods')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['vods'][0]['title'], 'Epic Gaming Session')
        self.assertEqual(resp.headers['cache-control'], 'no-store')


class StreamingStartTest(_AuthedCase):
    def test_missing_title_400(self):
        resp = self.client.post('/api/streaming/start', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Stream title required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success_persisted(self):
        db = MagicMock()
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/streaming/start',
                                    json={'title': 'Live!'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Stream started',
             'stream_url': 'rtmp://twitch.tv/...'})

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/streaming/start', json={'title': 'Live!'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Stream started (mock)',
             'stream_url': 'rtmp://twitch.tv/...'})


# ── progression ─────────────────────────────────────────────────────────────

class ProgressionTest(_AuthedCase):
    def test_get(self):
        resp = self.client.get('/api/progression')
        self.assertEqual(resp.status_code, 200)
        paths = resp.json()['paths']
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[0]['name'], 'Competitive Player')
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── ranked ──────────────────────────────────────────────────────────────────

class RankedTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = ('gold', 3)
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/ranked')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['current_tier_index'], 2)
        self.assertEqual(body['current_rank'], 'Gold 3')
        self.assertEqual(body['current_rank_emoji'], '🥇')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success_no_rating_defaults_bronze(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/ranked')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['current_tier_index'], 0)
        self.assertEqual(body['current_rank'], 'Bronze 1')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.get('/api/ranked')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['current_rank'], 'Silver II')
        self.assertEqual(body['current_tier_index'], 1)
        self.assertEqual(resp.headers['cache-control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
