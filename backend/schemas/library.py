"""Response schema for the library-comparison domain."""
from typing import List

from pydantic import BaseModel, Field


class LibraryComparison(BaseModel):
    your_games: List[str] = Field(default_factory=list)
    their_games: List[str] = Field(default_factory=list)
    shared_games: List[str] = Field(default_factory=list)
    your_only: List[str] = Field(default_factory=list)
    their_only: List[str] = Field(default_factory=list)
    your_count: int = 0
    their_count: int = 0
    shared_count: int = 0
