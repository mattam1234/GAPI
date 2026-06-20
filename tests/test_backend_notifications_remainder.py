#!/usr/bin/env python3
"""Tests for the remaining migrated notifications routes
(backend/routers/notifications.py): mock, list, read, send, and the
slack/teams/ifttt/homeassistant integration ``/test`` routes.

Outbound webhook calls are mocked via the WebhookNotifier send_* methods.

Run with:
    python -m pytest tests/test_backend_notifications_remainder.py
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
    return gapi_gui.app.session_interface.get_signing_serializer(
        gapi_gui.app).dumps({'username': username})


def _fake_get_db():
    """A generator yielding a MagicMock db session, mirroring database.get_db."""
    yield MagicMock()


class MockNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_requires_login(self):
        resp = self.client.get('/api/notifications/mock')
        self.assertEqual(resp.status_code, 401)

    def test_returns_mock_notifications(self):
        self.client.cookies.set('session', _session_cookie('alice'))
        resp = self.client.get('/api/notifications/mock')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['notifications']), 3)
        self.assertEqual(body['notifications'][0]['type'], 'mentions')
        self.assertEqual(resp.headers['Cache-Control'], 'no-store')


class ListNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        client = TestClient(app)
        resp = client.get('/api/notifications')
        self.assertEqual(resp.status_code, 401)

    def test_list_with_service(self):
        notifs = [{'id': 1, 'is_read': False}, {'id': 2, 'is_read': True}]
        svc = MagicMock()
        svc.get_all.return_value = notifs
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.get('/api/notifications')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['notifications'], notifs)
        self.assertEqual(body['unread_count'], 1)
        self.assertEqual(resp.headers['Cache-Control'], 'no-store')

    def test_list_unread_only_fallback_no_service(self):
        notifs = [{'id': 3, 'is_read': False}]
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', None), \
             patch.object(gapi_gui.database, 'get_notifications',
                          return_value=notifs) as gn:
            resp = self.client.get('/api/notifications?unread_only=true')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 1)
        # unread_only=true must be forwarded
        self.assertTrue(gn.call_args.kwargs['unread_only'])


class MarkReadTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/notifications/read', json={})
        self.assertEqual(resp.status_code, 401)

    def test_mark_read_success(self):
        svc = MagicMock()
        svc.mark_read.return_value = True
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/read', json={'ids': [1, 2]})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertEqual(svc.mark_read.call_args.kwargs['ids'], [1, 2])

    def test_mark_read_failure_500(self):
        svc = MagicMock()
        svc.mark_read.return_value = False
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/read', json={})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to mark notifications read')


class SendNotificationTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))

    def test_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/notifications/send', json={})
        self.assertEqual(resp.status_code, 401)

    def test_non_admin_403(self):
        svc = MagicMock()
        svc.is_admin.return_value = False
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/send',
                                    json={'username': 'bob', 'title': 't',
                                          'message': 'm'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'Admin access required')

    def test_missing_fields_400(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/send',
                                    json={'username': 'bob', 'title': '',
                                          'message': 'm'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('required', resp.json()['error'])

    def test_send_success(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.create.return_value = True
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/send',
                                    json={'username': 'bob', 'title': 'Hi',
                                          'message': 'There', 'type': 'success'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertEqual(svc.create.call_args.kwargs['notif_type'], 'success')

    def test_send_failure_500(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        svc.create.return_value = False
        with patch.object(gapi_gui.database, 'get_db', _fake_get_db), \
             patch.object(gapi_gui, '_notification_service', svc):
            resp = self.client.post('/api/notifications/send',
                                    json={'username': 'bob', 'title': 't',
                                          'message': 'm'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Failed to send notification')


class WebhookTestRoutesTest(unittest.TestCase):
    """The integration /test routes. Outbound webhooks are mocked."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))

    def test_slack_requires_login(self):
        client = TestClient(app)
        resp = client.post('/api/notifications/slack/test', json={})
        self.assertEqual(resp.status_code, 401)

    def test_slack_not_configured_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.post('/api/notifications/slack/test', json={})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Slack webhook URL not configured', resp.json()['error'])

    def test_slack_success_with_override(self):
        import webhook_notifier
        with patch.object(gapi_gui, 'picker', None), \
             patch.object(webhook_notifier.WebhookNotifier, 'send_slack',
                          return_value=True) as send:
            resp = self.client.post(
                '/api/notifications/slack/test',
                json={'webhook_url': 'https://hooks.slack.com/services/x'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'service': 'slack'})
        send.assert_called_once()

    def test_teams_not_configured_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.post('/api/notifications/teams/test', json={})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Teams webhook URL not configured', resp.json()['error'])

    def test_teams_success_with_override(self):
        import webhook_notifier
        with patch.object(gapi_gui, 'picker', None), \
             patch.object(webhook_notifier.WebhookNotifier, 'send_teams',
                          return_value=False) as send:
            resp = self.client.post(
                '/api/notifications/teams/test',
                json={'webhook_url': 'https://x.webhook.office.com/y'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': False, 'service': 'teams'})
        send.assert_called_once()

    def test_ifttt_not_configured_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.post('/api/notifications/ifttt/test', json={})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('IFTTT webhook key not configured', resp.json()['error'])

    def test_ifttt_success_with_override(self):
        import webhook_notifier
        with patch.object(gapi_gui, 'picker', None), \
             patch.object(webhook_notifier.WebhookNotifier, 'send_ifttt',
                          return_value=True) as send:
            resp = self.client.post(
                '/api/notifications/ifttt/test',
                json={'ifttt_webhook_key': 'KEY', 'ifttt_event_name': 'evt'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'service': 'ifttt'})
        # event name override forwarded
        self.assertEqual(send.call_args.args[1], 'evt')

    def test_homeassistant_not_configured_503(self):
        with patch.object(gapi_gui, 'picker', None):
            resp = self.client.post('/api/notifications/homeassistant/test', json={})
        self.assertEqual(resp.status_code, 503)
        self.assertIn('Home Assistant URL and webhook ID must be configured',
                      resp.json()['error'])

    def test_homeassistant_success_with_override(self):
        import webhook_notifier
        with patch.object(gapi_gui, 'picker', None), \
             patch.object(webhook_notifier.WebhookNotifier, 'send_homeassistant',
                          return_value=True) as send:
            resp = self.client.post(
                '/api/notifications/homeassistant/test',
                json={'homeassistant_url': 'http://ha.local:8123',
                      'homeassistant_webhook_id': 'gapi',
                      'homeassistant_token': 'tok'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True, 'service': 'homeassistant'})
        self.assertEqual(send.call_args.kwargs['token'], 'tok')


if __name__ == '__main__':
    unittest.main()
