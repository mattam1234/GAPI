"""Request schemas for the achievement-hunt domain.

Hunt records are returned as plain dicts (service-shaped) to pass through
verbatim.
"""
from typing import Any, Optional

from pydantic import BaseModel


class HuntStartIn(BaseModel):
    app_id: Optional[Any] = None
    game_name: Optional[Any] = None
    difficulty: Optional[str] = "medium"
    target_achievements: Optional[Any] = 0


class HuntUpdateIn(BaseModel):
    unlocked_achievements: Optional[Any] = None
    status: Optional[str] = None
