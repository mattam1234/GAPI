#!/usr/bin/env python3
"""Tests for the migrated grab-bag cluster (FastAPI).

Covers all routes across six prefixes:
  i18n (UNAUTHENTICATED):
    GET /api/i18n, GET /api/i18n/{lang}
  shop:
    GET /api/shop, POST /api/shop/purchase
  events:
    GET /api/events/seasonal, POST /api/events/{event_id}/claim
  twitch:
    GET /api/twitch/trending, GET /api/twitch/library-overlap
  cosmetics:
    POST /api/cosmetics/apply-theme
  anticheat:
    GET /api/anticheat

The ``/api/shop``, ``/api/events/*`` and ``/api/cosmetics/apply-theme`` routes
are REAL persistent features: they are exercised against an in-memory SQLite
database (StaticPool so every connection shares one schema/data set), with
``database.SessionLocal`` patched to a session factory bound to that engine. No
mock-success fallbacks remain for these three domains.

The ``/api/anticheat`` handler still references a never-defined
``gapi_gui.db_service``; the resulting ``AttributeError`` is caught and a
success-faking mock response is returned. That latent behaviour is preserved
and exercised (the "mock fallback" tests). Its persist path is exercised by
patching ``gapi_gui.db_service`` to a MagicMock — no real database is touched.
Twitch routes mock ``gapi_gui._get_twitch_client`` / ``gapi_gui.picker`` — no
network I/O.

i18n is PUBLIC (no auth) — mirrors the legacy lack of ``@require_login``.

Run with:
    python -m pytest tests/test_backend_misc.py
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

import gapi_gui
import database
from backend.main import app
import backend.models.storefront as storefront_models  # noqa: F401


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _AuthedCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))


# Storefront tables built into the in-memory test DB.
_STOREFRONT_TABLES = [
    storefront_models.StorefrontShopItem.__table__,
    storefront_models.StorefrontPurchase.__table__,
    storefront_models.StorefrontSeasonalEvent.__table__,
    storefront_models.StorefrontEventClaim.__table__,
    storefront_models.StorefrontUserCosmetics.__table__,
]


def _make_storefront_session():
    """In-memory SQLite engine + session factory with the storefront tables."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(bind=engine, tables=_STOREFRONT_TABLES)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, Session


class _StorefrontCase(unittest.TestCase):
    """Authed case with a fresh in-memory DB patched over SessionLocal."""

    def setUp(self):
        self.engine, self.Session = _make_storefront_session()
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


# ── i18n (UNAUTHENTICATED) ───────────────────────────────────────────────────

class I18nTest(unittest.TestCase):
    """i18n is public — no cookie set, must still succeed."""
    def setUp(self):
        self.client = TestClient(app)  # anonymous

    def test_list_no_auth_required(self):
        resp = self.client.get('/api/i18n')
        self.assertEqual(resp.status_code, 200)
        locales = resp.json()['locales']
        langs = {loc['lang'] for loc in locales}
        self.assertIn('en', langs)
        self.assertIn('es', langs)
        # lang_name present
        en = next(loc for loc in locales if loc['lang'] == 'en')
        self.assertEqual(en['lang_name'], 'English')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_get_locale_no_auth_required(self):
        resp = self.client.get('/api/i18n/en')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['lang'], 'en')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_get_unknown_locale_404(self):
        resp = self.client.get('/api/i18n/zz')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], "Locale 'zz' not found")
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_list_handles_listdir_error(self):
        with patch.object(gapi_gui.os, 'listdir', side_effect=OSError('boom')):
            resp = self.client.get('/api/i18n')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'locales': []})


# ── Auth gating (the five non-i18n prefixes) ─────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # no cookie -> anonymous

    def test_shop_get_requires_login(self):
        self.assertEqual(self.client.get('/api/shop').status_code, 401)

    def test_shop_purchase_requires_login(self):
        self.assertEqual(
            self.client.post('/api/shop/purchase', json={}).status_code, 401)

    def test_events_seasonal_requires_login(self):
        self.assertEqual(self.client.get('/api/events/seasonal').status_code, 401)

    def test_events_claim_requires_login(self):
        self.assertEqual(
            self.client.post('/api/events/5/claim').status_code, 401)

    def test_twitch_trending_requires_login(self):
        self.assertEqual(self.client.get('/api/twitch/trending').status_code, 401)

    def test_twitch_overlap_requires_login(self):
        self.assertEqual(
            self.client.get('/api/twitch/library-overlap').status_code, 401)

    def test_cosmetics_apply_requires_login(self):
        self.assertEqual(
            self.client.post('/api/cosmetics/apply-theme', json={}).status_code, 401)

    def test_anticheat_requires_login(self):
        self.assertEqual(self.client.get('/api/anticheat').status_code, 401)


