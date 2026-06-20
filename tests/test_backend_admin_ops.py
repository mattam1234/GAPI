#!/usr/bin/env python3
"""Tests for the migrated admin ops / observability routes (admin_ops domain):

  * GET  /api/admin/migrations
  * POST /api/admin/migrations/run
  * GET  /api/admin/audit-logs
  * GET  /api/admin/audit-logs/export
  * GET  /api/admin/user-activity/{target_user}
  * GET  /api/admin/security-info
  * GET  /api/admin/api-stats
  * POST /api/admin/api-stats/reset
  * GET  /api/admin/client-errors
  * POST /api/admin/client-errors/clear
  * GET  /api/admin/db/stats
  * GET  /api/admin/db/apply-indexes  (GET dry-run + POST execute)
  * POST /api/admin/db/archive-old-picks
  * GET  /api/admin/db/backup
  * GET  /api/admin/errors/rate
  * GET  /api/admin/email/status
  * POST /api/admin/email/test

Two admin checks are exercised:
  * ``require_admin_um`` (user_manager.is_admin) for the majority.
  * the inline ``_app_settings_service.is_admin`` check for audit-logs / export /
    user-activity (which also 503 BEFORE the admin check when the audit service
    is missing — that ordering is asserted).

Run with:
    python -m pytest tests/test_backend_admin_ops.py
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
    """Logged-in, admin-by-default client (user_manager.is_admin -> True)."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))
        self._admin = patch.object(gapi_gui.user_manager, 'is_admin', return_value=True)
        self._admin.start()

    def tearDown(self):
        self._admin.stop()


# ── Auth gating (require_admin_um routes) ────────────────────────────────────

class AuthGatingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_requires_login(self):
        resp = self.client.get('/api/admin/security-info')
        self.assertEqual(resp.status_code, 401)

    def test_forbidden_for_non_admin(self):
        self.client.cookies.set('session', _session_cookie('bob'))
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=False):
            resp = self.client.get('/api/admin/security-info')
        self.assertEqual(resp.status_code, 403)


# ── Migrations ───────────────────────────────────────────────────────────────

class MigrationsTest(_AuthedCase):
    def test_list_migrations(self):
        resp = self.client.get('/api/admin/migrations')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('migrations', body)
        self.assertTrue(len(body['migrations']) >= 1)
        self.assertIn('id', body['migrations'][0])
        self.assertEqual(resp.headers.get('cache-control'), 'no-store')

    def test_run_migration_db_unavailable_503(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            resp = self.client.post('/api/admin/migrations/run', json={'id': 'x'})
        self.assertEqual(resp.status_code, 503)

    def test_run_migration_invalid_id_400(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True):
            resp = self.client.post('/api/admin/migrations/run', json={'id': 'nope'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid migration id')

    def test_run_migration_success(self):
        mig_id = next(iter(gapi_gui.ADMIN_MIGRATIONS))
        fake_db = MagicMock()
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=fake_db), \
             patch.object(gapi_gui, '_run_sql_statements') as m:
            resp = self.client.post('/api/admin/migrations/run', json={'id': mig_id})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('executed successfully', resp.json()['message'])
        m.assert_called_once()
        fake_db.commit.assert_called_once()

    def test_run_migration_failure_500(self):
        mig_id = next(iter(gapi_gui.ADMIN_MIGRATIONS))
        fake_db = MagicMock()
        with patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', return_value=fake_db), \
             patch.object(gapi_gui, '_run_sql_statements', side_effect=RuntimeError('boom')):
            resp = self.client.post('/api/admin/migrations/run', json={'id': mig_id})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 'boom')


# ── Audit logs (inline app_settings admin check) ─────────────────────────────

class AuditLogsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('session', _session_cookie('admin'))

    def _admin_db(self):
        svc = MagicMock()
        svc.is_admin.return_value = True
        return svc

    def test_requires_login(self):
        client = TestClient(app)
        resp = client.get('/api/admin/audit-logs')
        self.assertEqual(resp.status_code, 401)

    def test_audit_service_missing_503(self):
        # 503 even for non-admins: the service check happens FIRST.
        with patch.object(gapi_gui, '_audit_service', None):
            resp = self.client.get('/api/admin/audit-logs')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'Audit service not available')

    def test_non_admin_403(self):
        svc = MagicMock()
        app_svc = MagicMock()
        app_svc.is_admin.return_value = False
        with patch.object(gapi_gui, '_audit_service', svc), \
             patch.object(gapi_gui, '_app_settings_service', app_svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])):
            resp = self.client.get('/api/admin/audit-logs')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'Admin access required')

    def test_get_audit_logs_success(self):
        svc = MagicMock()
        svc.get_audit_logs.return_value = {'logs': [], 'total': 0}
        app_svc = MagicMock()
        app_svc.is_admin.return_value = True
        with patch.object(gapi_gui, '_audit_service', svc), \
             patch.object(gapi_gui, '_app_settings_service', app_svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])):
            resp = self.client.get('/api/admin/audit-logs?page=2&limit=10&action=login&user=bob')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['page'], 2)
        _, kwargs = svc.get_audit_logs.call_args
        self.assertEqual(kwargs['limit'], 10)
        self.assertEqual(kwargs['offset'], 10)
        self.assertEqual(kwargs['filters'], {'action': 'login', 'username': 'bob'})

    def test_export_audit_logs_csv(self):
        svc = MagicMock()
        svc.export_audit_logs.return_value = 'a,b,c\n1,2,3\n'
        app_svc = MagicMock()
        app_svc.is_admin.return_value = True
        with patch.object(gapi_gui, '_audit_service', svc), \
             patch.object(gapi_gui, '_app_settings_service', app_svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])):
            resp = self.client.get('/api/admin/audit-logs/export')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers['content-type'].startswith('text/csv'))
        self.assertIn('attachment; filename=audit_logs.csv',
                      resp.headers.get('content-disposition', ''))
        self.assertIn('a,b,c', resp.text)

    def test_user_activity_success(self):
        svc = MagicMock()
        svc.get_user_activity.return_value = [{'action': 'login'}]
        app_svc = MagicMock()
        app_svc.is_admin.return_value = True
        with patch.object(gapi_gui, '_audit_service', svc), \
             patch.object(gapi_gui, '_app_settings_service', app_svc), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])):
            resp = self.client.get('/api/admin/user-activity/bob?limit=5')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['user'], 'bob')
        svc.get_user_activity.assert_called_once()
        self.assertEqual(svc.get_user_activity.call_args[0][2], 5)


