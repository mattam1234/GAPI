#!/usr/bin/env python3
"""
Tests for:
  - Audit logging wired to login/logout/suspensions/group actions (Item 2)
  - Search history tracking (Item 3)
  - Bug fixes: require_login patch compatibility, datetime timezone, PWA meta tags

Run with:
    python -m pytest tests/test_audit_search_history.py
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui
import database


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine('sqlite:///:memory:', echo=False)
    database.Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    return eng, Session()


# ---------------------------------------------------------------------------
# database.record_search / get_search_history / clear_search_history
# ---------------------------------------------------------------------------

class TestSearchHistoryHelpers(unittest.TestCase):

    def test_record_returns_true(self):
        _, db = _make_db()
        ok = database.record_search(db, 'alice', 'portal')
        self.assertTrue(ok)
        db.close()

    def test_record_none_db_returns_false(self):
        self.assertFalse(database.record_search(None, 'alice', 'portal'))

    def test_record_empty_query_returns_false(self):
        _, db = _make_db()
        self.assertFalse(database.record_search(db, 'alice', ''))
        db.close()

    def test_record_empty_username_returns_false(self):
        _, db = _make_db()
        self.assertFalse(database.record_search(db, '', 'portal'))
        db.close()

    def test_get_history_returns_entries(self):
        _, db = _make_db()
        database.record_search(db, 'bob', 'half-life')
        database.record_search(db, 'bob', 'portal')
        history = database.get_search_history(db, 'bob')
        self.assertEqual(len(history), 2)
        # Newest first
        self.assertEqual(history[0]['query'], 'portal')
        db.close()

    def test_get_history_respects_limit(self):
        _, db = _make_db()
        for i in range(10):
            database.record_search(db, 'carol', f'game {i}')
        history = database.get_search_history(db, 'carol', limit=5)
        self.assertLessEqual(len(history), 5)
        db.close()

    def test_get_history_none_db_returns_empty(self):
        self.assertEqual(database.get_search_history(None, 'alice'), [])

    def test_history_stores_filters(self):
        _, db = _make_db()
        database.record_search(db, 'dave', 'action', filters={'genre': 'Action'})
        history = database.get_search_history(db, 'dave', limit=1)
        self.assertIsNotNone(history[0].get('filters'))
        self.assertEqual(history[0]['filters']['genre'], 'Action')
        db.close()

    def test_history_stores_result_count(self):
        _, db = _make_db()
        database.record_search(db, 'eve', 'rpg', result_count=42)
        history = database.get_search_history(db, 'eve', limit=1)
        self.assertEqual(history[0]['result_count'], 42)
        db.close()

    def test_history_result_has_expected_keys(self):
        _, db = _make_db()
        database.record_search(db, 'frank', 'strategy')
        history = database.get_search_history(db, 'frank', limit=1)
        for key in ('id', 'query', 'filters', 'result_count', 'searched_at'):
            self.assertIn(key, history[0])
        db.close()

    def test_clear_history(self):
        _, db = _make_db()
        database.record_search(db, 'grace', 'shooter')
        database.record_search(db, 'grace', 'racing')
        ok = database.clear_search_history(db, 'grace')
        self.assertTrue(ok)
        self.assertEqual(database.get_search_history(db, 'grace'), [])
        db.close()

    def test_clear_history_none_db_returns_false(self):
        self.assertFalse(database.clear_search_history(None, 'alice'))

    def test_prune_caps_at_max(self):
        """After inserting more than SEARCH_HISTORY_MAX entries, only max are kept."""
        _, db = _make_db()
        original_max = database.SEARCH_HISTORY_MAX
        database.SEARCH_HISTORY_MAX = 5
        try:
            for i in range(8):
                database.record_search(db, 'henry', f'game {i}')
            all_entries = (
                db.query(database.SearchHistory)
                .filter(database.SearchHistory.username == 'henry')
                .all()
            )
            self.assertLessEqual(len(all_entries), 5)
        finally:
            database.SEARCH_HISTORY_MAX = original_max
        db.close()


# ---------------------------------------------------------------------------
# Flask search history endpoints
# ---------------------------------------------------------------------------

class TestSearchHistoryEndpoints(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def test_get_history_requires_login(self):
        resp = self.client.get('/api/search/history')
        self.assertIn(resp.status_code, (401, 403))

    def test_get_history_empty_when_db_unavailable(self):
        self._login()
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['history'], [])
        self.assertEqual(data['count'], 0)

    def test_get_history_returns_data(self):
        mock_db = MagicMock()
        fake_history = [
            {'id': 1, 'query': 'portal', 'filters': None,
             'result_count': 5, 'searched_at': '2026-01-01T00:00:00'},
        ]
        self._login()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_search_history', return_value=fake_history), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['history'][0]['query'], 'portal')

    def test_get_history_limit_capped(self):
        mock_db = MagicMock()
        self._login()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_search_history', return_value=[]) as mock_fn, \
             patch('database.get_db', return_value=iter([mock_db])):
            self.client.get('/api/search/history?limit=999')
        _, kwargs = mock_fn.call_args
        self.assertLessEqual(kwargs.get('limit', 0), 50)

    def test_delete_history_requires_login(self):
        resp = self.client.delete('/api/search/history')
        self.assertIn(resp.status_code, (401, 403))

    def test_delete_history_success(self):
        mock_db = MagicMock()
        self._login()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.clear_search_history', return_value=True), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.delete('/api/search/history')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['ok'])


# ---------------------------------------------------------------------------
# Audit helper _audit() — unit tests (call semantics, not DB write)
# ---------------------------------------------------------------------------

class TestAuditHelper(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_audit_does_nothing_when_db_unavailable(self):
        """_audit() must never raise even when DB_AVAILABLE is False."""
        with gapi_gui.app.test_request_context('/'):
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                # Should not raise
                gapi_gui._audit('test_action', resource_type='test')

    def test_audit_does_nothing_when_service_unavailable(self):
        """_audit() must never raise even when _audit_service is None."""
        with gapi_gui.app.test_request_context('/'):
            with patch.object(gapi_gui, '_audit_service', None):
                gapi_gui._audit('test_action', resource_type='test')

    def test_audit_calls_log_action(self):
        """When services are available, _audit() calls log_action."""
        mock_service = MagicMock()
        mock_db = MagicMock()
        with gapi_gui.app.test_request_context('/'):
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch.object(gapi_gui, '_audit_service', mock_service), \
                 patch('database.get_db', return_value=iter([mock_db])):
                gapi_gui._audit('login', resource_type='auth', description='desc')
        self.assertTrue(mock_service.log_action.called)
        _, kwargs = mock_service.log_action.call_args
        self.assertEqual(kwargs.get('action'), 'login')
        self.assertEqual(kwargs.get('resource_type'), 'auth')


# ---------------------------------------------------------------------------
# Audit wiring: login endpoint emits audit events
# ---------------------------------------------------------------------------

class TestLoginAuditWiring(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_successful_login_triggers_audit(self):
        """A successful login should call _audit with action='login'."""
        audit_calls = []
        original_audit = gapi_gui._audit

        def mock_audit(action, **kwargs):
            audit_calls.append((action, kwargs))

        with patch.object(gapi_gui, '_audit', side_effect=mock_audit):
            with patch.object(gapi_gui.user_manager, 'login', return_value=(True, 'ok')), \
                 patch.object(gapi_gui.user_manager, 'get_user_ids', return_value={}):
                self.client.post('/api/auth/login',
                                 json={'username': 'alice', 'password': 'pw'},
                                 content_type='application/json')
        # Should have at least one login audit call
        login_calls = [c for c in audit_calls if c[0] == 'login']
        self.assertGreater(len(login_calls), 0)
        # The successful one should not be a failure
        success_calls = [c for c in login_calls if c[1].get('status') != 'failure']
        self.assertGreater(len(success_calls), 0)

    def test_failed_login_triggers_failure_audit(self):
        """A failed login should call _audit with status='failure'."""
        audit_calls = []

        def mock_audit(action, **kwargs):
            audit_calls.append((action, kwargs))

        with patch.object(gapi_gui, '_audit', side_effect=mock_audit):
            with patch.object(gapi_gui.user_manager, 'login',
                              return_value=(False, 'Bad credentials')):
                self.client.post('/api/auth/login',
                                 json={'username': 'alice', 'password': 'wrong'},
                                 content_type='application/json')
        failure_calls = [c for c in audit_calls
                         if c[0] == 'login' and c[1].get('status') == 'failure']
        self.assertGreater(len(failure_calls), 0)


# ---------------------------------------------------------------------------
# Audit wiring: suspend/unsuspend endpoints
# ---------------------------------------------------------------------------

class TestSuspendAuditWiring(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _admin_login(self):
        with self.client.session_transaction() as sess:
            sess['username'] = 'admin'

    def test_suspend_triggers_audit(self):
        audit_calls = []

        def mock_audit(action, **kwargs):
            audit_calls.append(action)

        mock_db = MagicMock()
        fake_result = {
            'username': 'alice', 'is_suspended': True,
            'suspended_until': None, 'suspended_reason': 'abuse',
            'suspended_by': 'admin', 'suspended_at': '2026-01-01T00:00:00',
        }
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            self._admin_login()
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.suspend_user', return_value=fake_result), \
                 patch('database.get_db', return_value=iter([mock_db])), \
                 patch.object(gapi_gui, '_audit', side_effect=mock_audit):
                self.client.post('/api/admin/users/alice/suspend',
                                 json={'reason': 'abuse'})
        self.assertIn('ban_user', audit_calls)

    def test_unsuspend_triggers_audit(self):
        audit_calls = []

        def mock_audit(action, **kwargs):
            audit_calls.append(action)

        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            self._admin_login()
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.unsuspend_user', return_value=True), \
                 patch('database.get_db', return_value=iter([mock_db])), \
                 patch.object(gapi_gui, '_audit', side_effect=mock_audit):
                self.client.delete('/api/admin/users/alice/suspend')
        self.assertIn('unsuspend_user', audit_calls)


# ---------------------------------------------------------------------------
# PWA meta tags (regression guard)
# ---------------------------------------------------------------------------

class TestPWAMetaTagsRegression(unittest.TestCase):
    def _html(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates', 'index.html'
        )
        with open(path) as f:
            return f.read()

    def test_apple_mobile_capable_present(self):
        self.assertIn('apple-mobile-web-app-capable', self._html())

    def test_mobile_web_app_capable_present(self):
        self.assertIn('mobile-web-app-capable', self._html())

    def test_service_worker_registration_present(self):
        html = self._html()
        self.assertIn('serviceWorker', html)
        self.assertIn('sw.js', html)

    def test_manifest_link_present(self):
        html = self._html()
        self.assertIn('rel="manifest"', html)
        self.assertIn('/manifest.json', html)


if __name__ == '__main__':
    unittest.main()
