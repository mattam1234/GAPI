"""Request/response schemas for the playlists domain."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlaylistsList(BaseModel):
    playlists: List[Dict[str, Any]] = Field(default_factory=list)


class CreatePlaylistIn(BaseModel):
    name: Optional[str] = ""


class CreatePlaylistResult(BaseModel):
    success: bool = True
    name: str


class AddGameIn(BaseModel):
    game_id: Optional[str] = ""


class PlaylistGames(BaseModel):
    name: str
    games: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class SuccessResult(BaseModel):
    success: bool = True
