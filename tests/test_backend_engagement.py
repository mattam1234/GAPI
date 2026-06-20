#!/usr/bin/env python3
"""Tests for the engagement cluster (real, persistent FastAPI features).

Covers all routes across six prefixes:
  creator:      GET /api/creator/dashboard, POST /api/creator/apply
  battlepass:   GET /api/battlepass/current, POST /api/battlepass/claim/{level}
  referral:     GET /api/referral/code, POST /api/referral/use/{code}
  streaming:    GET /api/streaming/vods, POST /api/streaming/start
  progression:  GET /api/progression
  ranked:       GET /api/ranked

These exercise REAL behaviour against an in-memory SQLite database (StaticPool
so every connection shares one schema/data set). ``database.SessionLocal`` is
patched to a session factory bound to that engine. No mock-success fallbacks
remain. Each test class gets a fresh, isolated database.

Run with:
    python -m pytest tests/test_backend_engagement.py
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
import backend.models.engagement as em  # noqa: F401  (registers tables on Base)


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


_ENGAGEMENT_TABLES = [
    em.EngagementBattlePassProgress.__table__,
    em.EngagementCreatorApplication.__table__,
    em.EngagementReferralCode.__table__,
    em.EngagementReferralRedemption.__table__,
    em.EngagementStreamSession.__table__,
    em.EngagementProgressionState.__table__,
    em.EngagementRankedStanding.__table__,
]


def _make_engine_factory():
    """In-memory SQLite engine + session factory with the engagement tables."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(bind=engine, tables=_ENGAGEMENT_TABLES)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, Session


class _EngagementCase(unittest.TestCase):
    """Base: fresh in-memory DB + patched SessionLocal; authed as 'alice'."""

    def setUp(self):
        self.engine, self.Session = _make_engine_factory()
        self._patch = patch.object(database, 'SessionLocal', self.Session)
        self._patch.start()
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        self._patch.stop()
        self.engine.dispose()

    def _client_for(self, username):
        c = TestClient(app)
        c.cookies.set('session', _session_cookie(username))
        return c


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

class CreatorTest(_EngagementCase):
    def test_dashboard_default_status_none(self):
        resp = self.client.get('/api/creator/dashboard')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'none')
        self.assertIn('tier', body)
        self.assertIn('followers', body)
        self.assertIn('next_tier_followers', body)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_apply_creates_pending(self):
        resp = self.client.post('/api/creator/apply', json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['status'], 'pending')
        self.assertEqual(body['message'], 'Application submitted for review')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_apply_no_body(self):
        resp = self.client.post('/api/creator/apply')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'pending')

    def test_apply_idempotent(self):
        first = self.client.post('/api/creator/apply', json={})
        second = self.client.post('/api/creator/apply', json={})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['status'], 'pending')
        self.assertEqual(second.json()['message'], 'Application already on file')
        self.assertTrue(first.json()['success'])

    def test_dashboard_reflects_application(self):
        self.client.post('/api/creator/apply', json={})
        body = self.client.get('/api/creator/dashboard').json()
        self.assertEqual(body['status'], 'pending')


# ── battlepass ──────────────────────────────────────────────────────────────

class BattlepassTest(_EngagementCase):
    def test_current_lazy_default(self):
        resp = self.client.get('/api/battlepass/current')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['battle_pass']['season'], 5)
        self.assertEqual(body['battle_pass']['name'], 'Season 5: Storm Rising')
        self.assertEqual(body['battle_pass']['current_level'], 1)
        self.assertEqual(len(body['rewards']), 4)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_claim_tier_too_low_403(self):
        # Fresh user is tier 1; claiming level 25 should be forbidden.
        resp = self.client.post('/api/battlepass/claim/25')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_claim_unknown_level_404(self):
        resp = self.client.post('/api/battlepass/claim/7')
        self.assertEqual(resp.status_code, 404)

    def test_claim_non_numeric_404(self):
        resp = self.client.post('/api/battlepass/claim/abc')
        self.assertEqual(resp.status_code, 404)

    def _bump_tier(self, username, tier):
        s = self.Session()
        try:
            row = (s.query(em.EngagementBattlePassProgress)
                   .filter(em.EngagementBattlePassProgress.username == username).first())
            if row is None:
                row = em.EngagementBattlePassProgress(username=username, season=5, tier=tier)
                s.add(row)
            else:
                row.tier = tier
            s.commit()
        finally:
            s.close()

    def test_claim_success_when_tier_high_enough(self):
        # Ensure the row exists, then raise the tier above the reward level.
        self.client.get('/api/battlepass/current')
        self._bump_tier('alice', 30)
        resp = self.client.post('/api/battlepass/claim/25')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Reward for level 25 claimed!')
        self.assertEqual(body['item'], '500 Points')

    def test_claim_twice_409(self):
        self.client.get('/api/battlepass/current')
        self._bump_tier('alice', 30)
        self.assertEqual(self.client.post('/api/battlepass/claim/25').status_code, 200)
        resp = self.client.post('/api/battlepass/claim/25')
        self.assertEqual(resp.status_code, 409)

    def test_claim_persists_in_rewards_list(self):
        self.client.get('/api/battlepass/current')
        self._bump_tier('alice', 30)
        self.client.post('/api/battlepass/claim/25')
        rewards = self.client.get('/api/battlepass/current').json()['rewards']
        claimed = {r['level']: r['claimed'] for r in rewards}
        self.assertTrue(claimed[25])
        self.assertFalse(claimed[50])


