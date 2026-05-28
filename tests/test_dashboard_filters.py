#!/usr/bin/env python3
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gapi_gui


def _read(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *parts)
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


class TestDashboardFilterMarkup(unittest.TestCase):

    def test_index_contains_new_filter_controls(self):
        content = _read('templates', 'index.html')
        for token in (
            'library-platform-filter',
            'favorites-search',
            'favorites-platform-filter',
            'backlog-search',
            'backlog-platform-filter',
            'rec-search',
        ):
            self.assertIn(token, content)

    def test_main_js_contains_filter_handlers(self):
        content = _read('static', 'main.js')
        for token in (
            'applyLibraryFilters',
            'applyFavoritesFilters',
            'renderBacklogList',
            'renderRecommendationsList',
            'refresh_seed=',
        ):
            self.assertIn(token, content)

    def test_dashboard_recommendations_refresh_each_render(self):
        content = _read('static', 'main.js')
        self.assertIn("/api/recommendations?count=4&refresh_seed=${Date.now()}", content)


class TestPickerListFilterMarkup(unittest.TestCase):

    def test_index_contains_picker_list_filter_controls(self):
        content = _read('templates', 'index.html')
        for token in (
            'picker-list-filter-search',
            'picker-list-filter-list',
            'Pick from list',
        ):
            self.assertIn(token, content)

    def test_main_js_contains_picker_list_filter_logic(self):
        content = _read('static', 'main.js')
        for token in (
            'refreshPickerListFilters',
            'renderPickerListFilter',
            "body.collection_id = activePickerCollectionId",
            "safeFetch('/api/backlogs')",
        ):
            self.assertIn(token, content)

    def test_pick_api_accepts_collection_id(self):
        content = _read('gapi_gui.py')
        self.assertIn("data.get('collection_id') or data.get('list_id')", content)
        self.assertIn("backlog_service.get_games(", content)


class TestRecommendationsRefreshRoute(unittest.TestCase):

    def setUp(self):
        gapi_gui.app.config['TESTING'] = True
        gapi_gui.app.config['SECRET_KEY'] = 'test-secret'
        self.client = gapi_gui.app.test_client()
        with self.client.session_transaction() as sess:
            sess['username'] = 'alice'

    def test_refresh_seed_is_forwarded_to_picker(self):
        fake_picker = MagicMock()
        fake_picker.get_recommendations.return_value = []
        with patch.object(gapi_gui, 'ensure_picker_initialized', return_value=fake_picker):
            resp = self.client.get('/api/recommendations?count=5&refresh_seed=12345')
        self.assertEqual(resp.status_code, 200)
        fake_picker.get_recommendations.assert_called_once()
        self.assertEqual(fake_picker.get_recommendations.call_args.kwargs['refresh_seed'], '12345')


if __name__ == '__main__':
    unittest.main()
