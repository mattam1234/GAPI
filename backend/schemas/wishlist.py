"""Request/response schemas for the wishlist & sale-alerts domain."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WishlistEntry(BaseModel):
    game_id: str
    name: str
    platform: str = "steam"
    added_date: Optional[str] = None
    target_price: Optional[float] = None
    notes: str = ""


class WishlistList(BaseModel):
    entries: List[WishlistEntry] = Field(default_factory=list)
    count: int = 0


class WishlistIn(BaseModel):
    """Incoming wishlist body. Permissive types so the handler can reproduce the
    legacy endpoint's exact 400 responses rather than FastAPI's default 422."""
    game_id: Optional[str] = ""
    name: Optional[str] = ""
    platform: Optional[str] = "steam"
    target_price: Optional[Any] = None
    notes: Optional[str] = ""


class AddResult(BaseModel):
    success: bool = True
    game_id: str


class DeleteResult(BaseModel):
    success: bool = True


class SalesResult(BaseModel):
    sales: List[Dict[str, Any]] = Field(default_factory=list)
    checked: int = 0
    on_sale_count: int = 0
