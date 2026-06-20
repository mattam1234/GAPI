#!/usr/bin/env python3
"""
Tests for Phase 11 — Web Push Notifications:

  PushNotificationService (app/services/push_notification_service.py)
  database helpers:
    add_push_subscription
    remove_push_subscription
    get_user_push_subscriptions
    get_all_push_subscriptions
  Flask endpoints:
    GET  /api/push/vapid-public-key
    POST /api/push/subscribe
    DELETE /api/push/unsubscribe
    GET  /api/push/subscriptions
    POST /api/admin/push/broadcast

Run with:
    python -m pytest tests/test_push_notifications.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient as _FastTestClient

import database
import gapi_gui
from app.services.push_notification_service import PushNotificationService
from backend.main import app as _fastapi_app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _fast_login(client, username='alice'):
    ser = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    client.cookies.set('session', ser.dumps({'username': username}))


# ---------------------------------------------------------------------------
# In-memory SQLite helpers
# ---------------------------------------------------------------------------

def _make_session():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
    database.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _create_user(db, username='alice'):
    user = database.User(username=username, password='hash')
    db.add(user)
    db.commit()
    return db.query(database.User).filter_by(username=username).first()


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _set_user_session(client, username='alice'):
    with client.session_transaction() as sess:
        sess['username'] = username


_SAMPLE_SUB = {
    'endpoint': 'https://push.example.com/sub/abc123',
    'keys': {
        'p256dh': 'BNcr6_uh0Y6JNRqICWV5UZm4HxS7tWx_0k3iBWgfUkxk',
        'auth': 'tBHItJI5svbpez7KI4CCXg',
    },
}


# ===========================================================================
# PushNotificationService — unit tests
# ===========================================================================

class TestPushNotificationServiceUnconfigured(unittest.TestCase):
    """Service behaves gracefully when VAPID keys are not set."""

    def setUp(self):
        self.svc = PushNotificationService()  # no keys

    def test_is_configured_false(self):
        self.assertFalse(self.svc.is_configured())

    def test_get_public_key_empty(self):
        self.assertEqual(self.svc.get_public_key(), '')

    def test_send_push_returns_false(self):
        ok = self.svc.send_push(_SAMPLE_SUB, 'Hi', 'body')
        self.assertFalse(ok)

    def test_send_to_user_returns_zero_counts(self):
        db = MagicMock()
        sent, failed = self.svc.send_to_user(db, 'alice', 'Hi', 'body', db_module=database)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 0)

    def test_broadcast_dry_run_no_error(self):
        db = _make_session()
        result = self.svc.broadcast(db, 'Hi', 'body', db_module=database, dry_run=True)
        self.assertIn('total', result)
        self.assertIn('dry_run', result)
        db.close()

    def test_broadcast_unconfigured_returns_skipped(self):
        db = _make_session()
        result = self.svc.broadcast(db, 'Hi', 'body', db_module=database)
        self.assertEqual(result['sent'], 0)
        self.assertEqual(result['skipped'], result['total'])
        db.close()


class TestPushNotificationServiceFromEnv(unittest.TestCase):
    """from_env() reads VAPID_* environment variables."""

    def test_from_env_no_vars_unconfigured(self):
        env = {}
        with patch.dict(os.environ, env, clear=False):
            for key in ('VAPID_PRIVATE_KEY', 'VAPID_PUBLIC_KEY', 'VAPID_CLAIMS_EMAIL'):
                os.environ.pop(key, None)
            svc = PushNotificationService.from_env()
        self.assertFalse(svc.is_configured())

    def test_from_env_sets_email(self):
        with patch.dict(os.environ, {'VAPID_CLAIMS_EMAIL': 'mailto:test@example.com'}):
            svc = PushNotificationService.from_env()
        self.assertEqual(svc._claims_email, 'mailto:test@example.com')


class TestGenerateVapidKeys(unittest.TestCase):
    """generate_vapid_keys() returns usable key pair."""

    def test_returns_dict_with_both_keys(self):
        keys = PushNotificationService.generate_vapid_keys()
        self.assertIn('private_key', keys)
        self.assertIn('public_key', keys)

    def test_private_key_is_pem(self):
        keys = PushNotificationService.generate_vapid_keys()
        self.assertIn('BEGIN', keys['private_key'])

    def test_public_key_is_nonempty_string(self):
        keys = PushNotificationService.generate_vapid_keys()
        self.assertIsInstance(keys['public_key'], str)
        self.assertGreater(len(keys['public_key']), 10)

    def test_keys_differ_across_calls(self):
        k1 = PushNotificationService.generate_vapid_keys()
        k2 = PushNotificationService.generate_vapid_keys()
        self.assertNotEqual(k1['public_key'], k2['public_key'])


class TestPushNotificationServiceSend(unittest.TestCase):
    """send_push() calls webpush() correctly."""

    def _make_configured_svc(self):
        keys = PushNotificationService.generate_vapid_keys()
        return PushNotificationService(
            private_key_pem=keys['private_key'],
            public_key_b64=keys['public_key'],
            claims_email='mailto:test@example.com',
        )

    def test_send_push_calls_webpush(self):
        svc = self._make_configured_svc()
        with patch('app.services.push_notification_service.webpush') as mock_wp:
            mock_wp.return_value = MagicMock(status_code=201)
            ok = svc.send_push(_SAMPLE_SUB, 'Title', 'Body')
        self.assertTrue(ok)
        mock_wp.assert_called_once()

    def test_send_push_missing_endpoint_returns_false(self):
        svc = self._make_configured_svc()
        bad_sub = {'endpoint': '', 'keys': {'p256dh': 'x', 'auth': 'y'}}
        ok = svc.send_push(bad_sub, 'T', 'B')
        self.assertFalse(ok)

    def test_send_push_webpush_exception_returns_false(self):
        svc = self._make_configured_svc()
        from pywebpush import WebPushException
        with patch('app.services.push_notification_service.webpush',
                   side_effect=WebPushException("503")):
            ok = svc.send_push(_SAMPLE_SUB, 'T', 'B')
        self.assertFalse(ok)

    def test_send_push_generic_exception_returns_false(self):
        svc = self._make_configured_svc()
        with patch('app.services.push_notification_service.webpush',
                   side_effect=RuntimeError("oops")):
            ok = svc.send_push(_SAMPLE_SUB, 'T', 'B')
        self.assertFalse(ok)

    def test_send_to_user_delegates_per_subscription(self):
        svc = self._make_configured_svc()
        db = _make_session()
        # Add two subscriptions directly
        database.add_push_subscription(
            db, 'alice', 'https://push.example.com/1', 'pk1', 'auth1')
        database.add_push_subscription(
            db, 'alice', 'https://push.example.com/2', 'pk2', 'auth2')
        with patch.object(svc, 'send_push', return_value=True) as mock_send:
            sent, failed = svc.send_to_user(db, 'alice', 'Hi', 'Body', db_module=database)
        self.assertEqual(sent, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(mock_send.call_count, 2)
        db.close()

    def test_broadcast_sends_to_all(self):
        svc = self._make_configured_svc()
        db = _make_session()
        database.add_push_subscription(
            db, 'alice', 'https://push.example.com/a', 'pa', 'aa')
        database.add_push_subscription(
            db, 'bob', 'https://push.example.com/b', 'pb', 'ab')
        with patch.object(svc, 'send_push', return_value=True):
            result = svc.broadcast(db, 'News', 'GAPI update!', db_module=database)
        self.assertEqual(result['sent'], 2)
        self.assertEqual(result['failed'], 0)
        db.close()

    def test_broadcast_dry_run_does_not_call_send(self):
        svc = self._make_configured_svc()
        db = _make_session()
        database.add_push_subscription(
            db, 'alice', 'https://push.example.com/a', 'pa', 'aa')
        with patch.object(svc, 'send_push') as mock_send:
            result = svc.broadcast(db, 'News', 'msg', db_module=database, dry_run=True)
        mock_send.assert_not_called()
        self.assertEqual(result['dry_run'], True)
        self.assertEqual(result['sent'], 0)
        db.close()


# ===========================================================================
# database helpers — unit tests
# ===========================================================================

class TestAddPushSubscription(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        _create_user(self.db, 'alice')

    def tearDown(self):
        self.db.close()

    def test_add_returns_true(self):
        ok = database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/s1', 'pk', 'au')
        self.assertTrue(ok)

    def test_add_persists_record(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/s2', 'pk2', 'au2')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]['p256dh'], 'pk2')

    def test_add_duplicate_endpoint_updates_keys(self):
        ep = 'https://push.example.com/same'
        database.add_push_subscription(self.db, 'alice', ep, 'old_key', 'old_auth')
        database.add_push_subscription(self.db, 'alice', ep, 'new_key', 'new_auth')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]['p256dh'], 'new_key')

    def test_add_none_db_returns_false(self):
        ok = database.add_push_subscription(
            None, 'alice', 'https://push.example.com/x', 'pk', 'au')
        self.assertFalse(ok)

    def test_add_missing_fields_returns_false(self):
        ok = database.add_push_subscription(self.db, 'alice', '', 'pk', 'au')
        self.assertFalse(ok)

    def test_add_stores_user_agent(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/ua',
            'pk', 'au', user_agent='Mozilla/5.0')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        self.assertEqual(subs[0]['user_agent'], 'Mozilla/5.0')


class TestRemovePushSubscription(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        _create_user(self.db, 'alice')
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/del', 'pk', 'au')

    def tearDown(self):
        self.db.close()

    def test_remove_existing_returns_true(self):
        ok = database.remove_push_subscription(
            self.db, 'alice', 'https://push.example.com/del')
        self.assertTrue(ok)

    def test_remove_deletes_record(self):
        database.remove_push_subscription(
            self.db, 'alice', 'https://push.example.com/del')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        self.assertEqual(len(subs), 0)

    def test_remove_nonexistent_returns_false(self):
        ok = database.remove_push_subscription(
            self.db, 'alice', 'https://push.example.com/not_there')
        self.assertFalse(ok)

    def test_remove_wrong_user_returns_false(self):
        ok = database.remove_push_subscription(
            self.db, 'bob', 'https://push.example.com/del')
        self.assertFalse(ok)

    def test_remove_none_db_returns_false(self):
        ok = database.remove_push_subscription(
            None, 'alice', 'https://push.example.com/del')
        self.assertFalse(ok)


class TestGetUserPushSubscriptions(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        _create_user(self.db, 'alice')

    def tearDown(self):
        self.db.close()

    def test_empty_for_unknown_user(self):
        subs = database.get_user_push_subscriptions(self.db, 'nobody')
        self.assertEqual(subs, [])

    def test_returns_all_for_user(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/1', 'pk1', 'a1')
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/2', 'pk2', 'a2')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        self.assertEqual(len(subs), 2)

    def test_result_has_expected_keys(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/k', 'pk', 'a')
        subs = database.get_user_push_subscriptions(self.db, 'alice')
        for key in ('id', 'endpoint', 'p256dh', 'auth', 'user_agent', 'created_at'):
            self.assertIn(key, subs[0])

    def test_none_db_returns_empty(self):
        subs = database.get_user_push_subscriptions(None, 'alice')
        self.assertEqual(subs, [])


class TestGetAllPushSubscriptions(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        _create_user(self.db, 'alice')
        _create_user(self.db, 'bob')

    def tearDown(self):
        self.db.close()

    def test_returns_all_subscriptions(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/a', 'pka', 'aa')
        database.add_push_subscription(
            self.db, 'bob', 'https://push.example.com/b', 'pkb', 'ab')
        subs = database.get_all_push_subscriptions(self.db, push_enabled_only=False)
        self.assertEqual(len(subs), 2)

    def test_result_has_expected_keys(self):
        database.add_push_subscription(
            self.db, 'alice', 'https://push.example.com/a2', 'pka', 'aa')
        subs = database.get_all_push_subscriptions(self.db, push_enabled_only=False)
        for key in ('username', 'endpoint', 'p256dh', 'auth'):
            self.assertIn(key, subs[0])

    def test_none_db_returns_empty(self):
        subs = database.get_all_push_subscriptions(None)
        self.assertEqual(subs, [])


# ===========================================================================
# Flask endpoints — integration tests
# ===========================================================================

class TestPushVapidPublicKey(unittest.TestCase):
    # /api/push/* migrated to FastAPI (backend/routers/extensibility.py); these
    # now drive the FastAPI TestClient against the same Flask session cookie.

    def setUp(self):
        self.client = _FastTestClient(_fastapi_app)

    def test_returns_200(self):
        resp = self.client.get('/api/push/vapid-public-key')
        self.assertEqual(resp.status_code, 200)

    def test_response_has_public_key_and_configured(self):
        resp = self.client.get('/api/push/vapid-public-key')
        data = resp.json()
        self.assertIn('public_key', data)
        self.assertIn('configured', data)

    def test_configured_false_when_no_env_keys(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = False
        mock_svc.get_public_key.return_value = ''
        with patch.object(gapi_gui, '_push_service', mock_svc):
            resp = self.client.get('/api/push/vapid-public-key')
        data = resp.json()
        self.assertFalse(data['configured'])
        self.assertEqual(data['public_key'], '')

    def test_configured_true_when_service_configured(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        mock_svc.get_public_key.return_value = 'BFake_Public_Key'
        with patch.object(gapi_gui, '_push_service', mock_svc):
            resp = self.client.get('/api/push/vapid-public-key')
        data = resp.json()
        self.assertTrue(data['configured'])
        self.assertEqual(data['public_key'], 'BFake_Public_Key')


class TestPushSubscribeEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_login(self):
        resp = self.client.post('/api/push/subscribe', json=_SAMPLE_SUB)
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        _fast_login(self.client, 'alice')
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/push/subscribe', json=_SAMPLE_SUB)
        self.assertEqual(resp.status_code, 503)

    def test_400_when_missing_endpoint(self):
        _fast_login(self.client, 'alice')
        bad = {'keys': {'p256dh': 'x', 'auth': 'y'}}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([MagicMock()])):
            resp = self.client.post('/api/push/subscribe', json=bad)
        self.assertEqual(resp.status_code, 400)

    def test_400_when_missing_keys(self):
        _fast_login(self.client, 'alice')
        bad = {'endpoint': 'https://push.example.com/x'}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([MagicMock()])):
            resp = self.client.post('/api/push/subscribe', json=bad)
        self.assertEqual(resp.status_code, 400)

    def test_201_on_success(self):
        _fast_login(self.client, 'alice')
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.add_push_subscription', return_value=True):
            resp = self.client.post('/api/push/subscribe', json=_SAMPLE_SUB)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['subscribed'])

    def test_500_when_db_add_fails(self):
        _fast_login(self.client, 'alice')
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.add_push_subscription', return_value=False):
            resp = self.client.post('/api/push/subscribe', json=_SAMPLE_SUB)
        self.assertEqual(resp.status_code, 500)


class TestPushUnsubscribeEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_login(self):
        resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                   json={'endpoint': 'https://x.com/y'})
        self.assertIn(resp.status_code, (401, 403))

    def test_400_when_endpoint_missing(self):
        _fast_login(self.client, 'alice')
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([MagicMock()])):
            resp = self.client.request('DELETE', '/api/push/unsubscribe', json={})
        self.assertEqual(resp.status_code, 400)

    def test_200_when_removed(self):
        _fast_login(self.client, 'alice')
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.remove_push_subscription', return_value=True):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://push.example.com/del'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['unsubscribed'])

    def test_404_when_not_found(self):
        _fast_login(self.client, 'alice')
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.remove_push_subscription', return_value=False):
            resp = self.client.request('DELETE', '/api/push/unsubscribe',
                                       json={'endpoint': 'https://push.example.com/gone'})
        self.assertEqual(resp.status_code, 404)


class TestPushSubscriptionsListEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_login(self):
        resp = self.client.get('/api/push/subscriptions')
        self.assertIn(resp.status_code, (401, 403))

    def test_200_returns_list(self):
        _fast_login(self.client, 'alice')
        fake_subs = [
            {'id': 1, 'endpoint': 'https://push.example.com/1',
             'p256dh': 'pk1', 'auth': 'a1', 'user_agent': 'Chrome', 'created_at': '2026-01-01T00:00:00'},
        ]
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.get_user_push_subscriptions', return_value=fake_subs):
            resp = self.client.get('/api/push/subscriptions')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('subscriptions', data)
        self.assertIn('count', data)
        self.assertEqual(data['count'], 1)

    def test_keys_do_not_include_p256dh_or_auth(self):
        """Sensitive key material must not be returned to the caller."""
        _fast_login(self.client, 'alice')
        fake_subs = [
            {'id': 1, 'endpoint': 'https://push.example.com/s',
             'p256dh': 'secret_key', 'auth': 'secret_auth',
             'user_agent': '', 'created_at': None},
        ]
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])), \
             patch('database.get_user_push_subscriptions', return_value=fake_subs):
            resp = self.client.get('/api/push/subscriptions')
        data = resp.json()
        entry = data['subscriptions'][0]
        self.assertNotIn('p256dh', entry)
        self.assertNotIn('auth', entry)

    def test_graceful_when_db_unavailable(self):
        _fast_login(self.client, 'alice')
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/push/subscriptions')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['subscriptions'], [])


class TestAdminPushBroadcastEndpoint(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        # /api/admin/push/broadcast migrated to FastAPI (backend/routers/admin_growth.py).
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_admin(self):
        _fast_login(self.client, 'bob')
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=False):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'Hi', 'body': 'Hello'})
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        _fast_login(self.client, 'admin')
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'Hi', 'body': 'Hello'})
        self.assertEqual(resp.status_code, 503)

    def test_400_when_title_missing(self):
        _fast_login(self.client, 'admin')
        mock_db = MagicMock()
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'body': 'Hello'})
        self.assertEqual(resp.status_code, 400)

    def test_400_when_body_missing(self):
        _fast_login(self.client, 'admin')
        mock_db = MagicMock()
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'Hi'})
        self.assertEqual(resp.status_code, 400)

    def test_503_when_push_service_none(self):
        _fast_login(self.client, 'admin')
        mock_db = MagicMock()
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', None), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'Hi', 'body': 'Hello'})
        self.assertEqual(resp.status_code, 503)

    def test_200_with_result_dict(self):
        _fast_login(self.client, 'admin')
        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.broadcast.return_value = {
            'total': 5, 'sent': 5, 'failed': 0, 'skipped': 0, 'dry_run': False
        }
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', mock_svc), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'News', 'body': 'Update available'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('total', data)
        self.assertIn('sent', data)
        self.assertEqual(data['sent'], 5)

    def test_dry_run_forwarded_to_service(self):
        _fast_login(self.client, 'admin')
        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.broadcast.return_value = {
            'total': 3, 'sent': 0, 'failed': 0, 'skipped': 3, 'dry_run': True
        }
        with patch.object(gapi_gui._app_settings_service, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', mock_svc), \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.post('/api/admin/push/broadcast',
                             json={'title': 'T', 'body': 'B', 'dry_run': True})
        _, kwargs = mock_svc.broadcast.call_args
        self.assertTrue(kwargs.get('dry_run'))


# ===========================================================================
# Service Worker — push event handler presence
# ===========================================================================

class TestServiceWorkerPushHandlers(unittest.TestCase):
    """Verify the service worker includes push and notificationclick handlers."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_service_worker_includes_push_listener(self):
        resp = self.client.get('/sw.js')
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("addEventListener('push'", body)

    def test_service_worker_includes_notification_click_listener(self):
        resp = self.client.get('/sw.js')
        body = resp.data.decode()
        self.assertIn("addEventListener('notificationclick'", body)

    def test_service_worker_shows_notification(self):
        resp = self.client.get('/sw.js')
        body = resp.data.decode()
        self.assertIn('showNotification', body)

    def test_service_worker_content_type(self):
        resp = self.client.get('/sw.js')
        self.assertIn('javascript', resp.content_type)


if __name__ == '__main__':
    unittest.main()
