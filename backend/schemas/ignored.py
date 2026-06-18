"""Request/response schemas for the ignored-games domain."""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class IgnoredGame(BaseModel):
    app_id: Optional[Any] = None
    game_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[str] = None


class IgnoredGamesList(BaseModel):
    ignored_games: List[IgnoredGame] = Field(default_factory=list)


class ToggleIgnoreIn(BaseModel):
    app_id: Optional[Any] = None
    game_name: Optional[str] = ""
    reason: Optional[str] = ""


class ToggleResult(BaseModel):
    message: str
