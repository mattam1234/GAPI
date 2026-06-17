#!/usr/bin/env python3
"""Regression checks for the empty-state UX standard.

Terminal "nothing here yet" views should use the semantic `.empty-state`
class, not `.loading` (which is for in-progress states). This pins the Tier A
migration described in docs/UX_EMPTY_STATE_AUDIT.md so the migrated data views
don't regress back to `class="loading"`.
"""
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestEmptyStateStandard(unittest.TestCase):
    def setUp(self):
        self.css = (REPO_ROOT / 'static' / 'style.css').read_text(encoding='utf-8')
        self.js = (REPO_ROOT / 'static' / 'main.js').read_text(encoding='utf-8')

    def test_css_styles_empty_state_inside_list_container(self):
        # The empty-state class must be rendered by the shared list-container
        # rule so it is visually identical to the prior .loading/.dash-empty card.
        self.assertIn('.list-container > .empty-state', self.css)
        self.assertIn('.list-container > .empty-state::before', self.css)

    def test_migrated_views_use_empty_state_class(self):
        for snippet in (
            '<div class="empty-state">No users yet',
            '<div class="empty-state">No list selected yet',
            '<div class="empty-state">No list entries yet',
        ):
            self.assertIn(snippet, self.js)

    def test_migrated_views_no_longer_use_loading_for_empty(self):
        for snippet in (
            '<div class="loading">No users yet',
            '<div class="loading">No list selected yet',
            '<div class="loading">No list entries yet',
        ):
            self.assertNotIn(snippet, self.js)


if __name__ == '__main__':
    unittest.main()
