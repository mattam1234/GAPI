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


if __name__ == '__main__':
    unittest.main()
