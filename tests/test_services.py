#!/usr/bin/env python3
"""
Unit tests for the app/repositories and app/services layer.

Run with:
    python -m pytest tests/test_services.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repositories import (
    ReviewRepository, TagRepository, ScheduleRepository, PlaylistRepository,
    BacklogRepository, BudgetRepository, WishlistRepository,
    FavoritesRepository, HistoryRepository,
)
from app.services import (
    ReviewService, TagService, ScheduleService, PlaylistService,
    BacklogService, BudgetService, WishlistService, FavoritesService,
    HistoryService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_GAMES = [
    {'appid': 620,  'name': 'Portal 2',        'game_id': 'steam:620'},
    {'appid': 440,  'name': 'Team Fortress 2', 'game_id': 'steam:440'},
    {'appid': 570,  'name': 'Dota 2',           'game_id': 'steam:570'},
]


class TmpDirMixin(unittest.TestCase):
    """Creates a fresh temp directory for each test and cd's into it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.tmp, name)


# ===========================================================================
# Repository tests
# ===========================================================================

class TestReviewRepository(TmpDirMixin):

    def _make(self):
        return ReviewRepository(self._path('reviews.json'))

    def test_starts_empty(self):
        self.assertEqual(self._make().data, {})

    def test_upsert_and_find(self):
        repo = self._make()
        repo.upsert('steam:620', {'rating': 8, 'notes': 'great'})
        self.assertEqual(repo.find('steam:620')['rating'], 8)

    def test_delete_returns_true(self):
        repo = self._make()
        repo.upsert('steam:620', {'rating': 8})
        self.assertTrue(repo.delete('steam:620'))
        self.assertIsNone(repo.find('steam:620'))

    def test_delete_missing_returns_false(self):
        self.assertFalse(self._make().delete('steam:999'))

    def test_persisted_across_instances(self):
        path = self._path('reviews.json')
        r1 = ReviewRepository(path)
        r1.upsert('steam:620', {'rating': 7})
        r2 = ReviewRepository(path)
        self.assertIsNotNone(r2.find('steam:620'))

    def test_corrupt_file_returns_empty(self):
        path = self._path('reviews.json')
        with open(path, 'w') as f:
            f.write('NOT JSON')
        repo = ReviewRepository(path)
        self.assertEqual(repo.data, {})


class TestTagRepository(TmpDirMixin):

    def _make(self):
        return TagRepository(self._path('tags.json'))

    def test_starts_empty(self):
        self.assertEqual(self._make().data, {})

    def test_upsert_and_find(self):
        repo = self._make()
        repo.upsert('steam:620', ['rpg', 'action'])
        self.assertEqual(repo.find('steam:620'), ['rpg', 'action'])

    def test_find_missing_returns_empty_list(self):
        self.assertEqual(self._make().find('steam:999'), [])

    def test_delete_entry(self):
        repo = self._make()
        repo.upsert('steam:620', ['rpg'])
        repo.delete_entry('steam:620')
        self.assertEqual(repo.find('steam:620'), [])

    def test_persisted(self):
        path = self._path('tags.json')
        TagRepository(path).upsert('steam:620', ['indie'])
        self.assertIn('indie', TagRepository(path).find('steam:620'))


class TestFavoritesRepository(TmpDirMixin):

    def _make(self):
        return FavoritesRepository(self._path('favs.json'))

    def test_add_and_contains(self):
        repo = self._make()
        self.assertTrue(repo.add('steam:620'))
        self.assertTrue(repo.contains('steam:620'))

    def test_add_duplicate_returns_false(self):
        repo = self._make()
        repo.add('steam:620')
        self.assertFalse(repo.add('steam:620'))

    def test_remove(self):
        repo = self._make()
        repo.add('steam:620')
        self.assertTrue(repo.remove('steam:620'))
        self.assertFalse(repo.contains('steam:620'))

    def test_remove_missing_returns_false(self):
        self.assertFalse(self._make().remove('steam:999'))

    def test_normalises_int_ids_on_load(self):
        path = self._path('favs.json')
        with open(path, 'w') as f:
            json.dump([620, 440], f)
        repo = FavoritesRepository(path)
        self.assertIn('steam:620', repo.data)
        self.assertIn('steam:440', repo.data)


class TestHistoryRepository(TmpDirMixin):

    def _make(self, max_size=5):
        return HistoryRepository(self._path('history.json'), max_size=max_size)

    def test_append_and_data(self):
        repo = self._make()
        repo.append('steam:620')
        self.assertIn('steam:620', repo.data)

    def test_trim_on_save(self):
        repo = self._make(max_size=3)
        for i in range(5):
            repo.append(f'steam:{i}')
        saved = json.load(open(self._path('history.json')))
        self.assertLessEqual(len(saved), 3)

    def test_normalises_ints(self):
        path = self._path('history.json')
        with open(path, 'w') as f:
            json.dump([620, 440], f)
        repo = HistoryRepository(path)
        self.assertIn('steam:620', repo.data)


class TestBacklogRepository(TmpDirMixin):

    def _make(self):
        return BacklogRepository(self._path('backlog.json'))

    def test_upsert_and_find(self):
        repo = self._make()
        repo.upsert('steam:620', 'playing')
        self.assertEqual(repo.find('steam:620'), 'playing')

    def test_delete(self):
        repo = self._make()
        repo.upsert('steam:620', 'playing')
        self.assertTrue(repo.delete('steam:620'))
        self.assertIsNone(repo.find('steam:620'))


class TestBudgetRepository(TmpDirMixin):

    def _make(self):
        return BudgetRepository(self._path('budget.json'))

    def test_upsert_and_find(self):
        repo = self._make()
        repo.upsert('steam:620', {'price': 9.99, 'currency': 'USD'})
        self.assertEqual(repo.find('steam:620')['price'], 9.99)

    def test_delete(self):
        repo = self._make()
        repo.upsert('steam:620', {'price': 9.99})
        self.assertTrue(repo.delete('steam:620'))