# ── referral ────────────────────────────────────────────────────────────────

class ReferralTest(_EngagementCase):
    def test_code_get_or_create_stable(self):
        resp = self.client.get('/api/referral/code')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['code'].startswith('REFERALICE'))
        self.assertEqual(body['reward_per_use'], 500)
        self.assertTrue(body['active'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        # Stable across calls.
        again = self.client.get('/api/referral/code').json()['code']
        self.assertEqual(body['code'], again)

    def test_redeem_success(self):
        alice_code = self.client.get('/api/referral/code').json()['code']
        bob = self._client_for('bob')
        resp = bob.post(f'/api/referral/use/{alice_code}')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['points_gained'], 500)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_redeem_increments_owner_total_uses(self):
        alice_code = self.client.get('/api/referral/code').json()['code']
        self._client_for('bob').post(f'/api/referral/use/{alice_code}')
        body = self.client.get('/api/referral/code').json()
        self.assertEqual(body['total_uses'], 1)
        self.assertEqual(body['total_earned'], 500)

    def test_redeem_own_code_400(self):
        alice_code = self.client.get('/api/referral/code').json()['code']
        resp = self.client.post(f'/api/referral/use/{alice_code}')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_unknown_code_404(self):
        bob = self._client_for('bob')
        resp = bob.post('/api/referral/use/NOPE')
        self.assertEqual(resp.status_code, 404)

    def test_redeem_twice_409(self):
        alice_code = self.client.get('/api/referral/code').json()['code']
        bob = self._client_for('bob')
        self.assertEqual(bob.post(f'/api/referral/use/{alice_code}').status_code, 200)
        resp = bob.post(f'/api/referral/use/{alice_code}')
        self.assertEqual(resp.status_code, 409)


# ── streaming ───────────────────────────────────────────────────────────────

class StreamingTest(_EngagementCase):
    def test_vods_empty_default(self):
        resp = self.client.get('/api/streaming/vods')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'vods': []})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_start_missing_title_400(self):
        resp = self.client.post('/api/streaming/start', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Stream title required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_start_creates_live_session(self):
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False, create=True):
            resp = self.client.post('/api/streaming/start', json={'title': 'Live!'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Stream started')
        self.assertEqual(body['stream_url'], 'rtmp://twitch.tv/...')

    def test_start_then_vods_lists_session(self):
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False, create=True):
            self.client.post('/api/streaming/start', json={'title': 'Live!'})
        vods = self.client.get('/api/streaming/vods').json()['vods']
        self.assertEqual(len(vods), 1)
        self.assertEqual(vods[0]['title'], 'Live!')
        self.assertEqual(vods[0]['status'], 'live')

    def test_vods_scoped_per_user(self):
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False, create=True):
            self.client.post('/api/streaming/start', json={'title': 'Alice Stream'})
        bob = self._client_for('bob')
        self.assertEqual(bob.get('/api/streaming/vods').json()['vods'], [])


# ── progression ─────────────────────────────────────────────────────────────

class ProgressionTest(_EngagementCase):
    def test_get_lazy_default(self):
        resp = self.client.get('/api/progression')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        paths = body['paths']
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[0]['name'], 'Competitive Player')
        self.assertEqual(body['level'], 1)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_get_persists_state_row(self):
        self.client.get('/api/progression')
        s = self.Session()
        try:
            count = s.query(em.EngagementProgressionState).filter(
                em.EngagementProgressionState.username == 'alice').count()
        finally:
            s.close()
        self.assertEqual(count, 1)


# ── ranked ──────────────────────────────────────────────────────────────────

class RankedTest(_EngagementCase):
    def test_get_lazy_default_bronze(self):
        resp = self.client.get('/api/ranked')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['current_tier_index'], 0)
        self.assertTrue(body['current_rank'].startswith('Bronze'))
        self.assertEqual(body['rating_points'], 0)
        self.assertEqual(body['tiers'],
                         ['Bronze', 'Silver', 'Gold', 'Diamond', 'Master'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_get_reflects_higher_rating(self):
        # Seed a higher rating directly, then read it back.
        s = self.Session()
        try:
            s.add(em.EngagementRankedStanding(username='alice', rating=1300, wins=5, losses=2))
            s.commit()
        finally:
            s.close()
        body = self.client.get('/api/ranked').json()
        self.assertEqual(body['current_tier_index'], 2)  # 1300 // 600 == 2
        self.assertTrue(body['current_rank'].startswith('Gold'))
        self.assertEqual(body['wins'], 5)
        self.assertEqual(body['losses'], 2)

    def test_get_persists_state_row(self):
        self.client.get('/api/ranked')
        s = self.Session()
        try:
            count = s.query(em.EngagementRankedStanding).filter(
                em.EngagementRankedStanding.username == 'alice').count()
        finally:
            s.close()
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
