"""ORM models for the engagement cluster (FastAPI-era features).

Six small engagement domains, each backed by a real per-user table on the
shared ``database.Base``. Table/class names are prefixed (``Engagement*`` /
``engagement_*``) to avoid colliding with any legacy tables of similar names
(e.g. the legacy ``stream_vods`` / ``ranked_ratings`` raw-SQL tables the old
stubs referenced).

Class names are prefixed ``Engagement*`` because a legacy ``ReferralCode``
class already exists on the shared declarative ``Base`` (in ``database.py``);
prefixing every class keeps the registry unambiguous.

Models:
  * :class:`EngagementBattlePassProgress`   — engagement_battlepass_progress
        per-user battle-pass xp / tier / claimed-levels for the current season.
  * :class:`EngagementCreatorApplication`   — engagement_creator_applications
        a user's application to the creator program (status lifecycle).
  * :class:`EngagementReferralCode`         — engagement_referral_codes
        a user's unique, get-or-created referral code.
  * :class:`EngagementReferralRedemption`   — engagement_referral_redemptions
        a (code, redeemer) redemption; a user may redeem at most once.
  * :class:`EngagementStreamSession`        — engagement_stream_sessions
        a live / ended streaming session (the "VOD" once ended).
  * :class:`EngagementProgressionState`     — engagement_progression_state
        a user's overall progression level / xp (lazy-created with defaults).
  * :class:`EngagementRankedStanding`       — engagement_ranked_standings
        a user's ranked rating / win-loss record (lazy-created with defaults).

Each model registers on ``database.Base`` simply by being imported;
``backend.routers.engagement`` imports this module, and
``backend.main.create_app``'s ``create_all`` hook builds the tables.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint

from database import Base


class EngagementBattlePassProgress(Base):
    """A user's battle-pass progress for a given season.

    ``claimed_levels`` is a JSON-encoded list of integer levels already claimed.
    ``tier`` is the user's current battle-pass tier (a.k.a. level reached).
    """
    __tablename__ = "engagement_battlepass_progress"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    season = Column(Integer, nullable=False, default=1)
    xp = Column(Integer, nullable=False, default=0)
    tier = Column(Integer, nullable=False, default=1)
    claimed_levels = Column(Text, nullable=False, default="[]")  # JSON list[int]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("username", "season", name="uq_battlepass_user_season"),
    )


class EngagementCreatorApplication(Base):
    """A user's application to the creator program.

    status: 'pending' | 'approved' | 'rejected'. Re-applying is idempotent and
    returns the existing application.
    """
    __tablename__ = "engagement_creator_applications"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EngagementReferralCode(Base):
    """A user's unique referral code (get-or-created on first read)."""
    __tablename__ = "engagement_referral_codes"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EngagementReferralRedemption(Base):
    """A redemption of a referral ``code`` by a ``redeemer``.

    A given redeemer may redeem at most once overall (enforced by the unique
    constraint on ``redeemer``); ``code`` records which code they used.
    """
    __tablename__ = "engagement_referral_redemptions"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), nullable=False, index=True)
    redeemer = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EngagementStreamSession(Base):
    """A streaming session. ``status`` is 'live' until it ends.

    Once ended, ``ended_at`` is set and the row represents a VOD.
    """
    __tablename__ = "engagement_stream_sessions"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="")
    status = Column(String(20), nullable=False, default="live")  # 'live' | 'ended'
    stream_url = Column(String(512), nullable=False, default="")
    views = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)


class EngagementProgressionState(Base):
    """A user's overall progression state (lazy-created with defaults)."""
    __tablename__ = "engagement_progression_state"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    level = Column(Integer, nullable=False, default=1)
    xp = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EngagementRankedStanding(Base):
    """A user's ranked standing (lazy-created with defaults)."""
    __tablename__ = "engagement_ranked_standings"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    rating = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
