#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui
from app.repositories.backlog_repository import BacklogRepository
from app.services.backlog_service import BacklogService


def _read(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *parts)
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


class TestBacklogCollectionsMarkup(unittest.TestCase):

    def test_index_merges_playlists_and_backlogs(self):
        content = _read('templates', 'index.html')
        for token in (
            'backlog-selector',
            'backlog-selector-search',
            'backlog-side-panel',
            'backlog-collection-modal',
            'backlog-modal-collection',
            'backlog-library-search',
            'backlog-library-search-results',
            'backlog-library-preview',
            'backlog-library-add-select',
        ):
            self.assertIn(token, content)
        self.assertNotIn('Playlists &amp; Backlogs', content)
        self.assertNotIn('playlists-container', content)
        self.assertNotIn('id="playlists-tab"', content)
        self.assertNotIn('id="nav-playlists"', content)

    def test_main_js_contains_backlog_collection_handlers(self):
        content = _read('static', 'main.js')
        for token in (
            "if (tabName === 'playlists') tabName = 'backlog';",
            'ensureBacklogCollectionsLoaded',
            'filterBacklogCollections',
            'openBacklogCollectionModal',
            'leaveActiveBacklog',
            'loadPlaylists();',
            'loadBacklog();',
        ):
            self.assertIn(token, content)

    def test_style_contains_backlog_layout_classes(self):
        content = _read('static', 'style.css')
        for token in (
            '.backlog-shell',
            '.backlog-selector',
            '.backlog-side-panel',
            '.backlog-preview-grid',
            '.backlog-playlist-card',
            '.backlog-share-list',
        ):
            self.assertIn(token, content)


class TestBacklogCollectionRoutes(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def _fake_picker(self):
        return SimpleNamespace(games=[
            {'game_id': 'steam:620', 'name': 'Portal 2', 'platform': 'steam'},
        ])

    def _service(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return BacklogService(BacklogRepository(os.path.join(temp_dir.name, 'shared-backlogs.json')))

    def test_shared_backlog_is_visible_to_member(self):
        service = self._service()
        with patch.object(gapi_gui, '_shared_backlog_service', service), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            create_resp = self.client.post('/api/backlogs', json={
                'name': 'Weekend Picks',
                'members': ['bob'],
                'is_shared': True,
            })
            self.assertEqual(create_resp.status_code, 201)
            backlog_id = create_resp.get_json()['id']

            status_resp = self.client.post(f'/api/backlog/steam:620', json={
                'status': 'playing',
                'collection_id': backlog_id,
            })
            self.assertEqual(status_resp.status_code, 200)

            with self.client.session_transaction() as sess:
                sess['username'] = 'bob'

            list_resp = self.client.get(f'/api/backlog?collection_id={backlog_id}')
            self.assertEqual(list_resp.status_code, 200)
            data = list_resp.get_json()
            self.assertEqual(data['active_backlog_id'], backlog_id)
            self.assertEqual(len(data['games']), 1)
            self.assertEqual(data['games'][0]['backlog_status'], 'playing')

    def test_member_cannot_delete_but_can_leave_shared_backlog(self):
        service = self._service()
        shared = service.create_collection(
            name='Weekend Picks',
            owner_username='alice',
            members=['bob'],
            is_shared=True,
        )
        with self.client.session_transaction() as sess:
            sess['username'] = 'bob'
        with patch.object(gapi_gui, '_shared_backlog_service', service), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            delete_resp = self.client.delete(f'/api/backlogs/{shared["id"]}')
            self.assertEqual(delete_resp.status_code, 403)

            leave_resp = self.client.post(f'/api/backlogs/{shared["id"]}/leave')
            self.assertEqual(leave_resp.status_code, 200)

            list_resp = self.client.get('/api/backlogs')
            data = list_resp.get_json()
            self.assertNotIn(shared['id'], [backlog['id'] for backlog in data['backlogs']])

    def test_backlog_listing_includes_entry_and_invited_counts(self):
        service = self._service()
        with patch.object(gapi_gui, '_shared_backlog_service', service), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            create_resp = self.client.post('/api/backlogs', json={
                'name': 'Weekend Picks',
                'members': ['bob'],
                'is_shared': True,
            })
            self.assertEqual(create_resp.status_code, 201)
            backlog_id = create_resp.get_json()['id']
            status_resp = self.client.post('/api/backlog/steam:620', json={
                'status': 'want_to_play',
                'collection_id': backlog_id,
            })
            self.assertEqual(status_resp.status_code, 200)

            list_resp = self.client.get('/api/backlogs')
            self.assertEqual(list_resp.status_code, 200)
            payload = list_resp.get_json()
            shared = next(item for item in payload['backlogs'] if item['id'] == backlog_id)
            self.assertEqual(shared['entry_count'], 1)
            self.assertEqual(shared['invited_count'], 1)

    def test_backlog_listing_resolves_plain_app_id_entries(self):
        service = self._service()
        with patch.object(gapi_gui, '_shared_backlog_service', service), \
                patch.object(gapi_gui, 'ensure_picker_initialized', return_value=self._fake_picker()):
            status_resp = self.client.post('/api/backlog/620', json={
                'status': 'want_to_play',
            })
            self.assertEqual(status_resp.status_code, 200)

            list_resp = self.client.get('/api/backlog')
            self.assertEqual(list_resp.status_code, 200)
            payload = list_resp.get_json()
            self.assertEqual(len(payload['games']), 1)
            self.assertEqual(payload['games'][0]['game_id'], 'steam:620')
            self.assertEqual(payload['games'][0]['backlog_status'], 'want_to_play')

    def test_library_demo_payload_includes_composite_game_id(self):
        with patch.object(gapi_gui, 'ensure_db_available', return_value=False):
            response = self.client.get('/api/library')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['games'])
        first = data['games'][0]
        self.assertIn('game_id', first)
        self.assertTrue(str(first['game_id']).startswith('steam:'))


if __name__ == '__main__':
    unittest.main()