class TestWishlistRepository(TmpDirMixin):

    def _make(self):
        return WishlistRepository(self._path('wishlist.json'))

    def test_upsert_and_find(self):
        repo = self._make()
        repo.upsert('steam:620', {'name': 'Portal 2', 'target_price': 4.99})
        self.assertEqual(repo.find('steam:620')['name'], 'Portal 2')

    def test_delete(self):
        repo = self._make()
        repo.upsert('steam:620', {'name': 'Portal 2'})
        self.assertTrue(repo.delete('steam:620'))
        self.assertIsNone(repo.find('steam:620'))


# ===========================================================================
# Service tests
# ===========================================================================

class TestReviewService(TmpDirMixin):

    def _make(self):
        repo = ReviewRepository(self._path('reviews.json'))
        return ReviewService(repo), repo

    def test_add_or_update_success(self):
        svc, _ = self._make()
        self.assertTrue(svc.add_or_update('steam:620', 8, 'great game'))

    def test_add_or_update_persists(self):
        svc, repo = self._make()
        svc.add_or_update('steam:620', 8)
        self.assertEqual(repo.find('steam:620')['rating'], 8)

    def test_add_or_update_rejects_out_of_range(self):
        svc, _ = self._make()
        self.assertFalse(svc.add_or_update('steam:620', 0))
        self.assertFalse(svc.add_or_update('steam:620', 11))

    def test_get_returns_review(self):
        svc, _ = self._make()
        svc.add_or_update('steam:620', 7)
        self.assertEqual(svc.get('steam:620')['rating'], 7)

    def test_get_missing_returns_none(self):
        svc, _ = self._make()
        self.assertIsNone(svc.get('steam:999'))

    def test_remove_existing(self):
        svc, _ = self._make()
        svc.add_or_update('steam:620', 7)
        self.assertTrue(svc.remove('steam:620'))
        self.assertIsNone(svc.get('steam:620'))

    def test_remove_missing_returns_false(self):
        svc, _ = self._make()
        self.assertFalse(svc.remove('steam:999'))

    def test_get_all_returns_dict(self):
        svc, _ = self._make()
        svc.add_or_update('steam:620', 8)
        svc.add_or_update('steam:440', 6)
        all_reviews = svc.get_all()
        self.assertIn('steam:620', all_reviews)
        self.assertIn('steam:440', all_reviews)

    def test_updated_at_field_set(self):
        svc, _ = self._make()
        svc.add_or_update('steam:620', 9)
        self.assertIn('updated_at', svc.get('steam:620'))


class TestTagService(TmpDirMixin):

    def _make(self):
        repo = TagRepository(self._path('tags.json'))
        return TagService(repo)

    def test_add_tag(self):
        svc = self._make()
        self.assertTrue(svc.add('steam:620', 'rpg'))
        self.assertIn('rpg', svc.get('steam:620'))

    def test_add_duplicate_returns_false(self):
        svc = self._make()
        svc.add('steam:620', 'rpg')
        self.assertFalse(svc.add('steam:620', 'rpg'))

    def test_add_empty_tag_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.add('steam:620', '   '))

    def test_remove_tag(self):
        svc = self._make()
        svc.add('steam:620', 'rpg')
        self.assertTrue(svc.remove('steam:620', 'rpg'))
        self.assertNotIn('rpg', svc.get('steam:620'))

    def test_remove_last_tag_cleans_entry(self):
        svc = self._make()
        svc.add('steam:620', 'rpg')
        svc.remove('steam:620', 'rpg')
        self.assertEqual(svc.get_all(), {})

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove('steam:620', 'nonexistent'))

    def test_all_tag_names_deduplicated(self):
        svc = self._make()
        svc.add('steam:620', 'rpg')
        svc.add('steam:440', 'rpg')
        svc.add('steam:570', 'action')
        names = svc.all_tag_names()
        self.assertEqual(names, sorted(set(names)))
        self.assertEqual(len(names), len(set(names)))

    def test_filter_by_tag(self):
        svc = self._make()
        svc.add('steam:620', 'indie')
        result = svc.filter_by_tag('indie', FAKE_GAMES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['game_id'], 'steam:620')

    def test_filter_by_tag_no_match(self):
        svc = self._make()
        result = svc.filter_by_tag('nonexistent', FAKE_GAMES)
        self.assertEqual(result, [])


class TestScheduleService(TmpDirMixin):

    def _make(self):
        repo = ScheduleRepository(self._path('schedule.json'))
        return ScheduleService(repo)

    def test_add_event_returns_dict(self):
        svc = self._make()
        event = svc.add_event('Game Night', '2026-03-01', '20:00')
        self.assertIn('id', event)
        self.assertEqual(event['title'], 'Game Night')

    def test_add_event_persisted(self):
        svc = self._make()
        event = svc.add_event('Test', '2026-03-01', '19:00')
        self.assertEqual(len(svc.get_events()), 1)
        self.assertEqual(svc.get_events()[0]['id'], event['id'])

    def test_update_event(self):
        svc = self._make()
        event = svc.add_event('Old Title', '2026-03-01', '19:00')
        updated = svc.update_event(event['id'], title='New Title')
        self.assertEqual(updated['title'], 'New Title')

    def test_update_event_missing_returns_none(self):
        svc = self._make()
        self.assertIsNone(svc.update_event('nonexistent', title='X'))

    def test_remove_event(self):
        svc = self._make()
        event = svc.add_event('Test', '2026-03-01', '19:00')
        self.assertTrue(svc.remove_event(event['id']))
        self.assertEqual(svc.get_events(), [])

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove_event('nonexistent'))

    def test_get_events_sorted(self):
        svc = self._make()
        svc.add_event('B', '2026-03-02', '20:00')
        svc.add_event('A', '2026-03-01', '20:00')
        events = svc.get_events()
        self.assertEqual(events[0]['date'], '2026-03-01')


