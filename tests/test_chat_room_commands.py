#!/usr/bin/env python3
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestChatRoomCommands(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        self.gui = gapi_gui
        self.gui.live_sessions.clear()
        self.gui.chat_room_active_session.clear()
        self.gui.chat_rooms.clear()
        self.gui.chat_rooms['general'] = {
            'room': 'general',
            'owner': None,
            'is_private': False,
            'members': set(),
            'invites': set(),
            'created_at': datetime.utcnow(),
        }

    def test_private_room_requires_invite_to_join(self):
        create = self.gui._handle_chat_command(None, 'alice', 'general', '/room create squad private')
        self.assertTrue(create['ok'])
        self.assertTrue(self.gui.chat_rooms['squad']['is_private'])

        join = self.gui._handle_chat_command(None, 'bob', 'general', '/room join squad')
        self.assertFalse(join['ok'])
        self.assertEqual(join['status'], 403)

    def test_private_room_invite_allows_join(self):
        self.gui._handle_chat_command(None, 'alice', 'general', '/room create-private duo')
        invite = self.gui._handle_chat_command(None, 'alice', 'general', '/room invite bob duo')
        self.assertTrue(invite['ok'])

        join = self.gui._handle_chat_command(None, 'bob', 'general', '/room join duo')
        self.assertTrue(join['ok'])
        self.assertIn('bob', self.gui.chat_rooms['duo']['members'])

    def test_picker_sessions_are_room_scoped(self):
        start_team = self.gui._handle_chat_command(None, 'alice', 'team', '/picker start')
        self.assertTrue(start_team['ok'])
        start_general = self.gui._handle_chat_command(None, 'carol', 'general', '/picker start')
        self.assertTrue(start_general['ok'])

        self.assertIn('team', self.gui.chat_room_active_session)
        self.assertIn('general', self.gui.chat_room_active_session)
        self.assertNotEqual(
            self.gui.chat_room_active_session['team'],
            self.gui.chat_room_active_session['general']
        )

        join_team = self.gui._handle_chat_command(None, 'bob', 'team', '/picker join')
        self.assertTrue(join_team['ok'])
        session_id = self.gui.chat_room_active_session['team']
        session = self.gui.live_sessions[session_id]
        self.assertIn('bob', session['participants'])


if __name__ == '__main__':
    unittest.main()