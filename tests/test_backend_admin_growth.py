#!/usr/bin/env python3
"""Tests for the migrated admin-growth routes (backend/routers/admin_growth.py).

All routes are gated by the legacy ``@require_admin`` decorator, which maps to
the FastAPI ``require_admin`` dependency (``app_settings_service.is_admin``).

A/B tests (recommendation experiments):
  * POST  /api/admin/ab-tests
  * GET   /api/admin/ab-tests
  * PATCH /api/admin/ab-tests/{experiment_id}

User groups:
  * POST   /api/admin/user-groups
  * GET    /api/admin/user-groups
  * DELETE /api/admin/user-groups/{group_id}
  * POST   /api/admin/user-groups/{group_id}/members
  * GET    /api/admin/user-groups/{group_id}/members
  * DELETE /api/admin/user-groups/{group_id}/members/{username}

Push broadcast:
  * POST   /api/admin/push/broadcast

All DB / service / outbound calls are mocked via ``patch.object`` on
``gapi_gui.*`` — no real DB and no real network.

Run with:
    python -m pytest tests/test_backend_admin_growth.py
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


class _AdminCase(unittest.TestCase):
    """Logged-in, admin-by-default (app_settings_service.is_admin) client."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(
            gapi_gui._app_settings_service, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()


# ── Auth gating (one representative route per HTTP verb path family) ──────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_requires_login(self):
        # No session cookie -> 401 from require_login.
        resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 401)

    def test_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui._app_settings_service, 'is_admin',
                          return_value=False):
            resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 403)

    def test_user_groups_requires_login(self):
        resp = self.client.post('/api/admin/user-groups', json={'name': 'g'})
        self.assertEqual(resp.status_code, 401)

    def test_push_broadcast_requires_login(self):
        resp = self.client.post('/api/admin/push/broadcast',
                                json={'title': 'T', 'body': 'B'})
        self.assertEqual(resp.status_code, 401)


# ── A/B tests ────────────────────────────────────────────────────────────────

class CreateABTest(_AdminCase):
    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'e', 'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 503)

    def test_missing_name_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("'name'", resp.json()['error'])

    def test_single_variant_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'e', 'variants': ['only']})
        self.assertEqual(resp.status_code, 400)

    def test_non_list_variants_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'e', 'variants': 'a,b'})
        self.assertEqual(resp.status_code, 400)

    def test_create_201(self):
        mock_db = MagicMock()
        fake = {'id': 7, 'name': 'exp', 'variants': ['control', 'ml'],
                'status': 'draft'}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'create_experiment', return_value=fake), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'exp', 'variants': ['control', 'ml']})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['id'], 7)
        self.assertEqual(resp.headers['cache-control'], 'no-store')

    def test_conflict_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'create_experiment', return_value={}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'dup', 'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 409)

    def test_db_error_500(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'create_experiment',
                          side_effect=RuntimeError('boom')), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/ab-tests',
                                    json={'name': 'x', 'variants': ['a', 'b']})
        self.assertEqual(resp.status_code, 500)


class ListABTests(_AdminCase):
    def test_empty_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['experiments'], [])

    def test_returns_experiments_with_variant_counts(self):
        mock_db = MagicMock()
        exps = [{'id': 1, 'name': 'e'}]
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'list_experiments', return_value=exps), \
             patch.object(gapi_gui.database, 'get_experiment_variant_counts',
                          return_value={'control': 5}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/admin/ab-tests')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['experiments'][0]['variant_counts'], {'control': 5})


class UpdateABTest(_AdminCase):
    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.patch('/api/admin/ab-tests/1',
                                     json={'status': 'active'})
        self.assertEqual(resp.status_code, 503)

    def test_invalid_status_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.patch('/api/admin/ab-tests/1',
                                     json={'status': 'running'})
        self.assertEqual(resp.status_code, 400)

    def test_not_found_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'update_experiment_status',
                          return_value={}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.patch('/api/admin/ab-tests/99',
                                     json={'status': 'active'})
        self.assertEqual(resp.status_code, 404)

    def test_success_200(self):
        mock_db = MagicMock()
        fake = {'id': 1, 'status': 'active'}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'update_experiment_status',
                          return_value=fake), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.patch('/api/admin/ab-tests/1',
                                     json={'status': 'active'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'active')

    def test_non_int_experiment_id_422(self):
        # Typed int path param -> non-int 422 (FastAPI validation).
        resp = self.client.patch('/api/admin/ab-tests/abc',
                                 json={'status': 'active'})
        self.assertEqual(resp.status_code, 422)


# ── User groups ──────────────────────────────────────────────────────────────

class CreateUserGroup(_AdminCase):
    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/user-groups', json={'name': 'g'})
        self.assertEqual(resp.status_code, 503)

    def test_missing_name_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/user-groups', json={})
        self.assertEqual(resp.status_code, 400)

    def test_create_201_and_audits(self):
        mock_db = MagicMock()
        fake = {'id': 3, 'name': 'beta'}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'create_user_group', return_value=fake), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'), \
             patch.object(gapi_gui, '_audit') as mock_audit:
            resp = self.client.post('/api/admin/user-groups', json={'name': 'beta'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['id'], 3)
        mock_audit.assert_called_once()
        self.assertEqual(mock_audit.call_args[0][0], 'create_user_group')

    def test_conflict_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'create_user_group', return_value={}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/user-groups', json={'name': 'dup'})
        self.assertEqual(resp.status_code, 409)


class ListUserGroups(_AdminCase):
    def test_empty_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/user-groups')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['groups'], [])

    def test_returns_groups(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'list_user_groups',
                          return_value=[{'id': 1, 'name': 'g'}]), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/admin/user-groups')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['groups']), 1)


class DeleteUserGroup(_AdminCase):
    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.delete('/api/admin/user-groups/1')
        self.assertEqual(resp.status_code, 503)

    def test_not_found_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'delete_user_group', return_value=False), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.delete('/api/admin/user-groups/99')
        self.assertEqual(resp.status_code, 404)

    def test_success_and_audits(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'delete_user_group', return_value=True), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, '_audit') as mock_audit:
            resp = self.client.delete('/api/admin/user-groups/5')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(mock_audit.call_args[0][0], 'delete_user_group')


