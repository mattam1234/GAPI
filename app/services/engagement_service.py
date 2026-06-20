"""Business logic for the engagement cluster (six small domains).

Every function takes a SQLAlchemy ``db`` session as its first argument so the
caller (a FastAPI route handler) owns the session lifecycle. Validation
failures raise :class:`EngagementError`, which carries an HTTP status code; the
router maps these onto JSON error responses.

Domains & semantics
-------------------
battlepass
    A *season* is a config constant (:data:`CURRENT_SEASON` /
    :data:`SEASON_NAME` / :data:`SEASON_MAX_LEVEL` / :data:`SEASON_REWARDS`).
    Each user has a :class:`BattlePassProgress` row (xp / tier / claimed
    levels) lazily created with defaults. ``claim(level)`` grants a level's
    reward iff the user's ``tier >= level`` and the level has a defined reward
    and hasn't already been claimed; otherwise an error (404 unknown reward
    level, 403 tier too low, 409 already claimed).

creator
    ``dashboard`` returns the user's :class:`CreatorApplication` status plus
    basic (derived) stats. ``apply`` creates a ``pending`` application; calling
    it again is idempotent and returns the existing application.

referral
    ``get_or_create_code`` returns the user's unique :class:`ReferralCode`,
    creating it on first read. ``redeem(code, redeemer)`` records a
    :class:`ReferralRedemption` once per redeemer (400 if redeeming your own
    code, 404 if the code is unknown, 409 if the redeemer already redeemed).

streaming
    ``start`` opens a ``live`` :class:`StreamSession`. ``list_vods`` returns the
    user's sessions (newest first); a VOD is any session row.

progression / ranked
    GET-only lightweight views derived from a lazily-created
    :class:`ProgressionState` / :class:`RankedStanding` row (defaults on first
    read).
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

from backend.models.engagement import (
    EngagementBattlePassProgress as BattlePassProgress,
    EngagementCreatorApplication as CreatorApplication,
    EngagementReferralCode as ReferralCode,
    EngagementReferralRedemption as ReferralRedemption,
    EngagementStreamSession as StreamSession,
    EngagementProgressionState as ProgressionState,
    EngagementRankedStanding as RankedStanding,
)


class EngagementError(Exception):
    """An engagement operation failed. ``status_code`` is the HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── battlepass season config ─────────────────────────────────────────────────
# A season is a constant here (a "simple config row" equivalent). New users get
# a BattlePassProgress row defaulted to this season.
CURRENT_SEASON = 5
SEASON_NAME = "Season 5: Storm Rising"
SEASON_MAX_LEVEL = 100
SEASON_DAYS_REMAINING = 23
# xp required to advance one tier.
XP_PER_TIER = 1000
# Reward catalogue: level -> (reward label, reward type).
SEASON_REWARDS = {
    10: ("[Title] Storm Chaser", "title"),
    25: ("500 Points", "currency"),
    50: ("[Theme] Dark Storm", "cosmetic"),
    100: ("[Frame] Legendary Guardian", "cosmetic"),
}

# Ranked tier ladder (mirrors the legacy stub).
RANKED_TIERS = ["Bronze", "Silver", "Gold", "Diamond", "Master"]
RANKED_TIER_EMOJI = ["\U0001F95A", "\U0001F948", "\U0001F947", "\U0001F48E", "\U0001F451"]
# rating points needed to reach the next tier boundary.
RATING_PER_TIER = 600


