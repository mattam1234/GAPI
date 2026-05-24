#!/usr/bin/env python3
"""
Tests for persistent Discord-linked live session helpers.

Run with:
    python -m pytest tests/test_linked_discord_sessions.py
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import discord_bot
import gapi_gui


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id
        self.sent_messages = []

    async def create_dm(self):
        return self

    async def send(self, message: str):
        self.sent_messages.append(message)


class LinkedDiscordSessionTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        database.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _make_session(self):
        db = self.Session()
        try:
            session = database.create_linked_pick_session(
                db=db,
                session_id='sess-1',
                host_username='host',
                host_discord_id='100',
                name='Linked session',
                discord_location={
                    'guild_id': '1',
                    'guild_name': 'Guild One',
                    'channel_id': '10',
                    'channel_name': 'game-night',
                },
                coop_only=True,
            )
            self.assertIsNotNone(session)
        finally:
            db.close()

    def test_discord_location_cache_filters_to_member_guilds(self):
        db = self.Session()
        try:
            ok = database.refresh_discord_location_cache(db, [
                {
                    'guild_id': '1',
                    'name': 'Guild One',
                    'icon_url': '',
                    'channels': [{'channel_id': '10', 'name': 'general', 'channel_type': 'text', 'can_send': True}],
                    'members': [{'discord_user_id': '42', 'display_name': 'Alice'}],
                },
                {
                    'guild_id': '2',
                    'name': 'Guild Two',
                    'icon_url': '',
                    'channels': [{'channel_id': '20', 'name': 'lfg', 'channel_type': 'text', 'can_send': True}],
                    'members': [{'discord_user_id': '99', 'display_name': 'Bob'}],
                },
            ])
            self.assertTrue(ok)
            locations = database.list_discord_locations_for_user(db, '42')
        finally:
            db.close()

        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0]['guild_id'], '1')
        self.assertEqual(locations[0]['channels'][0]['channel_id'], '10')

    def test_complete_pending_join_adds_participant(self):
        self._make_session()
        db = self.Session()
        try:
            db.add(database.User(
                username='alice',
                password='hash',
                steam_id='76561190000000001',
                discord_id='42',
            ))
            db.commit()
            pending = database.upsert_pending_discord_session_join(db, 'sess-1', '42', 'Join me')
            self.assertIsNotNone(pending)
            joined = database.complete_pending_discord_session_joins_for_user(db, '42', 'alice')
            session = database.get_linked_pick_session(db, 'sess-1')
            view = database.linked_pick_session_to_dict(db, session)
        finally:
            db.close()

        self.assertEqual(joined, ['sess-1'])
        self.assertIn('alice', view['participants'])
        self.assertEqual(view['pending_joins'][0]['status'], 'completed')

    def test_discord_locations_api_returns_cached_guilds(self):
        db = self.Session()
        try:
            database.refresh_discord_location_cache(db, [{
                'guild_id': '1',
                'name': 'Guild One',
                'icon_url': '',
                'channels': [{'channel_id': '10', 'name': 'general', 'channel_type': 'text', 'can_send': True}],
                'members': [{'discord_user_id': '42', 'display_name': 'Alice'}],
            }])
        finally:
            db.close()

        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        client = gapi_gui.app.test_client()
        with client.session_transaction() as sess:
            sess['username'] = 'alice'
        with patch.object(gapi_gui, 'DB_AVAILABLE', True), \
             patch.object(gapi_gui, 'ensure_db_available', return_value=True), \
             patch.object(gapi_gui.database, 'SessionLocal', self.Session), \
             patch.object(gapi_gui, '_get_current_user_record', return_value={
                 'username': 'alice',
                 'discord_id': '42',
                 'steam_id': '76561190000000001',
             }):
            resp = client.get('/api/live-session/discord-locations')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data['guilds']), 1)
        self.assertEqual(data['guilds'][0]['guild_id'], '1')


class TestDiscordBotLinkedSessionHelpers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        database.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        try:
            database.create_linked_pick_session(
                db=db,
                session_id='sess-1',
                host_username='host',
                host_discord_id='100',
                name='Linked session',
                discord_location={
                    'guild_id': '1',
                    'guild_name': 'Guild One',
                    'channel_id': '10',
                    'channel_name': 'game-night',
                },
                coop_only=False,
            )
        finally:
            db.close()

        self.bot = object.__new__(discord_bot.GAPIBot)
        self.bot.user_mappings = {42: '76561190000000001'}
        self.bot.multi_picker = SimpleNamespace(users=[
            {'name': 'alice', 'steam_id': '76561190000000001'}
        ])
        self.bot.app_url = 'http://localhost:5000'
        self.bot._db_session = lambda: self.Session()

    def tearDown(self):
        self.engine.dispose()

    async def test_set_linked_session_membership_adds_linked_user(self):
        user = _FakeUser(42)
        view = await self.bot._set_linked_session_membership('sess-1', user, True)
        self.assertIsNotNone(view)
        self.assertIn('alice', view['participants'])

    async def test_unlinked_join_creates_pending_request_and_dm(self):
        user = _FakeUser(99)
        view = await self.bot._set_linked_session_membership('sess-1', user, True)
        self.assertIsNotNone(view)
        db = self.Session()
        try:
            pending = database.list_pending_discord_session_joins(db, 'sess-1', active_only=True)
        finally:
            db.close()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].discord_user_id, '99')
        self.assertTrue(user.sent_messages)

    def test_linked_session_embed_includes_participant_count(self):
        embed = self.bot._build_linked_session_embed({
            'session_id': 'sess-1',
            'name': 'Linked session',
            'host': 'host',
            'status': 'awaiting_vote',
            'participants': ['host', 'alice'],
            'pending_joins': [{'discord_user_id': '99', 'status': 'pending', 'expires_at': 'soon'}],
            'picked_game': {'name': 'Portal 2'},
            'round': 2,
            'vote_state': {'yes_count': 1, 'no_count': 0, 'required_for_majority': 2},
            'discord': {'guild_name': 'Guild One', 'channel_name': 'game-night'},
        })
        self.assertIn('Joined', [field.name for field in embed.fields])
        self.assertIn('Participants', [field.name for field in embed.fields])

