"""Business logic for the marketplace domain.

A *listing* is a player (``seller``) offering an ``item`` for a fixed integer
coin ``price``, with an optional ``category``. Listings start ``active`` and may
later become ``sold`` or ``cancelled``. A *offer* records a ``buyer`` bidding an
integer coin ``amount`` on a listing.

Semantics (documented sensible defaults):

  * ``create_listing`` creates an ``active`` listing. ``item`` is required and
    ``price`` must be a non-negative integer, else :class:`MarketError` (400).
  * ``list_listings`` returns ``active`` listings (newest first), optionally
    filtered by ``category``. The legacy sentinel category ``"all"`` (and an
    empty/None value) means "no filter".
  * ``make_offer`` records a buyer's offer on a listing. The listing must exist
    (404) and be ``active``; a buyer may not bid on their own listing and the
    offer ``amount`` must be a non-negative integer (400).

Every function takes a SQLAlchemy ``db`` session as its first argument so the
caller (the FastAPI route handler) controls the session lifecycle. Validation
failures raise :class:`MarketError`, which carries an HTTP status code the
router maps onto a JSON error response.
"""
from typing import Any, Dict, List, Optional

from backend.models.market import FeatureMarketListing, FeatureMarketOffer

# Listing status constants
LISTING_ACTIVE = "active"
LISTING_SOLD = "sold"
LISTING_CANCELLED = "cancelled"

# Offer status constants
OFFER_PENDING = "pending"
OFFER_ACCEPTED = "accepted"
OFFER_REJECTED = "rejected"

# Sentinel category meaning "no filter" (legacy default query value).
_CATEGORY_ALL = "all"


class MarketError(Exception):
    """A marketplace operation failed. ``status_code`` is the HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _coerce_price(value: Any) -> int:
    """Coerce an incoming price/amount into a non-negative int.

    Raises:
        MarketError(400): not an integer-like value, or negative.
    """
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise MarketError(400, "Invalid price")
    try:
        price = int(value)
    except (ValueError, TypeError):
        raise MarketError(400, "Invalid price")
    if price < 0:
        raise MarketError(400, "Invalid price")
    return price


def _normalize_category(category: Optional[str]) -> Optional[str]:
    """Normalise a category string; None/blank/'all' -> None (no filter)."""
    if category is None:
        return None
    category = str(category).strip()
    if not category or category.lower() == _CATEGORY_ALL:
        return None
    return category


def _listing_to_dict(listing: FeatureMarketListing) -> Dict[str, Any]:
    """Serialise a listing ORM row into the API response shape."""
    return {
        "id": listing.id,
        "seller": listing.seller,
        "item": listing.item,
        "price": listing.price,
        "category": listing.category,
        "status": listing.status,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }


def _offer_to_dict(offer: FeatureMarketOffer) -> Dict[str, Any]:
    """Serialise an offer ORM row into the API response shape."""
    return {
        "id": offer.id,
        "listing_id": offer.listing_id,
        "buyer": offer.buyer,
        "amount": offer.amount,
        "status": offer.status,
        "created_at": offer.created_at.isoformat() if offer.created_at else None,
    }


def create_listing(db, seller: str, item: Any, price: Any,
                   category: Optional[str] = None) -> Dict[str, Any]:
    """Create a new ``active`` listing.

    Raises:
        MarketError(400): missing item, or invalid (non-int/negative) price.
    """
    item = (str(item).strip() if item is not None else "")
    if not item:
        raise MarketError(400, "Item is required")
    price = _coerce_price(price)
    category = _normalize_category(category)

    listing = FeatureMarketListing(
        seller=seller,
        item=item,
        price=price,
        category=category,
        status=LISTING_ACTIVE,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return _listing_to_dict(listing)


def list_listings(db, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return ``active`` listings (newest first), optionally by category."""
    query = db.query(FeatureMarketListing).filter(
        FeatureMarketListing.status == LISTING_ACTIVE)
    category = _normalize_category(category)
    if category is not None:
        query = query.filter(FeatureMarketListing.category == category)
    rows = query.order_by(
        FeatureMarketListing.created_at.desc(),
        FeatureMarketListing.id.desc()).all()
    return [_listing_to_dict(r) for r in rows]


def make_offer(db, listing_id: Any, buyer: str, amount: Any) -> Dict[str, Any]:
    """Record a buyer's offer on a listing.

    Raises:
        MarketError(404): no such listing.
        MarketError(400): buyer is the seller, listing not active, or invalid
            (non-int/negative) amount.
    """
    try:
        lid = int(listing_id)
    except (ValueError, TypeError):
        raise MarketError(404, "Listing not found")

    listing = db.query(FeatureMarketListing).filter(
        FeatureMarketListing.id == lid).first()
    if listing is None:
        raise MarketError(404, "Listing not found")
    if listing.status != LISTING_ACTIVE:
        raise MarketError(400, "Listing is not active")
    if listing.seller == buyer:
        raise MarketError(400, "Cannot make an offer on your own listing")

    amount = _coerce_price(amount)

    offer = FeatureMarketOffer(
        listing_id=listing.id,
        buyer=buyer,
        amount=amount,
        status=OFFER_PENDING,
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return _offer_to_dict(offer)
