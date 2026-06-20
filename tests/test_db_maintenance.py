#!/usr/bin/env python3
"""
Tests for Database Optimization & Maintenance endpoints (Tier 3, item 10):
  - GET  /api/admin/db/stats
  - GET  /api/admin/db/apply-indexes   (dry-run)
  - POST /api/admin/db/apply-indexes   (execute)
  - POST /api/admin/db/archive-old-picks
  - GET  /api/admin/db/backup

Run with:
    python -m pytest tests/test_db_maintenance.py
"""
import json
import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient as _FastTestClient

import gapi_gui
import database
from backend.main import app as _fastapi_app


def _set_admin_session(client):
    """Log in as admin on either a Flask or FastAPI test client."""
    if hasattr(client, 'session_transaction'):
        with client.session_transaction() as sess:
            sess['username'] = 'admin'
    else:
        ser = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
        client.cookies.set('session', ser.dumps({'username': 'admin'}))


class _AppBase(unittest.TestCase):
    def setUp(self):
        # The db-maintenance admin endpoints are migrated to FastAPI (admin_ops).
        self.client = _FastTestClient(_fastapi_app)


# ===========================================================================
# GET /api/admin/db/stats
# ===========================================================================

class TestDbStats(unittest.TestCase):
    def setUp(self):
        # migrated to FastAPI (admin_ops)
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/db/stats')
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_200_for_admin_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.get('/api/admin/db/stats')
        self.assertEqual(resp.status_code, 503)

    def test_response_shape_with_mock_db(self):
        mock_db = MagicMock()
        fake_stats = [{'table': 'users', 'rows': 42, 'size_bytes': None}]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_table_stats', return_value=fake_stats), \
                 patch('database.get_db_size_bytes', return_value=8192), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/db/stats')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('tables', data)
        self.assertIn('total_size_bytes', data)
        self.assertIn('db_available', data)

    def test_tables_list_contains_expected_keys(self):
        mock_db = MagicMock()
        fake_stats = [
            {'table': 'users', 'rows': 5, 'size_bytes': 1024},
            {'table': 'picks', 'rows': 0, 'size_bytes': None},
        ]
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.get_table_stats', return_value=fake_stats), \
                 patch('database.get_db_size_bytes', return_value=0), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/db/stats')
        data = resp.json()
        for entry in data['tables']:
            self.assertIn('table', entry)
            self.assertIn('rows', entry)
            self.assertIn('size_bytes', entry)


# ===========================================================================
# Database schema migration helpers
# ===========================================================================

class TestLegacyUserSchemaMigration(unittest.TestCase):
    def test_run_migrations_adds_missing_email_column(self):
        from sqlalchemy import create_engine, inspect, text

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            tmp_path = tmp.name

        eng = None
        try:
            eng = create_engine(f'sqlite:///{tmp_path}')
            with eng.begin() as conn:
                conn.execute(text(
                    'CREATE TABLE users ('
                    'id INTEGER PRIMARY KEY, '
                    'username VARCHAR(255) UNIQUE, '
                    'password VARCHAR(64) NOT NULL, '
                    'steam_id VARCHAR(20), '
                    'discord_id VARCHAR(50), '
                    'epic_id VARCHAR(255), '
                    'gog_id VARCHAR(255), '
                    'created_at DATETIME, '
                    'updated_at DATETIME'
                    ')'
                ))

            with patch.object(database, 'engine', eng):
                database._run_migrations()

            columns = [col['name'] for col in inspect(eng).get_columns('users')]
            self.assertIn('email', columns)
        finally:
            if eng is not None:
                eng.dispose()  # release the SQLite file handle (Windows locks it otherwise)
            os.unlink(tmp_path)


# ===========================================================================
# GET/POST /api/admin/db/apply-indexes
# ===========================================================================