# ── Security info ────────────────────────────────────────────────────────────

class SecurityInfoTest(_AuthedCase):
    def test_security_info(self):
        resp = self.client.get('/api/admin/security-info')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('compression_enabled', body)
        self.assertIn('rate_limiting_enabled', body)
        self.assertTrue(body['security_headers_enabled'])


# ── API usage stats ──────────────────────────────────────────────────────────

class ApiStatsTest(_AuthedCase):
    def setUp(self):
        super().setUp()
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats.clear()

    def test_api_stats_shape(self):
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats['ep_a'] = {
                'calls': 3, 'errors': 1, 'total_ms': 30.0,
                'min_ms': 5.0, 'max_ms': 20.0}
            gapi_gui._api_endpoint_stats['ep_b'] = {
                'calls': 5, 'errors': 0, 'total_ms': 50.0,
                'min_ms': 1.0, 'max_ms': 30.0}
        resp = self.client.get('/api/admin/api-stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['endpoint_count'], 2)
        # Sorted descending by call count -> ep_b first.
        self.assertEqual(body['stats'][0]['endpoint'], 'ep_b')
        self.assertEqual(body['stats'][0]['avg_ms'], 10.0)

    def test_api_stats_reset(self):
        with gapi_gui._api_stats_lock:
            gapi_gui._api_endpoint_stats['ep_a'] = {
                'calls': 1, 'errors': 0, 'total_ms': 1.0,
                'min_ms': 1.0, 'max_ms': 1.0}
        resp = self.client.post('/api/admin/api-stats/reset')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['reset'])
        with gapi_gui._api_stats_lock:
            self.assertEqual(len(gapi_gui._api_endpoint_stats), 0)


# ── Client-side error reports ────────────────────────────────────────────────

class ClientErrorsTest(_AuthedCase):
    def setUp(self):
        super().setUp()
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.clear()

    def test_client_errors_newest_first_and_limit(self):
        with gapi_gui._client_errors_lock:
            for i in range(5):
                gapi_gui._client_errors.append({'message': f'e{i}', 'timestamp': ''})
        resp = self.client.get('/api/admin/client-errors?limit=2')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_stored'], 5)
        self.assertEqual(len(body['errors']), 2)
        self.assertEqual(body['errors'][0]['message'], 'e4')

    def test_client_errors_clear(self):
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.append({'message': 'x', 'timestamp': ''})
        resp = self.client.post('/api/admin/client-errors/clear')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['cleared'])
        with gapi_gui._client_errors_lock:
            self.assertEqual(len(gapi_gui._client_errors), 0)


# ── Database maintenance ─────────────────────────────────────────────────────

