#!/usr/bin/env python3
"""
Tests for:
  - User Suspension / Account Status (Item 5)
  - User Groups (Item 5)
  - User Reputation / Trust Score + Auto-ban (Item 7)
  - API Deprecation Headers (Item 9)

Run with:
    python -m pytest tests/test_user_mgmt_reputation_deprecation.py
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui
import database


def _make_db():
    """Create an in-memory SQLite session with all tables."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine('sqlite:///:memory:', echo=False)
    database.Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    return eng, Session()


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess['username'] = 'admin'


def _set_user_session(client, username='bob'):
    with client.session_transaction() as sess:
        sess['username'] = username


# ---------------------------------------------------------------------------
# database.suspend_user / unsuspend_user / get_user_status
# ---------------------------------------------------------------------------

class TestSuspendUserHelper(unittest.TestCase):
    def _add_user(self, db, username='alice'):
        import hashlib
        u = database.User(
            username=username,
            password=hashlib.sha256(b'pw').hexdigest(),
        )
        db.add(u)
        db.commit()
        return u

    def test_suspend_nonexistent_returns_empty(self):
        _, db = _make_db()
        result = database.suspend_user(db, 'nobody', 'test', 'admin')
        self.assertEqual(result, {})
        db.close()

    def test_suspend_none_db_returns_empty(self):
        self.assertEqual(database.suspend_user(None, 'alice', 'test', 'admin'), {})

    def test_suspend_permanent_ban(self):
        _, db = _make_db()
        self._add_user(db, 'alice')
        result = database.suspend_user(db, 'alice', reason='abuse', suspended_by='admin')
        self.assertTrue(result.get('is_suspended'))
        self.assertIsNone(result.get('suspended_until'))
        self.assertEqual(result.get('suspended_reason'), 'abuse')
        self.assertEqual(result.get('suspended_by'), 'admin')
        db.close()

    def test_suspend_temporary(self):
        _, db = _make_db()
        self._add_user(db, 'bob')
        result = database.suspend_user(db, 'bob', reason='spam', suspended_by='admin',
                                       duration_minutes=60)
        self.assertTrue(result.get('is_suspended'))
        self.assertIsNotNone(result.get('suspended_until'))
        db.close()

    def test_unsuspend_user(self):
        _, db = _make_db()
        self._add_user(db, 'carol')
        database.suspend_user(db, 'carol', reason='test', suspended_by='admin')
        ok = database.unsuspend_user(db, 'carol')
        self.assertTrue(ok)
        status = database.get_user_status(db, 'carol')
        self.assertEqual(status['status'], 'active')
        self.assertFalse(status['is_suspended'])
        db.close()

    def test_unsuspend_nonexistent_returns_false(self):
        _, db = _make_db()
        ok = database.unsuspend_user(db, 'nobody')
        self.assertFalse(ok)
        db.close()

    def test_unsuspend_none_db_returns_false(self):
        self.assertFalse(database.unsuspend_user(None, 'alice'))

    def test_get_user_status_active(self):
        _, db = _make_db()
        self._add_user(db, 'dave')
        status = database.get_user_status(db, 'dave')
        self.assertEqual(status['status'], 'active')
        self.assertFalse(status['is_suspended'])
        db.close()

    def test_get_user_status_suspended(self):
        _, db = _make_db()
        self._add_user(db, 'eve')
        database.suspend_user(db, 'eve', reason='test', suspended_by='admin',
                               duration_minutes=120)
        status = database.get_user_status(db, 'eve')
        self.assertEqual(status['status'], 'suspended')
        db.close()

    def test_get_user_status_banned(self):
        _, db = _make_db()
        self._add_user(db, 'frank')
        database.suspend_user(db, 'frank', reason='ban', suspended_by='admin')
        status = database.get_user_status(db, 'frank')
        self.assertEqual(status['status'], 'banned')
        db.close()

    def test_get_user_status_auto_expires(self):
        from datetime import datetime, timedelta
        _, db = _make_db()
        self._add_user(db, 'grace')
        # Suspend in the past
        user = db.query(database.User).filter(database.User.username == 'grace').first()
        user.is_suspended = True
        user.suspended_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        status = database.get_user_status(db, 'grace')
        self.assertEqual(status['status'], 'active')
        db.close()

    def test_get_user_status_missing_returns_empty(self):
        _, db = _make_db()
        self.assertEqual(database.get_user_status(db, 'nobody'), {})
        db.close()


