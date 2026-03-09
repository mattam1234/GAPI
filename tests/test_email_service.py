#!/usr/bin/env python3
"""
Tests for the EmailService and the email-related Flask endpoints:

  GET  /api/admin/email/status
  POST /api/admin/email/test
  POST /api/admin/notifications/send-digests
  GET  /api/users/<username>/email
  PUT  /api/users/<username>/email

database helpers tested:
  database.get_user_email
  database.set_user_email

Run with:
    python -m pytest tests/test_email_service.py
"""
import json
import os
import sys
import unittest
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.email_service import EmailService
import database
import gapi_gui

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
    database.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _create_user(db, username='alice', email=None):
    user = database.User(username=username, password='hash', email=email)
    db.add(user)
    db.commit()
    return db.query(database.User).filter_by(username=username).first()


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _set_user_session(client, username='alice'):
    with client.session_transaction() as sess:
        sess['username'] = username


# ===========================================================================
# EmailService unit tests
# ===========================================================================

class TestEmailServiceIsConfigured(unittest.TestCase):

    def test_not_configured_when_host_empty(self):
        svc = EmailService(host='')
        self.assertFalse(svc.is_configured())

    def test_not_configured_when_host_none(self):
        svc = EmailService(host=None)
        self.assertFalse(svc.is_configured())

    def test_configured_when_host_set(self):
        svc = EmailService(host='smtp.example.com')
        self.assertTrue(svc.is_configured())

    def test_config_info_returns_all_keys(self):
        svc = EmailService(host='smtp.example.com', port=587, sender='from@example.com',
                           use_tls=True, use_ssl=False)
        info = svc.config_info()
        for key in ('configured', 'sender', 'host', 'port', 'use_tls', 'use_ssl'):
            self.assertIn(key, info)

    def test_config_info_does_not_expose_password(self):
        svc = EmailService(host='smtp.example.com', username='user', password='secret123')
        info = svc.config_info()
        info_str = str(info)
        self.assertNotIn('secret123', info_str)

    def test_config_info_configured_false_when_no_host(self):
        svc = EmailService(host='')
        self.assertFalse(svc.config_info()['configured'])


class TestEmailServiceFromEnv(unittest.TestCase):

    def test_disabled_when_smtp_host_absent(self):
        env = {}
        with patch.dict(os.environ, env, clear=False):
            old = os.environ.pop('SMTP_HOST', None)
            try:
                svc = EmailService.from_env()
                self.assertFalse(svc.is_configured())
            finally:
                if old is not None:
                    os.environ['SMTP_HOST'] = old

    def test_configured_from_env(self):
        with patch.dict(os.environ, {
            'SMTP_HOST':     'mail.example.com',
            'SMTP_PORT':     '465',
            'SMTP_USER':     'user@example.com',
            'SMTP_PASSWORD': 'secret',
            'SMTP_FROM':     'noreply@example.com',
            'SMTP_USE_TLS':  'false',
            'SMTP_USE_SSL':  'true',
        }):
            svc = EmailService.from_env()
        self.assertTrue(svc.is_configured())
        self.assertEqual(svc._host, 'mail.example.com')
        self.assertEqual(svc._port, 465)
        self.assertEqual(svc._username, 'user@example.com')
        self.assertEqual(svc._sender, 'noreply@example.com')
        self.assertFalse(svc._use_tls)
        self.assertTrue(svc._use_ssl)

    def test_invalid_port_falls_back_to_587(self):
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': 'bad'}):
            svc = EmailService.from_env()
        self.assertEqual(svc._port, 587)


class TestEmailServiceSendEmailDisabled(unittest.TestCase):

    def setUp(self):
        self.svc = EmailService(host='')  # disabled

    def test_send_email_returns_false_when_not_configured(self):
        result = self.svc.send_email('user@example.com', 'Hi', 'Hello')
        self.assertFalse(result)

    def test_send_notification_email_returns_false_when_not_configured(self):
        result = self.svc.send_notification_email(
            'user@example.com', 'alice', {'title': 'T', 'message': 'M'}
        )
        self.assertFalse(result)

    def test_send_digest_email_returns_false_when_not_configured(self):
        result = self.svc.send_digest_email(
            'user@example.com', 'alice', [{'title': 'T', 'message': 'M'}]
        )
        self.assertFalse(result)

    def test_send_test_email_returns_false_when_not_configured(self):
        result = self.svc.send_test_email('user@example.com')
        self.assertFalse(result)