class DbMaintenanceTest(_AuthedCase):
    def test_db_stats_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/db/stats')
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertFalse(body['db_available'])

    def test_db_stats_success(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'get_table_stats',
                          return_value=[{'table': 'picks', 'rows': 3}]), \
             patch.object(gapi_gui.database, 'get_db_size_bytes', return_value=1234):
            resp = self.client.get('/api/admin/db/stats')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_size_bytes'], 1234)
        self.assertTrue(body['db_available'])

    def test_apply_indexes_dryrun(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'apply_indexes',
                          return_value={'dry_run': True, 'applied': []}) as m:
            resp = self.client.get('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['dry_run'])
        self.assertTrue(m.call_args.kwargs['dry_run'])

    def test_apply_indexes_execute(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'apply_indexes',
                          return_value={'dry_run': False, 'applied': ['x']}) as m:
            resp = self.client.post('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(m.call_args.kwargs['dry_run'])

    def test_apply_indexes_db_unavailable_503(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', False):
            resp = self.client.get('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 503)

    def test_archive_old_picks_success(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'archive_old_picks',
                          return_value={'deleted_picks': 2, 'days': 30}) as m:
            resp = self.client.post('/api/admin/db/archive-old-picks', json={'days': 30})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['deleted_picks'], 2)
        self.assertEqual(m.call_args.kwargs['days'], 30)

    def test_archive_old_picks_default_days(self):
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'get_db',
                          side_effect=lambda: iter([MagicMock()])), \
             patch.object(gapi_gui.database, 'archive_old_picks',
                          return_value={'deleted_picks': 0, 'days': 365}) as m:
            resp = self.client.post('/api/admin/db/archive-old-picks', json={'days': 'bad'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(m.call_args.kwargs['days'], 365)

    def test_backup_non_sqlite(self):
        engine = MagicMock()
        engine.dialect.name = 'postgresql'
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'engine', engine):
            resp = self.client.get('/api/admin/db/backup')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['dialect'], 'postgresql')
        self.assertIn('pg_dump', body['message'])

    def test_backup_sqlite_missing_file_404(self):
        engine = MagicMock()
        engine.dialect.name = 'sqlite'
        engine.url = 'sqlite:////nonexistent/path/to.db'
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui.database, 'engine', engine):
            resp = self.client.get('/api/admin/db/backup')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'SQLite file not found')

    def test_backup_sqlite_streams_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as fh:
            fh.write(b'SQLITE_DATA')
            tmp_path = fh.name
        try:
            engine = MagicMock()
            engine.dialect.name = 'sqlite'
            engine.url = f'sqlite:///{tmp_path}'
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch.object(gapi_gui.database, 'engine', engine):
                resp = self.client.get('/api/admin/db/backup')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content, b'SQLITE_DATA')
            self.assertIn('attachment', resp.headers.get('content-disposition', ''))
        finally:
            os.unlink(tmp_path)


# ── Error-rate dashboard ─────────────────────────────────────────────────────

class ErrorRateTest(_AuthedCase):
    def setUp(self):
        super().setUp()
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.clear()

    def test_error_rate_shape(self):
        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()
        with gapi_gui._client_errors_lock:
            gapi_gui._client_errors.append({'message': 'e', 'timestamp': now_iso})
        resp = self.client.get('/api/admin/errors/rate')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['buckets']), 24)
        self.assertEqual(body['total_all'], 1)
        self.assertGreaterEqual(body['total_24h'], 1)


# ── Email management ─────────────────────────────────────────────────────────

class EmailTest(_AuthedCase):
    def test_email_status_not_loaded(self):
        with patch.object(gapi_gui, '_email_service', None):
            resp = self.client.get('/api/admin/email/status')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['configured'])

    def test_email_status_configured(self):
        svc = MagicMock()
        svc.config_info.return_value = {'configured': True, 'host': 'smtp'}
        with patch.object(gapi_gui, '_email_service', svc):
            resp = self.client.get('/api/admin/email/status')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['configured'])

    def test_email_test_not_loaded_503(self):
        with patch.object(gapi_gui, '_email_service', None):
            resp = self.client.post('/api/admin/email/test', json={'to': 'a@b.com'})
        self.assertEqual(resp.status_code, 503)

    def test_email_test_not_configured_503(self):
        svc = MagicMock()
        svc.is_configured.return_value = False
        with patch.object(gapi_gui, '_email_service', svc):
            resp = self.client.post('/api/admin/email/test', json={'to': 'a@b.com'})
        self.assertEqual(resp.status_code, 503)

    def test_email_test_invalid_address_400(self):
        svc = MagicMock()
        svc.is_configured.return_value = True
        with patch.object(gapi_gui, '_email_service', svc):
            resp = self.client.post('/api/admin/email/test', json={'to': 'notanemail'})
        self.assertEqual(resp.status_code, 400)

    def test_email_test_success(self):
        svc = MagicMock()
        svc.is_configured.return_value = True
        svc.send_test_email.return_value = True
        with patch.object(gapi_gui, '_email_service', svc):
            resp = self.client.post('/api/admin/email/test', json={'to': 'good@example.com'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['to'], 'good@example.com')


if __name__ == '__main__':
    unittest.main()
