"""Business logic for the community domain (guilds + teams).

Functions take a SQLAlchemy ``db`` session plus plain arguments and return plain
data (dicts / lists / model instances), leaving the session lifecycle to the
caller (the FastAPI router). This mirrors the convention used by the other
``app/services`` modules.

Rules enforced:
  * A user cannot own two guilds (or teams) with the same name — a
    ``ValueError`` is raised on a duplicate-name create for the same owner.
  * The creator is auto-joined as the owner/admin of the guild/team they create.
  * Joining is idempotent: re-joining an already-joined guild/team succeeds
    without inserting a duplicate membership row.
  * Joining a non-existent guild/team raises ``LookupError`` (mapped to 404 by
    the router).
"""
from typing import List, Optional

from backend.models.community import (CommunityGuild, CommunityGuildMember,
                                       CommunityTeam, CommunityTeamMember)


# ── serialization helpers ────────────────────────────────────────────────────

def _guild_to_dict(db, guild: CommunityGuild, *, username: Optional[str] = None) -> dict:
    """Serialize a guild plus its membership summary."""
    members = list(guild.members)
    role = None
    is_member = False
    if username is not None:
        for m in members:
            if m.username == username:
                role = m.role
                is_member = True
                break
    return {
        "id": guild.id,
        "name": guild.name,
        "description": guild.description or "",
        "owner": guild.owner,
        "members": len(members),
        "role": role,
        "is_member": is_member,
        "created_at": guild.created_at.isoformat() if guild.created_at else None,
    }


def _team_to_dict(db, team: CommunityTeam, *, username: Optional[str] = None) -> dict:
    """Serialize a team plus its membership summary."""
    members = list(team.members)
    is_member = (username is not None
                 and any(m.username == username for m in members))
    return {
        "id": str(team.id),
        "name": team.name,
        "owner": team.owner,
        "members": [m.username for m in members],
        "is_member": is_member,
        "created_at": team.created_at.isoformat() if team.created_at else None,
    }


# ── guilds ────────────────────────────────────────────────────────────────────

def create_guild(db, owner: str, name: str,
                 description: str = "") -> CommunityGuild:
    """Create a guild owned by *owner*; auto-join *owner* as ``owner`` role.

    Raises:
        ValueError: if *name* is empty, or *owner* already has a guild with
            that name.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Guild name required")

    existing = db.query(CommunityGuild).filter(
        CommunityGuild.owner == owner,
        CommunityGuild.name == name,
    ).first()
    if existing is not None:
        raise ValueError(f'You already own a guild named "{name}"')

    guild = CommunityGuild(name=name, description=(description or "").strip(),
                           owner=owner)
    db.add(guild)
    db.flush()  # assign guild.id
    db.add(CommunityGuildMember(guild_id=guild.id, username=owner, role="owner"))
    db.commit()
    db.refresh(guild)
    return guild


def join_guild(db, guild_id: int, username: str) -> CommunityGuild:
    """Add *username* to the guild (idempotent).

    Raises:
        LookupError: if the guild does not exist.
    """
    guild = db.query(CommunityGuild).filter(CommunityGuild.id == guild_id).first()
    if guild is None:
        raise LookupError(f"Guild {guild_id} not found")

    existing = db.query(CommunityGuildMember).filter(
        CommunityGuildMember.guild_id == guild_id,
        CommunityGuildMember.username == username,
    ).first()
    if existing is None:
        db.add(CommunityGuildMember(guild_id=guild_id, username=username,
                                    role="member"))
        db.commit()
        db.refresh(guild)
    return guild


def list_guilds_for_user(db, username: str) -> dict:
    """Return the user's guild (if any) plus other guilds to recommend.

    Shape mirrors the original stub: ``{'my_guild': {...}|None,
    'recommended_guilds': [...]}``.
    """
    my_membership = db.query(CommunityGuildMember).filter(
        CommunityGuildMember.username == username,
    ).first()

    my_guild = None
    my_guild_id = None
    if my_membership is not None:
        guild = db.query(CommunityGuild).filter(
            CommunityGuild.id == my_membership.guild_id).first()
        if guild is not None:
            my_guild_id = guild.id
            my_guild = _guild_to_dict(db, guild, username=username)

    recommended_query = db.query(CommunityGuild)
    if my_guild_id is not None:
        recommended_query = recommended_query.filter(
            CommunityGuild.id != my_guild_id)
    recommended = recommended_query.order_by(
        CommunityGuild.created_at.desc()).limit(10).all()

    return {
        "my_guild": my_guild,
        "recommended_guilds": [
            _guild_to_dict(db, g, username=username) for g in recommended
        ],
    }


# ── teams ─────────────────────────────────────────────────────────────────────

def create_team(db, owner: str, name: str) -> CommunityTeam:
    """Create a team owned by *owner*; auto-join *owner* as a member.

    Raises:
        ValueError: if *name* is empty, or *owner* already has a team with
            that name.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Team name required")

    existing = db.query(CommunityTeam).filter(
        CommunityTeam.owner == owner,
        CommunityTeam.name == name,
    ).first()
    if existing is not None:
        raise ValueError(f'You already own a team named "{name}"')

    team = CommunityTeam(name=name, owner=owner)
    db.add(team)
    db.flush()  # assign team.id
    db.add(CommunityTeamMember(team_id=team.id, username=owner))
    db.commit()
    db.refresh(team)
    return team


def join_team(db, team_id: int, username: str) -> CommunityTeam:
    """Add *username* to the team (idempotent).

    Raises:
        LookupError: if the team does not exist.
    """
    team = db.query(CommunityTeam).filter(CommunityTeam.id == team_id).first()
    if team is None:
        raise LookupError(f"Team {team_id} not found")

    existing = db.query(CommunityTeamMember).filter(
        CommunityTeamMember.team_id == team_id,
        CommunityTeamMember.username == username,
    ).first()
    if existing is None:
        db.add(CommunityTeamMember(team_id=team_id, username=username))
        db.commit()
        db.refresh(team)
    return team


def list_teams_for_user(db, username: str) -> List[dict]:
    """Return all teams with membership info for *username*.

    Shape mirrors the original stub: a list of team dicts under ``teams``.
    """
    teams = db.query(CommunityTeam).order_by(
        CommunityTeam.created_at.desc()).limit(50).all()
    return [_team_to_dict(db, t, username=username) for t in teams]