# ── shop ─────────────────────────────────────────────────────────────────────

class ShopListTest(_StorefrontCase):
    def test_lists_seeded_items_not_owned(self):
        resp = self.client.get('/api/shop')
        self.assertEqual(resp.status_code, 200)
        items = resp.json()['items']
        # Two default items are seeded on first use.
        self.assertEqual(len(items), 2)
        names = {it['name'] for it in items}
        self.assertIn('Dark Neon Theme', names)
        self.assertIn('Legendary Title', names)
        self.assertTrue(all(it['owned'] is False for it in items))
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_owned_flag_after_purchase(self):
        item_id = self.client.get('/api/shop').json()['items'][0]['id']
        self.client.post('/api/shop/purchase', json={'item_id': item_id})
        items = self.client.get('/api/shop').json()['items']
        owned = next(it for it in items if it['id'] == item_id)
        self.assertTrue(owned['owned'])

    def test_ownership_is_per_user(self):
        item_id = self.client.get('/api/shop').json()['items'][0]['id']
        self.client.post('/api/shop/purchase', json={'item_id': item_id})
        bob = self._client_for('bob')
        items = bob.get('/api/shop').json()['items']
        self.assertTrue(all(it['owned'] is False for it in items))


class ShopPurchaseTest(_StorefrontCase):
    def _first_item_id(self):
        return self.client.get('/api/shop').json()['items'][0]['id']

    def test_missing_item_id_400(self):
        resp = self.client.post('/api/shop/purchase', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Item ID required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_unknown_item_404(self):
        resp = self.client.post('/api/shop/purchase', json={'item_id': '999999'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Item not found')

    def test_purchase_success_persists(self):
        item_id = self._first_item_id()
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            resp = self.client.post('/api/shop/purchase', json={'item_id': item_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True, 'message': 'Purchase successful', 'new_balance': 1000})
        # Persisted: re-listing shows it owned.
        items = self.client.get('/api/shop').json()['items']
        self.assertTrue(next(it for it in items if it['id'] == item_id)['owned'])

    def test_already_owned_409(self):
        item_id = self._first_item_id()
        with patch.object(gapi_gui, 'REALTIME_AVAILABLE', False):
            self.client.post('/api/shop/purchase', json={'item_id': item_id})
            resp = self.client.post('/api/shop/purchase', json={'item_id': item_id})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'Already owned')


# ── events ───────────────────────────────────────────────────────────────────

class EventsTest(_StorefrontCase):
    def test_seasonal_lists_seeded_events(self):
        resp = self.client.get('/api/events/seasonal')
        self.assertEqual(resp.status_code, 200)
        events = resp.json()['active_events']
        self.assertEqual(len(events), 2)
        names = {e['name'] for e in events}
        self.assertIn('Spring Festival 2026', names)
        self.assertTrue(all(e['reward_claimed'] is False for e in events))
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_claim_success_persists(self):
        eid = self.client.get('/api/events/seasonal').json()['active_events'][0]['id']
        resp = self.client.post(f'/api/events/{eid}/claim')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['message'], 'Event reward claimed!')
        self.assertIn('reward', body)
        self.assertEqual(resp.headers['cache-control'], 'no-store')
        # Persisted: re-listing flags it claimed.
        events = self.client.get('/api/events/seasonal').json()['active_events']
        self.assertTrue(next(e for e in events if e['id'] == eid)['reward_claimed'])

    def test_claim_unknown_event_404(self):
        resp = self.client.post('/api/events/999999/claim')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Event not found')

    def test_claim_twice_409(self):
        eid = self.client.get('/api/events/seasonal').json()['active_events'][0]['id']
        self.assertEqual(self.client.post(f'/api/events/{eid}/claim').status_code, 200)
        resp = self.client.post(f'/api/events/{eid}/claim')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'Reward already claimed')

    def test_claim_is_per_user(self):
        eid = self.client.get('/api/events/seasonal').json()['active_events'][0]['id']
        self.client.post(f'/api/events/{eid}/claim')
        bob = self._client_for('bob')
        # bob can still claim the same event.
        self.assertEqual(bob.post(f'/api/events/{eid}/claim').status_code, 200)


# ── twitch ───────────────────────────────────────────────────────────────────

