#!/usr/bin/env python3
"""
Tests for the migrated budget-tracking domain (backend/routers/budget.py).

Covers the spending summary, set/update price, delete, and the legacy
validation contract (absent vs non-numeric vs negative price), plus the
path-style game_id. Auth is bridged via the Flask session cookie; the per-user
picker is stubbed.

Run with:
    python -m pytest tests/test_backend_budget.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import gapi_gui
from backend.main import app


def _session_cookie(username):
    serializer = gapi_gui.app.session_interface.get_signing_serializer(gapi_gui.app)
    return serializer.dumps({'username': username})


class _MemoryBudgetService:
    """In-memory stand-in mirroring app.services.budget_service.BudgetService."""
    def __init__(self):
        self._data = {}

    def set_entry(self, game_id, price, currency='USD', purchase_date='', notes=''):
        if price < 0:
            return False
        self._data[game_id] = {
            'game_id': game_id, 'price': round(float(price), 2),
            'currency': (currency.strip().upper() or 'USD'),
            'purchase_date': purchase_date or '', 'notes': notes,
        }
        return True

    def remove_entry(self, game_id):
        return self._data.pop(game_id, None) is not None

    def get_summary(self, all_games):
        name_map = {g.get('game_id', ''): g.get('name', '') for g in all_games}
        entries, totals = [], {}
        for gid, e in self._data.items():
            ec = dict(e)
            ec['name'] = name_map.get(gid, '')
            entries.append(ec)
            cur = e.get('currency', 'USD')
            totals[cur] = round(totals.get(cur, 0.0) + e.get('price', 0.0), 2)
        primary = max(totals, key=totals.get) if totals else 'USD'
        return {
            'total_spent': round(totals.get(primary, 0.0), 2),
            'primary_currency': primary,
            'currency_breakdown': totals,
            'game_count': len(self._data),
            'entries': entries,
        }


class _FakePicker:
    def __init__(self):
        self.budget_service = _MemoryBudgetService()
        self.games = [{'game_id': 'steam:620', 'name': 'Portal 2'}]


class BackendBudgetTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.picker = _FakePicker()
        self._patch = patch.object(gapi_gui, 'ensure_picker_initialized',
                                   return_value=self.picker)
        self._patch.start()
        self.client.cookies.set('session', _session_cookie('alice'))

    def tearDown(self):
        self._patch.stop()

    # --- auth ------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get('/api/budget').status_code, 401)

    # --- summary / set / delete -----------------------------------------

    def test_empty_summary(self):
        resp = self.client.get('/api/budget')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['game_count'], 0)
        self.assertEqual(body['total_spent'], 0)
        self.assertEqual(body['entries'], [])

    def test_set_then_summary(self):
        resp = self.client.post('/api/budget/steam:620',
                                json={'price': 14.99, 'currency': 'usd'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'success': True, 'game_id': 'steam:620', 'price': 14.99})

        summary = self.client.get('/api/budget').json()
        self.assertEqual(summary['game_count'], 1)
        self.assertEqual(summary['total_spent'], 14.99)
        self.assertEqual(summary['primary_currency'], 'USD')
        self.assertEqual(summary['entries'][0]['name'], 'Portal 2')

    def test_put_upserts(self):
        self.client.post('/api/budget/g1', json={'price': 5})
        self.client.put('/api/budget/g1', json={'price': 9})
        self.assertEqual(self.client.get('/api/budget').json()['total_spent'], 9)

    def test_delete_then_404(self):
        self.client.post('/api/budget/g2', json={'price': 1})
        self.assertEqual(self.client.delete('/api/budget/g2').status_code, 200)
        self.assertEqual(self.client.delete('/api/budget/g2').status_code, 404)

    # --- validation parity ----------------------------------------------

    def test_absent_price_is_required(self):
        resp = self.client.post('/api/budget/g3', json={'currency': 'USD'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price is required', resp.json()['detail'])

    def test_null_price_must_be_a_number(self):
        resp = self.client.post('/api/budget/g4', json={'price': None})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price must be a number', resp.json()['detail'])

    def test_non_numeric_price_must_be_a_number(self):
        resp = self.client.post('/api/budget/g5', json={'price': 'free'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('price must be a number', resp.json()['detail'])

    def test_negative_price_rejected(self):
        resp = self.client.post('/api/budget/g6', json={'price': -3})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('must not be negative', resp.json()['detail'])


if __name__ == '__main__':
    unittest.main()