class TestEmailServiceSendEmailInvalidAddress(unittest.TestCase):

    def test_returns_false_for_missing_at_sign(self):
        svc = EmailService(host='smtp.example.com')
        self.assertFalse(svc.send_email('notavalidemail', 'Subject', 'Body'))

    def test_returns_false_for_empty_address(self):
        svc = EmailService(host='smtp.example.com')
        self.assertFalse(svc.send_email('', 'Subject', 'Body'))

    def test_returns_false_for_at_sign_only(self):
        svc = EmailService(host='smtp.example.com')
        self.assertFalse(svc.send_email('@', 'Subject', 'Body'))

    def test_returns_false_for_no_domain_dot(self):
        svc = EmailService(host='smtp.example.com')
        self.assertFalse(svc.send_email('user@nodot', 'Subject', 'Body'))

    def test_valid_address_passes_validation(self):
        # A valid address should not be rejected (SMTP failure is expected in tests)
        svc = EmailService(host='smtp.example.com')
        with patch.object(svc, '_send', side_effect=ConnectionRefusedError):
            result = svc.send_email('valid@example.com', 'Subject', 'Body')
        self.assertFalse(result)  # False because SMTP failed, not validation


class TestEmailServiceBuildMessage(unittest.TestCase):

    def setUp(self):
        self.svc = EmailService(host='smtp.example.com', sender='from@example.com')

    def test_build_message_sets_headers(self):
        msg = self.svc._build_message('to@example.com', 'Hi', 'plain body')
        self.assertEqual(msg['To'], 'to@example.com')
        self.assertEqual(msg['From'], 'from@example.com')
        self.assertEqual(msg['Subject'], 'Hi')

    def test_build_message_plain_only(self):
        msg = self.svc._build_message('to@example.com', 'S', 'body', html_body=None)
        payloads = msg.get_payload()
        # Should have one plain part
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0].get_content_type(), 'text/plain')

    def test_build_message_with_html(self):
        msg = self.svc._build_message('to@example.com', 'S', 'plain', '<p>html</p>')
        payloads = msg.get_payload()
        content_types = [p.get_content_type() for p in payloads]
        self.assertIn('text/plain', content_types)
        self.assertIn('text/html', content_types)


class TestEmailServiceSendEmailMocked(unittest.TestCase):

    def _make_svc(self, use_ssl=False):
        return EmailService(
            host='smtp.example.com',
            port=587,
            username='user',
            password='pass',
            sender='from@example.com',
            use_tls=True,
            use_ssl=use_ssl,
        )

    def test_send_calls_starttls_and_login_via_mock_send(self):
        """Verify _send invokes STARTTLS and authenticates on an SMTP connection."""
        svc = self._make_svc(use_ssl=False)
        mock_server = MagicMock()

        class _MockSMTP:
            def __init__(self, *a, **kw):
                pass
            def __enter__(self):
                return mock_server
            def __exit__(self, *a):
                return False

        with patch('smtplib.SMTP', _MockSMTP):
            msg = svc._build_message('to@example.com', 'S', 'Body')
            svc._send(msg, ['to@example.com'])

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with('user', 'pass')
        mock_server.sendmail.assert_called_once()

    def test_send_returns_false_on_smtp_exception(self):
        svc = self._make_svc(use_ssl=False)
        with patch('smtplib.SMTP', side_effect=ConnectionRefusedError('refused')):
            result = svc.send_email('to@example.com', 'Subj', 'Body')
        self.assertFalse(result)

    def test_send_uses_smtp_ssl_when_use_ssl_true(self):
        svc = self._make_svc(use_ssl=True)
        with patch('smtplib.SMTP_SSL', side_effect=ConnectionRefusedError('refused')):
            result = svc.send_email('to@example.com', 'Subj', 'Body')
        self.assertFalse(result)