class TestPlaylistService(TmpDirMixin):

    def _make(self):
        repo = PlaylistRepository(self._path('playlists.json'))
        return PlaylistService(repo)

    def test_create(self):
        svc = self._make()
        self.assertTrue(svc.create('Cozy Games'))
        self.assertEqual(len(svc.list_all()), 1)

    def test_create_duplicate_returns_false(self):
        svc = self._make()
        svc.create('Cozy Games')
        self.assertFalse(svc.create('Cozy Games'))

    def test_create_empty_name_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.create('  '))

    def test_delete(self):
        svc = self._make()
        svc.create('Cozy Games')
        self.assertTrue(svc.delete('Cozy Games'))
        self.assertEqual(svc.list_all(), [])

    def test_add_game(self):
        svc = self._make()
        svc.create('Cozy Games')
        self.assertTrue(svc.add_game('Cozy Games', 'steam:620'))
        result = svc.get_games('Cozy Games', FAKE_GAMES)
        self.assertEqual(len(result), 1)

    def test_add_game_duplicate_returns_false(self):
        svc = self._make()
        svc.create('Cozy Games')
        svc.add_game('Cozy Games', 'steam:620')
        self.assertFalse(svc.add_game('Cozy Games', 'steam:620'))

    def test_remove_game(self):
        svc = self._make()
        svc.create('Cozy Games')
        svc.add_game('Cozy Games', 'steam:620')
        self.assertTrue(svc.remove_game('Cozy Games', 'steam:620'))
        self.assertEqual(svc.get_games('Cozy Games', FAKE_GAMES), [])

    def test_get_games_missing_playlist_returns_none(self):
        svc = self._make()
        self.assertIsNone(svc.get_games('nonexistent', FAKE_GAMES))

    def test_list_all_counts(self):
        svc = self._make()
        svc.create('A')
        svc.add_game('A', 'steam:620')
        svc.add_game('A', 'steam:440')
        summary = svc.list_all()
        self.assertEqual(summary[0]['count'], 2)


class TestBacklogService(TmpDirMixin):

    def _make(self):
        repo = BacklogRepository(self._path('backlog.json'))
        return BacklogService(repo)

    def test_set_status_valid(self):
        svc = self._make()
        self.assertTrue(svc.set_status('steam:620', 'playing'))
        self.assertEqual(svc.get_status('steam:620'), 'playing')

    def test_set_status_invalid(self):
        svc = self._make()
        self.assertFalse(svc.set_status('steam:620', 'unknown_status'))

    def test_remove(self):
        svc = self._make()
        svc.set_status('steam:620', 'completed')
        self.assertTrue(svc.remove('steam:620'))
        self.assertIsNone(svc.get_status('steam:620'))

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove('steam:999'))

    def test_get_games_all(self):
        svc = self._make()
        svc.set_status('steam:620', 'playing')
        result = svc.get_games(FAKE_GAMES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['backlog_status'], 'playing')

    def test_get_games_filtered_by_status(self):
        svc = self._make()
        svc.set_status('steam:620', 'playing')
        svc.set_status('steam:440', 'completed')
        result = svc.get_games(FAKE_GAMES, status='completed')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['game_id'], 'steam:440')

    def test_all_valid_statuses(self):
        svc = self._make()
        for status in ('want_to_play', 'playing', 'completed', 'dropped'):
            self.assertTrue(svc.set_status('steam:620', status))


class TestBudgetService(TmpDirMixin):

    def _make(self):
        repo = BudgetRepository(self._path('budget.json'))
        return BudgetService(repo)

    def test_set_entry(self):
        svc = self._make()
        self.assertTrue(svc.set_entry('steam:620', 14.99))

    def test_set_entry_negative_price_rejected(self):
        svc = self._make()
        self.assertFalse(svc.set_entry('steam:620', -1.0))

    def test_set_entry_zero_price_allowed(self):
        svc = self._make()
        self.assertTrue(svc.set_entry('steam:620', 0.0))

    def test_currency_uppercased(self):
        svc = self._make()
        svc.set_entry('steam:620', 9.99, currency='usd')
        self.assertEqual(svc.get_entry('steam:620')['currency'], 'USD')

    def test_remove_entry(self):
        svc = self._make()
        svc.set_entry('steam:620', 9.99)
        self.assertTrue(svc.remove_entry('steam:620'))
        self.assertIsNone(svc.get_entry('steam:620'))

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove_entry('steam:999'))

    def test_get_summary_total(self):
        svc = self._make()
        svc.set_entry('steam:620', 14.99)
        svc.set_entry('steam:440', 9.99)
        summary = svc.get_summary(FAKE_GAMES)
        self.assertAlmostEqual(summary['total_spent'], 24.98, places=2)

    def test_get_summary_game_count(self):
        svc = self._make()
        svc.set_entry('steam:620', 14.99)
        summary = svc.get_summary(FAKE_GAMES)
        self.assertEqual(summary['game_count'], 1)

    def test_get_summary_enriched_with_name(self):
        svc = self._make()
        svc.set_entry('steam:620', 14.99)
        summary = svc.get_summary(FAKE_GAMES)
        entry = next(e for e in summary['entries'] if e['game_id'] == 'steam:620')
        self.assertEqual(entry['name'], 'Portal 2')

    def test_get_summary_empty(self):
        svc = self._make()
        summary = svc.get_summary([])
        self.assertEqual(summary['total_spent'], 0.0)
        self.assertEqual(summary['game_count'], 0)

    def test_get_summary_currency_breakdown(self):
        svc = self._make()
        svc.set_entry('steam:620', 14.99, currency='USD')
        svc.set_entry('steam:440', 9.99, currency='EUR')
        summary = svc.get_summary(FAKE_GAMES)
        self.assertIn('USD', summary['currency_breakdown'])
        self.assertIn('EUR', summary['currency_breakdown'])