# ---------------------------------------------------------------------------
# database.search_users_admin
# ---------------------------------------------------------------------------

class TestSearchUsersAdmin(unittest.TestCase):
    def _add_user(self, db, username, roles=None):
        import hashlib
        u = database.User(
            username=username,
            password=hashlib.sha256(b'pw').hexdigest(),
        )
        db.add(u)
        db.commit()
        if roles:
            database.set_user_roles(db, username, roles)
        return u

    def test_returns_empty_on_none_db(self):
        self.assertEqual(database.search_users_admin(None), [])

    def test_returns_all_by_default(self):
        _, db = _make_db()
        self._add_user(db, 'u1')
        self._add_user(db, 'u2')
        results = database.search_users_admin(db)
        usernames = [r['username'] for r in results]
        self.assertIn('u1', usernames)
        self.assertIn('u2', usernames)
        db.close()

    def test_query_filter(self):
        _, db = _make_db()
        self._add_user(db, 'alice_admin')
        self._add_user(db, 'bob_user')
        results = database.search_users_admin(db, query='alice')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['username'], 'alice_admin')
        db.close()

    def test_status_filter_active(self):
        _, db = _make_db()
        self._add_user(db, 'active_user')
        self._add_user(db, 'susp_user')
        database.suspend_user(db, 'susp_user', reason='test', suspended_by='admin',
                               duration_minutes=60)
        results = database.search_users_admin(db, status='active')
        names = [r['username'] for r in results]
        self.assertIn('active_user', names)
        self.assertNotIn('susp_user', names)
        db.close()

    def test_status_filter_suspended(self):
        _, db = _make_db()
        self._add_user(db, 'normal')
        self._add_user(db, 'temp_banned')
        database.suspend_user(db, 'temp_banned', reason='spam', suspended_by='admin',
                               duration_minutes=60)
        results = database.search_users_admin(db, status='suspended')
        names = [r['username'] for r in results]
        self.assertIn('temp_banned', names)
        self.assertNotIn('normal', names)
        db.close()

    def test_status_filter_banned(self):
        _, db = _make_db()
        self._add_user(db, 'not_banned')
        self._add_user(db, 'perm_banned')
        database.suspend_user(db, 'perm_banned', reason='abuse', suspended_by='admin')
        results = database.search_users_admin(db, status='banned')
        names = [r['username'] for r in results]
        self.assertIn('perm_banned', names)
        self.assertNotIn('not_banned', names)
        db.close()

    def test_limit_respected(self):
        _, db = _make_db()
        for i in range(10):
            self._add_user(db, f'user_{i:02d}')
        results = database.search_users_admin(db, limit=3)
        self.assertLessEqual(len(results), 3)
        db.close()

    def test_result_contains_expected_keys(self):
        _, db = _make_db()
        self._add_user(db, 'tester')
        results = database.search_users_admin(db, query='tester')
        self.assertEqual(len(results), 1)
        r = results[0]
        for key in ('username', 'display_name', 'status', 'roles', 'created_at'):
            self.assertIn(key, r)
        db.close()


# ---------------------------------------------------------------------------
# Flask endpoints: user suspension
# ---------------------------------------------------------------------------