def _loads_int_list(value: Optional[str]) -> List[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out = []
    for x in parsed:
        try:
            out.append(int(x))
        except (ValueError, TypeError):
            continue
    return out


# ── battlepass ────────────────────────────────────────────────────────────────

def _get_or_create_battlepass(db, username: str) -> BattlePassProgress:
    row = (
        db.query(BattlePassProgress)
        .filter(BattlePassProgress.username == username,
                BattlePassProgress.season == CURRENT_SEASON)
        .first()
    )
    if row is None:
        row = BattlePassProgress(
            username=username, season=CURRENT_SEASON, xp=0, tier=1,
            claimed_levels="[]")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_current_battlepass(db, username: str) -> Dict[str, Any]:
    """Return the current season + the user's xp/tier, plus the reward list."""
    row = _get_or_create_battlepass(db, username)
    exp_into_tier = row.xp % XP_PER_TIER
    claimed = set(_loads_int_list(row.claimed_levels))
    rewards = [
        {"level": lvl, "reward": label, "type": rtype,
         "claimed": lvl in claimed}
        for lvl, (label, rtype) in sorted(SEASON_REWARDS.items())
    ]
    return {
        "battle_pass": {
            "name": SEASON_NAME,
            "season": row.season,
            "current_level": row.tier,
            "experience": exp_into_tier,
            "exp_to_next": XP_PER_TIER - exp_into_tier,
            "max_level": SEASON_MAX_LEVEL,
            "has_premium": True,
            "days_remaining": SEASON_DAYS_REMAINING,
        },
        "rewards": rewards,
    }


def claim_battlepass_reward(db, username: str, level: Any) -> Dict[str, Any]:
    """Grant the reward for ``level`` to the user.

    Raises EngagementError(404) for an unknown reward level, 403 if the user's
    tier is below the level, 409 if already claimed.
    """
    try:
        lvl = int(level)
    except (ValueError, TypeError):
        raise EngagementError(404, "Unknown reward level")

    if lvl not in SEASON_REWARDS:
        raise EngagementError(404, "Unknown reward level")

    row = _get_or_create_battlepass(db, username)
    if row.tier < lvl:
        raise EngagementError(403, f"Tier {lvl} not yet reached")

    claimed = _loads_int_list(row.claimed_levels)
    if lvl in claimed:
        raise EngagementError(409, f"Reward for level {lvl} already claimed")

    claimed.append(lvl)
    row.claimed_levels = json.dumps(sorted(set(claimed)))
    db.commit()

    label, _rtype = SEASON_REWARDS[lvl]
    return {
        "success": True,
        "message": f"Reward for level {lvl} claimed!",
        "item": label,
    }


# ── creator ───────────────────────────────────────────────────────────────────

def get_creator_dashboard(db, username: str) -> Dict[str, Any]:
    """Return the user's creator status plus basic (derived) stats."""
    app_row = (
        db.query(CreatorApplication)
        .filter(CreatorApplication.username == username)
        .first()
    )
    status = app_row.status if app_row else "none"
    # 'tier'/'status' fields reflect the application lifecycle.
    tier = "gold" if status == "approved" else "none"
    return {
        "tier": tier,
        "followers": 0,
        "total_views": 0,
        "revenue_share": 30 if status == "approved" else 0,
        "this_month_earnings": 0,
        "status": status,
        "next_tier_followers": 500000,
    }


def apply_creator(db, username: str) -> Dict[str, Any]:
    """Create (or return existing) a pending creator application (idempotent)."""
    app_row = (
        db.query(CreatorApplication)
        .filter(CreatorApplication.username == username)
        .first()
    )
    if app_row is None:
        app_row = CreatorApplication(username=username, status="pending")
        db.add(app_row)
        db.commit()
        db.refresh(app_row)
        message = "Application submitted for review"
    else:
        message = "Application already on file"
    return {"success": True, "message": message, "status": app_row.status}


# ── referral ──────────────────────────────────────────────────────────────────

def _gen_code(username: str) -> str:
    """Deterministic, unique-per-user referral code."""
    digest = hashlib.sha1(username.encode("utf-8")).hexdigest()[:6].upper()
    return f"REFER{username.upper()}{digest}"


def get_or_create_referral_code(db, username: str) -> Dict[str, Any]:
    """Return the user's referral code, creating it on first read."""
    row = (
        db.query(ReferralCode)
        .filter(ReferralCode.username == username)
        .first()
    )
    if row is None:
        row = ReferralCode(username=username, code=_gen_code(username))
        db.add(row)
        db.commit()
        db.refresh(row)

    total_uses = (
        db.query(ReferralRedemption)
        .filter(ReferralRedemption.code == row.code)
        .count()
    )
    return {
        "code": row.code,
        "reward_per_use": 500,
        "total_uses": total_uses,
        "total_earned": total_uses * 500,
        "active": True,
    }


def redeem_referral_code(db, redeemer: str, code: str) -> Dict[str, Any]:
    """Redeem someone's referral ``code`` for ``redeemer`` (once per redeemer).

    Raises 400 (own/self code), 404 (unknown code), 409 (already redeemed).
    """
    code = (code or "").strip()
    if not code:
        raise EngagementError(404, "Unknown referral code")

    owner = (
        db.query(ReferralCode)
        .filter(ReferralCode.code == code)
        .first()
    )
    if owner is None:
        raise EngagementError(404, "Unknown referral code")
    if owner.username == redeemer:
        raise EngagementError(400, "Cannot redeem your own referral code")

    existing = (
        db.query(ReferralRedemption)
        .filter(ReferralRedemption.redeemer == redeemer)
        .first()
    )
    if existing is not None:
        raise EngagementError(409, "You have already redeemed a referral code")

    db.add(ReferralRedemption(code=code, redeemer=redeemer))
    db.commit()
    return {
        "success": True,
        "message": "Gained 500 points from referral!",
        "points_gained": 500,
    }


# ── streaming ─────────────────────────────────────────────────────────────────

def _stream_to_dict(s: StreamSession) -> Dict[str, Any]:
    return {
        "id": str(s.id),
        "title": s.title,
        "status": s.status,
        "views": s.views,
        "stream_url": s.stream_url,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
    }


def list_vods(db, username: str) -> List[Dict[str, Any]]:
    """Return the user's stream sessions (VODs), newest first."""
    rows = (
        db.query(StreamSession)
        .filter(StreamSession.username == username)
        .order_by(StreamSession.started_at.desc(), StreamSession.id.desc())
        .all()
    )
    return [_stream_to_dict(s) for s in rows]


def start_stream(db, username: str, title: str) -> Dict[str, Any]:
    """Create a new live stream session. Raises 400 on a missing title."""
    title = (title or "").strip()
    if not title:
        raise EngagementError(400, "Stream title required")

    stream_url = "rtmp://twitch.tv/..."
    session = StreamSession(
        username=username, title=title, status="live", stream_url=stream_url)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "success": True,
        "message": "Stream started",
        "stream_url": stream_url,
        "id": str(session.id),
        "title": session.title,
    }