class TestWishlistService(TmpDirMixin):

    def _make(self):
        repo = WishlistRepository(self._path('wishlist.json'))
        return WishlistService(repo)

    def test_add(self):
        svc = self._make()
        self.assertTrue(svc.add('steam:620', 'Portal 2'))
        self.assertIn('steam:620', svc.get_all())

    def test_add_stores_fields(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2', platform='steam',
                target_price=9.99, notes='Want this')
        entry = svc.get('steam:620')
        self.assertEqual(entry['target_price'], 9.99)
        self.assertEqual(entry['notes'], 'Want this')

    def test_add_negative_target_price_rejected(self):
        svc = self._make()
        self.assertFalse(svc.add('steam:620', 'Portal 2', target_price=-1.0))

    def test_add_zero_target_price_allowed(self):
        svc = self._make()
        self.assertTrue(svc.add('steam:620', 'Portal 2', target_price=0.0))

    def test_add_none_target_price_allowed(self):
        svc = self._make()
        self.assertTrue(svc.add('steam:620', 'Portal 2', target_price=None))

    def test_remove(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2')
        self.assertTrue(svc.remove('steam:620'))
        self.assertNotIn('steam:620', svc.get_all())

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove('steam:999'))

    def test_check_sales_no_client(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2')
        self.assertEqual(svc.check_sales(None), [])

    def test_check_sales_on_sale(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2')
        mock_client = MagicMock()
        mock_client.get_price_overview.return_value = {
            'discount_percent': 50, 'final': 999, 'initial': 1999,
            'final_formatted': '$9.99', 'initial_formatted': '$19.99',
        }
        result = svc.check_sales(mock_client)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['discount_percent'], 50)

    def test_check_sales_below_target(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2', target_price=15.00)
        mock_client = MagicMock()
        mock_client.get_price_overview.return_value = {
            'discount_percent': 0, 'final': 1499, 'initial': 1999,
            'final_formatted': '$14.99', 'initial_formatted': '$19.99',
        }
        result = svc.check_sales(mock_client)
        self.assertEqual(len(result), 1)
        self.assertIn('target', result[0]['sale_reason'])

    def test_check_sales_not_on_sale(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2', target_price=5.00)
        mock_client = MagicMock()
        mock_client.get_price_overview.return_value = {
            'discount_percent': 0, 'final': 1999, 'initial': 1999,
            'final_formatted': '$19.99', 'initial_formatted': '$19.99',
        }
        self.assertEqual(svc.check_sales(mock_client), [])

    def test_check_sales_skips_non_steam(self):
        svc = self._make()
        svc.add('epic:ABC', 'Epic Game', platform='epic')
        mock_client = MagicMock()
        svc.check_sales(mock_client)
        mock_client.get_price_overview.assert_not_called()

    def test_check_sales_skips_no_price_data(self):
        svc = self._make()
        svc.add('steam:620', 'Portal 2')
        mock_client = MagicMock()
        mock_client.get_price_overview.return_value = None
        self.assertEqual(svc.check_sales(mock_client), [])


class TestFavoritesService(TmpDirMixin):

    def _make(self):
        repo = FavoritesRepository(self._path('favs.json'))
        return FavoritesService(repo)

    def test_add(self):
        svc = self._make()
        self.assertTrue(svc.add('steam:620'))
        self.assertTrue(svc.contains('steam:620'))

    def test_add_duplicate_returns_false(self):
        svc = self._make()
        svc.add('steam:620')
        self.assertFalse(svc.add('steam:620'))

    def test_remove(self):
        svc = self._make()
        svc.add('steam:620')
        self.assertTrue(svc.remove('steam:620'))
        self.assertFalse(svc.contains('steam:620'))

    def test_remove_missing_returns_false(self):
        svc = self._make()
        self.assertFalse(svc.remove('steam:999'))

    def test_normalises_int_id(self):
        svc = self._make()
        svc.add(620)  # int
        self.assertTrue(svc.contains('steam:620'))

    def test_get_all(self):
        svc = self._make()
        svc.add('steam:620')
        svc.add('steam:440')
        self.assertEqual(len(svc.get_all()), 2)


class TestHistoryService(TmpDirMixin):

    def _make(self, max_size=10):
        repo = HistoryRepository(self._path('history.json'), max_size=max_size)
        return HistoryService(repo)

    def test_append_and_data(self):
        svc = self._make()
        svc.append('steam:620')
        self.assertIn('steam:620', svc.data)

    def test_append_persisted(self):
        path = self._path('history.json')
        repo = HistoryRepository(path)
        svc = HistoryService(repo)
        svc.append('steam:620')
        with open(path) as f:
            saved = json.load(f)
        self.assertIn('steam:620', saved)

    def test_clear(self):
        svc = self._make()
        svc.append('steam:620')
        svc.clear()
        self.assertEqual(svc.data, [])

    def test_export_creates_file(self):
        svc = self._make()
        svc.append('steam:620')
        out = self._path('export.json')
        self.assertTrue(svc.export(out))
        self.assertTrue(os.path.exists(out))

    def test_export_contains_history(self):
        svc = self._make()
        svc.append('steam:620')
        out = self._path('export.json')
        svc.export(out)
        with open(out) as f:
            data = json.load(f)
        self.assertIn('history', data)
        self.assertIn('steam:620', data['history'])

    def test_export_contains_exported_at(self):
        svc = self._make()
        out = self._path('export.json')
        svc.export(out)
        with open(out) as f:
            data = json.load(f)
        self.assertIn('exported_at', data)

    def test_import_from_list(self):
        svc = self._make()
        src = self._path('src.json')
        with open(src, 'w') as f:
            json.dump(['steam:620', 'steam:440'], f)
        count = svc.import_from(src)
        self.assertEqual(count, 2)
        self.assertIn('steam:620', svc.data)

    def test_import_from_export_dict(self):
        svc = self._make()
        src = self._path('src.json')
        with open(src, 'w') as f:
            json.dump({'history': ['steam:570'], 'exported_at': '2026-01-01'}, f)
        count = svc.import_from(src)
        self.assertEqual(count, 1)
        self.assertIn('steam:570', svc.data)

    def test_import_from_missing_file_returns_none(self):
        svc = self._make()
        self.assertIsNone(svc.import_from(self._path('no_such_file.json')))

    def test_import_from_invalid_format_returns_none(self):
        svc = self._make()
        src = self._path('bad.json')
        with open(src, 'w') as f:
            json.dump({'no_history_key': True}, f)
        self.assertIsNone(svc.import_from(src))

    def test_import_replaces_existing(self):
        svc = self._make()
        svc.append('steam:999')
        src = self._path('src.json')
        with open(src, 'w') as f:
            json.dump(['steam:620'], f)
        svc.import_from(src)
        self.assertNotIn('steam:999', svc.data)
        self.assertIn('steam:620', svc.data)


# ===========================================================================
# Integration: GamePicker wires services and shared references stay in sync
# ===========================================================================

class TestGamePickerServiceIntegration(TmpDirMixin):
    """Verify that picker.xxx (legacy attr) and picker.xxx_service stay in sync."""

    def _make_picker(self):
        import gapi
        cfg_path = self._path('config.json')
        with open(cfg_path, 'w') as f:
            json.dump({'steam_api_key': 'TEST_KEY_12345',
                       'steam_id':      '76561190000000001'}, f)
        return gapi.GamePicker(cfg_path)

    def test_review_service_exposed(self):
        picker = self._make_picker()
        self.assertIsInstance(picker.review_service, ReviewService)

    def test_budget_service_exposed(self):
        picker = self._make_picker()
        self.assertIsInstance(picker.budget_service, BudgetService)

    def test_wishlist_service_exposed(self):
        picker = self._make_picker()
        self.assertIsInstance(picker.wishlist_service, WishlistService)

    def test_legacy_attr_reflects_service_change(self):
        """picker.reviews dict == repo.data — a service write shows in legacy attr."""
        picker = self._make_picker()
        picker.review_service.add_or_update('steam:620', 8)
        self.assertIn('steam:620', picker.reviews)
        self.assertEqual(picker.reviews['steam:620']['rating'], 8)

    def test_legacy_method_reflects_in_service(self):
        """Writing via the old GamePicker method is visible through the service."""
        picker = self._make_picker()
        picker.add_or_update_review('steam:440', 9)
        self.assertEqual(picker.review_service.get('steam:440')['rating'], 9)

    def test_budget_service_and_legacy_attr_shared(self):
        picker = self._make_picker()
        picker.budget_service.set_entry('steam:620', 9.99)
        self.assertIn('steam:620', picker.budget)

    def test_wishlist_service_and_legacy_attr_shared(self):
        picker = self._make_picker()
        picker.wishlist_service.add('steam:620', 'Portal 2')
        self.assertIn('steam:620', picker.wishlist)

    def test_favorites_service_and_legacy_attr_shared(self):
        picker = self._make_picker()
        picker.favorites_service.add('steam:620')
        self.assertIn('steam:620', picker.favorites)

    def test_history_service_exposed(self):
        picker = self._make_picker()
        from app.services import HistoryService
        self.assertIsInstance(picker.history_service, HistoryService)

    def test_history_service_and_legacy_attr_shared(self):
        picker = self._make_picker()
        picker.history_service.append('steam:620')
        self.assertIn('steam:620', picker.history)


# ===========================================================================
# DB-backed service tests (NotificationService, ChatService, FriendService)
# ===========================================================================

class _MockDB:
    """Minimal stand-in for the database module so service tests don't
    need a real PostgreSQL connection."""

    def __init__(self):
        self._notifications = {}  # {username: [notif_dict, ...]}
        self._messages = {}       # {room: [msg_dict, ...]}
        self._friends = {}        # {username: {status, other}}
        self._roles = {}          # {username: [roles]}
        self._next_id = 0

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    # Notification helpers
    def create_notification(self, db, username, title, message, type='info'):
        if username not in self._notifications:
            self._notifications[username] = []
        self._notifications[username].append({
            'id': self._new_id(), 'type': type, 'title': title,
            'message': message, 'is_read': False, 'created_at': None,
        })
        return True

    def get_notifications(self, db, username, unread_only=False):
        notifs = self._notifications.get(username, [])
        if unread_only:
            return [n for n in notifs if not n['is_read']]
        return list(notifs)

    def mark_notifications_read(self, db, username, notification_ids=None):
        for n in self._notifications.get(username, []):
            if notification_ids is None or n['id'] in notification_ids:
                n['is_read'] = True
        return True

    def get_user_roles(self, db, username):
        return self._roles.get(username, [])

    # Chat helpers
    def send_chat_message(self, db, sender_username, message, room='general',
                          recipient_username=None):
        if room not in self._messages:
            self._messages[room] = []
        msg = {'id': self._new_id(), 'sender': sender_username,
               'room': room, 'message': message, 'created_at': None}
        self._messages[room].append(msg)
        return msg

    def get_chat_messages(self, db, room='general', limit=50, since_id=0):
        msgs = self._messages.get(room, [])
        if since_id:
            msgs = [m for m in msgs if m['id'] > since_id]
        return msgs[:limit]

    # Friend helpers
    def send_friend_request(self, db, from_username, to_username):
        key = (from_username, to_username)
        self._friends[key] = 'pending'
        return True, 'Friend request sent'

    def respond_friend_request(self, db, username, requester_username, accept):
        key = (requester_username, username)
        if key not in self._friends:
            return False, 'No pending friend request found'
        self._friends[key] = 'accepted' if accept else 'declined'
        return True, 'accepted' if accept else 'declined'

    def get_app_friends(self, db, username):
        friends, sent, received = [], [], []
        for (fr, to), status in self._friends.items():
            if status == 'accepted':
                if fr == username:
                    friends.append({'username': to, 'display_name': to})
                elif to == username:
                    friends.append({'username': fr, 'display_name': fr})
            elif status == 'pending':
                if fr == username:
                    sent.append({'username': to, 'display_name': to})
                elif to == username:
                    received.append({'username': fr, 'display_name': fr,
                                     'requester': fr})
        return {'friends': friends, 'sent': sent, 'received': received}

    def remove_app_friend(self, db, username, other_username):
        removed = False
        for key in list(self._friends.keys()):
            if set(key) == {username, other_username}:
                del self._friends[key]
                removed = True
        return removed


DB = None  # dummy session placeholder — MockDB ignores it


class TestNotificationService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockDB()
        from app.services import NotificationService
        self.svc = NotificationService(self.mock_db)

    def test_create_and_get_all(self):
        self.svc.create(DB, 'alice', 'Hello', 'World')
        notifs = self.svc.get_all(DB, 'alice')
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]['title'], 'Hello')

    def test_get_all_unread_only(self):
        self.svc.create(DB, 'alice', 'T1', 'M1')
        self.svc.create(DB, 'alice', 'T2', 'M2')
        # mark first one read
        nid = self.svc.get_all(DB, 'alice')[0]['id']
        self.svc.mark_read(DB, 'alice', ids=[nid])
        unread = self.svc.get_all(DB, 'alice', unread_only=True)
        self.assertEqual(len(unread), 1)
        self.assertFalse(unread[0]['is_read'])

    def test_mark_read_all(self):
        self.svc.create(DB, 'alice', 'T1', 'M1')
        self.svc.create(DB, 'alice', 'T2', 'M2')
        self.svc.mark_read(DB, 'alice')
        notifs = self.svc.get_all(DB, 'alice', unread_only=True)
        self.assertEqual(notifs, [])

    def test_mark_read_specific(self):
        self.svc.create(DB, 'alice', 'T1', 'M1')
        self.svc.create(DB, 'alice', 'T2', 'M2')
        nids = [n['id'] for n in self.svc.get_all(DB, 'alice')]
        self.svc.mark_read(DB, 'alice', ids=[nids[0]])
        all_notifs = self.svc.get_all(DB, 'alice')
        read_count = sum(1 for n in all_notifs if n['is_read'])
        self.assertEqual(read_count, 1)

    def test_is_admin_true(self):
        self.mock_db._roles['alice'] = ['admin', 'user']
        self.assertTrue(self.svc.is_admin(DB, 'alice'))

    def test_is_admin_false(self):
        self.mock_db._roles['bob'] = ['user']
        self.assertFalse(self.svc.is_admin(DB, 'bob'))

    def test_is_admin_no_roles(self):
        self.assertFalse(self.svc.is_admin(DB, 'unknown'))

    def test_create_returns_true(self):
        self.assertTrue(self.svc.create(DB, 'alice', 'T', 'M'))

    def test_notif_type_stored(self):
        self.svc.create(DB, 'alice', 'T', 'M', notif_type='warning')
        self.assertEqual(self.svc.get_all(DB, 'alice')[0]['type'], 'warning')

    def test_different_users_isolated(self):
        self.svc.create(DB, 'alice', 'T', 'M')
        self.assertEqual(self.svc.get_all(DB, 'bob'), [])


class TestChatService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockDB()
        from app.services import ChatService
        self.svc = ChatService(self.mock_db)

    def test_send_and_get(self):
        self.svc.send(DB, 'alice', 'Hello!')
        msgs = self.svc.get_messages(DB)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]['message'], 'Hello!')
        self.assertEqual(msgs[0]['sender'], 'alice')

    def test_send_returns_dict(self):
        result = self.svc.send(DB, 'alice', 'Hi')
        self.assertIn('id', result)
        self.assertIn('message', result)

    def test_get_messages_room_filter(self):
        self.svc.send(DB, 'alice', 'general msg', room='general')
        self.svc.send(DB, 'bob', 'private msg', room='lobby')
        general = self.svc.get_messages(DB, room='general')
        self.assertEqual(len(general), 1)
        self.assertEqual(general[0]['room'], 'general')

    def test_get_messages_since_id(self):
        msg1 = self.svc.send(DB, 'alice', 'first')
        self.svc.send(DB, 'alice', 'second')
        newer = self.svc.get_messages(DB, since_id=msg1['id'])
        self.assertEqual(len(newer), 1)
        self.assertEqual(newer[0]['message'], 'second')

    def test_get_messages_limit(self):
        for i in range(5):
            self.svc.send(DB, 'alice', f'msg {i}')
        msgs = self.svc.get_messages(DB, limit=3)
        self.assertEqual(len(msgs), 3)

    def test_empty_room_returns_empty_list(self):
        self.assertEqual(self.svc.get_messages(DB, room='empty'), [])


