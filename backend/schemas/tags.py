"""Request/response schemas for the tags domain."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AllTags(BaseModel):
    tags: List[str] = Field(default_factory=list)
    game_tags: Dict[str, List[str]] = Field(default_factory=dict)


class GameTags(BaseModel):
    game_id: str
    tags: List[str] = Field(default_factory=list)


class TagIn(BaseModel):
    tag: Optional[str] = ""


class AddTagResult(BaseModel):
    success: bool = True
    added: bool
    game_id: str
    tags: List[str] = Field(default_factory=list)


class RemoveTagResult(BaseModel):
    success: bool = True
    game_id: str
    tags: List[str] = Field(default_factory=list)


class GameWithTags(BaseModel):
    app_id: Optional[Any] = None
    game_id: Optional[str] = None
    name: str = "Unknown"
    playtime_hours: float = 0
    tags: List[str] = Field(default_factory=list)


class LibraryByTag(BaseModel):
    tag: str
    games: List[GameWithTags] = Field(default_factory=list)
    count: int = 0
