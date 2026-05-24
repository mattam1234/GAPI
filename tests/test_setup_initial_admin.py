#!/usr/bin/env python3
"""Regression tests for initial admin setup transaction handling."""

import contextlib
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine('sqlite:///:memory:', echo=False)
    database.Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    return Session()


class TestInitialAdminSetupHelpers(unittest.TestCase):
    def test_create_or_update_user_bootstraps_admin_role(self):
        db = _make_db()
        try:
            user = database.create_or_update_user(
                db, 'admin', password='hash123', role='admin', roles=['admin']
            )
            self.assertIsNotNone(user)
            self.assertEqual(database.get_user_roles(db, 'admin'), ['admin'])
        finally:
            db.close()

    def test_get_user_count_rolls_back_on_error(self):
        db = MagicMock()
        db.query.return_value.count.side_effect = RuntimeError('boom')

        count = database.get_user_count(db)

        self.assertEqual(count, 0)
        db.rollback.assert_called_once()

    def test_ensure_role_rolls_back_on_error(self):
        db = MagicMock()
        db.no_autoflush = contextlib.nullcontext()
        db.query.return_value.filter.return_value.first.side_effect = RuntimeError('boom')

        role = database.ensure_role(db, 'admin')

        self.assertIsNone(role)
        db.rollback.assert_called_once()

