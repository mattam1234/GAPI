#!/usr/bin/env python3
"""
Tests for app.services.analytics_service.AnalyticsService.

Covers the metrics that power the admin analytics dashboard:
  - Top games (now enriched with human-readable names)
  - Pick trends / totals (read from 'pick' audit-log entries)
  - Review statistics distribution
  - Engagement / active-user counts
  - Safe behaviour on an empty database

Run with:
    python -m pytest tests/test_analytics_service.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import database
import gapi_gui
from app.services.analytics_service import AnalyticsService


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine('sqlite:///:memory:', echo=False)
    database.Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    return eng, Session()


def _pick(db, username, game_id, name, when=None):
    db.add(database.AuditLog(
        username=username, action='pick', resource_type='game',
        resource_id=game_id, description=name,
        timestamp=when or datetime.utcnow(),
    ))


class AnalyticsServiceTest(unittest.TestCase):
    def setUp(self):
        self.eng, self.db = _make_db()
        self.svc = AnalyticsService(database)

    def tearDown(self):
        self.db.close()

    def _seed(self):
        # Users
        for u in ('alice', 'bob', 'carol'):
            self.db.add(database.User(username=u, password='x'))
        # Picks: Portal x3 (alice, bob, alice), CS x1 (carol)
        _pick(self.db, 'alice', 'steam:570', 'Portal')
        _pick(self.db, 'bob', 'steam:570', 'Portal')
        _pick(self.db, 'alice', 'steam:570', 'Portal')
        _pick(self.db, 'carol', 'steam:730', 'Counter-Strike')
        # A non-pick audit entry that must be ignored by pick metrics
        self.db.add(database.AuditLog(
            username='alice', action='login', resource_type='auth',
            resource_id='alice', timestamp=datetime.utcnow(),
        ))
        # Reviews: ratings 5, 5, 3
        for r in (5, 5, 3):
            self.db.add(database.GameReview(
                user_id=1, game_name='Portal', rating=r,
                created_at=datetime.utcnow(),
            ))
        self.db.commit()

    # --- top games -------------------------------------------------------

    def test_top_games_includes_names_and_counts(self):
        self._seed()
        top = self.svc.get_top_games(self.db, limit=10)
        self.assertEqual(len(top), 2)
        # Most-picked first
        self.assertEqual(top[0]['game_id'], 'steam:570')
        self.assertEqual(top[0]['game_name'], 'Portal')
        self.assertEqual(top[0]['pick_count'], 3)
        self.assertEqual(top[1]['game_id'], 'steam:730')
        self.assertEqual(top[1]['game_name'], 'Counter-Strike')
        self.assertEqual(top[1]['pick_count'], 1)

    def test_top_games_respects_limit(self):
        self._seed()
        top = self.svc.get_top_games(self.db, limit=1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]['game_id'], 'steam:570')

    def test_top_games_ignores_non_pick_entries(self):
        self._seed()
        top = self.svc.get_top_games(self.db, limit=10)
        # The 'login' audit row must not appear as a game
        ids = {g['game_id'] for g in top}
        self.assertNotIn('alice', ids)

    # --- trends / totals -------------------------------------------------

    def test_pick_trends_count_only_picks(self):
        self._seed()
        trends = self.svc.get_pick_trends(self.db, days=7)
        total = sum(t['picks'] for t in trends)
        self.assertEqual(total, 4)  # 3 Portal + 1 CS, login excluded

    def test_pick_trends_excludes_old_picks(self):
        _pick(self.db, 'alice', 'steam:1', 'Old', when=datetime.utcnow() - timedelta(days=30))
        _pick(self.db, 'alice', 'steam:2', 'New', when=datetime.utcnow())
        self.db.commit()
        trends = self.svc.get_pick_trends(self.db, days=7)
        self.assertEqual(sum(t['picks'] for t in trends), 1)

    def test_dashboard_summary_totals(self):
        self._seed()
        summary = self.svc.get_dashboard_summary(self.db)
        self.assertEqual(summary['total_users'], 3)
        self.assertEqual(summary['total_picks'], 4)
        self.assertEqual(summary['total_reviews'], 3)

    # --- reviews ---------------------------------------------------------

    def test_review_stats_distribution_and_average(self):
        self._seed()
        stats = self.svc.get_review_stats(self.db)
        self.assertEqual(stats['total'], 3)
        self.assertAlmostEqual(stats['average_rating'], round((5 + 5 + 3) / 3, 2))
        self.assertEqual(stats['distribution']['star_5'], 2)
        self.assertEqual(stats['distribution']['star_3'], 1)
        self.assertEqual(stats['distribution']['star_1'], 0)

    # --- engagement / active users --------------------------------------

    def test_engagement_counts_distinct_pickers(self):
        self._seed()
        eng = self.svc.get_engagement_metrics(self.db)
        # alice, bob, carol all picked
        self.assertEqual(eng['users_picked'], 3)
        self.assertEqual(eng['total_users'], 3)

    def test_active_users_counts_distinct_per_day(self):
        self._seed()
        active = self.svc.get_active_users(self.db, days=7)
        self.assertTrue(active)
        # All activity seeded "today" -> one bucket with 3 distinct users
        self.assertEqual(active[-1]['active_users'], 3)

    # --- regressions / safety -------------------------------------------

    def test_fake_genre_popularity_removed(self):
        # The hardcoded fake-data method must no longer exist.
        self.assertFalse(hasattr(self.svc, 'get_genre_popularity'))

    def test_empty_db_safe_defaults(self):
        self.assertEqual(self.svc.get_top_games(self.db), [])
        self.assertEqual(self.svc.get_pick_trends(self.db), [])
        summary = self.svc.get_dashboard_summary(self.db)
        self.assertEqual(summary['total_picks'], 0)
        self.assertEqual(summary['total_users'], 0)


class _FakeSvc:
    """Returns JSON-serialisable values for the picker's sub-services."""
    def get(self, *a, **k):
        return None

    def get_status(self, *a, **k):
        return None

    def filter_by_tag(self, tag, games):
        return games


