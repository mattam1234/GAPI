#!/usr/bin/env python3
"""
Tests for the migrated schedule-collections routes (backend/routers/schedule.py,
chunk 1: /api/schedules).

The per-user picker's schedule_service is stubbed with an in-memory collection
store mirroring the real service's collection semantics (access control, owner
checks, personal-schedule protection).

Run with:
    python -m pytest tests/test_backend_schedule.py
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _MemScheduleService:
    def __init__(self):
        self._s = {
            'personal:alice': {
                'id': 'personal:alice', 'name': 'Personal',
                'owner': 'alice', 'members': [], 'is_shared': False,
            }
        }
        self._n = 0

    def _can_access_schedule(self, schedule, username):
        u = (username or '').lower()
        return (schedule.get('owner', '').lower() == u
                or u in [m.lower() for m in schedule.get('members', [])])

    def list_schedules(self, username=None):
        return [s for s in self._s.values()
                if self._can_access_schedule(s, username)]

    def resolve_schedule_for_user(self, requested, username):
        if requested and requested in self._s:
            return requested
        return f'personal:{(username or "").lower()}'

    def create_schedule(self, name, owner_username, members, is_shared):
        self._n += 1
        sid = f'sched-{self._n}'
        s = {'id': sid, 'name': name, 'owner': owner_username,
             'members': list(members), 'is_shared': is_shared}
        self._s[sid] = s
        return s

    def get_schedule(self, sid):
        return self._s.get(sid)

    def update_schedule(self, schedule_id, username, name, members, is_shared=None):
        s = self._s.get(schedule_id)
        if not s or not self._can_access_schedule(s, username):
            return None
        s['name'] = name
        s['members'] = list(members)
        if is_shared is not None:
            s['is_shared'] = is_shared
        return s

    def remove_schedule(self, schedule_id, username=None):
        return self._s.pop(schedule_id, None) is not None


class BackendScheduleCollectionsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('alice'))
        self.svc = _MemScheduleService()
        self.picker = SimpleNamespace(schedule_service=self.svc)
        self._patch = patch.object(gapi_gui, 'ensure_picker_initialized',
                                   return_value=self.picker)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    # --- auth / init -----------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/schedules').status_code, 401)

    def test_not_initialized_is_400(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=None):
            resp = self.client.get('/api/schedules')
        self.assertEqual(resp.status_code, 400)

    # --- list / create ---------------------------------------------------

    def test_list_includes_active(self):
        resp = self.client.get('/api/schedules')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['active_schedule_id'], 'personal:alice')
        self.assertGreaterEqual(body['count'], 1)

    def test_create_201(self):
        resp = self.client.post('/api/schedules',
                                json={'name': 'Weekend', 'members': ['bob']})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['name'], 'Weekend')
        self.assertEqual(resp.json()['owner'], 'alice')

    def test_create_requires_name(self):
        resp = self.client.post('/api/schedules', json={'name': '  '})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name is required', resp.json()['detail'])

    # --- update ----------------------------------------------------------

    def test_update_requires_name(self):
        resp = self.client.put('/api/schedules/sched-x', json={'name': ''})
        self.assertEqual(resp.status_code, 400)

    def test_update_unknown_404(self):
        resp = self.client.put('/api/schedules/ghost', json={'name': 'New'})
        self.assertEqual(resp.status_code, 404)

    def test_update_success(self):
        sid = self.client.post('/api/schedules', json={'name': 'A'}).json()['id']
        resp = self.client.put(f'/api/schedules/{sid}', json={'name': 'B'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'B')

    # --- delete (permissions) -------------------------------------------

    def test_delete_unknown_404(self):
        self.assertEqual(self.client.delete('/api/schedules/ghost').status_code, 404)

    def test_delete_personal_is_400(self):
        resp = self.client.delete('/api/schedules/personal:alice')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('personal schedule cannot be deleted', resp.json()['detail'])

    def test_delete_non_owner_is_403(self):
        sid = self.client.post('/api/schedules',
                               json={'name': 'Shared', 'members': ['bob'],
                                     'is_shared': True}).json()['id']
        self.client.cookies.set('session', _session_cookie('bob'))
        resp = self.client.delete(f'/api/schedules/{sid}')
        self.assertEqual(resp.status_code, 403)

    def test_delete_owner_success(self):
        sid = self.client.post('/api/schedules', json={'name': 'Temp'}).json()['id']
        self.assertEqual(self.client.delete(f'/api/schedules/{sid}').status_code, 200)


if __name__ == '__main__':
    unittest.main()
