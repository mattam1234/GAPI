"""ORM models for the storefront cluster (FastAPI-era persistent features).

Three small domains share this module and the ``database.Base`` metadata:

  * **shop**      — :class:`StorefrontShopItem` (a purchasable catalog entry) and
    :class:`StorefrontPurchase` (a user's ownership record of a one-time item).
  * **events**    — :class:`StorefrontSeasonalEvent` (a time-boxed event) and
    :class:`StorefrontEventClaim` (a user's once-only claim of an event reward).
  * **cosmetics** — :class:`StorefrontUserCosmetics` (a user's currently applied theme).

These replace the old stub handlers in ``backend/routers/misc.py`` that faked
success against a never-defined ``gapi_gui.db_service``. The tables are real and
persistent.

Table names are prefixed ``storefront_*`` to avoid colliding with any legacy
SQL tables (the legacy stub referenced ``shop_items`` / ``user_inventory``
strings that were never actually created in this app, but the prefix keeps us
safe regardless).

The models register on the shared ``database.Base`` simply by being imported;
``backend.routers.misc`` imports this module, and
``backend.main.create_app``'s ``create_all`` hook builds the tables.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from database import Base


# ── shop ─────────────────────────────────────────────────────────────────────

class StorefrontShopItem(Base):
    """A purchasable item in the shop catalog."""
    __tablename__ = "storefront_shop_items"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    price = Column(Integer, nullable=False, default=0)
    category = Column(String(64), nullable=False, default="cosmetic")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StorefrontPurchase(Base):
    """A record that ``username`` owns shop item ``item_id`` (one-time items)."""
    __tablename__ = "storefront_purchases"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("username", "item_id", name="uq_storefront_purchase"),
        Index("idx_storefront_purchase_user_item", "username", "item_id"),
    )


# ── events ───────────────────────────────────────────────────────────────────

class StorefrontSeasonalEvent(Base):
    """A time-boxed seasonal event whose reward a user may claim once."""
    __tablename__ = "storefront_seasonal_events"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    season = Column(String(64), nullable=False, default="season")
    reward = Column(String(255), nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True, index=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StorefrontEventClaim(Base):
    """A record that ``username`` claimed the reward for ``event_id`` (once)."""
    __tablename__ = "storefront_event_claims"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    event_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("username", "event_id", name="uq_storefront_event_claim"),
        Index("idx_storefront_claim_user_event", "username", "event_id"),
    )


# ── cosmetics ────────────────────────────────────────────────────────────────

class StorefrontUserCosmetics(Base):
    """A user's currently applied cosmetic theme (one row per user)."""
    __tablename__ = "storefront_user_cosmetics"

    username = Column(String(255), primary_key=True)
    theme = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
