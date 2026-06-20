"""Business logic for the storefront cluster: shop, events, cosmetics.

These are the real, persistent replacements for the old stub handlers in
``backend/routers/misc.py``. Every function takes a SQLAlchemy ``db`` session as
its first argument so the caller (the FastAPI route handler) controls the
session lifecycle. Validation failures raise :class:`StorefrontError`, which
carries an HTTP status code the router maps onto JSON error responses.

Domains
-------
shop
    A catalog of :class:`StorefrontShopItem` rows (seeded with sensible defaults on first
    use). ``list_items`` reports each item plus whether the caller owns it.
    ``purchase`` records a :class:`StorefrontPurchase`; items are one-time, so a second
    purchase of the same item is a 409. Buying an unknown / inactive item is a
    404.
events
    A catalog of :class:`StorefrontSeasonalEvent` rows (seeded on first use).
    ``list_active_events`` reports active events plus whether the caller has
    claimed each. ``claim_event`` records an :class:`StorefrontEventClaim` once; an
    unknown or inactive event is a 404 and a repeat claim is a 409.
cosmetics
    A single :class:`StorefrontUserCosmetics` row per user. ``apply_theme`` validates the
    theme id against the allowed set (400) and upserts the user's theme.

Item / event catalogs are persisted on first use via the ``_seed_*`` helpers so
the GET endpoints return real, stable data without a separate migration step.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.models.storefront import (
    StorefrontEventClaim,
    StorefrontPurchase,
    StorefrontSeasonalEvent,
    StorefrontShopItem,
    StorefrontUserCosmetics,
)


class StorefrontError(Exception):
    """A storefront operation failed. ``status_code`` is the HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── default catalogs (persisted on first use) ────────────────────────────────

# Cosmetic theme ids the app recognises for apply-theme.
VALID_THEMES = {"default", "neon", "dark", "spring", "anniversary"}

# (name, icon, price, currency, category, active, premium)
# icon/currency/premium are presentation-only and recomputed at serialise time
# from category; they are not stored on the row (only the structural columns are).
_DEFAULT_SHOP_ITEMS = [
    {"name": "Dark Neon Theme", "price": 500, "category": "cosmetic", "active": True},
    {"name": "Legendary Title", "price": 100, "category": "premium", "active": True},
]

# (name, season, reward, active, days_left)
_DEFAULT_EVENTS = [
    {"name": "Spring Festival 2026", "season": "spring",
     "reward": "🌸 Spring Bloom Theme", "active": True, "days_left": 15},
    {"name": "Anniversary Celebration", "season": "year",
     "reward": "🎂 Anniversary Badge", "active": True, "days_left": 5},
]


def _seed_shop_items(db) -> None:
    """Persist the default shop catalog once (no-op if any item exists)."""
    if db.query(StorefrontShopItem.id).first() is not None:
        return
    for spec in _DEFAULT_SHOP_ITEMS:
        db.add(StorefrontShopItem(name=spec["name"], price=spec["price"],
                        category=spec["category"], active=spec["active"]))
    db.commit()


def _seed_events(db) -> None:
    """Persist the default seasonal-event catalog once (no-op if any exists)."""
    if db.query(StorefrontSeasonalEvent.id).first() is not None:
        return
    now = datetime.utcnow()
    for spec in _DEFAULT_EVENTS:
        db.add(StorefrontSeasonalEvent(
            name=spec["name"], season=spec["season"], reward=spec["reward"],
            active=spec["active"], starts_at=now,
            ends_at=now + timedelta(days=spec["days_left"])))
    db.commit()


# ── serialisation helpers (preserve legacy response keys) ────────────────────

def _icon_for(category: str) -> str:
    return "👑" if category == "premium" else "🎨"


def _currency_for(category: str) -> str:
    return "coins" if category == "premium" else "xp"


def _shop_item_dict(item: StorefrontShopItem, owned: bool) -> Dict[str, Any]:
    """Serialise a StorefrontShopItem into the legacy shop response shape."""
    return {
        "id": str(item.id),
        "icon": _icon_for(item.category),
        "name": item.name,
        "price": item.price,
        "currency": _currency_for(item.category),
        "premium": item.category == "premium",
        "owned": owned,
    }


def _days_left(event: StorefrontSeasonalEvent) -> int:
    if not event.ends_at:
        return 0
    return max(0, (event.ends_at - datetime.utcnow()).days)


def _event_dict(event: StorefrontSeasonalEvent, claimed: bool) -> Dict[str, Any]:
    """Serialise a StorefrontSeasonalEvent into the legacy seasonal-events response shape."""
    return {
        "id": event.id,
        "name": event.name,
        "season": event.season,
        "reward": event.reward,
        "days_left": _days_left(event),
        "reward_claimed": claimed,
    }


