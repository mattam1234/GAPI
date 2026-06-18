"""Request schemas for the multiplayer achievement-challenges domain.

Challenge objects are returned as plain dicts (DB-shaped) to pass through
verbatim.
"""
from typing import Any, Optional

from pydantic import BaseModel


class CreateChallengeIn(BaseModel):
    title: Optional[str] = ""
    app_id: Optional[str] = ""
    game_name: Optional[str] = ""
    target_achievement_ids: Any = None  # list or comma-separated string
    starts_at: Optional[str] = ""
    ends_at: Optional[str] = ""


class ChallengeProgressIn(BaseModel):
    unlocked_count: Any = 0
