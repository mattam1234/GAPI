#!/usr/bin/env python3
"""Unit tests for Discord /link account validation logic."""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
import discord_bot


class _FakeMultiPicker:
    def __init__(self):
        self.users = []

    def add_user(self, name, steam_id="", email="", discord_id="", **kwargs):
        self.users.append({
            'name': name,
            'discord_id': discord_id,
            'platforms': {'steam': steam_id},
        })
        return True

    def save_users(self):
        return None


class TestDiscordBotLinkCommand(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        database.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        self.bot = object.__new__(discord_bot.GAPIBot)
        self.bot.user_mappings = {}
        self.bot.multi_picker = _FakeMultiPicker()
        self.bot._db_session = lambda: self.Session()

    def tearDown(self):
        self.engine.dispose()

    def _seed_user(self, username='alice', steam_id='76561190000000001', discord_id=None):
        db = self.Session()
        try:
            db.add(database.User(
                username=username,
                password='hash',
                steam_id=steam_id,
                discord_id=discord_id,
            ))
            db.commit()
        finally:
            db.close()

    def _get_user(self, username):
        db = self.Session()
        try:
            return database.get_user_by_username(db, username)
        finally:
            db.close()

    def test_link_requires_existing_gapi_username(self):
        success, message = self.bot._link_discord_account(42, 'missing-user', None)
        self.assertFalse(success)
        self.assertIn('was not found', message)

    def test_link_rejects_already_linked_username(self):
        self._seed_user(username='alice', discord_id='123')
        success, message = self.bot._link_discord_account(42, 'alice', None)
        self.assertFalse(success)
        self.assertIn('already linked to another Discord account', message)

    def test_link_requires_steam_when_not_saved(self):
        self._seed_user(username='alice', steam_id=None)
        success, message = self.bot._link_discord_account(42, 'alice', None)
        self.assertFalse(success)
        self.assertIn('No Steam ID is saved', message)

    def test_link_uses_saved_steam_id_when_optional_param_missing(self):
        self._seed_user(username='alice', steam_id='76561190000000001')
        success, message = self.bot._link_discord_account(42, 'alice', None)
        self.assertTrue(success)
        self.assertIn('Linked', message)
        self.assertEqual(self.bot.user_mappings[42], '76561190000000001')
        self.assertEqual(self._get_user('alice').discord_id, '42')
        self.assertEqual(len(self.bot.multi_picker.users), 1)
        self.assertEqual(self.bot.multi_picker.users[0]['name'], 'alice')

    def test_link_accepts_optional_steam_override(self):
        self._seed_user(username='alice', steam_id=None)
        success, _ = self.bot._link_discord_account(42, 'alice', '76561190000000077')
        self.assertTrue(success)
        user = self._get_user('alice')
        self.assertEqual(user.discord_id, '42')
        self.assertEqual(user.steam_id, '76561190000000077')
        self.assertEqual(self.bot.user_mappings[42], '76561190000000077')


if __name__ == '__main__':
    unittest.main()
