#!/usr/bin/env python3
"""Tests for the migrated community cluster (FastAPI).

Covers all routes across four prefixes:
  guilds:  GET /api/guilds, POST /api/guilds/create, POST /api/guilds/{id}/join
  teams:   GET /api/teams, POST /api/teams/create, POST /api/teams/{id}/join
  market:  GET /api/market, POST /api/market/sell, POST /api/market/{id}/offer
  system:  GET /api/system/cache/stats, POST /api/system/cache/clear,
           GET /api/system/indexes

The ``/api/teams`` handlers reference a never-defined ``gapi_gui.db_service``;
the resulting ``AttributeError`` is caught and a success-faking mock response is
returned. That latent behaviour is preserved and exercised (the "mock fallback"
tests). The persist path is exercised by patching ``gapi_gui.db_service`` to a
MagicMock — no real database is ever touched. Guilds/market are pure stubs.

Run with:
    python -m pytest tests/test_backend_community.py
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

class GuildsTest(_AuthedCase):
    def test_list(self):
        resp = self.client.get('/api/guilds')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['my_guild']['name'], 'Shadow Legends')
        self.assertEqual(len(body['recommended_guilds']), 2)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_create(self):
        resp = self.client.post('/api/guilds/create', json={'name': 'Wolves'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Guild "Wolves" created!', 'guild_id': 99})

    def test_create_empty_body(self):
        resp = self.client.post('/api/guilds/create', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Guild "" created!')

    def test_join(self):
        resp = self.client.post('/api/guilds/7/join')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Guild joined successfully!'})


# ── teams ───────────────────────────────────────────────────────────────────

class GetTeamsTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            (3, 'Alpha', 9, 5, 70, 2, 1),
        ]
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/teams')
        self.assertEqual(resp.status_code, 200)
        team = resp.json()['teams'][0]
        self.assertEqual(team['id'], '3')
        self.assertEqual(team['name'], 'Alpha')
        self.assertEqual(team['winrate'], 70)
        self.assertTrue(team['is_member'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.get('/api/teams')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['teams'][0]['name'], 'Elite Gaming Squad')
        self.assertEqual(resp.headers['cache-control'], 'no-store')


class CreateTeamTest(_AuthedCase):
    def test_missing_name_400(self):
        resp = self.client.post('/api/teams/create', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Team name required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.lastrowid = 12
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/teams/create', json={'name': 'Beta'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Team "Beta" created', 'team_id': '12'})

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/teams/create', json={'name': 'Beta'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Team created (mock)', 'team_id': '4'})


class JoinTeamTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = ('Gamma',)
        svc = MagicMock()
        svc.get_db.return_value = db
        svc.get_current_user.return_value = MagicMock(id=1)
        with patch.object(gapi_gui, 'db_service', svc, create=True), \
                patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/teams/8/join')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {'success': True, 'message': 'Joined team successfully'})

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.post('/api/teams/8/join')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {'success': True, 'message': 'Joined team (mock)'})


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
