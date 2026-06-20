"""ORM models for the community domain (guilds + teams).

These extend the *same* SQLAlchemy ``Base`` declared in the legacy ``database``
module, so they share its metadata/engine. Tables auto-create via the idempotent
``create_all`` hook in :func:`backend.main.create_app` — but only because the
community router imports this module, registering the models on the shared
metadata. See ``backend/models/__init__.py``.

NOTE ON NAMING: ``database.py`` already defines legacy ORM classes named
``Guild``/``GuildMember``/``Team``/``TeamMembership`` bound to the tables
``guilds``/``guild_members``/``teams``/``team_memberships``. SQLAlchemy's single
declarative registry (shared ``Base``) forbids re-using either those class names
or those table names. These FastAPI-era models therefore use distinct,
collision-free names (``Community*`` classes on ``community_*`` tables). The
public API surface (request/response shapes, route names) is unchanged; only the
internal storage tables differ from the never-populated legacy ones.

Conventions mirror the existing models in ``database.py``: integer primary keys,
``String``/``Text`` columns, and ``DateTime`` timestamps defaulting to
``datetime.utcnow``.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from database import Base


class CommunityGuild(Base):
    """A player guild owned by a single user."""
    __tablename__ = "community_guilds"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    owner = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship(
        "CommunityGuildMember", back_populates="guild",
        cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_community_guild_owner_name"),
    )


class CommunityGuildMember(Base):
    """Membership record linking a user to a guild."""
    __tablename__ = "community_guild_members"

    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("community_guilds.id"),
                      nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    role = Column(String(50), default="member")   # 'owner' | 'member'
    joined_at = Column(DateTime, default=datetime.utcnow)

    guild = relationship("CommunityGuild", back_populates="members")

    __table_args__ = (
        UniqueConstraint("guild_id", "username", name="uq_community_guild_member"),
    )


class CommunityTeam(Base):
    """A team owned by a single user."""
    __tablename__ = "community_teams"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    owner = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship(
        "CommunityTeamMember", back_populates="team",
        cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_community_team_owner_name"),
    )


class CommunityTeamMember(Base):
    """Membership record linking a user to a team."""
    __tablename__ = "community_team_members"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("community_teams.id"),
                     nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

    team = relationship("CommunityTeam", back_populates="members")

    __table_args__ = (
        UniqueConstraint("team_id", "username", name="uq_community_team_member"),
    )