class TestSuspendEndpoints(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_suspend_requires_admin(self):
        resp = self.client.post('/api/admin/users/alice/suspend',
                                json={'reason': 'test'})
        self.assertIn(resp.status_code, (401, 403))

    def test_suspend_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/users/alice/suspend',
                                        json={'reason': 'test'})
        self.assertEqual(resp.status_code, 503)

    def test_suspend_missing_reason_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/users/alice/suspend', json={})
        self.assertEqual(resp.status_code, 400)

    def test_suspend_invalid_duration_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/users/alice/suspend',
                                        json={'reason': 'test', 'duration_minutes': 'bad'})
        self.assertEqual(resp.status_code, 400)

    def test_suspend_nonpositive_duration_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/users/alice/suspend',
                                        json={'reason': 'test', 'duration_minutes': -1})
        self.assertEqual(resp.status_code, 400)

    def test_suspend_user_not_found_returns_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.suspend_user', return_value={}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/users/nobody/suspend',
                                        json={'reason': 'test'})
        self.assertEqual(resp.status_code, 404)

    def test_suspend_success_returns_200(self):
        mock_db = MagicMock()
        fake_result = {
            'username': 'alice', 'is_suspended': True,
            'suspended_until': None, 'suspended_reason': 'abuse',
            'suspended_by': 'admin', 'suspended_at': '2026-01-01T00:00:00',
        }
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.suspend_user', return_value=fake_result), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/users/alice/suspend',
                                        json={'reason': 'abuse'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['is_suspended'])

    def test_unsuspend_requires_admin(self):
        resp = self.client.delete('/api/admin/users/alice/suspend')
        self.assertIn(resp.status_code, (401, 403))

    def test_unsuspend_not_found_returns_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.unsuspend_user', return_value=False), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.delete('/api/admin/users/nobody/suspend')
        self.assertEqual(resp.status_code, 404)

    def test_unsuspend_success_returns_200(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.unsuspend_user', return_value=True), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.delete('/api/admin/users/alice/suspend')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['ok'])

    def test_get_user_status_requires_admin(self):
        resp = self.client.get('/api/admin/users/alice/status')
        self.assertIn(resp.status_code, (401, 403))

    def test_get_user_status_not_found_returns_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_user_status', return_value={}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/users/nobody/status')
        self.assertEqual(resp.status_code, 404)

    def test_get_user_status_returns_200(self):
        mock_db = MagicMock()
        fake_status = {
            'username': 'alice', 'status': 'active',
            'is_suspended': False, 'suspended_until': None,
            'suspended_reason': None, 'suspended_by': None, 'suspended_at': None,
        }
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_user_status', return_value=fake_status), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/users/alice/status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['status'], 'active')


# ---------------------------------------------------------------------------
# Flask endpoints: admin user search
# ---------------------------------------------------------------------------