class TwitchTrendingTest(_AuthedCase):
    def test_no_credentials_503(self):
        with patch.object(gapi_gui, '_get_twitch_client', return_value=None):
            resp = self.client.get('/api/twitch/trending')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('credentials not configured', resp.json()['error'])
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_success(self):
        client = MagicMock()
        client.get_top_games.return_value = [
            {'id': '1', 'name': 'GTA V', 'viewer_count': 100},
        ]
        with patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/trending', params={'count': 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['trending'][0]['name'], 'GTA V')
        client.get_top_games.assert_called_once_with(count=5)

    def test_count_clamped(self):
        client = MagicMock()
        client.get_top_games.return_value = []
        with patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/trending', params={'count': 999})
        self.assertEqual(resp.status_code, 200)
        client.get_top_games.assert_called_once_with(count=100)

    def test_auth_error_502(self):
        import twitch_client
        client = MagicMock()
        client.get_top_games.side_effect = twitch_client.TwitchAuthError('bad')
        with patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/trending')
        self.assertEqual(resp.status_code, 502)
        self.assertIn('authentication failed', resp.json()['error'])

    def test_api_error_502(self):
        import twitch_client
        client = MagicMock()
        client.get_top_games.side_effect = twitch_client.TwitchAPIError('oops')
        with patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/trending')
        self.assertEqual(resp.status_code, 502)
        self.assertIn('Twitch API error', resp.json()['error'])

    def test_unexpected_error_500(self):
        client = MagicMock()
        client.get_top_games.side_effect = RuntimeError('boom')
        with patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/trending')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Unexpected error')


class TwitchOverlapTest(_AuthedCase):
    def test_no_picker_400(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.get('/api/twitch/library-overlap')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Not initialized. Please log in.')

    def test_no_credentials_503(self):
        with patch.object(gapi_gui, 'picker', MagicMock()), \
                patch.object(gapi_gui, '_get_twitch_client', return_value=None):
            resp = self.client.get('/api/twitch/library-overlap')
        self.assertEqual(resp.status_code, 503)
        self.assertIn('credentials not configured', resp.json()['error'])

    def test_success(self):
        client = MagicMock()
        client.get_top_games.return_value = [{'id': '1', 'name': 'CS2'}]
        client.find_library_overlap.return_value = [{'appid': 730, 'name': 'CS2'}]
        _p = MagicMock()
        _p.games = ['CS2']
        with patch.object(gapi_gui, 'picker', MagicMock()), \
                patch.object(gapi_gui, '_get_twitch_client', return_value=client), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=_p):
            resp = self.client.get('/api/twitch/library-overlap')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['trending_count'], 1)
        self.assertEqual(body['overlap'][0]['appid'], 730)

    def test_auth_error_502(self):
        import twitch_client
        client = MagicMock()
        client.get_top_games.side_effect = twitch_client.TwitchAuthError('bad')
        with patch.object(gapi_gui, 'picker', MagicMock()), \
                patch.object(gapi_gui, '_get_twitch_client', return_value=client):
            resp = self.client.get('/api/twitch/library-overlap')
        self.assertEqual(resp.status_code, 502)


# ── cosmetics ────────────────────────────────────────────────────────────────

class CosmeticsTest(_StorefrontCase):
    def test_missing_theme_id_400(self):
        resp = self.client.post('/api/cosmetics/apply-theme', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Theme ID required')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_invalid_theme_400(self):
        resp = self.client.post('/api/cosmetics/apply-theme',
                                json={'theme_id': 'nonsense'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid theme')
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_apply_success_persists_and_upserts(self):
        resp = self.client.post('/api/cosmetics/apply-theme',
                                json={'theme_id': 'neon'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {'success': True, 'message': 'Theme applied'})
        self.assertEqual(resp.headers['cache-control'], 'no-store')

        # Upsert: applying a second theme updates the same user's row.
        from app.services import storefront_service
        self.client.post('/api/cosmetics/apply-theme', json={'theme_id': 'dark'})
        db = self.Session()
        try:
            self.assertEqual(
                storefront_service.get_theme(db, 'alice'), {'theme_id': 'dark'})
            rows = db.query(storefront_models.StorefrontUserCosmetics).filter(
                storefront_models.StorefrontUserCosmetics.username == 'alice').count()
            self.assertEqual(rows, 1)  # upsert, not insert
        finally:
            db.close()


# ── anticheat ────────────────────────────────────────────────────────────────

class AnticheatTest(_AuthedCase):
    def test_success_persisted(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = [200]  # total picks
        svc = MagicMock()
        svc.get_db.return_value = db
        with patch.object(gapi_gui, 'db_service', svc, create=True):
            resp = self.client.get('/api/anticheat')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 200 picks * 0.01 = 2 flagged -> integrity 99.0
        self.assertEqual(body['integrity_score'], 99.0)
        self.assertEqual(len(body['flagged_picks']), 1)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_mock_fallback_when_db_service_undefined(self):
        resp = self.client.get('/api/anticheat')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['integrity_score'], 99.2)
        self.assertEqual(body['flagged_picks'], [])
        self.assertEqual(resp.headers['cache-control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