# ── progression ───────────────────────────────────────────────────────────────

def _get_or_create_progression(db, username: str) -> ProgressionState:
    row = (
        db.query(ProgressionState)
        .filter(ProgressionState.username == username)
        .first()
    )
    if row is None:
        row = ProgressionState(username=username, level=1, xp=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_progression(db, username: str) -> Dict[str, Any]:
    """Lightweight GET-only progression view (lazy-created defaults)."""
    row = _get_or_create_progression(db, username)
    # Derive a few progression "paths" from the single state row so the
    # response keeps the stub's 'paths' shape.
    paths = [
        {
            "id": 1,
            "name": "Competitive Player",
            "description": "Master competitive gameplay",
            "current_step": row.level,
            "total_steps": 10,
            "progress": min(100, int(row.level / 10 * 100)),
            "next_reward": "[Title] Rank Master",
        },
        {
            "id": 2,
            "name": "Streamer Path",
            "description": "Build your streaming career",
            "current_step": min(10, row.level),
            "total_steps": 10,
            "progress": min(100, int(row.level / 10 * 100)),
            "next_reward": "[Frame] Broadcaster Elite",
        },
        {
            "id": 3,
            "name": "Collector",
            "description": "Collect all cosmetics",
            "current_step": min(15, row.level),
            "total_steps": 15,
            "progress": min(100, int(row.level / 15 * 100)),
            "next_reward": "[Theme] Collector's Gold",
        },
    ]
    return {"paths": paths, "level": row.level, "xp": row.xp}


# ── ranked ────────────────────────────────────────────────────────────────────

def _get_or_create_ranked(db, username: str) -> RankedStanding:
    row = (
        db.query(RankedStanding)
        .filter(RankedStanding.username == username)
        .first()
    )
    if row is None:
        row = RankedStanding(username=username, rating=0, wins=0, losses=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_ranked(db, username: str) -> Dict[str, Any]:
    """Lightweight GET-only ranked view (lazy-created defaults)."""
    row = _get_or_create_ranked(db, username)
    tier_index = min(row.rating // RATING_PER_TIER, len(RANKED_TIERS) - 1)
    tier_name = RANKED_TIERS[tier_index]
    # tier_level: position within the current tier band (1-based, capped).
    tier_level = (row.rating % RATING_PER_TIER) // (RATING_PER_TIER // 3 or 1) + 1
    rating_points_needed = (tier_index + 1) * RATING_PER_TIER
    return {
        "current_tier_index": tier_index,
        "current_rank": f"{tier_name} {tier_level}",
        "current_rank_emoji": RANKED_TIER_EMOJI[tier_index],
        "rating_points": row.rating,
        "rating_points_needed": rating_points_needed,
        "wins": row.wins,
        "losses": row.losses,
        "tiers": list(RANKED_TIERS),
    }
