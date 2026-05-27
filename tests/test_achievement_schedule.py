#!/usr/bin/env python3
"""
Tests for achievement stats, iCal schedule export, ignored-games endpoint,
and achievement rarity filter on the game picker.

Run with:
    python -m pytest tests/test_achievement_schedule.py
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import gapi_gui
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


def _read(*parts):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *parts), 'r', encoding='utf-8') as handle:
        return handle.read()


def _add_achievement(db, user, app_id='620', game_name='Portal 2',
                     achievement_id='ACH1', name='Win',
                     unlocked=False, rarity=None):
    a = database.Achievement(
        user_id=user.id, app_id=app_id, game_name=game_name,
        achievement_id=achievement_id, achievement_name=name,
        unlocked=unlocked, rarity=rarity,
    )
    db.add(a)
    db.commit()
    return a


# ===========================================================================
# get_achievement_stats
# ===========================================================================

class TestGetAchievementStats(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_empty(self):
        self.assertEqual(database.get_achievement_stats(None, 'alice'), {})

    def test_unknown_user_returns_empty(self):
        self.assertEqual(database.get_achievement_stats(self.db, 'nobody'), {})

    def test_no_achievements_returns_zero_counts(self):
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertEqual(result['total_tracked'], 0)
        self.assertEqual(result['total_unlocked'], 0)
        self.assertEqual(result['completion_percent'], 0.0)
        self.assertIsNone(result['rarest_achievement'])
        self.assertEqual(result['games'], [])

    def test_counts_and_completion(self):
        _add_achievement(self.db, self.user, achievement_id='A1', unlocked=True)
        _add_achievement(self.db, self.user, achievement_id='A2', unlocked=False)
        _add_achievement(self.db, self.user, achievement_id='A3', unlocked=True)
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertEqual(result['total_tracked'], 3)
        self.assertEqual(result['total_unlocked'], 2)
        self.assertAlmostEqual(result['completion_percent'], 66.7, places=1)

    def test_rarest_achievement_selected_by_min_rarity(self):
        _add_achievement(self.db, self.user, achievement_id='A1', rarity=50.0)
        _add_achievement(self.db, self.user, achievement_id='A2', rarity=2.5)
        _add_achievement(self.db, self.user, achievement_id='A3', rarity=90.0)
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertIsNotNone(result['rarest_achievement'])
        self.assertEqual(result['rarest_achievement']['achievement_id'], 'A2')
        self.assertAlmostEqual(result['rarest_achievement']['rarity'], 2.5)

    def test_rarest_achievement_none_when_no_rarity_data(self):
        _add_achievement(self.db, self.user, achievement_id='A1', rarity=None)
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertIsNone(result['rarest_achievement'])

    def test_games_sorted_alphabetically(self):
        _add_achievement(self.db, self.user, app_id='400', game_name='Zelda', achievement_id='Z1')
        _add_achievement(self.db, self.user, app_id='100', game_name='Alchemy', achievement_id='A1')
        result = database.get_achievement_stats(self.db, 'alice')
        names = [g['game_name'] for g in result['games']]
        self.assertEqual(names, sorted(names))

    def test_per_game_completion_percent(self):
        _add_achievement(self.db, self.user, achievement_id='A1', unlocked=True)
        _add_achievement(self.db, self.user, achievement_id='A2', unlocked=False)
        result = database.get_achievement_stats(self.db, 'alice')
        game = result['games'][0]
        self.assertEqual(game['total'], 2)
        self.assertEqual(game['unlocked'], 1)
        self.assertAlmostEqual(game['completion_percent'], 50.0)

    def test_per_game_rarest_rarity(self):
        _add_achievement(self.db, self.user, achievement_id='A1', rarity=10.0)
        _add_achievement(self.db, self.user, achievement_id='A2', rarity=1.0)
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertAlmostEqual(result['games'][0]['rarest_rarity'], 1.0)

    def test_per_game_rarest_rarity_none_when_missing(self):
        _add_achievement(self.db, self.user, achievement_id='A1', rarity=None)
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertIsNone(result['games'][0]['rarest_rarity'])

    def test_multiple_games(self):
        _add_achievement(self.db, self.user, app_id='620', game_name='Portal 2',
                         achievement_id='A1')
        _add_achievement(self.db, self.user, app_id='440', game_name='TF2',
                         achievement_id='B1')
        result = database.get_achievement_stats(self.db, 'alice')
        self.assertEqual(len(result['games']), 2)

    def test_result_is_json_serialisable(self):
        _add_achievement(self.db, self.user, rarity=5.0)
        result = database.get_achievement_stats(self.db, 'alice')
        json.dumps(result)  # must not raise


# ===========================================================================
# get_games_with_rare_achievements
# ===========================================================================

class TestGetGamesWithRareAchievements(unittest.TestCase):

    def setUp(self):
        self.db = _make_session()
        self.user = _create_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_none_db_returns_empty(self):
        self.assertEqual(database.get_games_with_rare_achievements(None, 'alice'), [])

    def test_unknown_user_returns_empty(self):
        self.assertEqual(database.get_games_with_rare_achievements(self.db, 'nobody'), [])

    def test_returns_app_id_for_locked_achievement_in_range(self):
        _add_achievement(self.db, self.user, app_id='620', rarity=3.0, unlocked=False)
        result = database.get_games_with_rare_achievements(self.db, 'alice', max_rarity=5.0)
        self.assertIn('620', result)

    def test_excludes_locked_achievement_outside_range(self):
        _add_achievement(self.db, self.user, app_id='620', rarity=50.0, unlocked=False)
        result = database.get_games_with_rare_achievements(self.db, 'alice', max_rarity=5.0)
        self.assertNotIn('620', result)

    def test_excludes_unlocked_achievement_even_if_in_range(self):
        _add_achievement(self.db, self.user, app_id='620', rarity=1.0, unlocked=True)
        result = database.get_games_with_rare_achievements(self.db, 'alice', max_rarity=5.0)
        self.assertNotIn('620', result)

    def test_excludes_achievement_with_no_rarity(self):
        _add_achievement(self.db, self.user, app_id='620', rarity=None, unlocked=False)
        result = database.get_games_with_rare_achievements(self.db, 'alice', max_rarity=5.0)
        self.assertNotIn('620', result)

    def test_min_rarity_lower_bound(self):
        _add_achievement(self.db, self.user, app_id='620', rarity=2.0, unlocked=False)
        _add_achievement(self.db, self.user, app_id='440', rarity=30.0, unlocked=False)
        result = database.get_games_with_rare_achievements(
            self.db, 'alice', min_rarity=10.0, max_rarity=50.0)
        self.assertIn('440', result)
        self.assertNotIn('620', result)

    def test_no_duplicates_in_result(self):
        # Two achievements from same game, both in range
        _add_achievement(self.db, self.user, app_id='620', achievement_id='A1',
                         rarity=2.0, unlocked=False)
        _add_achievement(self.db, self.user, app_id='620', achievement_id='A2',
                         rarity=3.0, unlocked=False)
        result = database.get_games_with_rare_achievements(self.db, 'alice', max_rarity=5.0)
        self.assertEqual(result.count('620'), 1)


# ===========================================================================
# iCalendar schedule export (pure Python generation)
# ===========================================================================

class TestICalScheduleExport(unittest.TestCase):
    """Tests the iCal generation logic independently from Flask."""

    def _generate_ical(self, events):
        """Replicate the VCALENDAR generation used in api_export_schedule_ics."""
        lines = [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//GAPI//Game Night Schedule//EN',
            'CALSCALE:GREGORIAN',
            'METHOD:PUBLISH',
        ]
        for ev in events:
            date_str = ev.get('date', '')
            time_str = ev.get('time', '00:00')
            dtstart = ''
            if date_str:
                clean_date = date_str.replace('-', '')
                clean_time = time_str.replace(':', '')
                if len(clean_time) == 4:
                    clean_time += '00'
                dtstart = f'{clean_date}T{clean_time}'
            invitee_names = ev.get('invited_attendees', ev.get('attendees', []))
            invitee_ids = ev.get('invited_attendee_ids', ev.get('attendee_ids', []))
            attendees = ', '.join(invitee_names)
            game_name = ev.get('game_name', '')
            notes = ev.get('notes', '')
            rsvp_statuses = ev.get('rsvp_statuses', {}) if isinstance(ev.get('rsvp_statuses'), dict) else {}
            desc_parts = []
            if game_name:
                desc_parts.append(f'Game: {game_name}')
            if attendees:
                desc_parts.append(f'Attendees: {attendees}')
            if invitee_names:
                rsvp_lines = []
                for index, attendee_name in enumerate(invitee_names):
                    attendee_id = invitee_ids[index] if index < len(invitee_ids) else attendee_name
                    status = rsvp_statuses.get(attendee_id) or rsvp_statuses.get(attendee_name) or 'pending'
                    rsvp_lines.append(f'{attendee_name} ({status})')
                desc_parts.append(f'RSVP: {", ".join(rsvp_lines)}')
            if notes:
                desc_parts.append(notes)
            description = '\\n'.join(desc_parts)
            uid = f"{ev.get('id', 'unknown')}@gapi"
            lines.append('BEGIN:VEVENT')
            lines.append(f'UID:{uid}')
            lines.append(f'SUMMARY:{ev.get("title", "Game Night")}')
            if dtstart:
                lines.append(f'DTSTART:{dtstart}')
            if description:
                lines.append(f'DESCRIPTION:{description}')
            lines.append('END:VEVENT')
        lines.append('END:VCALENDAR')
        return '\r\n'.join(lines) + '\r\n'

    def test_empty_schedule_produces_valid_vcalendar(self):
        ical = self._generate_ical([])
        self.assertIn('BEGIN:VCALENDAR', ical)
        self.assertIn('END:VCALENDAR', ical)
        self.assertNotIn('BEGIN:VEVENT', ical)

    def test_single_event_produces_vevent(self):
        events = [{'id': 'abc123', 'title': 'Game Night', 'date': '2026-03-01',
                   'time': '20:00', 'attendees': ['alice', 'bob'],
                   'game_name': 'Portal 2', 'notes': 'Bring snacks'}]
        ical = self._generate_ical(events)
        self.assertIn('BEGIN:VEVENT', ical)
        self.assertIn('END:VEVENT', ical)
        self.assertIn('SUMMARY:Game Night', ical)

    def test_dtstart_format(self):
        events = [{'id': 'x', 'title': 'T', 'date': '2026-03-15', 'time': '19:30',
                   'attendees': [], 'game_name': '', 'notes': ''}]
        ical = self._generate_ical(events)
        self.assertIn('DTSTART:20260315T193000', ical)

    def test_uid_contains_event_id(self):
        events = [{'id': 'ev42', 'title': 'T', 'date': '', 'time': '',
                   'attendees': [], 'game_name': '', 'notes': ''}]
        ical = self._generate_ical(events)
        self.assertIn('UID:ev42@gapi', ical)

    def test_game_and_attendees_in_description(self):
        events = [{'id': 'x', 'title': 'T', 'date': '2026-03-01', 'time': '20:00',
                   'attendees': ['carol'], 'game_name': 'Hades', 'notes': ''}]
        ical = self._generate_ical(events)
        self.assertIn('Game: Hades', ical)
        self.assertIn('Attendees: carol', ical)

    def test_rsvp_statuses_in_description(self):
        events = [{
            'id': 'x',
            'title': 'T',
            'date': '2026-03-01',
            'time': '20:00',
            'invited_attendees': ['carol', 'dave'],
            'invited_attendee_ids': ['carol', 'dave'],
            'rsvp_statuses': {'carol': 'accepted', 'dave': 'pending'},
        }]
        ical = self._generate_ical(events)
        self.assertIn('RSVP: carol (accepted), dave (pending)', ical)

    def test_multiple_events_produce_multiple_vevents(self):
        events = [
            {'id': 'e1', 'title': 'Night 1', 'date': '2026-03-01', 'time': '20:00',
             'attendees': [], 'game_name': '', 'notes': ''},
            {'id': 'e2', 'title': 'Night 2', 'date': '2026-03-08', 'time': '20:00',
             'attendees': [], 'game_name': '', 'notes': ''},
        ]
        ical = self._generate_ical(events)
        self.assertEqual(ical.count('BEGIN:VEVENT'), 2)

    def test_lines_separated_by_crlf(self):
        ical = self._generate_ical([])
        self.assertIn('\r\n', ical)

    def test_no_empty_dtstart_when_date_missing(self):
        events = [{'id': 'x', 'title': 'T', 'date': '', 'time': '',
                   'attendees': [], 'game_name': '', 'notes': ''}]
        ical = self._generate_ical(events)
        self.assertNotIn('DTSTART:', ical)


# ===========================================================================
# OpenAPI spec — new paths present
# ===========================================================================

class TestOpenAPINewPaths(unittest.TestCase):

    def setUp(self):
        self.spec = build_spec()
        self.paths = self.spec['paths']

    def test_achievement_stats_present(self):
        self.assertIn('/api/achievements/stats', self.paths)

    def test_achievement_stats_is_get(self):
        self.assertIn('get', self.paths['/api/achievements/stats'])

    def test_ignored_games_present(self):
        self.assertIn('/api/ignored-games', self.paths)

    def test_ignored_games_is_get(self):
        self.assertIn('get', self.paths['/api/ignored-games'])

    def test_schedule_ics_export_present(self):
        self.assertIn('/api/schedule/export.ics', self.paths)

    def test_schedule_ics_export_is_get(self):
        self.assertIn('get', self.paths['/api/schedule/export.ics'])

    def test_pick_has_min_rarity_param(self):
        pick_schema = (
            self.paths['/api/pick']['post']['requestBody']
            ['content']['application/json']['schema']
        )
        self.assertIn('min_rarity', pick_schema['properties'])

    def test_pick_has_max_rarity_param(self):
        pick_schema = (
            self.paths['/api/pick']['post']['requestBody']
            ['content']['application/json']['schema']
        )
        self.assertIn('max_rarity', pick_schema['properties'])

    def test_spec_is_json_serialisable(self):
        json.dumps(self.spec)

    def test_total_paths_count(self):
        # Ensure we haven't accidentally removed paths — at least 85
        self.assertGreaterEqual(len(self.paths), 85)


class TestScheduleEnhancementMarkup(unittest.TestCase):

    def test_index_contains_schedule_modal_and_filters(self):
        content = _read('templates', 'index.html')
        for token in (
            'schedule-modal',
            'schedule-collection-modal',
            'schedule-selector-search',
            'schedule-filter-start',
            'schedule-right-rail',
            'schedule-rename-btn',
            'schedule-pending-list',
            'schedule-rsvp-list',
            'schedule-common-games-list',
            'schedule-ical-modal',
            'sch-discord-guild-search',
            'sidebar-user-notif',
        ):
            self.assertIn(token, content)
        self.assertNotIn('<a class="sidebar-item" id="nav-notifications"', content)

    def test_main_js_contains_schedule_modal_handlers(self):
        content = _read('static', 'main.js')
        for token in (
            'filterScheduleCollections',
            'openScheduleCreateModal',
            'openScheduleCollectionModal',
            'openRenameScheduleModal',
            'applyScheduleFilters',
            'setScheduleFiltersToAgendaWeek',
            'updateScheduleRsvpStatus',
            'renderSchedulePendingInvites',
            'submitScheduleRsvp',
            'openScheduleCommonGamePicker',
            'openScheduleIcalSyncModal',
            'showScheduleDiscordGuildSearch',
        ):
            self.assertIn(token, content)
        self.assertNotIn('function createAgendaEvent()', content)

    def test_style_contains_schedule_modal_and_rsvp_classes(self):
        content = _read('static', 'style.css')
        for token in (
            '.schedule-modal',
            '.schedule-sidebar',
            '.schedule-right-rail',
            '.schedule-selector-list',
            '.schedule-form-grid',
            '.schedule-rsvp-row',
            '.schedule-filter-toolbar',
            '.schedule-common-game-item',
            '.schedule-upcoming-list',
            '.sidebar-user-notif',
            '.schedule-attendee-pill',
            '.schedule-rsvp-chip',
        ):
            self.assertIn(token, content)


class TestScheduleIcalSyncRoutes(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def _fake_picker(self):
        return SimpleNamespace(
            schedule_service=SimpleNamespace(
                get_events=lambda **kwargs: [
                    {
                        'id': 'ev1',
                        'title': 'Game Night',
                        'date': '2026-03-15',
                        'time': '20:00',
                        'attendees': ['alice'],
                        'attendee_ids': ['alice'],
                        'rsvp_statuses': {'alice': 'accepted'},
                        'game_name': 'Portal 2',
                        'notes': 'Bring snacks',
                    }
                ]
            )
        )

    def test_sync_info_returns_private_feed_urls(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            resp = self.client.get('/api/schedule/ical-sync-info')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('/api/schedule/export.ics?token=', data['feed_url'])
        self.assertTrue(data['webcal_url'].startswith('webcal'))

    def test_export_ical_accepts_signed_token(self):
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            info_resp = self.client.get('/api/schedule/ical-sync-info')
            token = parse_qs(urlparse(info_resp.get_json()['feed_url']).query)['token'][0]
            resp = self.client.get(f'/api/schedule/export.ics?token={token}&download=0')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('BEGIN:VCALENDAR', resp.get_data(as_text=True))
        self.assertEqual(resp.headers['Content-Type'], 'text/calendar; charset=utf-8')


class TestScheduleSystemdFilesAndDocs(unittest.TestCase):

    def test_systemd_units_exist(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel_path in (
            ('systemd', 'gapi.service'),
            ('systemd', 'gapi-watch.service'),
            ('systemd', 'gapi-watch.path'),
        ):
            self.assertTrue(os.path.exists(os.path.join(root, *rel_path)))

    def test_docs_reference_watch_unit_enable_flow(self):
        readme = _read('README.md')
        self.assertIn('gapi-watch.path', readme)
        self.assertIn('systemctl enable --now gapi.service gapi-watch.path', readme)


class _FakeScheduleService:
    def __init__(self, event):
        self._event = dict(event)
        self.rsvp_updates = []

    def get_event(self, event_id):
        if str(self._event.get('id')) != str(event_id):
            return None
        return dict(self._event)

    def update_event(self, event_id, username=None, **kwargs):
        if str(self._event.get('id')) != str(event_id):
            return None
        self._event.update(kwargs)
        if 'attendees' in kwargs:
            self._event['invited_attendees'] = list(kwargs.get('attendees') or [])
        if 'attendee_ids' in kwargs:
            self._event['invited_attendee_ids'] = list(kwargs.get('attendee_ids') or [])
        return dict(self._event)

    def update_event_rsvp(self, event_id, attendee_identity, status):
        if str(self._event.get('id')) != str(event_id):
            return None
        self.rsvp_updates.append((attendee_identity, status))
        rsvps = dict(self._event.get('rsvp_statuses') or {})
        rsvps[attendee_identity] = status
        self._event['rsvp_statuses'] = rsvps
        invited_names = list(self._event.get('invited_attendees', []))
        invited_ids = list(self._event.get('invited_attendee_ids', []))
        accepted = []
        accepted_ids = []
        pending = []
        pending_ids = []
        for idx, name in enumerate(invited_names):
            attendee_id = invited_ids[idx] if idx < len(invited_ids) else name
            attendee_status = rsvps.get(attendee_id, 'pending')
            if attendee_status == 'accepted':
                accepted.append(name)
                accepted_ids.append(attendee_id)
            if attendee_status == 'pending':
                pending.append(name)
                pending_ids.append(attendee_id)
        self._event['attendees'] = accepted
        self._event['attendee_ids'] = accepted_ids
        self._event['pending_attendees'] = pending
        self._event['pending_attendee_ids'] = pending_ids
        return dict(self._event)


class TestScheduleRsvpPermissionAndFanoutRoutes(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'host'
        self.event = {
            'id': 'ev1',
            'title': 'Game Night',
            'date': '2026-03-15',
            'time': '20:00',
            'created_by': 'host',
            'invited_attendees': ['alice', 'bob'],
            'invited_attendee_ids': ['alice', 'bob'],
            'attendees': [],
            'attendee_ids': [],
            'rsvp_statuses': {'alice': 'pending', 'bob': 'pending'},
        }

    def _picker(self, event=None):
        return SimpleNamespace(schedule_service=_FakeScheduleService(event or self.event))

    def test_creator_cannot_update_rsvp_via_event_put(self):
        picker = self._picker()
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.put('/api/schedule/ev1', json={'rsvp_statuses': {'alice': 'accepted'}})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('/api/schedule/<event_id>/rsvp', resp.get_data(as_text=True))

    def test_invited_user_can_rsvp_for_self_and_triggers_fanout(self):
        picker = self._picker()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            with patch.object(gapi_gui, '_send_schedule_in_app_notifications') as notif_mock:
                with patch.object(gapi_gui, '_send_schedule_discord_dm', return_value=True) as dm_mock:
                    resp = self.client.post('/api/schedule/ev1/rsvp', json={'status': 'accepted'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(picker.schedule_service.rsvp_updates, [('alice', 'accepted')])
        notif_mock.assert_called_once()
        dm_targets = [call.args[0] for call in dm_mock.call_args_list]
        self.assertIn('host', dm_targets)
        self.assertNotIn('alice', dm_targets)

    def test_updating_event_invites_notifies_newly_added_members(self):
        picker = self._picker()
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            with patch.object(gapi_gui, '_send_schedule_in_app_notifications') as notif_mock:
                resp = self.client.put('/api/schedule/ev1', json={
                    'title': 'Game Night',
                    'attendees': ['alice', 'bob', 'carol'],
                    'attendee_ids': ['alice', 'bob', 'carol'],
                })
        self.assertEqual(resp.status_code, 200)
        notif_mock.assert_called_once()
        self.assertIn('carol', notif_mock.call_args.args[0])

    def test_non_member_cannot_rsvp(self):
        picker = self._picker()
        with self.client.session_transaction() as sess:
            sess['username'] = 'mallory'
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=picker):
            resp = self.client.post('/api/schedule/ev1/rsvp', json={'status': 'accepted'})
        self.assertEqual(resp.status_code, 403)


class TestScheduleCommonGamePickerRoutes(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    @staticmethod
    def _fake_picker_with_games():
        return SimpleNamespace(games=[
            {'appid': '620', 'name': 'Portal 2', 'platform': 'steam', 'owners': ['alice']},
            {'appid': '440', 'name': 'Team Fortress 2', 'platform': 'steam', 'owners': ['alice']},
        ])

    def test_common_games_uses_selected_list_when_no_attendees(self):
        class FakeBacklogService:
            def resolve_collection_for_user(self, requested_collection_id, username):
                return requested_collection_id

            def get_games(self, all_games, status=None, username=None, collection_id=None):
                if collection_id == 'list-coop':
                    return [all_games[1]]
                return all_games

        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker_with_games()):
            with patch.object(gapi_gui, '_get_shared_backlog_service', return_value=FakeBacklogService()):
                resp = self.client.post('/api/schedule/common-games', json={
                    'attendees': [],
                    'collection_id': 'list-coop',
                })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['games'][0]['app_id'], '440')
        self.assertEqual(data['collection_id'], 'list-coop')

    def test_random_common_game_uses_selected_list_when_no_attendees(self):
        class FakeBacklogService:
            def resolve_collection_for_user(self, requested_collection_id, username):
                return requested_collection_id

            def get_games(self, all_games, status=None, username=None, collection_id=None):
                if collection_id == 'list-coop':
                    return [all_games[0]]
                return all_games

        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker_with_games()):
            with patch.object(gapi_gui, '_get_shared_backlog_service', return_value=FakeBacklogService()):
                resp = self.client.post('/api/schedule/common-games/random', json={
                    'attendees': [],
                    'collection_id': 'list-coop',
                })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['game']['app_id'], '620')
        self.assertEqual(data['collection_id'], 'list-coop')


if __name__ == '__main__':
    unittest.main()