class TestFriendService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockDB()
        from app.services import FriendService
        self.svc = FriendService(self.mock_db)

    def test_send_request(self):
        ok, msg = self.svc.send_request(DB, 'alice', 'bob')
        self.assertTrue(ok)
        self.assertIn('sent', msg.lower())

    def test_get_friends_pending_sent(self):
        self.svc.send_request(DB, 'alice', 'bob')
        result = self.svc.get_friends(DB, 'alice')
        self.assertEqual(len(result['sent']), 1)
        self.assertEqual(result['sent'][0]['username'], 'bob')

    def test_get_friends_pending_received(self):
        self.svc.send_request(DB, 'alice', 'bob')
        result = self.svc.get_friends(DB, 'bob')
        self.assertEqual(len(result['received']), 1)
        self.assertEqual(result['received'][0]['username'], 'alice')

    def test_respond_accept(self):
        self.svc.send_request(DB, 'alice', 'bob')
        ok, msg = self.svc.respond(DB, 'bob', 'alice', accept=True)
        self.assertTrue(ok)
        result = self.svc.get_friends(DB, 'bob')
        self.assertEqual(len(result['friends']), 1)

    def test_respond_decline(self):
        self.svc.send_request(DB, 'alice', 'bob')
        ok, msg = self.svc.respond(DB, 'bob', 'alice', accept=False)
        self.assertTrue(ok)
        result = self.svc.get_friends(DB, 'bob')
        self.assertEqual(len(result['friends']), 0)

    def test_respond_no_pending_returns_false(self):
        ok, msg = self.svc.respond(DB, 'bob', 'charlie', accept=True)
        self.assertFalse(ok)

    def test_remove_friend(self):
        self.svc.send_request(DB, 'alice', 'bob')
        self.svc.respond(DB, 'bob', 'alice', accept=True)
        ok = self.svc.remove(DB, 'alice', 'bob')
        self.assertTrue(ok)
        result = self.svc.get_friends(DB, 'alice')
        self.assertEqual(result['friends'], [])

    def test_remove_nonexistent_returns_false(self):
        ok = self.svc.remove(DB, 'alice', 'nobody')
        self.assertFalse(ok)

    def test_friends_list_empty_initially(self):
        result = self.svc.get_friends(DB, 'alice')
        self.assertEqual(result['friends'], [])
        self.assertEqual(result['sent'], [])
        self.assertEqual(result['received'], [])


