#!/usr/bin/env python3
"""Tests for the migrated community cluster (FastAPI).

Covers all routes across four prefixes:
  guilds:  GET /api/guilds, POST /api/guilds/create, POST /api/guilds/{id}/join
  teams:   GET /api/teams, POST /api/teams/create, POST /api/teams/{id}/join
  market:  GET /api/market, POST /api/market/sell, POST /api/market/{id}/offer
  system:  GET /api/system/cache/stats, POST /api/system/cache/clear,
           GET /api/system/indexes

Guilds and teams are now REAL, persistent features backed by the
``backend.models.community`` ORM models and the ``app.services.community_service``
business layer. The guild/team tests below run against a fresh in-memory SQLite
database (created per test via :class:`_CommunityDbCase`, which patches
``database.SessionLocal`` to a session bound to that engine), so create/join
behaviour is exercised end-to-end without touching the real database. Market and
system remain stubs / mock-backed and are tested unchanged.

Run with:
    python -m pytest tests/test_backend_community.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
import gapi_gui
from backend.main import app
# Ensure the community models are registered on the shared Base metadata.
from backend.models import community as community_models  # noqa: F401


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


class _CommunityDbCase(unittest.TestCase):
    """Authenticated case with a fresh in-memory SQLite DB per test.

    Patches ``database.SessionLocal`` (which the community router calls) to a
    sessionmaker bound to a private in-memory engine with the community tables
    created. The patch is active for the duration of each test.
    """
    username = 'alice'

    def setUp(self):
        self.engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        database.Base.metadata.create_all(bind=self.engine)
        self.TestSession = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine)
        self._patcher = patch.object(database, 'SessionLocal', self.TestSession)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self.engine.dispose)

        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie(self.username))

    def _client_as(self, username):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie(username))
        return client


class _AdminCase(unittest.TestCase):
    """Authenticated as the literal user 'admin' (system cache-clear gate)."""
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))


# ── Auth gating ─────────────────────────────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_guilds_get_requires_login(self):
        self.assertEqual(self.client.get('/api/guilds').status_code, 401)

    def test_guilds_create_requires_login(self):
        self.assertEqual(
            self.client.post('/api/guilds/create', json={}).status_code, 401)

    def test_guilds_join_requires_login(self):
        self.assertEqual(
            self.client.post('/api/guilds/5/join').status_code, 401)

    def test_teams_get_requires_login(self):
        self.assertEqual(self.client.get('/api/teams').status_code, 401)

    def test_teams_create_requires_login(self):
        self.assertEqual(
            self.client.post('/api/teams/create', json={}).status_code, 401)

    def test_teams_join_requires_login(self):
        self.assertEqual(
            self.client.post('/api/teams/5/join').status_code, 401)

    def test_market_get_requires_login(self):
        self.assertEqual(self.client.get('/api/market').status_code, 401)

    def test_market_sell_requires_login(self):
        self.assertEqual(
            self.client.post('/api/market/sell', json={}).status_code, 401)

    def test_market_offer_requires_login(self):
        self.assertEqual(
            self.client.post('/api/market/5/offer', json={}).status_code, 401)

    def test_system_cache_stats_requires_login(self):
        self.assertEqual(
            self.client.get('/api/system/cache/stats').status_code, 401)

    def test_system_cache_clear_requires_login(self):
        self.assertEqual(
            self.client.post('/api/system/cache/clear').status_code, 401)

    def test_system_indexes_requires_login(self):
        self.assertEqual(
            self.client.get('/api/system/indexes').status_code, 401)


# ── guilds ──────────────────────────────────────────────────────────────────

class GuildsTest(_CommunityDbCase):
    def test_list_empty(self):
        resp = self.client.get('/api/guilds')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body['my_guild'])
        self.assertEqual(body['recommended_guilds'], [])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_create_then_appears_in_list(self):
        resp = self.client.post('/api/guilds/create', json={'name': 'Wolves'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Guild "Wolves" created!')
        guild_id = body['guild_id']
        self.assertIsInstance(guild_id, int)

        # Creator is auto-joined as owner -> guild becomes "my_guild".
        resp = self.client.get('/api/guilds')
        body = resp.json()
        self.assertIsNotNone(body['my_guild'])
        self.assertEqual(body['my_guild']['name'], 'Wolves')
        self.assertEqual(body['my_guild']['owner'], 'alice')
        self.assertEqual(body['my_guild']['role'], 'owner')
        self.assertEqual(body['my_guild']['members'], 1)
        self.assertTrue(body['my_guild']['is_member'])

    def test_create_empty_name_400(self):
        resp = self.client.post('/api/guilds/create', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Guild name required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_create_duplicate_name_same_owner_400(self):
        self.client.post('/api/guilds/create', json={'name': 'Wolves'})
        resp = self.client.post('/api/guilds/create', json={'name': 'Wolves'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('already own', resp.json()['error'])

    def test_join_persists_membership(self):
        # bob creates a guild; alice joins it.
        bob = self._client_as('bob')
        guild_id = bob.post(
            '/api/guilds/create', json={'name': 'Phoenix'}).json()['guild_id']

        resp = self.client.post(f'/api/guilds/{guild_id}/join')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Guild joined successfully!'})

        body = self.client.get('/api/guilds').json()
        self.assertEqual(body['my_guild']['name'], 'Phoenix')
        self.assertEqual(body['my_guild']['role'], 'member')
        self.assertEqual(body['my_guild']['members'], 2)

    def test_join_idempotent(self):
        bob = self._client_as('bob')
        guild_id = bob.post(
            '/api/guilds/create', json={'name': 'Phoenix'}).json()['guild_id']
        self.client.post(f'/api/guilds/{guild_id}/join')
        resp = self.client.post(f'/api/guilds/{guild_id}/join')
        self.assertEqual(resp.status_code, 200)
        # No duplicate row: still owner(bob) + alice == 2 members.
        body = self.client.get('/api/guilds').json()
        self.assertEqual(body['my_guild']['members'], 2)

    def test_join_missing_404(self):
        resp = self.client.post('/api/guilds/99999/join')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Guild not found')
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── teams ───────────────────────────────────────────────────────────────────

class GetTeamsTest(_CommunityDbCase):
    def test_list_empty(self):
        resp = self.client.get('/api/teams')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['teams'], [])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_created_team_appears(self):
        self.client.post('/api/teams/create', json={'name': 'Alpha'})
        resp = self.client.get('/api/teams')
        self.assertEqual(resp.status_code, 200)
        team = resp.json()['teams'][0]
        self.assertEqual(team['name'], 'Alpha')
        self.assertEqual(team['owner'], 'alice')
        self.assertTrue(team['is_member'])
        self.assertEqual(team['members'], ['alice'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')


class CreateTeamTest(_CommunityDbCase):
    def test_missing_name_400(self):
        resp = self.client.post('/api/teams/create', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Team name required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success_persisted(self):
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/teams/create', json={'name': 'Beta'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Team "Beta" created')
        self.assertEqual(body['team_id'], str(int(body['team_id'])))

        # Creator auto-joins; team persists in list.
        teams = self.client.get('/api/teams').json()['teams']
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]['members'], ['alice'])

    def test_duplicate_name_same_owner_400(self):
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            self.client.post('/api/teams/create', json={'name': 'Beta'})
            resp = self.client.post('/api/teams/create', json={'name': 'Beta'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('already own', resp.json()['error'])


class JoinTeamTest(_CommunityDbCase):
    def test_success_persisted(self):
        bob = self._client_as('bob')
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            team_id = bob.post(
                '/api/teams/create', json={'name': 'Gamma'}).json()['team_id']
            resp = self.client.post(f'/api/teams/{team_id}/join')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {'success': True, 'message': 'Joined team successfully'})

        team = self.client.get('/api/teams').json()['teams'][0]
        self.assertTrue(team['is_member'])
        self.assertCountEqual(team['members'], ['bob', 'alice'])

    def test_join_idempotent(self):
        bob = self._client_as('bob')
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            team_id = bob.post(
                '/api/teams/create', json={'name': 'Gamma'}).json()['team_id']
            self.client.post(f'/api/teams/{team_id}/join')
            resp = self.client.post(f'/api/teams/{team_id}/join')
        self.assertEqual(resp.status_code, 200)
        team = self.client.get('/api/teams').json()['teams'][0]
        self.assertEqual(len(team['members']), 2)

    def test_join_missing_404(self):
        resp = self.client.post('/api/teams/99999/join')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Team not found')
        self.assertEqual(resp.headers['cache-control'], 'no-store')


# ── market ──────────────────────────────────────────────────────────────────

class MarketTest(_AuthedCase):
    def test_list(self):
        resp = self.client.get('/api/market')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['listings']), 2)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_list_with_category(self):
        resp = self.client.get('/api/market', params={'category': 'themes'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['listings'][0]['seller'], 'SkylarMint')

    def test_sell(self):
        resp = self.client.post('/api/market/sell',
                                json={'item': 'X', 'price': 999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Item listed for 999 points!',
             'listing_id': 123})

    def test_sell_empty_body(self):
        resp = self.client.post('/api/market/sell', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Item listed for 0 points!')

    def test_offer(self):
        resp = self.client.post('/api/market/55/offer',
                                json={'offer_price': 1500})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Offer of 1500 points submitted!',
             'offer_id': 456})

    def test_offer_empty_body(self):
        resp = self.client.post('/api/market/55/offer', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Offer of 0 points submitted!')


# ── system ──────────────────────────────────────────────────────────────────

class SystemUnavailableTest(_AuthedCase):
    """PERFORMANCE_AVAILABLE False -> 503 on every system route."""
    def test_cache_stats_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/system/cache/stats')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Performance module not available')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_cache_clear_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.post('/api/system/cache/clear')
        self.assertEqual(resp.status_code, 503)

    def test_indexes_503(self):
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', False):
            resp = self.client.get('/api/system/indexes')
        self.assertEqual(resp.status_code, 503)


class SystemCacheStatsTest(_AuthedCase):
    def test_success(self):
        perf = MagicMock()
        perf.get_cache.return_value.stats.return_value = {'hits': 5}
        perf.get_monitor.return_value.get_all_stats.return_value = {'p50': 1}
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = self.client.get('/api/system/cache/stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['cache'], {'hits': 5})
        self.assertEqual(body['performance'], {'p50': 1})
        self.assertIn('timestamp', body)

    def test_error_500(self):
        perf = MagicMock()
        perf.get_cache.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = self.client.get('/api/system/cache/stats')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to get stats')


class SystemCacheClearTest(unittest.TestCase):
    def test_non_admin_403(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('alice'))
        perf = MagicMock()
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = client.post('/api/system/cache/clear')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'Unauthorized')

    def test_admin_success(self):
        client = TestClient(app)
        client.cookies.set('session', _session_cookie('admin'))
        perf = MagicMock()
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = client.post('/api/system/cache/clear')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {'success': True, 'message': 'Cache cleared'})
        perf.get_cache.return_value.clear.assert_called_once()


class SystemIndexesTest(_AuthedCase):
    def test_success(self):
        perf = MagicMock()
        perf.IndexAnalyzer.analyze_query_bottlenecks.return_value = ['CREATE INDEX a']
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = self.client.get('/api/system/indexes')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['suggestions'], ['CREATE INDEX a'])
        self.assertEqual(body['count'], 1)

    def test_error_500(self):
        perf = MagicMock()
        perf.IndexAnalyzer.analyze_query_bottlenecks.side_effect = RuntimeError('nope')
        with patch.object(gapi_gui, 'PERFORMANCE_AVAILABLE', True), \
                patch.object(gapi_gui, 'performance', perf, create=True):
            resp = self.client.get('/api/system/indexes')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'nope')


if __name__ == '__main__':
    unittest.main()
