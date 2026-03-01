#!/usr/bin/env python3
"""
Tests for:
  - Achievement statistics by platform
  - Multiplayer achievement challenges (DB helpers)
  - GraphQL endpoint (schema + query execution)
  - OpenAPI spec additions (challenges, graphql paths)

Run with:
    python -m pytest tests/test_challenges_graphql.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from openapi_spec import build_spec
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# In-memory DB helper
# ---------------------------------------------------------------------------

def _make_session():
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _create_user(db, username='alice'):
    user = database.User(username=username, password='hash')
    db.add(user)
    db.commit()
    return db.query(database.User).filter_by(username=username).first()


def _add_achievement(db, user, app_id='620', game_name='Portal 2',
                     achievement_id='ACH1', unlocked=False, rarity=None):
    a = database.Achievement(
        user_id=user.id, app_id=app_id, game_name=game_name,
        achievement_id=achievement_id, achievement_name='Test',
        unlocked=unlocked, rarity=rarity,
    )
    db.add(a)
    db.commit()
    return a


def _add_library_cache(db, user, app_id='620', game_name='Portal 2', platform='steam'):
    g = database.GameLibraryCache(
        user_id=user.id, app_id=app_id, game_name=game_name,
        platform=platform, playtime_hours=1.5,
    )
    db.add(g)
    db.commit()
    return g


# ===========================================================================
# get_achievement_stats_by_platform
# ===========================================================================

class TestGetAchievementStatsByPlatform(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_empty(self):
        self.assertEqual(database.get_achievement_stats_by_platform(None, 'alice'), [])

    def test_unknown_user_returns_empty(self):
        self.assertEqual(database.get_achievement_stats_by_platform(self.db, 'nobody'), [])

    def test_no_achievements_returns_empty(self):
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        self.assertEqual(result, [])

    def test_single_platform_from_library_cache(self):
        _add_library_cache(self.db, self.user, app_id='620', platform='steam')
        _add_achievement(self.db, self.user, app_id='620', unlocked=True)
        _add_achievement(self.db, self.user, app_id='620', achievement_id='A2', unlocked=False)
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row['platform'], 'steam')
        self.assertEqual(row['total_tracked'], 2)
        self.assertEqual(row['total_unlocked'], 1)
        self.assertAlmostEqual(row['completion_percent'], 50.0)
        self.assertEqual(row['game_count'], 1)

    def test_multiple_platforms(self):
        _add_library_cache(self.db, self.user, app_id='620', platform='steam')
        _add_library_cache(self.db, self.user, app_id='999', platform='epic')
        _add_achievement(self.db, self.user, app_id='620', achievement_id='S1', unlocked=True)
        _add_achievement(self.db, self.user, app_id='999', achievement_id='E1', unlocked=False)
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        platforms = {r['platform'] for r in result}
        self.assertEqual(platforms, {'steam', 'epic'})

    def test_unknown_app_defaults_to_steam(self):
        # No library cache entry — should default to 'steam'
        _add_achievement(self.db, self.user, app_id='11111', achievement_id='X1')
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['platform'], 'steam')

    def test_sorted_by_platform_name(self):
        _add_library_cache(self.db, self.user, app_id='1', platform='steam')
        _add_library_cache(self.db, self.user, app_id='2', platform='epic')
        _add_library_cache(self.db, self.user, app_id='3', platform='gog')
        _add_achievement(self.db, self.user, app_id='1', achievement_id='A1')
        _add_achievement(self.db, self.user, app_id='2', achievement_id='B1')
        _add_achievement(self.db, self.user, app_id='3', achievement_id='C1')
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        platforms = [r['platform'] for r in result]
        self.assertEqual(platforms, sorted(platforms))

    def test_result_is_json_serialisable(self):
        _add_achievement(self.db, self.user, app_id='620')
        json.dumps(database.get_achievement_stats_by_platform(self.db, 'alice'))

    def test_completion_percent_100_when_all_unlocked(self):
        _add_library_cache(self.db, self.user, app_id='620', platform='steam')
        _add_achievement(self.db, self.user, app_id='620', achievement_id='A1', unlocked=True)
        _add_achievement(self.db, self.user, app_id='620', achievement_id='A2', unlocked=True)
        result = database.get_achievement_stats_by_platform(self.db, 'alice')
        self.assertAlmostEqual(result[0]['completion_percent'], 100.0)


# ===========================================================================
# create_achievement_challenge
# ===========================================================================

class TestCreateAchievementChallenge(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_empty(self):
        self.assertEqual(
            database.create_achievement_challenge(None, 'alice', 'T', '620', 'G'), {})

    def test_unknown_user_returns_empty(self):
        self.assertEqual(
            database.create_achievement_challenge(self.db, 'nobody', 'T', '620', 'G'), {})

    def test_creates_challenge_with_defaults(self):
        result = database.create_achievement_challenge(
            self.db, 'alice', 'My Challenge', '620', 'Portal 2')
        self.assertIn('id', result)
        self.assertEqual(result['title'], 'My Challenge')
        self.assertEqual(result['app_id'], '620')
        self.assertEqual(result['game_name'], 'Portal 2')
        self.assertEqual(result['status'], 'open')
        self.assertEqual(result['created_by'], 'alice')

    def test_creator_added_as_first_participant(self):
        result = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G')
        self.assertEqual(len(result['participants']), 1)
        self.assertEqual(result['participants'][0]['username'], 'alice')

    def test_target_achievement_ids_stored(self):
        result = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G',
            target_achievement_ids=['ACH1', 'ACH2'])
        self.assertIn('ACH1', result['target_achievement_ids'])
        self.assertIn('ACH2', result['target_achievement_ids'])

    def test_no_winner_initially(self):
        result = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G')
        self.assertIsNone(result['winner'])

    def test_result_is_json_serialisable(self):
        result = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G')
        json.dumps(result)


# ===========================================================================
# join_achievement_challenge
# ===========================================================================

class TestJoinAchievementChallenge(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.alice = _create_user(self.db, 'alice')
        self.bob = _create_user(self.db, 'bob')
        challenge = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G')
        self.challenge_id = challenge['id']

    def tearDown(self):
        self.db.close()

    def test_join_adds_participant(self):
        result = database.join_achievement_challenge(self.db, self.challenge_id, 'bob')
        usernames = [p['username'] for p in result['participants']]
        self.assertIn('bob', usernames)

    def test_join_sets_status_to_in_progress(self):
        result = database.join_achievement_challenge(self.db, self.challenge_id, 'bob')
        self.assertEqual(result['status'], 'in_progress')

    def test_join_unknown_challenge_returns_empty(self):
        self.assertEqual(
            database.join_achievement_challenge(self.db, 'nonexistent', 'bob'), {})

    def test_join_idempotent_for_existing_participant(self):
        database.join_achievement_challenge(self.db, self.challenge_id, 'bob')
        result = database.join_achievement_challenge(self.db, self.challenge_id, 'bob')
        usernames = [p['username'] for p in result['participants']]
        self.assertEqual(usernames.count('bob'), 1)


# ===========================================================================
# record_challenge_unlock / cancel
# ===========================================================================

class TestRecordAndCancelChallenge(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.alice = _create_user(self.db, 'alice')
        self.bob = _create_user(self.db, 'bob')
        challenge = database.create_achievement_challenge(
            self.db, 'alice', 'T', '620', 'G',
            target_achievement_ids=['A1', 'A2'])
        self.challenge_id = challenge['id']
        database.join_achievement_challenge(self.db, self.challenge_id, 'bob')

    def tearDown(self):
        self.db.close()

    def test_record_unlock_updates_count(self):
        result = database.record_challenge_unlock(self.db, self.challenge_id, 'alice', 1)
        alice_part = next(p for p in result['participants'] if p['username'] == 'alice')
        self.assertEqual(alice_part['unlocked_count'], 1)

    def test_completing_all_targets_marks_winner(self):
        result = database.record_challenge_unlock(self.db, self.challenge_id, 'bob', 2)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['winner'], 'bob')

    def test_completing_all_targets_marks_participant_done(self):
        result = database.record_challenge_unlock(self.db, self.challenge_id, 'alice', 2)
        alice_part = next(p for p in result['participants'] if p['username'] == 'alice')
        self.assertTrue(alice_part['completed'])

    def test_cancel_challenge_by_creator(self):
        ok = database.cancel_achievement_challenge(self.db, self.challenge_id, 'alice')
        self.assertTrue(ok)
        result = database.get_achievement_challenge(self.db, self.challenge_id)
        self.assertEqual(result['status'], 'cancelled')

    def test_cancel_challenge_by_non_creator_fails(self):
        ok = database.cancel_achievement_challenge(self.db, self.challenge_id, 'bob')
        self.assertFalse(ok)

    def test_cancel_unknown_challenge_returns_false(self):
        self.assertFalse(
            database.cancel_achievement_challenge(self.db, 'nope', 'alice'))


# ===========================================================================
# get_achievement_challenges / get_achievement_challenge
# ===========================================================================

class TestGetAchievementChallenges(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.alice = _create_user(self.db, 'alice')
        self.bob = _create_user(self.db, 'bob')

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_empty(self):
        self.assertEqual(database.get_achievement_challenges(None, 'alice'), [])

    def test_unknown_user_returns_empty(self):
        self.assertEqual(database.get_achievement_challenges(self.db, 'nobody'), [])

    def test_returns_created_challenges(self):
        database.create_achievement_challenge(self.db, 'alice', 'T1', '620', 'G')
        result = database.get_achievement_challenges(self.db, 'alice')
        self.assertEqual(len(result), 1)

    def test_returns_joined_challenges(self):
        challenge = database.create_achievement_challenge(self.db, 'alice', 'T', '620', 'G')
        database.join_achievement_challenge(self.db, challenge['id'], 'bob')
        result = database.get_achievement_challenges(self.db, 'bob')
        self.assertEqual(len(result), 1)

    def test_no_duplicates_for_creator(self):
        database.create_achievement_challenge(self.db, 'alice', 'T', '620', 'G')
        # Alice is both creator and participant — should appear once
        result = database.get_achievement_challenges(self.db, 'alice')
        ids = [c['id'] for c in result]
        self.assertEqual(len(ids), len(set(ids)))

    def test_get_challenge_by_id(self):
        c = database.create_achievement_challenge(self.db, 'alice', 'T', '620', 'G')
        result = database.get_achievement_challenge(self.db, c['id'])
        self.assertEqual(result['id'], c['id'])

    def test_get_unknown_challenge_returns_empty(self):
        self.assertEqual(database.get_achievement_challenge(self.db, 'nope'), {})


# ===========================================================================
# GraphQL schema execution
# ===========================================================================

class TestGraphQLSchema(unittest.TestCase):

    def setUp(self):
        try:
            import graphene  # noqa: F401
            self._graphene_available = True
        except ImportError:
            self._graphene_available = False

    def _exec(self, query, context=None):
        """Build schema and execute a query."""
        import graphene

        # Minimal stand-in that doesn't hit the DB
        class GameType(graphene.ObjectType):
            app_id = graphene.String()
            name = graphene.String()
            platform = graphene.String()
            playtime_hours = graphene.Float()

        class StatsType(graphene.ObjectType):
            total_games = graphene.Int()
            total_playtime = graphene.Float()

        class Query(graphene.ObjectType):
            games = graphene.List(GameType)
            stats = graphene.Field(StatsType)

            def resolve_games(root, info):
                return [GameType(app_id='620', name='Portal 2',
                                 platform='steam', playtime_hours=3.5)]

            def resolve_stats(root, info):
                return StatsType(total_games=1, total_playtime=3.5)

        schema = graphene.Schema(query=Query)
        return schema.execute(query, context=context or {})

    def test_graphene_importable(self):
        self.assertTrue(self._graphene_available, "graphene not installed")

    def test_query_games(self):
        if not self._graphene_available:
            self.skipTest("graphene not installed")
        result = self._exec('{ games { appId name platform playtimeHours } }')
        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data['games']), 1)
        self.assertEqual(result.data['games'][0]['name'], 'Portal 2')

    def test_query_stats(self):
        if not self._graphene_available:
            self.skipTest("graphene not installed")
        result = self._exec('{ stats { totalGames totalPlaytime } }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['stats']['totalGames'], 1)

    def test_introspection_typename(self):
        if not self._graphene_available:
            self.skipTest("graphene not installed")
        result = self._exec('{ __typename }')
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['__typename'], 'Query')

    def test_invalid_query_returns_errors(self):
        if not self._graphene_available:
            self.skipTest("graphene not installed")
        result = self._exec('{ nonExistentField }')
        self.assertIsNotNone(result.errors)

    def test_empty_query_returns_errors(self):
        if not self._graphene_available:
            self.skipTest("graphene not installed")
        result = self._exec('{ }')
        self.assertIsNotNone(result.errors)


# ===========================================================================
# OpenAPI spec — new paths
# ===========================================================================

class TestOpenAPINewPaths(unittest.TestCase):

    def setUp(self):
        self.spec = build_spec()
        self.paths = self.spec['paths']

    def test_challenge_list_create_present(self):
        self.assertIn('/api/achievement-challenges', self.paths)

    def test_challenge_has_get_and_post(self):
        methods = self.paths['/api/achievement-challenges']
        self.assertIn('get', methods)
        self.assertIn('post', methods)

    def test_challenge_detail_present(self):
        self.assertIn('/api/achievement-challenges/{challenge_id}', self.paths)

    def test_challenge_join_present(self):
        self.assertIn('/api/achievement-challenges/{challenge_id}/join', self.paths)

    def test_challenge_progress_present(self):
        self.assertIn('/api/achievement-challenges/{challenge_id}/progress', self.paths)

    def test_graphql_endpoint_present(self):
        self.assertIn('/api/graphql', self.paths)

    def test_graphql_is_post(self):
        self.assertIn('post', self.paths['/api/graphql'])

    def test_achievement_stats_has_by_platform(self):
        props = (
            self.paths['/api/achievements/stats']['get']['responses']['200']
            ['content']['application/json']['schema']['properties']
        )
        self.assertIn('by_platform', props)

    def test_spec_is_json_serialisable(self):
        json.dumps(self.spec)

    def test_total_paths_count(self):
        self.assertGreaterEqual(len(self.paths), 90)

    def test_graphql_tag_in_tags_list(self):
        tag_names = [t['name'] for t in self.spec.get('tags', [])]
        self.assertIn('graphql', tag_names)


if __name__ == '__main__':
    unittest.main()