# ===========================================================================
# LeaderboardService tests
# ===========================================================================

class _MockLeaderboardDB:
    """Minimal stand-in for the database module used by LeaderboardService."""

    def __init__(self):
        self._board = [
            {'rank': 1, 'username': 'alice', 'score': 120.5},
            {'rank': 2, 'username': 'bob', 'score': 60.0},
        ]
        self._cards = {
            'alice': {
                'username': 'alice',
                'display_name': 'Alice',
                'bio': '',
                'avatar_url': '',
                'roles': ['user'],
                'steam_id': '',
                'stats': {'total_games': 10, 'total_playtime_hours': 120.5,
                          'total_achievements': 5},
                'joined': None,
            }
        }
        self._profiles = {}

    def get_leaderboard(self, db, metric='playtime', limit=20):
        return self._board[:limit]

    def get_user_card(self, db, username):
        return self._cards.get(username, {})

    def update_user_profile(self, db, username, display_name=None, bio=None,
                            avatar_url=None):
        self._profiles[username] = {
            'display_name': display_name,
            'bio': bio,
            'avatar_url': avatar_url,
        }
        return True


class TestLeaderboardService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockLeaderboardDB()
        from app.services import LeaderboardService
        self.svc = LeaderboardService(self.mock_db)

    def test_get_rankings_returns_list(self):
        rows = self.svc.get_rankings(DB)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 2)

    def test_get_rankings_default_metric_playtime(self):
        rows = self.svc.get_rankings(DB, metric='playtime')
        self.assertEqual(rows[0]['username'], 'alice')

    def test_get_rankings_respects_limit(self):
        rows = self.svc.get_rankings(DB, limit=1)
        self.assertEqual(len(rows), 1)

    def test_get_user_card_found(self):
        card = self.svc.get_user_card(DB, 'alice')
        self.assertIsNotNone(card)
        self.assertEqual(card['username'], 'alice')
        self.assertIn('stats', card)

    def test_get_user_card_missing_returns_none(self):
        card = self.svc.get_user_card(DB, 'nobody')
        self.assertIsNone(card)

    def test_update_profile_returns_true(self):
        ok = self.svc.update_profile(DB, 'alice', display_name='Al', bio='Hi')
        self.assertTrue(ok)

    def test_update_profile_stores_values(self):
        self.svc.update_profile(DB, 'alice', display_name='Al', bio='gamer',
                                avatar_url='http://example.com/a.png')
        stored = self.mock_db._profiles['alice']
        self.assertEqual(stored['display_name'], 'Al')
        self.assertEqual(stored['bio'], 'gamer')