class TestAdminSearchUsers(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/users/search')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_empty_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.get('/api/admin/users/search')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['users'], [])

    def test_returns_users(self):
        mock_db = MagicMock()
        fake_users = [
            {'username': 'alice', 'display_name': 'Alice', 'status': 'active',
             'roles': [], 'created_at': '2026-01-01T00:00:00', 'last_seen': None},
        ]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.search_users_admin', return_value=fake_users), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/users/search?q=alice')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('users', data)
        self.assertEqual(data['count'], 1)

    def test_forwards_filters_to_helper(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.search_users_admin', return_value=[]) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.get('/api/admin/users/search?q=test&status=suspended&role=admin&limit=25&offset=10')
        _, kwargs = mock_fn.call_args
        self.assertEqual(kwargs.get('query'), 'test')
        self.assertEqual(kwargs.get('status'), 'suspended')
        self.assertEqual(kwargs.get('role'), 'admin')
        self.assertEqual(kwargs.get('limit'), 25)
        self.assertEqual(kwargs.get('offset'), 10)


# ---------------------------------------------------------------------------
# database: User Group helpers
# ---------------------------------------------------------------------------

class TestUserGroupHelpers(unittest.TestCase):
    def test_create_group(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'beta_testers', description='Beta users')
        self.assertIn('id', grp)
        self.assertEqual(grp['name'], 'beta_testers')
        self.assertEqual(grp['description'], 'Beta users')
        self.assertEqual(grp['member_count'], 0)
        db.close()

    def test_create_group_none_db_returns_empty(self):
        self.assertEqual(database.create_user_group(None, 'grp'), {})

    def test_create_group_empty_name_returns_empty(self):
        _, db = _make_db()
        self.assertEqual(database.create_user_group(db, ''), {})
        db.close()

    def test_list_groups(self):
        _, db = _make_db()
        database.create_user_group(db, 'group_a')
        database.create_user_group(db, 'group_b')
        groups = database.list_user_groups(db)
        self.assertEqual(len(groups), 2)
        names = {g['name'] for g in groups}
        self.assertIn('group_a', names)
        self.assertIn('group_b', names)
        db.close()

    def test_list_groups_empty_on_none_db(self):
        self.assertEqual(database.list_user_groups(None), [])

    def test_delete_group(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'to_delete')
        ok = database.delete_user_group(db, grp['id'])
        self.assertTrue(ok)
        self.assertEqual(database.list_user_groups(db), [])
        db.close()

    def test_delete_nonexistent_group(self):
        _, db = _make_db()
        ok = database.delete_user_group(db, 99999)
        self.assertFalse(ok)
        db.close()

    def test_add_member(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'team_x')
        result = database.add_group_member(db, grp['id'], 'alice')
        self.assertTrue(result['ok'])
        members = database.get_group_members(db, grp['id'])
        self.assertIn('alice', members)
        db.close()

    def test_add_member_twice_returns_error(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'team_y')
        database.add_group_member(db, grp['id'], 'alice')
        result = database.add_group_member(db, grp['id'], 'alice')
        self.assertFalse(result['ok'])
        self.assertIn('member', result.get('error', '').lower())
        db.close()

    def test_add_member_to_nonexistent_group(self):
        _, db = _make_db()
        result = database.add_group_member(db, 99999, 'alice')
        self.assertFalse(result['ok'])
        db.close()

    def test_remove_member(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'team_z')
        database.add_group_member(db, grp['id'], 'bob')
        ok = database.remove_group_member(db, grp['id'], 'bob')
        self.assertTrue(ok)
        self.assertNotIn('bob', database.get_group_members(db, grp['id']))
        db.close()

    def test_remove_nonexistent_member(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'team_w')
        ok = database.remove_group_member(db, grp['id'], 'nobody')
        self.assertFalse(ok)
        db.close()

    def test_member_count_in_list(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'counted')
        database.add_group_member(db, grp['id'], 'u1')
        database.add_group_member(db, grp['id'], 'u2')
        groups = database.list_user_groups(db)
        found = next((g for g in groups if g['name'] == 'counted'), None)
        self.assertIsNotNone(found)
        self.assertEqual(found['member_count'], 2)
        db.close()

    def test_delete_group_also_removes_members(self):
        _, db = _make_db()
        grp = database.create_user_group(db, 'ephemeral')
        database.add_group_member(db, grp['id'], 'alice')
        database.delete_user_group(db, grp['id'])
        # After group deletion, member rows should be gone too
        members = database.get_group_members(db, grp['id'])
        self.assertEqual(members, [])
        db.close()


# ---------------------------------------------------------------------------
# Flask endpoints: user groups
# ---------------------------------------------------------------------------

class TestUserGroupEndpoints(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_create_group_requires_admin(self):
        resp = self.client.post('/api/admin/user-groups', json={'name': 'grp'})
        self.assertIn(resp.status_code, (401, 403))

    def test_create_group_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/user-groups', json={'name': 'grp'})
        self.assertEqual(resp.status_code, 503)

    def test_create_group_missing_name_returns_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/user-groups', json={})
        self.assertEqual(resp.status_code, 400)

    def test_create_group_success_201(self):
        mock_db = MagicMock()
        fake_grp = {'id': 1, 'name': 'beta', 'description': '',
                    'created_by': 'admin', 'created_at': '2026-01-01T00:00:00',
                    'member_count': 0}
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_user_group', return_value=fake_grp), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/user-groups', json={'name': 'beta'})
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.data)
        self.assertEqual(data['name'], 'beta')

    def test_create_group_conflict_returns_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.create_user_group', return_value={}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/user-groups', json={'name': 'dup'})
        self.assertEqual(resp.status_code, 409)

    def test_list_groups_requires_admin(self):
        resp = self.client.get('/api/admin/user-groups')
        self.assertIn(resp.status_code, (401, 403))

    def test_list_groups_returns_groups(self):
        mock_db = MagicMock()
        fake_groups = [{'id': 1, 'name': 'beta', 'description': '', 'created_by': 'admin',
                        'created_at': None, 'member_count': 3}]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.list_user_groups', return_value=fake_groups), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/user-groups')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('groups', data)
        self.assertEqual(len(data['groups']), 1)

    def test_delete_group_requires_admin(self):
        resp = self.client.delete('/api/admin/user-groups/1')
        self.assertIn(resp.status_code, (401, 403))

    def test_delete_group_not_found_returns_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.delete_user_group', return_value=False), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.delete('/api/admin/user-groups/99')
        self.assertEqual(resp.status_code, 404)

    def test_add_member_requires_admin(self):
        resp = self.client.post('/api/admin/user-groups/1/members',
                                json={'username': 'alice'})
        self.assertIn(resp.status_code, (401, 403))

    def test_add_member_missing_username_400(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True):
                resp = self.client.post('/api/admin/user-groups/1/members', json={})
        self.assertEqual(resp.status_code, 400)

    def test_add_member_success_201(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.add_group_member',
                       return_value={'ok': True, 'username': 'alice', 'group_id': 1}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/user-groups/1/members',
                                        json={'username': 'alice'})
        self.assertEqual(resp.status_code, 201)

    def test_add_member_already_member_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.add_group_member',
                       return_value={'ok': False, 'error': 'Already a member'}), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/user-groups/1/members',
                                        json={'username': 'alice'})
        self.assertEqual(resp.status_code, 409)

    def test_remove_member_requires_admin(self):
        resp = self.client.delete('/api/admin/user-groups/1/members/alice')
        self.assertIn(resp.status_code, (401, 403))

    def test_get_members_requires_admin(self):
        resp = self.client.get('/api/admin/user-groups/1/members')
        self.assertIn(resp.status_code, (401, 403))

    def test_get_members_returns_list(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_group_members', return_value=['alice', 'bob']), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/user-groups/1/members')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['members'], ['alice', 'bob'])