class GroupMembers(_AdminCase):
    def test_add_member_missing_username_400(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/user-groups/1/members', json={})
        self.assertEqual(resp.status_code, 400)

    def test_add_member_201(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'add_group_member',
                          return_value={'ok': True, 'username': 'alice', 'group_id': 1}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'), \
             patch.object(gapi_gui, '_audit') as mock_audit:
            resp = self.client.post('/api/admin/user-groups/1/members',
                                    json={'username': 'alice'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(mock_audit.call_args[0][0], 'add_group_member')

    def test_add_member_already_member_409(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'add_group_member',
                          return_value={'ok': False, 'error': 'Already a member'}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/user-groups/1/members',
                                    json={'username': 'alice'})
        self.assertEqual(resp.status_code, 409)

    def test_add_member_group_not_found_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'add_group_member',
                          return_value={'ok': False, 'error': 'Group not found'}), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, 'get_current_username', return_value='admin'):
            resp = self.client.post('/api/admin/user-groups/1/members',
                                    json={'username': 'alice'})
        self.assertEqual(resp.status_code, 404)

    def test_get_members_empty_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/user-groups/1/members')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'group_id': 1, 'members': []})

    def test_get_members_returns_list(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_group_members',
                          return_value=['alice', 'bob']), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.get('/api/admin/user-groups/2/members')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['group_id'], 2)
        self.assertEqual(data['members'], ['alice', 'bob'])

    def test_remove_member_not_found_404(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'remove_group_member', return_value=False), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.delete('/api/admin/user-groups/1/members/ghost')
        self.assertEqual(resp.status_code, 404)

    def test_remove_member_success_and_audits(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'remove_group_member', return_value=True), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])), \
             patch.object(gapi_gui, '_audit') as mock_audit:
            resp = self.client.delete('/api/admin/user-groups/1/members/alice')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(mock_audit.call_args[0][0], 'remove_group_member')


# ── Push broadcast (outbound delivery mocked) ────────────────────────────────

class PushBroadcast(_AdminCase):
    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'T', 'body': 'B'})
        self.assertEqual(resp.status_code, 503)

    def test_400_when_title_missing(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'body': 'B'})
        self.assertEqual(resp.status_code, 400)

    def test_400_when_body_missing(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'T'})
        self.assertEqual(resp.status_code, 400)

    def test_503_when_push_service_none(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', None), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'T', 'body': 'B'})
        self.assertEqual(resp.status_code, 503)

    def test_200_with_result_dict(self):
        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.broadcast.return_value = {
            'total': 5, 'sent': 5, 'failed': 0, 'skipped': 0, 'dry_run': False}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', mock_svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'News', 'body': 'Update'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['sent'], 5)
        # No real network: outbound delivery went through the mocked service.
        mock_svc.broadcast.assert_called_once()

    def test_dry_run_forwarded(self):
        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.broadcast.return_value = {'total': 3, 'sent': 0, 'dry_run': True}
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', mock_svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            self.client.post('/api/admin/push/broadcast',
                             json={'title': 'T', 'body': 'B', 'dry_run': True})
        _, kwargs = mock_svc.broadcast.call_args
        self.assertTrue(kwargs.get('dry_run'))
        self.assertEqual(kwargs.get('url'), '/')

    def test_service_exception_500(self):
        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_svc.broadcast.side_effect = RuntimeError('smtp down')
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, '_push_service', mock_svc), \
             patch.object(gapi_gui.database, 'get_db', return_value=iter([mock_db])):
            resp = self.client.post('/api/admin/push/broadcast',
                                    json={'title': 'T', 'body': 'B'})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'Internal server error')


if __name__ == '__main__':
    unittest.main()
