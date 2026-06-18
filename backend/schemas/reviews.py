"""Request/response schemas for the reviews domain."""
from typing import Any, Optional

from pydantic import BaseModel, Field


class Review(BaseModel):
    """A stored personal review."""
    rating: int
    notes: str = ""
    updated_at: Optional[str] = None


class ReviewIn(BaseModel):
    """Incoming review body.

    ``rating`` is intentionally permissive (``Any``) so the handler can
    reproduce the legacy endpoint's exact 400 responses for missing /
    non-integer / out-of-range values, rather than FastAPI's default 422.
    """
    rating: Optional[Any] = None
    notes: Optional[str] = ""


class ReviewSaved(BaseModel):
    success: bool = True
    game_id: str
    rating: int
    notes: str = ""


class DeleteResult(BaseModel):
    success: bool = True
