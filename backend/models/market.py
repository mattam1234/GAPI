"""ORM models for the marketplace domain (FastAPI-era feature).

A *listing* is a player offering an item for sale at a fixed coin price. A
*offer* is another player bidding a coin ``amount`` on a listing.

Listing status lifecycle:  ``active`` -> ``sold`` | ``cancelled``.
Offer status lifecycle:    ``pending`` -> ``accepted`` | ``rejected``.

NOTE ON NAMING: ``database.py`` already defines legacy ORM classes named
``TradingMarket`` (table ``trading_markets``) and ``MarketOffer`` (table
``market_offers``). SQLAlchemy's single declarative registry (shared ``Base``)
forbids re-using either those class names or those table names. These
FastAPI-era models therefore use distinct, collision-free names
(``FeatureMarketListing`` / ``FeatureMarketOffer`` on the ``feature_market_*``
tables). The public API surface is unchanged; only the internal storage tables
differ from the never-populated legacy ones.

The models register on the shared ``database.Base`` simply by being imported;
``backend.routers.community`` imports this module, and
``backend.main.create_app``'s ``create_all`` hook builds the tables.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, String)
from sqlalchemy.orm import relationship

from database import Base


class FeatureMarketListing(Base):
    """A player-created sale listing for a single item."""
    __tablename__ = "feature_market_listings"

    id = Column(Integer, primary_key=True)
    seller = Column(String(255), nullable=False, index=True)
    item = Column(String(255), nullable=False)        # item name / app_id
    price = Column(Integer, nullable=False)           # coin price (int)
    category = Column(String(100), nullable=True, index=True)
    # status: 'active' | 'sold' | 'cancelled'
    status = Column(String(20), default='active', nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    offers = relationship(
        "FeatureMarketOffer", back_populates="listing",
        cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_feature_market_status_category', 'status', 'category'),
    )


class FeatureMarketOffer(Base):
    """A buyer's coin offer on a listing."""
    __tablename__ = "feature_market_offers"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("feature_market_listings.id"),
                        nullable=False, index=True)
    buyer = Column(String(255), nullable=False, index=True)
    amount = Column(Integer, nullable=False)          # offered coin amount (int)
    # status: 'pending' | 'accepted' | 'rejected'
    status = Column(String(20), default='pending', nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    listing = relationship("FeatureMarketListing", back_populates="offers")