# ── shop ─────────────────────────────────────────────────────────────────────

def list_items(db, username: str) -> List[Dict[str, Any]]:
    """Return all active shop items, each flagged with the caller's ownership."""
    _seed_shop_items(db)
    items = (db.query(StorefrontShopItem)
             .filter(StorefrontShopItem.active.is_(True))
             .order_by(StorefrontShopItem.id.asc())
             .all())
    owned_ids = {
        p.item_id for p in db.query(StorefrontPurchase).filter(StorefrontPurchase.username == username)
    }
    return [_shop_item_dict(it, it.id in owned_ids) for it in items]


def purchase_item(db, username: str, item_id: Any) -> Dict[str, Any]:
    """Buy a one-time shop item for *username*.

    Raises:
        StorefrontError(400): missing / non-integer item id.
        StorefrontError(404): no such active item.
        StorefrontError(409): the user already owns the item.
    """
    _seed_shop_items(db)
    if item_id in (None, ""):
        raise StorefrontError(400, "Item ID required")
    try:
        iid = int(item_id)
    except (ValueError, TypeError):
        raise StorefrontError(404, "Item not found")

    item = (db.query(StorefrontShopItem)
            .filter(StorefrontShopItem.id == iid, StorefrontShopItem.active.is_(True))
            .first())
    if item is None:
        raise StorefrontError(404, "Item not found")

    already = (db.query(StorefrontPurchase)
               .filter(StorefrontPurchase.username == username, StorefrontPurchase.item_id == iid)
               .first())
    if already is not None:
        raise StorefrontError(409, "Already owned")

    db.add(StorefrontPurchase(username=username, item_id=iid))
    db.commit()
    return {"success": True, "message": "Purchase successful",
            "item_id": str(iid), "item_name": item.name}


# ── events ───────────────────────────────────────────────────────────────────

def list_active_events(db, username: str) -> List[Dict[str, Any]]:
    """Return all active seasonal events, each flagged with the caller's claim."""
    _seed_events(db)
    events = (db.query(StorefrontSeasonalEvent)
              .filter(StorefrontSeasonalEvent.active.is_(True))
              .order_by(StorefrontSeasonalEvent.id.asc())
              .all())
    claimed_ids = {
        c.event_id for c in db.query(StorefrontEventClaim).filter(StorefrontEventClaim.username == username)
    }
    return [_event_dict(e, e.id in claimed_ids) for e in events]


def claim_event(db, username: str, event_id: Any) -> Dict[str, Any]:
    """Claim the reward for an active event, once.

    Raises:
        StorefrontError(404): unknown or inactive event (or bad id).
        StorefrontError(409): the user already claimed this event.
    """
    _seed_events(db)
    try:
        eid = int(event_id)
    except (ValueError, TypeError):
        raise StorefrontError(404, "Event not found")

    event = (db.query(StorefrontSeasonalEvent)
             .filter(StorefrontSeasonalEvent.id == eid, StorefrontSeasonalEvent.active.is_(True))
             .first())
    if event is None:
        raise StorefrontError(404, "Event not found")

    already = (db.query(StorefrontEventClaim)
               .filter(StorefrontEventClaim.username == username, StorefrontEventClaim.event_id == eid)
               .first())
    if already is not None:
        raise StorefrontError(409, "Reward already claimed")

    db.add(StorefrontEventClaim(username=username, event_id=eid))
    db.commit()
    return {"success": True, "message": "Event reward claimed!",
            "reward": event.reward}


# ── cosmetics ────────────────────────────────────────────────────────────────

def apply_theme(db, username: str, theme_id: Any) -> Dict[str, Any]:
    """Validate and upsert the user's applied cosmetic theme.

    Raises:
        StorefrontError(400): missing theme id, or an unrecognised theme id.
    """
    if not theme_id:
        raise StorefrontError(400, "Theme ID required")
    theme = str(theme_id)
    if theme not in VALID_THEMES:
        raise StorefrontError(400, "Invalid theme")

    row = db.query(StorefrontUserCosmetics).filter(StorefrontUserCosmetics.username == username).first()
    if row is None:
        db.add(StorefrontUserCosmetics(username=username, theme=theme))
    else:
        row.theme = theme
    db.commit()
    return {"success": True, "message": "Theme applied", "theme_id": theme}


def get_theme(db, username: str) -> Dict[str, Any]:
    """Return the user's current theme (defaulting to ``default`` if unset)."""
    row = db.query(StorefrontUserCosmetics).filter(StorefrontUserCosmetics.username == username).first()
    return {"theme_id": row.theme if row else "default"}
