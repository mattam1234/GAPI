"""Business logic for game purchase / budget tracking."""
from typing import Dict, List, Optional

from ..repositories.budget_repository import BudgetRepository


class BudgetService:
    """Records game purchase prices and generates spending summaries,
    delegating persistence to
    :class:`~app.repositories.budget_repository.BudgetRepository`.

    Rules
    -----
    * ``price`` must be a non-negative float (0 = free / gifted).
    * ``currency`` defaults to ``"USD"``; it is stored upper-cased.
    * ``purchase_date`` is an optional ISO date string.
    """

    def __init__(self, repository: BudgetRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_entry(self, game_id: str, price: float,
                  currency: str = 'USD',
                  purchase_date: str = '',
                  notes: str = '') -> bool:
        """Record or update the purchase price for *game_id*.

        Returns:
            ``True`` on success; ``False`` if *price* is negative.
        """
        if price < 0:
            return False
        entry: Dict = {
            'game_id': game_id,
            'price': round(float(price), 2),
            'currency': (currency.strip().upper() or 'USD'),
            'purchase_date': purchase_date or '',
            'notes': notes,
        }
        self._repo.upsert(game_id, entry)
        return True

    def remove_entry(self, game_id: str) -> bool:
        """Remove the budget entry for *game_id*.  Returns ``True`` if it existed."""
        return self._repo.delete(game_id)

    def get_entry(self, game_id: str) -> Optional[Dict]:
        """Return the budget entry for *game_id*, or ``None``."""
        return self._repo.find(game_id)

    def get_summary(self, all_games: List[Dict]) -> Dict:
        """Compute an aggregated spending summary.

        Args:
            all_games: The picker's full game list (used to look up names).

        Returns:
            A dict with keys ``total_spent``, ``primary_currency``,
            ``currency_breakdown``, ``game_count``, and ``entries`` (sorted by
            purchase date, newest first, each entry enriched with ``name``).
        """
        name_map: Dict[str, str] = {
            g.get('game_id', ''): g.get('name', '') for g in all_games
        }

        entries = []
        currency_totals: Dict[str, float] = {}
        for game_id, entry in self._repo.data.items():
            entry_copy = dict(entry)
            entry_copy['name'] = name_map.get(game_id, '')
            entries.append(entry_copy)
            cur = entry.get('currency', 'USD')
            currency_totals[cur] = round(
                currency_totals.get(cur, 0.0) + entry.get('price', 0.0), 2
            )

        primary_currency = (
            max(currency_totals, key=currency_totals.get)  # type: ignore[arg-type]
            if currency_totals else 'USD'
        )
        total_spent = currency_totals.get(primary_currency, 0.0)

        return {
            'total_spent': round(total_spent, 2),
            'primary_currency': primary_currency,
            'currency_breakdown': currency_totals,
            'game_count': len(self._repo.data),
            'entries': sorted(
                entries,
                key=lambda e: e.get('purchase_date', ''),
                reverse=True,
            ),
        }
