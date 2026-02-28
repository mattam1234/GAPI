"""Business logic for the wishlist and sale-alert features."""
import datetime
from typing import Any, Dict, List, Optional

from ..repositories.wishlist_repository import WishlistRepository


class WishlistService:
    """Manages wishlist entries and checks Steam prices for sale alerts,
    delegating persistence to
    :class:`~app.repositories.wishlist_repository.WishlistRepository`.

    Rules
    -----
    * ``target_price`` must be ``None`` or a non-negative float.
    * ``platform`` defaults to ``"steam"``.
    * ``check_sales`` requires a Steam client with a ``get_price_overview``
      method; non-Steam entries and entries with no price data are silently
      skipped.
    """

    def __init__(self, repository: WishlistRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, game_id: str, name: str,
            platform: str = 'steam',
            target_price: Optional[float] = None,
            notes: str = '') -> bool:
        """Add or update a wishlist entry.

        Returns:
            ``True`` on success; ``False`` if *target_price* is negative.
        """
        if target_price is not None and target_price < 0:
            return False
        entry: Dict = {
            'game_id': game_id,
            'name': name,
            'platform': platform,
            'added_date': datetime.date.today().strftime('%Y-%m-%d'),
            'target_price': target_price,
            'notes': notes,
        }
        self._repo.upsert(game_id, entry)
        return True

    def remove(self, game_id: str) -> bool:
        """Remove *game_id* from the wishlist.  Returns ``True`` if it existed."""
        return self._repo.delete(game_id)

    def get(self, game_id: str) -> Optional[Dict]:
        """Return the wishlist entry for *game_id*, or ``None``."""
        return self._repo.find(game_id)

    def get_all(self) -> Dict[str, Dict]:
        """Return all wishlist entries as ``{game_id: entry}``."""
        return self._repo.data

    def check_sales(self, steam_client: Any) -> List[Dict]:
        """Check current Steam prices and return entries that are on sale or
        at/below the user's target price.

        Args:
            steam_client: An object with a ``get_price_overview(app_id)``
                method (typically :class:`gapi.SteamAPIClient`).  Pass
                ``None`` to get an empty result without side-effects.

        Returns:
            List of wishlist entry dicts enriched with ``current_price_usd``,
            ``original_price_usd``, ``discount_percent``, ``formatted_price``,
            ``formatted_original``, and ``sale_reason``.
        """
        if steam_client is None:
            return []

        sales: List[Dict] = []
        for game_id, entry in self._repo.data.items():
            if entry.get('platform', 'steam') != 'steam':
                continue

            # Extract numeric app_id from composite id (e.g. "steam:620" → "620")
            raw_id = game_id
            if ':' in raw_id:
                raw_id = raw_id.split(':', 1)[1]

            price_data = steam_client.get_price_overview(raw_id)
            if not price_data:
                continue

            discount = price_data.get('discount_percent', 0)
            final_cents = price_data.get('final', 0)
            initial_cents = price_data.get('initial', 0)
            current_price = round(final_cents / 100, 2)
            original_price = round(initial_cents / 100, 2)
            target = entry.get('target_price')

            on_sale = discount > 0
            below_target = (target is not None and current_price <= target)

            if on_sale or below_target:
                reasons = []
                if on_sale:
                    reasons.append(
                        f"{discount}% off ({price_data.get('final_formatted', '')})"
                    )
                if below_target:
                    reasons.append(f"at or below your target of ${target:.2f}")
                result = dict(entry)
                result.update({
                    'current_price_usd': current_price,
                    'original_price_usd': original_price,
                    'discount_percent': discount,
                    'formatted_price': price_data.get('final_formatted', ''),
                    'formatted_original': price_data.get('initial_formatted', ''),
                    'sale_reason': ' and '.join(reasons),
                })
                sales.append(result)

        return sales