# ===========================================================================
# PluginService tests
# ===========================================================================

class _MockPluginDB:
    """Minimal stand-in for the database module used by PluginService."""

    def __init__(self):
        self._plugins = {}
        self._next_id = 0
        self._roles = {}

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def get_plugins(self, db):
        return list(self._plugins.values())

    def register_plugin(self, db, name, description='', version='1.0.0',
                        author='', config=None):
        if name in self._plugins:
            self._plugins[name].update(
                {'description': description, 'version': version,
                 'author': author})
        else:
            self._plugins[name] = {
                'id': self._new_id(), 'name': name,
                'description': description, 'version': version,
                'author': author, 'enabled': True, 'created_at': None,
            }
        return True

    def toggle_plugin(self, db, plugin_id, enabled):
        for p in self._plugins.values():
            if p['id'] == plugin_id:
                p['enabled'] = enabled
                return True
        return False

    def get_user_roles(self, db, username):
        return self._roles.get(username, [])


class TestPluginService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockPluginDB()
        from app.services import PluginService
        self.svc = PluginService(self.mock_db)

    def test_get_all_empty_initially(self):
        self.assertEqual(self.svc.get_all(DB), [])

    def test_register_adds_plugin(self):
        ok = self.svc.register(DB, 'MyPlugin', version='1.2.0')
        self.assertTrue(ok)
        plugins = self.svc.get_all(DB)
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]['name'], 'MyPlugin')

    def test_register_updates_existing(self):
        self.svc.register(DB, 'MyPlugin', version='1.0.0')
        self.svc.register(DB, 'MyPlugin', version='2.0.0')
        plugins = self.svc.get_all(DB)
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]['version'], '2.0.0')

    def test_toggle_enables_disables(self):
        self.svc.register(DB, 'P1')
        pid = self.svc.get_all(DB)[0]['id']
        ok = self.svc.toggle(DB, pid, enabled=False)
        self.assertTrue(ok)
        self.assertFalse(self.svc.get_all(DB)[0]['enabled'])

    def test_toggle_nonexistent_returns_false(self):
        ok = self.svc.toggle(DB, 9999, enabled=True)
        self.assertFalse(ok)

    def test_is_admin_true(self):
        self.mock_db._roles['admin_user'] = ['admin']
        self.assertTrue(self.svc.is_admin(DB, 'admin_user'))

    def test_is_admin_false(self):
        self.mock_db._roles['regular'] = ['user']
        self.assertFalse(self.svc.is_admin(DB, 'regular'))


