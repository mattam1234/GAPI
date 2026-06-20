"""ORM model for the trades domain (FastAPI-era feature).

A *trade* is an offer from one GAPI user (``from_user``) to another
(``to_user``) to swap one or more games. ``from_user`` puts up ``offered_items``
and asks for ``requested_items`` in return. Both item lists are stored as JSON
text (the same text-backed-JSON convention the rest of ``database.py`` uses for
SQLite/PostgreSQL portability).

Status lifecycle:  ``pending`` -> ``accepted`` | ``declined``.

The model registers on the shared ``database.Base`` simply by being imported;
``backend.routers.trades`` imports this module, and
``backend.main.create_app``'s ``create_all`` hook builds the table.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Index

from database import Base


class Trade(Base):
    """A game-swap offer between two users."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    from_user = Column(String(255), nullable=False, index=True)  # proposer
    to_user = Column(String(255), nullable=False, index=True)    # recipient
    offered_items = Column(Text, nullable=False, default='[]')   # JSON list
    requested_items = Column(Text, nullable=False, default='[]')  # JSON list
    # status: 'pending' | 'accepted' | 'declined'
    status = Column(String(20), default='pending', nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_trade_from_to', 'from_user', 'to_user'),
    )