class TestEmailServiceNotificationEmail(unittest.TestCase):

    def setUp(self):
        self.svc = EmailService(host='smtp.example.com', sender='from@example.com')

    def test_notification_email_subject_contains_title(self):
        captured = {}

        def fake_send(msg, recipients):
            captured['subject'] = msg['Subject']
            captured['body'] = msg.get_payload()[0].get_payload(decode=True).decode()

        with patch.object(self.svc, '_send', side_effect=fake_send):
            self.svc.send_notification_email(
                'user@example.com', 'alice',
                {'title': 'Friend Request', 'message': 'Bob wants to connect'}
            )
        self.assertIn('Friend Request', captured.get('subject', ''))
        self.assertIn('alice', captured.get('body', ''))
        self.assertIn('Bob wants to connect', captured.get('body', ''))

    def test_digest_email_with_no_notifications_returns_false(self):
        result = self.svc.send_digest_email('user@example.com', 'alice', [])
        self.assertFalse(result)

    def test_digest_email_subject_contains_count(self):
        captured = {}

        def fake_send(msg, recipients):
            captured['subject'] = msg['Subject']

        notifs = [
            {'title': 'T1', 'message': 'M1'},
            {'title': 'T2', 'message': 'M2'},
        ]
        with patch.object(self.svc, '_send', side_effect=fake_send):
            self.svc.send_digest_email('user@example.com', 'alice', notifs, period='daily')
        self.assertIn('2', captured.get('subject', ''))
        self.assertIn('Daily', captured.get('subject', ''))

    def test_digest_email_body_contains_all_titles(self):
        captured = {}

        def fake_send(msg, recipients):
            captured['body'] = msg.get_payload()[0].get_payload(decode=True).decode()

        notifs = [{'title': 'Game Night', 'message': 'Scheduled for Friday'}]
        with patch.object(self.svc, '_send', side_effect=fake_send):
            self.svc.send_digest_email('user@example.com', 'alice', notifs)
        self.assertIn('Game Night', captured.get('body', ''))

    def test_test_email_subject(self):
        captured = {}

        def fake_send(msg, recipients):
            captured['subject'] = msg['Subject']

        with patch.object(self.svc, '_send', side_effect=fake_send):
            self.svc.send_test_email('admin@example.com')
        self.assertIn('test', captured.get('subject', '').lower())


# ===========================================================================
# database.get_user_email / set_user_email
# ===========================================================================