class _FakePicker:
    BARELY_PLAYED_THRESHOLD_MINUTES = 60
    WELL_PLAYED_THRESHOLD_MINUTES = 600

    def __init__(self):
        self.games = [{'appid': 570, 'name': 'Portal'}]
        self.favorites = set()
        self.config = {}
        self.steam_client = None
        self.review_service = _FakeSvc()
        self.tag_service = _FakeSvc()
        self.backlog_service = _FakeSvc()

    def filter_games(self, **kwargs):
        return self.games

    def pick_random_game(self, filtered_games=None):
        return {
            'appid': 570, 'name': 'Portal',
            'game_id': 'steam:570', 'playtime_forever': 120,
        }


class TestPickAuditWiring(unittest.TestCase):
    """The /api/pick endpoint must record a 'pick' audit entry so the
    analytics dashboard has data to report."""

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def test_pick_emits_pick_audit_event(self):
        audit_calls = []

        def fake_audit(action, **kwargs):
            audit_calls.append((action, kwargs))

        with patch.object(gapi_gui, 'DB_AVAILABLE', False), \
             patch.object(gapi_gui, '_discord_rpc', None), \
             patch.object(gapi_gui, 'ensure_picker_initialized',
                          return_value=_FakePicker()), \
             patch.object(gapi_gui, '_get_shared_backlog_service',
                          return_value=_FakeSvc()), \
             patch.object(gapi_gui, '_audit', side_effect=fake_audit):
            resp = self.client.post('/api/pick', json={},
                                    content_type='application/json')

        self.assertEqual(resp.status_code, 200)
        pick_calls = [c for c in audit_calls if c[0] == 'pick']
        self.assertEqual(len(pick_calls), 1)
        _, kwargs = pick_calls[0]
        self.assertEqual(kwargs.get('resource_type'), 'game')
        self.assertEqual(kwargs.get('resource_id'), 'steam:570')
        self.assertEqual(kwargs.get('description'), 'Portal')


if __name__ == '__main__':
    unittest.main()
