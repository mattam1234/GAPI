"""ORM models for the tournaments domain (FastAPI-era feature).

These extend the shared SQLAlchemy ``Base`` from the legacy ``database`` module,
so they live on the same metadata/engine. The models register on
``database.Base.metadata`` simply by being imported; the tournaments router
imports this module, and ``backend.main.create_app`` runs an idempotent
``create_all`` after all routers load, so the tables exist.

Status lifecycle (see ``app/services/tournament_service.py`` for the rules):

    upcoming  ->  open (registration)  ->  active  ->  completed

Tables:
  * ``feature_tournaments``               — one row per tournament
  * ``feature_tournament_registrations``  — one row per (tournament, user)
                                             registration, unique on
                                             (tournament_id, username)

NOTE: the legacy ``database`` module already defines unrelated, unused
``tournaments`` / ``tournament_participants`` tables with a different schema.
To stay conflict-free (and avoid editing ``database.py``), this real feature
uses its own ``feature_tournaments`` / ``feature_tournament_registrations``
tables on the shared metadata.
"""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class FeatureTournament(Base):
    """A tournament with a registration / play lifecycle.

    Named ``FeatureTournament`` (not ``Tournament``) because the legacy
    ``database`` module already registers an unrelated ``Tournament`` class on
    the shared declarative ``Base``; distinct class names keep the registry
    unambiguous.
    """
    __tablename__ = "feature_tournaments"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    game = Column(String(255), nullable=True)
    # lifecycle: 'upcoming' -> 'open' -> 'active' -> 'completed'
    status = Column(String(50), default='upcoming', nullable=False, index=True)
    starts_at = Column(DateTime, nullable=True)
    max_players = Column(Integer, nullable=True)        # None = unlimited
    created_by = Column(String(255), nullable=True)     # username of creator
    created_at = Column(DateTime, default=datetime.utcnow)

    registrations = relationship(
        "FeatureTournamentRegistration",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )


class FeatureTournamentRegistration(Base):
    """A single user's registration for a tournament."""
    __tablename__ = "feature_tournament_registrations"

    id = Column(Integer, primary_key=True)
    tournament_id = Column(
        Integer, ForeignKey("feature_tournaments.id"), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    registered_at = Column(DateTime, default=datetime.utcnow)

    tournament = relationship("FeatureTournament", back_populates="registrations")

    __table_args__ = (
        UniqueConstraint(
            'tournament_id', 'username', name='uq_tournament_registration'),
    )