class TestDatabaseUserEmail(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()

    def tearDown(self):
        self.db.close()

    def test_get_user_email_returns_empty_for_unknown_user(self):
        self.assertEqual(database.get_user_email(self.db, 'nobody'), '')

    def test_get_user_email_returns_empty_when_db_none(self):
        self.assertEqual(database.get_user_email(None, 'alice'), '')

    def test_get_user_email_returns_stored_email(self):
        _create_user(self.db, 'alice', email='alice@example.com')
        result = database.get_user_email(self.db, 'alice')
        self.assertEqual(result, 'alice@example.com')

    def test_get_user_email_returns_empty_when_not_set(self):
        _create_user(self.db, 'bob', email=None)
        result = database.get_user_email(self.db, 'bob')
        self.assertEqual(result, '')

    def test_set_user_email_stores_value(self):
        _create_user(self.db, 'carol')
        ok = database.set_user_email(self.db, 'carol', 'carol@example.com')
        self.assertTrue(ok)
        self.assertEqual(database.get_user_email(self.db, 'carol'), 'carol@example.com')

    def test_set_user_email_clears_value(self):
        _create_user(self.db, 'dave', email='dave@example.com')
        ok = database.set_user_email(self.db, 'dave', '')
        self.assertTrue(ok)
        self.assertEqual(database.get_user_email(self.db, 'dave'), '')

    def test_set_user_email_returns_false_for_unknown_user(self):
        ok = database.set_user_email(self.db, 'nobody', 'x@example.com')
        self.assertFalse(ok)

    def test_set_user_email_returns_false_when_db_none(self):
        self.assertFalse(database.set_user_email(None, 'alice', 'x@example.com'))

    def test_set_user_email_strips_whitespace(self):
        _create_user(self.db, 'eve')
        database.set_user_email(self.db, 'eve', '  eve@example.com  ')
        self.assertEqual(database.get_user_email(self.db, 'eve'), 'eve@example.com')


# ===========================================================================
# Flask endpoint tests
# ===========================================================================

class _AppBase(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()


class TestEmailStatusEndpoint(_AppBase):

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/email/status')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_200_for_admin(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/email/status')
        self.assertEqual(resp.status_code, 200)

    def test_response_contains_configured_key(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/email/status')
        data = json.loads(resp.data)
        self.assertIn('configured', data)

    def test_not_configured_when_smtp_host_absent(self):
        mock_svc = EmailService(host='')  # real object, not configured
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.get('/api/admin/email/status')
        data = json.loads(resp.data)
        self.assertFalse(data['configured'])


class TestEmailTestEndpoint(_AppBase):

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/email/test', json={'to': 'x@example.com'})
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_503_when_not_configured(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = False
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/email/test', json={'to': 'x@example.com'})
        self.assertEqual(resp.status_code, 503)

    def test_returns_400_for_invalid_address(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/email/test', json={'to': 'notanemail'})
        self.assertEqual(resp.status_code, 400)

    def test_returns_success_true_when_send_succeeds(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        mock_svc.send_test_email.return_value = True
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/email/test', json={'to': 'test@example.com'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['to'], 'test@example.com')

    def test_returns_success_false_when_send_fails(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        mock_svc.send_test_email.return_value = False
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/email/test', json={'to': 'test@example.com'})
        data = json.loads(resp.data)
        self.assertFalse(data['success'])


class TestSendDigestsEndpoint(_AppBase):

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', False):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertEqual(resp.status_code, 503)

    def test_returns_503_when_smtp_not_configured(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = False
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_email_service', mock_svc):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/notifications/send-digests', json={})
        self.assertEqual(resp.status_code, 503)

    def test_dry_run_returns_correct_shape(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        mock_db = MagicMock()
        fake_prefs = {'email_enabled': True, 'digest_frequency': 'daily'}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_email_service', mock_svc), \
             patch('database.get_all_users', return_value=[]), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/notifications/send-digests',
                                    json={'dry_run': True, 'period': 'daily'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('sent', data)
        self.assertIn('skipped', data)
        self.assertIn('failed', data)
        self.assertTrue(data['dry_run'])

    def test_invalid_period_defaults_to_daily(self):
        mock_svc = MagicMock()
        mock_svc.is_configured.return_value = True
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_email_service', mock_svc), \
             patch('database.get_all_users', return_value=[]), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_admin_session(self.client)
            resp = self.client.post('/api/admin/notifications/send-digests',
                                    json={'period': 'BADVALUE', 'dry_run': True})
        self.assertEqual(resp.status_code, 200)


class TestUserEmailEndpoints(_AppBase):

    def test_get_email_requires_login(self):
        resp = self.client.get('/api/users/alice/email')
        self.assertIn(resp.status_code, (401, 403))

    def test_put_email_requires_login(self):
        resp = self.client.put('/api/users/alice/email', json={'email': 'a@b.com'})
        self.assertIn(resp.status_code, (401, 403))

    def test_put_email_returns_400_for_invalid_format(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_user_session(self.client, 'alice')
            resp = self.client.put('/api/users/alice/email', json={'email': 'notvalid'})
        self.assertEqual(resp.status_code, 400)

    def test_put_email_own_account_succeeds(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.set_user_email', return_value=True), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_user_session(self.client, 'alice')
            resp = self.client.put('/api/users/alice/email', json={'email': 'alice@example.com'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['email'], 'alice@example.com')

    def test_put_email_forbidden_for_other_user(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            _set_user_session(self.client, 'alice')
            resp = self.client.put('/api/users/bob/email', json={'email': 'bob@example.com'})
        self.assertIn(resp.status_code, (401, 403))

    def test_put_email_admin_can_update_other_user(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True), \
             patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.set_user_email', return_value=True), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_admin_session(self.client)
            resp = self.client.put('/api/users/bob/email', json={'email': 'bob@example.com'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_get_email_own_account_succeeds(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_user_email', return_value='alice@example.com'), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_user_session(self.client, 'alice')
            resp = self.client.get('/api/users/alice/email')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['email'], 'alice@example.com')
        self.assertEqual(data['username'], 'alice')

    def test_get_email_returns_null_when_not_set(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_user_email', return_value=''), \
             patch('database.get_db', return_value=iter([mock_db])):
            _set_user_session(self.client, 'alice')
            resp = self.client.get('/api/users/alice/email')
        data = json.loads(resp.data)
        self.assertIsNone(data['email'])

    def test_get_email_returns_503_when_db_unavailable(self):
        _set_user_session(self.client, 'alice')
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/users/alice/email')
        self.assertEqual(resp.status_code, 503)


if __name__ == '__main__':
    unittest.main()