# ===========================================================================
# AppSettingsService tests
# ===========================================================================

class _MockSettingsDB:
    """Minimal stand-in for the database module used by AppSettingsService."""

    _DEFAULTS = {
        'registration_open': 'true',
        'announcement': '',
        'max_pick_count': '10',
        'leaderboard_public': 'true',
    }

    def __init__(self):
        self._settings = {}
        self._roles = {}

    def get_app_settings(self, db):
        merged = dict(self._DEFAULTS)
        merged.update(self._settings)
        return merged

    def get_app_setting(self, db, key, default=None):
        return self.get_app_settings(db).get(key, default)

    def set_app_settings(self, db, updates, updated_by=None):
        self._settings.update({k: str(v) for k, v in updates.items()})
        return True

    def get_settings_with_meta(self, db):
        current = self.get_app_settings(db)
        return [{'key': k, 'value': v, 'description': ''}
                for k, v in current.items()]

    def get_user_roles(self, db, username):
        return self._roles.get(username, [])


class TestAppSettingsService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockSettingsDB()
        from app.services import AppSettingsService
        self.svc = AppSettingsService(self.mock_db)

    def test_get_all_returns_dict(self):
        settings = self.svc.get_all(DB)
        self.assertIsInstance(settings, dict)
        self.assertIn('registration_open', settings)

    def test_get_single_key(self):
        val = self.svc.get(DB, 'max_pick_count')
        self.assertEqual(val, '10')

    def test_get_missing_key_returns_default(self):
        val = self.svc.get(DB, 'nonexistent_key', default='fallback')
        self.assertEqual(val, 'fallback')

    def test_save_updates_value(self):
        self.svc.save(DB, {'announcement': 'Server maintenance tonight'})
        self.assertEqual(self.svc.get(DB, 'announcement'),
                         'Server maintenance tonight')

    def test_save_returns_true(self):
        ok = self.svc.save(DB, {'registration_open': 'false'})
        self.assertTrue(ok)

    def test_get_with_meta_returns_list(self):
        meta = self.svc.get_with_meta(DB)
        self.assertIsInstance(meta, list)
        keys = [m['key'] for m in meta]
        self.assertIn('registration_open', keys)

    def test_is_admin_true(self):
        self.mock_db._roles['boss'] = ['admin', 'user']
        self.assertTrue(self.svc.is_admin(DB, 'boss'))

    def test_is_admin_false(self):
        self.mock_db._roles['pleb'] = ['user']
        self.assertFalse(self.svc.is_admin(DB, 'pleb'))

    def test_save_multiple_keys(self):
        self.svc.save(DB, {'announcement': 'Hi', 'registration_open': 'false'})
        self.assertEqual(self.svc.get(DB, 'announcement'), 'Hi')
        self.assertEqual(self.svc.get(DB, 'registration_open'), 'false')


# ===========================================================================
# IgnoredGamesService tests
# ===========================================================================

class _MockIgnoredGamesDB:
    """Minimal stand-in for the database module used by IgnoredGamesService."""

    def __init__(self):
        self._ignored = {}  # {username: set of app_ids}

    def get_ignored_games(self, db, username):
        return list(self._ignored.get(username, set()))

    def toggle_ignore_game(self, db, username, app_id, game_name='',
                           reason=''):
        if username not in self._ignored:
            self._ignored[username] = set()
        app_id = str(app_id)
        if app_id in self._ignored[username]:
            self._ignored[username].discard(app_id)
        else:
            self._ignored[username].add(app_id)
        return True

    def get_shared_ignore_games(self, db, usernames):
        if not usernames:
            return []
        sets = [self._ignored.get(u, set()) for u in usernames]
        shared = sets[0].copy()
        for s in sets[1:]:
            shared &= s
        return list(shared)


class TestIgnoredGamesService(unittest.TestCase):

    def setUp(self):
        self.mock_db = _MockIgnoredGamesDB()
        from app.services import IgnoredGamesService
        self.svc = IgnoredGamesService(self.mock_db)

    def test_get_ignored_empty_initially(self):
        self.assertEqual(self.svc.get_ignored(DB, 'alice'), [])

    def test_toggle_adds_game(self):
        self.svc.toggle(DB, 'alice', '620')
        self.assertIn('620', self.svc.get_ignored(DB, 'alice'))

    def test_toggle_removes_game_on_second_call(self):
        self.svc.toggle(DB, 'alice', '620')
        self.svc.toggle(DB, 'alice', '620')
        self.assertNotIn('620', self.svc.get_ignored(DB, 'alice'))

    def test_toggle_returns_true(self):
        ok = self.svc.toggle(DB, 'alice', '620')
        self.assertTrue(ok)

    def test_get_shared_ignored_intersection(self):
        self.svc.toggle(DB, 'alice', '620')
        self.svc.toggle(DB, 'alice', '730')
        self.svc.toggle(DB, 'bob', '730')
        shared = self.svc.get_shared_ignored(DB, ['alice', 'bob'])
        self.assertEqual(shared, ['730'])

    def test_get_shared_ignored_empty_when_no_common(self):
        self.svc.toggle(DB, 'alice', '620')
        self.svc.toggle(DB, 'bob', '440')
        shared = self.svc.get_shared_ignored(DB, ['alice', 'bob'])
        self.assertEqual(shared, [])

    def test_get_shared_ignored_single_user(self):
        self.svc.toggle(DB, 'alice', '620')
        shared = self.svc.get_shared_ignored(DB, ['alice'])
        self.assertIn('620', shared)

    def test_get_shared_ignored_empty_list_of_users(self):
        shared = self.svc.get_shared_ignored(DB, [])
        self.assertEqual(shared, [])

    def test_different_users_isolated(self):
        self.svc.toggle(DB, 'alice', '620')
        self.assertEqual(self.svc.get_ignored(DB, 'bob'), [])


if __name__ == '__main__':
    unittest.main()