# ---------------------------------------------------------------------------
# database: User Reputation helpers
# ---------------------------------------------------------------------------

class TestUserReputationHelpers(unittest.TestCase):
    def test_get_reputation_creates_default(self):
        _, db = _make_db()
        rep = database.get_reputation(db, 'alice')
        self.assertEqual(rep['username'], 'alice')
        self.assertEqual(rep['score'], 100)
        self.assertEqual(rep['violation_count'], 0)
        db.close()

    def test_get_reputation_none_db_returns_empty(self):
        self.assertEqual(database.get_reputation(None, 'alice'), {})

    def test_update_reputation_deducts_score(self):
        _, db = _make_db()
        rep = database.update_reputation(db, 'bob', 'warn')
        expected = 100 - database.REPUTATION_PENALTIES['warn']
        self.assertEqual(rep['score'], expected)
        self.assertEqual(rep['violation_count'], 1)
        self.assertEqual(rep['last_action'], 'warn')
        db.close()

    def test_update_reputation_multiple_actions(self):
        _, db = _make_db()
        database.update_reputation(db, 'carol', 'warn')
        database.update_reputation(db, 'carol', 'mute')
        rep = database.get_reputation(db, 'carol')
        expected = 100 - database.REPUTATION_PENALTIES['warn'] - database.REPUTATION_PENALTIES['mute']
        self.assertEqual(rep['score'], expected)
        self.assertEqual(rep['violation_count'], 2)
        db.close()

    def test_score_does_not_go_below_zero(self):
        _, db = _make_db()
        for _ in range(5):
            database.update_reputation(db, 'dave', 'ban')
        rep = database.get_reputation(db, 'dave')
        self.assertGreaterEqual(rep['score'], 0)
        db.close()

    def test_unknown_action_uses_default_penalty(self):
        _, db = _make_db()
        rep = database.update_reputation(db, 'eve', 'unknown_action')
        expected = 100 - database.REPUTATION_PENALTIES['default']
        self.assertEqual(rep['score'], expected)
        db.close()

    def test_auto_ban_triggered_below_threshold(self):
        _, db = _make_db()
        import hashlib
        db.add(database.User(
            username='frank',
            password=hashlib.sha256(b'pw').hexdigest(),
        ))
        db.commit()
        # Drop score below threshold
        for _ in range(4):
            database.update_reputation(db, 'frank', 'ban')
        # User should be suspended now
        status = database.get_user_status(db, 'frank')
        self.assertTrue(status.get('is_suspended', False))
        db.close()

    def test_auto_ban_flag_in_update_result(self):
        _, db = _make_db()
        # Start from threshold + 1 to ensure single ban triggers it
        rep_row = database.UserReputation(
            username='grace',
            score=database.REPUTATION_AUTO_BAN_THRESHOLD + 1,
        )
        db.add(rep_row)
        db.commit()
        result = database.update_reputation(db, 'grace', 'ban')
        # If score is now <= threshold, auto_suspended should be True
        if result['score'] <= database.REPUTATION_AUTO_BAN_THRESHOLD:
            self.assertTrue(result.get('auto_suspended'))
        db.close()

    def test_update_reputation_none_db_returns_empty(self):
        self.assertEqual(database.update_reputation(None, 'alice', 'warn'), {})

    def test_get_low_reputation_users(self):
        _, db = _make_db()
        database.update_reputation(db, 'low1', 'ban')
        database.update_reputation(db, 'low1', 'ban')
        database.update_reputation(db, 'low1', 'ban')
        database.get_reputation(db, 'high_rep')  # creates default 100
        results = database.get_low_reputation_users(db, threshold=80)
        names = [r['username'] for r in results]
        self.assertIn('low1', names)
        self.assertNotIn('high_rep', names)
        db.close()

    def test_get_low_reputation_none_db_returns_empty(self):
        self.assertEqual(database.get_low_reputation_users(None), [])


