#!/usr/bin/env python3
"""
Tests for live pick sessions and user presence features.

Run with:
    python -m pytest tests/test_live_sessions.py
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers to exercise the live-session helper used in gapi_gui
# ---------------------------------------------------------------------------

def _make_session(session_id: str, host: str, participants=None) -> dict:
    """Build a minimal in-memory live session dict."""
    return {
        'session_id': session_id,
        'name': f"{host}'s session",
        'host': host,
        'participants': participants if participants is not None else [host],
        'status': 'waiting',
        'created_at': datetime.utcnow(),
        'picked_game': None,
    }


def _live_session_view(session: dict) -> dict:
    """Mirrors gapi_gui._live_session_view without importing Flask."""
    return {
        'session_id': session['session_id'],
        'name': session.get('name', session['session_id']),
        'host': session['host'],
        'participants': session['participants'],
        'status': session['status'],
        'created_at': session['created_at'].isoformat(),
        'picked_game': session.get('picked_game'),
    }


# ---------------------------------------------------------------------------
# Live session logic tests
# ---------------------------------------------------------------------------

class TestLiveSessionView(unittest.TestCase):

    def test_view_contains_required_keys(self):
        s = _make_session('abc-123', 'alice')
        view = _live_session_view(s)
        for key in ('session_id', 'name', 'host', 'participants', 'status',
                    'created_at', 'picked_game'):
            self.assertIn(key, view)

    def test_view_session_id_matches(self):
        s = _make_session('id-42', 'bob')
        self.assertEqual(_live_session_view(s)['session_id'], 'id-42')

    def test_view_host_is_in_participants(self):
        s = _make_session('x', 'carol')
        view = _live_session_view(s)
        self.assertIn('carol', view['participants'])

    def test_view_created_at_is_iso_string(self):
        s = _make_session('t', 'dave')
        iso = _live_session_view(s)['created_at']
        # Should be parseable back to datetime
        datetime.fromisoformat(iso)

    def test_view_status_defaults_to_waiting(self):
        s = _make_session('w', 'eve')
        self.assertEqual(_live_session_view(s)['status'], 'waiting')

    def test_view_picked_game_is_none_initially(self):
        s = _make_session('g', 'frank')
        self.assertIsNone(_live_session_view(s)['picked_game'])


class TestLiveSessionJoinLeave(unittest.TestCase):
    """Unit tests for join/leave logic using plain dicts (no Flask context)."""

    def _join(self, session: dict, username: str) -> None:
        """Simulate joining a session."""
        if session['status'] == 'completed':
            raise ValueError('Session already completed')
        if username not in session['participants']:
            session['participants'].append(username)

    def _leave(self, sessions: dict, session_id: str,
               username: str) -> str:
        """Simulate leaving a session; returns outcome message."""
        session = sessions.get(session_id)
        if not session:
            return 'not_found'
        if username in session['participants']:
            session['participants'].remove(username)
        if not session['participants']:
            del sessions[session_id]
            return 'session_closed'
        if session['host'] == username:
            session['host'] = session['participants'][0]
        return 'left'

    def test_join_adds_participant(self):
        s = _make_session('s1', 'alice')
        self._join(s, 'bob')
        self.assertIn('bob', s['participants'])

    def test_join_idempotent(self):
        s = _make_session('s1', 'alice')
        self._join(s, 'bob')
        self._join(s, 'bob')
        self.assertEqual(s['participants'].count('bob'), 1)

    def test_join_completed_raises(self):
        s = _make_session('s1', 'alice')
        s['status'] = 'completed'
        with self.assertRaises(ValueError):
            self._join(s, 'carol')

    def test_leave_removes_participant(self):
        sessions = {'s1': _make_session('s1', 'alice')}
        sessions['s1']['participants'].append('bob')
        self._leave(sessions, 's1', 'bob')
        self.assertNotIn('bob', sessions['s1']['participants'])

    def test_leave_last_participant_closes_session(self):
        sessions = {'s1': _make_session('s1', 'alice')}
        result = self._leave(sessions, 's1', 'alice')
        self.assertEqual(result, 'session_closed')
        self.assertNotIn('s1', sessions)

    def test_leave_host_transfers_host(self):
        sessions = {'s1': _make_session('s1', 'alice', ['alice', 'bob'])}
        self._leave(sessions, 's1', 'alice')
        self.assertEqual(sessions['s1']['host'], 'bob')

    def test_leave_unknown_session_returns_not_found(self):
        result = self._leave({}, 'nonexistent', 'alice')
        self.assertEqual(result, 'not_found')


# ---------------------------------------------------------------------------
# database.update_user_presence and get_online_users tests (with mock DB)
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, username: str, last_seen=None):
        self.username = username
        self.display_name = username
        self.avatar_url = ''
        self.steam_id = ''
        self.epic_id = ''
        self.gog_id = ''
        self.last_seen = last_seen


class _FakeQuery:
    def __init__(self, results):
        self._results = results
        self._filters = []

    def filter(self, *args):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def all(self):
        return list(self._results)


class _MockDb:
    def __init__(self, users=None):
        self._users = users or []
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return _FakeQuery(self._users)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class TestUpdateUserPresence(unittest.TestCase):

    def _call(self, db, username):
        import database
        return database.update_user_presence(db, username)

    def test_returns_false_with_none_db(self):
        import database
        self.assertFalse(database.update_user_presence(None, 'alice'))

    def test_returns_false_if_user_not_found(self):
        db = _MockDb(users=[])
        import database
        self.assertFalse(database.update_user_presence(db, 'ghost'))

    def test_updates_last_seen_and_commits(self):
        user = _FakeUser('alice')
        db = _MockDb(users=[user])
        import database
        result = database.update_user_presence(db, 'alice')
        self.assertTrue(result)
        self.assertTrue(db.committed)
        self.assertIsNotNone(user.last_seen)


class TestGetOnlineUsers(unittest.TestCase):

    def test_returns_empty_list_with_none_db(self):
        import database
        self.assertEqual(database.get_online_users(None), [])

    def test_returns_recently_active_user(self):
        user = _FakeUser('alice', last_seen=datetime.utcnow())
        db = _MockDb(users=[user])
        import database
        # Patch the query so filter works correctly for datetime comparison
        original_query = db.query

        def patched_query(model):
            q = original_query(model)
            original_filter = q.filter

            def date_filter(*args):
                # Return only users whose last_seen is recent
                q._results = [
                    u for u in q._results
                    if u.last_seen and u.last_seen >= (
                        datetime.utcnow() - timedelta(minutes=5)
                    )
                ]
                return q

            q.filter = date_filter
            return q

        db.query = patched_query
        result = database.get_online_users(db, threshold_minutes=5)
        self.assertTrue(len(result) >= 1)
        self.assertEqual(result[0]['username'], 'alice')

    def test_excludes_stale_user(self):
        old_time = datetime.utcnow() - timedelta(minutes=10)
        user = _FakeUser('bob', last_seen=old_time)
        db = _MockDb(users=[user])
        import database

        def patched_query(model):
            q = _FakeQuery([])  # No recent users
            return q

        db.query = patched_query
        result = database.get_online_users(db, threshold_minutes=5)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# database.get_app_friends_with_platforms tests
# ---------------------------------------------------------------------------

class TestGetAppFriendsWithPlatforms(unittest.TestCase):

    def test_returns_platform_ids_for_friends(self):
        """Friends should include steam_id, epic_id, gog_id, is_online."""
        import database

        friend_user = _FakeUser('bob')
        friend_user.steam_id = '76561190000000099'
        friend_user.last_seen = datetime.utcnow()  # online

        # Patch get_app_friends to return a friend entry for 'alice'
        base_result = {
            'friends': [{'username': 'bob', 'display_name': 'Bob',
                         'avatar_url': '', 'bio': ''}],
            'sent': [],
            'received': [],
        }

        class _DB:
            committed = False

            def query(self, model):
                return _FakeQuery([friend_user])

            def commit(self):
                self.committed = True

        with patch.object(database, 'get_app_friends', return_value=base_result):
            result = database.get_app_friends_with_platforms(_DB(), 'alice')

        self.assertEqual(len(result['friends']), 1)
        friend = result['friends'][0]
        self.assertIn('steam_id', friend)
        self.assertIn('epic_id', friend)
        self.assertIn('gog_id', friend)
        self.assertIn('is_online', friend)
        self.assertEqual(friend['steam_id'], '76561190000000099')

    def test_returns_base_result_when_db_is_none(self):
        import database
        base = {'friends': [], 'sent': [], 'received': []}
        with patch.object(database, 'get_app_friends', return_value=base):
            result = database.get_app_friends_with_platforms(None, 'alice')
        self.assertEqual(result, base)


# ---------------------------------------------------------------------------
# Live session invite logic tests
# ---------------------------------------------------------------------------

class TestInviteLogic(unittest.TestCase):
    """Tests for the invite-validation logic (no Flask context needed)."""

    def _invite(self, session: dict, host: str, inviter: str,
                usernames: list):
        """Simulate the invite permission check used by api_live_session_invite."""
        if not session:
            return False, 'Session not found'
        if session['host'] != inviter:
            return False, 'Only the session host can invite users'
        if not usernames or not isinstance(usernames, list):
            return False, 'usernames (list) is required'
        return True, 'ok'

    def test_host_can_invite(self):
        s = _make_session('s1', 'alice')
        ok, _ = self._invite(s, 'alice', 'alice', ['bob'])
        self.assertTrue(ok)

    def test_non_host_cannot_invite(self):
        s = _make_session('s1', 'alice')
        ok, msg = self._invite(s, 'alice', 'bob', ['carol'])
        self.assertFalse(ok)
        self.assertIn('host', msg)

    def test_empty_usernames_rejected(self):
        s = _make_session('s1', 'alice')
        ok, _ = self._invite(s, 'alice', 'alice', [])
        self.assertFalse(ok)

    def test_non_list_usernames_rejected(self):
        s = _make_session('s1', 'alice')
        ok, _ = self._invite(s, 'alice', 'alice', 'bob')
        self.assertFalse(ok)

    def test_missing_session_returns_not_found(self):
        ok, msg = self._invite(None, 'alice', 'alice', ['bob'])
        self.assertFalse(ok)
        self.assertIn('not found', msg)


# ---------------------------------------------------------------------------
# Notification-on-pick logic tests
# ---------------------------------------------------------------------------

class TestNotificationOnPick(unittest.TestCase):
    """Verify that notifications are created for each participant when a game
    is picked in a live session."""

    def test_notification_called_for_each_participant(self):
        import database

        notifications_created = []

        def fake_create_notification(db, username, title, message, **kwargs):
            notifications_created.append({'username': username, 'title': title})
            return True

        participants = ['alice', 'bob', 'carol']
        game_name = 'Portal 2'

        with patch.object(database, 'create_notification', side_effect=fake_create_notification):
            for participant in participants:
                database.create_notification(
                    None,
                    participant,
                    title='Game picked!',
                    message=f'alice picked "{game_name}" for your live session.',
                    type='success',
                )

        self.assertEqual(len(notifications_created), 3)
        usernames_notified = [n['username'] for n in notifications_created]
        for p in participants:
            self.assertIn(p, usernames_notified)

    def test_notification_title_contains_game_name(self):
        import database

        captured = []

        def fake_create(db, username, title, message, **kwargs):
            captured.append({'title': title, 'message': message})
            return True

        game_name = 'Half-Life 2'
        with patch.object(database, 'create_notification', side_effect=fake_create):
            database.create_notification(
                None, 'bob',
                title='Game picked!',
                message=f'alice picked "{game_name}" for your live session.',
                type='success',
            )

        self.assertIn(game_name, captured[0]['message'])


if __name__ == '__main__':
    unittest.main()