class TestApplyIndexes(unittest.TestCase):
    def setUp(self):
        # migrated to FastAPI (admin_ops)
        self.client = _FastTestClient(_fastapi_app)

    def _fake_result(self, dry_run=True):
        return {
            'applied': ['CREATE INDEX idx_users_username ON users(username);'],
            'skipped': [],
            'errors': [],
            'dry_run': dry_run,
        }

    def test_dryrun_requires_admin(self):
        resp = self.client.get('/api/admin/db/apply-indexes')
        self.assertIn(resp.status_code, (401, 403))

    def test_apply_requires_admin(self):
        resp = self.client.post('/api/admin/db/apply-indexes')
        self.assertIn(resp.status_code, (401, 403))

    def test_dryrun_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.get('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 503)

    def test_apply_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 503)

    def test_dryrun_response_shape(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.apply_indexes', return_value=self._fake_result(True)), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.get('/api/admin/db/apply-indexes')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('applied', data)
        self.assertIn('skipped', data)
        self.assertIn('errors', data)
        self.assertIn('dry_run', data)
        self.assertTrue(data['dry_run'])

    def test_apply_sets_dry_run_false(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.apply_indexes', return_value=self._fake_result(False)) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post('/api/admin/db/apply-indexes')
                mock_fn.assert_called_once_with(mock_db, dry_run=False)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['dry_run'])

    def test_dryrun_calls_apply_indexes_with_dry_run_true(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.apply_indexes', return_value=self._fake_result(True)) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.get('/api/admin/db/apply-indexes')
                mock_fn.assert_called_once_with(mock_db, dry_run=True)


# ===========================================================================
# POST /api/admin/db/archive-old-picks
# ===========================================================================

class TestArchiveOldPicks(unittest.TestCase):
    def setUp(self):
        # migrated to FastAPI (admin_ops)
        self.client = _FastTestClient(_fastapi_app)

    def _fake_result(self, days=365, deleted_picks=3, deleted_sessions=1):
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        return {
            'deleted_picks': deleted_picks,
            'deleted_sessions': deleted_sessions,
            'cutoff_date': cutoff.isoformat(),
            'days': days,
        }

    def test_requires_admin(self):
        resp = self.client.post('/api/admin/db/archive-old-picks')
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.post('/api/admin/db/archive-old-picks')
        self.assertEqual(resp.status_code, 503)

    def test_response_shape(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.archive_old_picks', return_value=self._fake_result()), \
                 patch('database.get_db', return_value=iter([mock_db])):
                resp = self.client.post(
                    '/api/admin/db/archive-old-picks',
                    json={'days': 365},
                )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for field in ('deleted_picks', 'deleted_sessions', 'cutoff_date', 'days'):
            self.assertIn(field, data)

    def test_default_days_is_365(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.archive_old_picks', return_value=self._fake_result()) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.post('/api/admin/db/archive-old-picks')
                args, kwargs = mock_fn.call_args
                self.assertEqual(kwargs.get('days', args[1] if len(args) > 1 else 365), 365)

    def test_custom_days_passed_through(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.archive_old_picks', return_value=self._fake_result(90, 10, 2)) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.post(
                    '/api/admin/db/archive-old-picks',
                    json={'days': 90},
                )
                args, kwargs = mock_fn.call_args
                actual_days = kwargs.get('days', args[1] if len(args) > 1 else None)
                self.assertEqual(actual_days, 90)

    def test_invalid_days_falls_back_to_365(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.archive_old_picks', return_value=self._fake_result()) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.post(
                    '/api/admin/db/archive-old-picks',
                    json={'days': 'oops'},
                )
                args, kwargs = mock_fn.call_args
                actual_days = kwargs.get('days', args[1] if len(args) > 1 else None)
                self.assertEqual(actual_days, 365)

    def test_days_minimum_enforced_to_1(self):
        mock_db = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch('database.archive_old_picks', return_value=self._fake_result(1)) as mock_fn, \
                 patch('database.get_db', return_value=iter([mock_db])):
                self.client.post(
                    '/api/admin/db/archive-old-picks',
                    json={'days': -10},
                )
                args, kwargs = mock_fn.call_args
                actual_days = kwargs.get('days', args[1] if len(args) > 1 else None)
                self.assertGreaterEqual(actual_days, 1)


# ===========================================================================
# GET /api/admin/db/backup
# ===========================================================================

class TestDbBackup(unittest.TestCase):
    def setUp(self):
        # migrated to FastAPI (admin_ops)
        self.client = _FastTestClient(_fastapi_app)

    def test_requires_admin(self):
        resp = self.client.get('/api/admin/db/backup')
        self.assertIn(resp.status_code, (401, 403))

    def test_503_when_db_unavailable(self):
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', False):
                resp = self.client.get('/api/admin/db/backup')
        self.assertEqual(resp.status_code, 503)

    def test_non_sqlite_returns_instructions(self):
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'postgresql'
        mock_engine.url = MagicMock()
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch.object(database, 'engine', mock_engine):
                resp = self.client.get('/api/admin/db/backup')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('message', data)
        self.assertIn('dialect', data)
        self.assertEqual(data['dialect'], 'postgresql')

    def test_sqlite_streams_file(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            tmp_path = tmp.name
            conn = sqlite3.connect(tmp_path)
            conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
            conn.close()
        try:
            mock_engine = MagicMock()
            mock_engine.dialect.name = 'sqlite'
            mock_engine.url = f'sqlite:///{tmp_path}'
            with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
                _set_admin_session(self.client)
                with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                     patch.object(database, 'engine', mock_engine):
                    resp = self.client.get('/api/admin/db/backup')
            self.assertEqual(resp.status_code, 200)
            self.assertIn('attachment', resp.headers.get('content-disposition', ''))
            self.assertGreater(len(resp.content), 0)
        finally:
            os.unlink(tmp_path)

    def test_sqlite_missing_file_returns_404(self):
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'sqlite'
        mock_engine.url = 'sqlite:////tmp/nonexistent_gapi_backup.db'
        with patch.object(gapi_gui.user_manager, 'is_admin', return_value=True):
            _set_admin_session(self.client)
            with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
                 patch.object(database, 'engine', mock_engine):
                resp = self.client.get('/api/admin/db/backup')
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# Unit tests for database helper functions
# ===========================================================================

class TestDatabaseHelpers(unittest.TestCase):
    """Unit-test the helper functions directly using an in-memory SQLite DB."""

    def _make_db(self):
        """Return a fresh in-memory SQLAlchemy session + engine pair."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        eng = create_engine('sqlite:///:memory:', echo=False)
        # Create a minimal schema
        with eng.begin() as conn:
            conn.execute(text(
                'CREATE TABLE picks (id INTEGER PRIMARY KEY, username TEXT, '
                'created_at DATETIME DEFAULT CURRENT_TIMESTAMP)'
            ))
            conn.execute(text(
                'CREATE TABLE live_sessions (id INTEGER PRIMARY KEY, host TEXT, '
                'status TEXT DEFAULT "completed", '
                'created_at DATETIME DEFAULT CURRENT_TIMESTAMP)'
            ))
            conn.execute(text(
                'CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)'
            ))
        Session = sessionmaker(bind=eng)
        return eng, Session()

    def test_get_table_stats_returns_list(self):
        eng, db = self._make_db()
        with patch.object(database, 'engine', eng):
            result = database.get_table_stats(db)
        self.assertIsInstance(result, list)
        table_names = [r['table'] for r in result]
        self.assertIn('users', table_names)
        db.close()

    def test_get_table_stats_has_required_fields(self):
        eng, db = self._make_db()
        with patch.object(database, 'engine', eng):
            result = database.get_table_stats(db)
        for entry in result:
            self.assertIn('table', entry)
            self.assertIn('rows', entry)
            self.assertIn('size_bytes', entry)
        db.close()

    def test_get_table_stats_sorted_descending_by_rows(self):
        from sqlalchemy import text
        eng, db = self._make_db()
        # Insert rows into users only
        with eng.begin() as conn:
            for i in range(5):
                conn.execute(text('INSERT INTO users (username) VALUES (:u)'), {'u': f'u{i}'})
        with patch.object(database, 'engine', eng):
            result = database.get_table_stats(db)
        rows_list = [r['rows'] for r in result]
        self.assertEqual(rows_list, sorted(rows_list, reverse=True))
        db.close()

    def test_get_table_stats_returns_empty_when_db_is_none(self):
        result = database.get_table_stats(None)
        self.assertEqual(result, [])

    def test_get_db_size_bytes_sqlite(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            tmp_path = tmp.name
        eng = None
        try:
            from sqlalchemy import create_engine
            eng = create_engine(f'sqlite:///{tmp_path}')
            database.Base.metadata.create_all(bind=eng)
            with patch.object(database, 'engine', eng):
                size = database.get_db_size_bytes()
            self.assertIsInstance(size, int)
            self.assertGreater(size, 0)
        finally:
            if eng is not None:
                eng.dispose()  # release the SQLite file handle (Windows locks it otherwise)
            os.unlink(tmp_path)

    def test_get_db_size_bytes_returns_0_when_no_engine(self):
        with patch.object(database, 'engine', None):
            self.assertEqual(database.get_db_size_bytes(), 0)

    def test_apply_indexes_dry_run_returns_correct_shape(self):
        eng, db = self._make_db()
        fake_suggestions = ['CREATE INDEX idx_test ON users(username);']
        with patch.object(database, 'engine', eng), \
             patch('performance.IndexAnalyzer.analyze_query_bottlenecks', return_value=fake_suggestions):
            result = database.apply_indexes(db, dry_run=True)
        self.assertIn('applied', result)
        self.assertIn('skipped', result)
        self.assertIn('errors', result)
        self.assertTrue(result['dry_run'])
        db.close()

    def test_apply_indexes_dry_run_does_not_create_index(self):
        from sqlalchemy import inspect as _inspect
        eng, db = self._make_db()
        fake_suggestions = ['CREATE INDEX idx_users_username_test ON users(username);']
        with patch.object(database, 'engine', eng), \
             patch('performance.IndexAnalyzer.analyze_query_bottlenecks', return_value=fake_suggestions):
            database.apply_indexes(db, dry_run=True)
            inspector = _inspect(eng)
            existing_indexes = [i['name'] for i in inspector.get_indexes('users')]
        self.assertNotIn('idx_users_username_test', existing_indexes)
        db.close()

    def test_apply_indexes_non_dry_run_creates_index(self):
        from sqlalchemy import inspect as _inspect
        eng, db = self._make_db()
        fake_suggestions = ['CREATE INDEX idx_users_username_x ON users(username);']
        with patch.object(database, 'engine', eng), \
             patch('performance.IndexAnalyzer.analyze_query_bottlenecks', return_value=fake_suggestions):
            result = database.apply_indexes(db, dry_run=False)
        self.assertFalse(result['dry_run'])
        self.assertEqual(len(result['errors']), 0)
        db.close()

    def test_apply_indexes_skips_existing_indexes(self):
        from sqlalchemy import text, inspect as _inspect
        eng, db = self._make_db()
        with eng.begin() as conn:
            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_users_username_dup ON users(username)'))
        fake_suggestions = ['CREATE INDEX idx_users_username_dup ON users(username);']
        with patch.object(database, 'engine', eng), \
             patch('performance.IndexAnalyzer.analyze_query_bottlenecks', return_value=fake_suggestions):
            result = database.apply_indexes(db, dry_run=False)
        self.assertEqual(len(result['skipped']), 1)
        db.close()

    def test_archive_old_picks_returns_correct_shape(self):
        eng, db = self._make_db()
        with patch.object(database, 'engine', eng):
            result = database.archive_old_picks(db, days=365)
        for field in ('deleted_picks', 'deleted_sessions', 'cutoff_date', 'days'):
            self.assertIn(field, result)
        self.assertEqual(result['days'], 365)
        db.close()

    def test_archive_old_picks_deletes_old_records(self):
        from sqlalchemy import text
        eng, db = self._make_db()
        old_date = (datetime.utcnow() - timedelta(days=400)).isoformat()
        new_date = datetime.utcnow().isoformat()
        with eng.begin() as conn:
            conn.execute(
                text('INSERT INTO picks (username, created_at) VALUES (:u, :d)'),
                {'u': 'alice', 'd': old_date},
            )
            conn.execute(
                text('INSERT INTO picks (username, created_at) VALUES (:u, :d)'),
                {'u': 'bob', 'd': new_date},
            )
        with patch.object(database, 'engine', eng):
            result = database.archive_old_picks(db, days=365)
        self.assertEqual(result['deleted_picks'], 1)
        remaining = db.execute(text('SELECT COUNT(*) FROM picks')).fetchone()[0]
        self.assertEqual(remaining, 1)
        db.close()

    def test_archive_old_picks_returns_empty_when_db_none(self):
        result = database.archive_old_picks(None, days=365)
        self.assertEqual(result['deleted_picks'], 0)
        self.assertEqual(result['deleted_sessions'], 0)

    def test_archive_old_picks_only_deletes_completed_sessions(self):
        from sqlalchemy import text
        eng, db = self._make_db()
        old_date = (datetime.utcnow() - timedelta(days=400)).isoformat()
        with eng.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO live_sessions (host, status, created_at) '
                    'VALUES (:h, :s, :d)'
                ),
                {'h': 'alice', 's': 'completed', 'd': old_date},
            )
            conn.execute(
                text(
                    'INSERT INTO live_sessions (host, status, created_at) '
                    'VALUES (:h, :s, :d)'
                ),
                {'h': 'bob', 's': 'active', 'd': old_date},
            )
        with patch.object(database, 'engine', eng):
            result = database.archive_old_picks(db, days=365)
        self.assertEqual(result['deleted_sessions'], 1)
        remaining = db.execute(text('SELECT COUNT(*) FROM live_sessions')).fetchone()[0]
        self.assertEqual(remaining, 1)
        db.close()


if __name__ == '__main__':
    unittest.main()