# ---------------------------------------------------------------------------
# Flask endpoints: reputation
# ---------------------------------------------------------------------------

class TestReputationEndpoints(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def test_reputation_requires_login(self):
        resp = self.client.get('/api/users/alice/reputation')
        self.assertIn(resp.status_code, (401, 403))

    def test_reputation_returns_default_when_db_unavailable(self):
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/users/alice/reputation')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['score'], 100)

    def test_reputation_returns_data(self):
        mock_db = MagicMock()
        fake_rep = {'username': 'alice', 'score': 85, 'violation_count': 2,
                    'last_updated': '2026-01-01T00:00:00', 'last_action': 'warn'}
        _set_user_session(self.client)
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch('database.get_reputation', return_value=fake_rep), \
             patch('database.get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/users/alice/reputation')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['score'], 85)

    def test_low_reputation_requires_admin(self):
        resp = self.client.get('/api/admin/users/low-reputation')
        self.assertIn(resp.status_code, (401, 403))

    def test_low_reputation_returns_users(self):
        mock_db = MagicMock()
        fake_users = [
            {'username': 'badactor', 'score': 30, 'violation_count': 5,
             'last_action': 'ban', 'last_updated': '2026-01-01T00:00:00'},
        ]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_low_reputation_users', return_value=fake_users), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/users/low-reputation')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('users', data)
        self.assertIn('threshold', data)


# ---------------------------------------------------------------------------
# API Deprecation Headers
# ---------------------------------------------------------------------------

class TestDeprecationHeaders(unittest.TestCase):
    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()

    def _hit_legacy_endpoint(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            return self.client.get('/api/users/legacy')

    def test_deprecated_endpoint_has_deprecation_header(self):
        resp = self._hit_legacy_endpoint()
        self.assertEqual(resp.headers.get('Deprecation'), 'true')

    def test_deprecated_endpoint_has_sunset_header(self):
        resp = self._hit_legacy_endpoint()
        sunset = resp.headers.get('Sunset', '')
        self.assertTrue(len(sunset) > 0, 'Sunset header should be present')

    def test_deprecated_endpoint_has_message_header(self):
        resp = self._hit_legacy_endpoint()
        msg = resp.headers.get('X-Deprecation-Message', '')
        self.assertIn('deprecated', msg.lower())

    def test_non_deprecated_endpoint_has_no_deprecation_header(self):
        resp = self.client.get('/api/changelog')
        self.assertIsNone(resp.headers.get('Deprecation'))

    def test_deprecated_endpoints_dict_populated(self):
        self.assertGreater(len(gapi_gui._DEPRECATED_ENDPOINTS), 0)
        for key, value in gapi_gui._DEPRECATED_ENDPOINTS.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, tuple)
            self.assertEqual(len(value), 2)

    def test_sunset_date_is_future(self):
        """Sunset dates in the deprecation config should be in the future."""
        from datetime import date
        today = date.today()
        for _, (_, sunset_str) in gapi_gui._DEPRECATED_ENDPOINTS.items():
            sunset = date.fromisoformat(sunset_str)
            self.assertGreater(sunset, today,
                               f'Sunset date {sunset_str} should be in the future')


if __name__ == '__main__':
    unittest.main()
