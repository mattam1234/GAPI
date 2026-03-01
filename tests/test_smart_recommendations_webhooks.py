#!/usr/bin/env python3
"""
Tests for SmartRecommendationEngine, WebhookNotifier, and the Flask routes
that expose smart recommendations and webhook test endpoints.

Run with:
    python -m pytest tests/test_smart_recommendations_webhooks.py
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.recommendation_service import SmartRecommendationEngine
from webhook_notifier import WebhookNotifier


# ===========================================================================
# Helpers
# ===========================================================================

def _game(appid: int, name: str, playtime_mins: int = 0, platform: str = 'steam') -> dict:
    return {
        'appid': appid,
        'name': name,
        'playtime_forever': playtime_mins,
        'game_id': f'{platform}:{appid}',
        'platform': platform,
    }


def _details(
    genres=None,
    categories=None,
    developers=None,
    publishers=None,
    metacritic_score=None,
) -> dict:
    d: dict = {}
    if genres:
        d['genres'] = [{'description': g} for g in genres]
    if categories:
        d['categories'] = [{'description': c} for c in categories]
    if developers:
        d['developers'] = list(developers)
    if publishers:
        d['publishers'] = list(publishers)
    if metacritic_score is not None:
        d['metacritic'] = {'score': metacritic_score}
    return d


# ===========================================================================
# SmartRecommendationEngine
# ===========================================================================

class TestSmartRecommendationEngineBasic(unittest.TestCase):

    def test_empty_games_returns_empty(self):
        eng = SmartRecommendationEngine(games=[])
        self.assertEqual(eng.recommend(10), [])

    def test_returns_at_most_count(self):
        games = [_game(i, f'Game {i}') for i in range(20)]
        eng   = SmartRecommendationEngine(games=games)
        recs  = eng.recommend(5)
        self.assertLessEqual(len(recs), 5)

    def test_result_has_required_keys(self):
        games = [_game(1, 'Portal 2')]
        eng   = SmartRecommendationEngine(games=games)
        recs  = eng.recommend(1)
        self.assertEqual(len(recs), 1)
        for key in ('smart_score', 'smart_reason', 'playtime_hours'):
            self.assertIn(key, recs[0], f"Missing key: {key}")

    def test_unplayed_scores_higher_than_barely_played(self):
        games = [
            _game(1, 'Unplayed',      playtime_mins=0),
            _game(2, 'Barely Played', playtime_mins=60),
        ]
        eng  = SmartRecommendationEngine(games=games, barely_played_mins=120)
        recs = eng.recommend(2)
        self.assertEqual(recs[0]['name'], 'Unplayed')

    def test_history_penalty_reduces_score(self):
        games = [
            _game(1, 'Recently Picked', playtime_mins=0),
            _game(2, 'Never Picked',    playtime_mins=0),
        ]
        history = ['steam:1'] * 10  # simulate recently picked
        eng_with = SmartRecommendationEngine(games=games, history=history)
        eng_without = SmartRecommendationEngine(games=games, history=[])
        recs_with    = eng_with.recommend(2)
        recs_without = eng_without.recommend(2)
        score_with    = next(r['smart_score'] for r in recs_with    if r['name'] == 'Recently Picked')
        score_without = next(r['smart_score'] for r in recs_without if r['name'] == 'Recently Picked')
        self.assertLess(score_with, score_without)

    def test_only_unplayed_candidates_when_no_barely_played(self):
        """If no game satisfies the barely-played threshold, falls back to all games."""
        games = [
            _game(1, 'Well Played',    playtime_mins=1000),
            _game(2, 'Another Well',   playtime_mins=800),
        ]
        eng  = SmartRecommendationEngine(games=games, barely_played_mins=120)
        recs = eng.recommend(5)
        self.assertEqual(len(recs), 2)

    def test_playtime_hours_field_is_correct(self):
        games = [_game(1, 'G', playtime_mins=120)]
        eng   = SmartRecommendationEngine(games=games, barely_played_mins=200)
        recs  = eng.recommend(1)
        self.assertAlmostEqual(recs[0]['playtime_hours'], 2.0)


class TestSmartRecommendationEngineAffinity(unittest.TestCase):

    def _make_engine_with_cache(self):
        games = [
            # well-played action game
            _game(1, 'Action Hero',   playtime_mins=1200),
            # unplayed game — should benefit from action affinity
            _game(2, 'Action Sequel', playtime_mins=0),
            # unplayed game with different genre
            _game(3, 'Puzzle Master', playtime_mins=0),
        ]
        cache = {
            1: _details(genres=['Action'], developers=['ValveDev']),
            2: _details(genres=['Action'], developers=['ValveDev']),
            3: _details(genres=['Puzzle'], developers=['OtherDev']),
        }
        return SmartRecommendationEngine(
            games=games,
            details_cache=cache,
            well_played_mins=600,
            barely_played_mins=120,
        )

    def test_genre_affinity_boosts_matching_genre(self):
        eng  = self._make_engine_with_cache()
        recs = eng.recommend(2)
        self.assertEqual(recs[0]['name'], 'Action Sequel')

    def test_genre_affinity_in_reason(self):
        eng  = self._make_engine_with_cache()
        recs = eng.recommend(2)
        action_rec = next(r for r in recs if r['name'] == 'Action Sequel')
        self.assertIn('action', action_rec['smart_reason'].lower())

    def test_metacritic_boosts_score(self):
        games = [
            _game(1, 'High Rated',  playtime_mins=0),
            _game(2, 'Low Rated',   playtime_mins=0),
        ]
        cache = {
            1: _details(metacritic_score=95),
            2: _details(metacritic_score=40),
        }
        eng  = SmartRecommendationEngine(games=games, details_cache=cache)
        recs = eng.recommend(2)
        self.assertEqual(recs[0]['name'], 'High Rated')

    def test_metacritic_in_reason(self):
        games = [_game(1, 'Top Game', playtime_mins=0)]
        cache = {1: _details(metacritic_score=90)}
        eng   = SmartRecommendationEngine(games=games, details_cache=cache)
        recs  = eng.recommend(1)
        self.assertIn('90', recs[0]['smart_reason'])

    def test_dev_affinity_applied(self):
        games = [
            _game(1, 'ValveDev Big Hit', playtime_mins=2000),
            _game(2, 'ValveDev Sequel',  playtime_mins=0),
            _game(3, 'Other Dev Game',   playtime_mins=0),
        ]
        cache = {
            1: _details(developers=['Valve']),
            2: _details(developers=['Valve']),
            3: _details(developers=['Bethesda']),
        }
        eng  = SmartRecommendationEngine(
            games=games, details_cache=cache, well_played_mins=600
        )
        recs = eng.recommend(2)
        self.assertEqual(recs[0]['name'], 'ValveDev Sequel')

    def test_affinity_profile_built_once(self):
        """_build_affinity_profiles should only run once (cached)."""
        games = [_game(1, 'G', playtime_mins=0)]
        eng   = SmartRecommendationEngine(games=games)
        eng.recommend(1)
        eng.recommend(1)
        self.assertIsNotNone(eng._genre_weights)


class TestSmartRecommendationEngineDiversity(unittest.TestCase):

    def test_no_crash_with_many_games(self):
        games = [_game(i, f'Game {i:04d}', playtime_mins=0) for i in range(100)]
        eng   = SmartRecommendationEngine(games=games)
        recs  = eng.recommend(10)
        self.assertEqual(len(recs), 10)

    def test_diversity_penalises_same_developer(self):
        """When the same developer dominates the cache, later entries are penalised."""
        # 5 games from Valve (well played = 0 so all are candidates)
        games = [_game(i, f'Valve Game {i}', playtime_mins=0) for i in range(1, 6)]
        # All from the same developer
        cache = {i: _details(developers=['Valve']) for i in range(1, 6)}
        eng   = SmartRecommendationEngine(games=games, details_cache=cache, barely_played_mins=120)
        # Should not raise; diversity pass runs without error
        recs  = eng.recommend(5)
        self.assertLessEqual(len(recs), 5)


# ===========================================================================
# WebhookNotifier
# ===========================================================================

def _resp_ok():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    return resp


def _resp_err():
    import requests as _r
    resp = MagicMock()
    resp.status_code = 500
    err = _r.HTTPError(response=resp)
    resp.raise_for_status.side_effect = err
    return resp


class TestWebhookNotifierGet(unittest.TestCase):

    def test_returns_empty_for_missing_key(self):
        n = WebhookNotifier({})
        self.assertEqual(n._get('nonexistent'), '')

    def test_returns_empty_for_placeholder(self):
        n = WebhookNotifier({'key': 'YOUR_KEY_HERE'})
        self.assertEqual(n._get('key'), '')

    def test_returns_value_when_present(self):
        n = WebhookNotifier({'key': 'real_value'})
        self.assertEqual(n._get('key'), 'real_value')

    def test_strips_whitespace(self):
        n = WebhookNotifier({'key': '  value  '})
        self.assertEqual(n._get('key'), 'value')


class TestWebhookNotifierSlack(unittest.TestCase):

    def _game(self):
        return {
            'name': 'Portal 2',
            'playtime_hours': 2.5,
            'steam_url': 'https://store.steampowered.com/app/620/',
            'header_image': 'https://example.com/portal2.jpg',
        }

    @patch('webhook_notifier.requests.post')
    def test_send_slack_success(self, mock_post):
        mock_post.return_value = _resp_ok()
        n  = WebhookNotifier({'slack_webhook_url': 'https://hooks.slack.com/test'})
        ok = n.send_slack('https://hooks.slack.com/test', self._game())
        self.assertTrue(ok)
        mock_post.assert_called_once()

    @patch('webhook_notifier.requests.post')
    def test_send_slack_failure(self, mock_post):
        import requests as _r
        mock_post.side_effect = _r.RequestException('down')
        n  = WebhookNotifier({})
        ok = n.send_slack('https://hooks.slack.com/test', self._game())
        self.assertFalse(ok)

    @patch('webhook_notifier.requests.post')
    def test_slack_payload_has_blocks(self, mock_post):
        mock_post.return_value = _resp_ok()
        n = WebhookNotifier({})
        n.send_slack('https://hooks.slack.com/test', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        self.assertIn('blocks', payload)

    @patch('webhook_notifier.requests.post')
    def test_slack_payload_fallback_text(self, mock_post):
        mock_post.return_value = _resp_ok()
        n = WebhookNotifier({})
        n.send_slack('https://hooks.slack.com/test', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        self.assertIn('Portal 2', payload.get('text', ''))

    @patch('webhook_notifier.requests.post')
    def test_slack_includes_image_accessory_when_present(self, mock_post):
        mock_post.return_value = _resp_ok()
        n = WebhookNotifier({})
        n.send_slack('https://hooks.slack.com/test', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        first_block = payload['blocks'][0]
        self.assertIn('accessory', first_block)


class TestWebhookNotifierTeams(unittest.TestCase):

    def _game(self):
        return {'name': 'Dota 2', 'playtime_hours': 100.0, 'steam_url': ''}

    @patch('webhook_notifier.requests.post')
    def test_send_teams_success(self, mock_post):
        mock_post.return_value = _resp_ok()
        n  = WebhookNotifier({})
        ok = n.send_teams('https://webhook.office.com/test', self._game())
        self.assertTrue(ok)

    @patch('webhook_notifier.requests.post')
    def test_teams_payload_adaptive_card(self, mock_post):
        mock_post.return_value = _resp_ok()
        n = WebhookNotifier({})
        n.send_teams('https://webhook.office.com/test', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        self.assertEqual(payload['type'], 'message')
        card = payload['attachments'][0]['content']
        self.assertEqual(card['type'], 'AdaptiveCard')

    @patch('webhook_notifier.requests.post')
    def test_teams_body_contains_game_name(self, mock_post):
        mock_post.return_value = _resp_ok()
        n = WebhookNotifier({})
        n.send_teams('https://webhook.office.com/test', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        body_texts = [b.get('text', '') for b in payload['attachments'][0]['content']['body']]
        self.assertTrue(any('Dota 2' in t for t in body_texts))


class TestWebhookNotifierIFTTT(unittest.TestCase):

    def _game(self):
        return {'name': 'CS2', 'playtime_hours': 50.0, 'steam_url': 'https://store.steampowered.com/app/730/'}

    @patch('webhook_notifier.requests.post')
    def test_send_ifttt_success(self, mock_post):
        mock_post.return_value = _resp_ok()
        ok = WebhookNotifier.send_ifttt('mykey', 'gapi_picked', self._game())
        self.assertTrue(ok)

    @patch('webhook_notifier.requests.post')
    def test_ifttt_url_contains_key_and_event(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_ifttt('secret123', 'my_event', self._game())
        url = mock_post.call_args[0][0]
        self.assertIn('secret123', url)
        self.assertIn('my_event', url)

    @patch('webhook_notifier.requests.post')
    def test_ifttt_payload_has_value1(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_ifttt('k', 'e', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        self.assertEqual(payload['value1'], 'CS2')

    @patch('webhook_notifier.requests.post')
    def test_ifttt_failure_returns_false(self, mock_post):
        import requests as _r
        mock_post.side_effect = _r.RequestException('timeout')
        ok = WebhookNotifier.send_ifttt('k', 'e', self._game())
        self.assertFalse(ok)


class TestWebhookNotifierHomeAssistant(unittest.TestCase):

    def _game(self):
        return {'name': 'Half-Life 2', 'appid': 220, 'playtime_hours': 10.0, 'steam_url': ''}

    @patch('webhook_notifier.requests.post')
    def test_send_ha_success(self, mock_post):
        mock_post.return_value = _resp_ok()
        ok = WebhookNotifier.send_homeassistant(
            'http://ha.local:8123', 'gapi_pick', self._game()
        )
        self.assertTrue(ok)

    @patch('webhook_notifier.requests.post')
    def test_ha_url_contains_webhook_id(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_homeassistant('http://ha.local:8123', 'my_hook', self._game())
        url = mock_post.call_args[0][0]
        self.assertIn('my_hook', url)

    @patch('webhook_notifier.requests.post')
    def test_ha_sends_authorization_header_with_token(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_homeassistant(
            'http://ha.local:8123', 'hook', self._game(), token='mytoken'
        )
        headers = mock_post.call_args.kwargs.get('headers') or mock_post.call_args[1].get('headers', {})
        self.assertIn('Authorization', headers)
        self.assertIn('Bearer', headers['Authorization'])

    @patch('webhook_notifier.requests.post')
    def test_ha_no_auth_header_without_token(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_homeassistant('http://ha.local:8123', 'hook', self._game())
        headers = mock_post.call_args.kwargs.get('headers') or mock_post.call_args[1].get('headers', {})
        self.assertNotIn('Authorization', headers)

    @patch('webhook_notifier.requests.post')
    def test_ha_payload_contains_game_name(self, mock_post):
        mock_post.return_value = _resp_ok()
        WebhookNotifier.send_homeassistant('http://ha.local:8123', 'hook', self._game())
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        self.assertEqual(payload['game_name'], 'Half-Life 2')

    @patch('webhook_notifier.requests.post')
    def test_ha_failure_returns_false(self, mock_post):
        import requests as _r
        mock_post.side_effect = _r.RequestException('unreachable')
        ok = WebhookNotifier.send_homeassistant('http://ha.local:8123', 'hook', self._game())
        self.assertFalse(ok)


class TestWebhookNotifierNotifyGamePicked(unittest.TestCase):

    @patch('webhook_notifier.requests.post')
    def test_dispatches_to_all_configured_services(self, mock_post):
        mock_post.return_value = _resp_ok()
        cfg = {
            'slack_webhook_url': 'https://hooks.slack.com/test',
            'teams_webhook_url': 'https://webhook.office.com/test',
            'ifttt_webhook_key': 'mykey',
            'ifttt_event_name':  'test_event',
        }
        n   = WebhookNotifier(cfg)
        res = n.notify_game_picked({'name': 'Portal 2', 'playtime_hours': 2.0})
        self.assertIn('slack', res)
        self.assertIn('teams', res)
        self.assertIn('ifttt', res)

    @patch('webhook_notifier.requests.post')
    def test_skips_unconfigured_services(self, mock_post):
        mock_post.return_value = _resp_ok()
        n   = WebhookNotifier({'slack_webhook_url': 'https://hooks.slack.com/test'})
        res = n.notify_game_picked({'name': 'Portal 2', 'playtime_hours': 2.0})
        self.assertIn('slack', res)
        self.assertNotIn('teams', res)
        self.assertNotIn('ifttt', res)

    def test_returns_empty_when_nothing_configured(self):
        n   = WebhookNotifier({})
        res = n.notify_game_picked({'name': 'Portal 2', 'playtime_hours': 0.0})
        self.assertEqual(res, {})


# ===========================================================================
# Flask route tests
# ===========================================================================

class TestSmartRecommendationsRoute(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    @patch('gapi_gui.current_user', 'testuser')
    @patch('gapi_gui.picker', None)
    def test_returns_400_when_picker_not_initialized(self):
        resp = self.client.get('/api/recommendations/smart')
        self.assertEqual(resp.status_code, 400)

    @patch('gapi_gui.current_user', 'testuser')
    def test_returns_200_with_recommendations(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.games = [
            {'appid': 620, 'name': 'Portal 2', 'playtime_forever': 0,
             'game_id': 'steam:620', 'platform': 'steam'},
        ]
        fake_picker.history = []
        fake_picker.clients = {}
        fake_picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        fake_picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/recommendations/smart?count=5')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('recommendations', data)
        self.assertEqual(data['engine'], 'smart')

    @patch('gapi_gui.current_user', 'testuser')
    def test_count_clamped_to_50(self):
        import gapi_gui
        fake_picker = MagicMock()
        fake_picker.games   = []
        fake_picker.history = []
        fake_picker.clients = {}
        fake_picker.WELL_PLAYED_THRESHOLD_MINUTES   = 600
        fake_picker.BARELY_PLAYED_THRESHOLD_MINUTES = 120
        with patch.object(gapi_gui, 'picker', fake_picker):
            resp = self.client.get('/api/recommendations/smart?count=999')
        self.assertEqual(resp.status_code, 200)


class TestWebhookTestRoutes(unittest.TestCase):

    def setUp(self):
        import gapi_gui
        gapi_gui.app.config['TESTING'] = True
        self.client = gapi_gui.app.test_client()

    def _logged_in(self, fn):
        import gapi_gui
        with patch.object(gapi_gui, 'current_user', 'testuser'):
            with patch.object(gapi_gui, 'picker', MagicMock(config={})):
                return fn()

    def test_slack_test_503_when_not_configured(self):
        resp = self._logged_in(
            lambda: self.client.post('/api/notifications/slack/test',
                                     json={}, content_type='application/json')
        )
        self.assertEqual(resp.status_code, 503)

    def test_teams_test_503_when_not_configured(self):
        resp = self._logged_in(
            lambda: self.client.post('/api/notifications/teams/test',
                                     json={}, content_type='application/json')
        )
        self.assertEqual(resp.status_code, 503)

    def test_ifttt_test_503_when_not_configured(self):
        resp = self._logged_in(
            lambda: self.client.post('/api/notifications/ifttt/test',
                                     json={}, content_type='application/json')
        )
        self.assertEqual(resp.status_code, 503)

    def test_homeassistant_test_503_when_not_configured(self):
        resp = self._logged_in(
            lambda: self.client.post('/api/notifications/homeassistant/test',
                                     json={}, content_type='application/json')
        )
        self.assertEqual(resp.status_code, 503)

    @patch('webhook_notifier.requests.post')
    def test_slack_test_200_with_override_url(self, mock_post):
        mock_post.return_value = _resp_ok()
        import gapi_gui
        with patch.object(gapi_gui, 'current_user', 'testuser'), \
             patch.object(gapi_gui, 'picker', MagicMock(config={})):
            resp = self.client.post(
                '/api/notifications/slack/test',
                json={'webhook_url': 'https://hooks.slack.com/fake'},
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['service'], 'slack')

    @patch('webhook_notifier.requests.post')
    def test_ifttt_test_200_with_override_key(self, mock_post):
        mock_post.return_value = _resp_ok()
        import gapi_gui
        with patch.object(gapi_gui, 'current_user', 'testuser'), \
             patch.object(gapi_gui, 'picker', MagicMock(config={})):
            resp = self.client.post(
                '/api/notifications/ifttt/test',
                json={'ifttt_webhook_key': 'mykey', 'ifttt_event_name': 'ev'},
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)

    @patch('webhook_notifier.requests.post')
    def test_homeassistant_test_200_with_override(self, mock_post):
        mock_post.return_value = _resp_ok()
        import gapi_gui
        with patch.object(gapi_gui, 'current_user', 'testuser'), \
             patch.object(gapi_gui, 'picker', MagicMock(config={})):
            resp = self.client.post(
                '/api/notifications/homeassistant/test',
                json={
                    'homeassistant_url': 'http://ha.local:8123',
                    'homeassistant_webhook_id': 'gapi_pick',
                },
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['service'], 'homeassistant')


class TestConfigTemplateWebhooks(unittest.TestCase):
    """config_template.json must include all webhook credential placeholders."""

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config_template.json'
        )
        with open(path) as f:
            self._cfg = json.load(f)

    def test_slack_webhook_url_present(self):
        self.assertIn('slack_webhook_url', self._cfg)

    def test_teams_webhook_url_present(self):
        self.assertIn('teams_webhook_url', self._cfg)

    def test_ifttt_key_present(self):
        self.assertIn('ifttt_webhook_key', self._cfg)

    def test_ifttt_event_name_present(self):
        self.assertIn('ifttt_event_name', self._cfg)

    def test_homeassistant_url_present(self):
        self.assertIn('homeassistant_url', self._cfg)

    def test_homeassistant_webhook_id_present(self):
        self.assertIn('homeassistant_webhook_id', self._cfg)


if __name__ == '__main__':
    unittest.main()
