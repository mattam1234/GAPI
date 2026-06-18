"""Request/response schemas for the budget-tracking domain."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BudgetEntry(BaseModel):
    game_id: str
    price: float = 0
    currency: str = "USD"
    purchase_date: str = ""
    notes: str = ""
    name: Optional[str] = None


class BudgetSummary(BaseModel):
    total_spent: float = 0
    primary_currency: str = "USD"
    currency_breakdown: Dict[str, float] = Field(default_factory=dict)
    game_count: int = 0
    entries: List[BudgetEntry] = Field(default_factory=list)


class BudgetIn(BaseModel):
    """Incoming budget body. ``price`` is permissive so the handler can
    reproduce the legacy 400 contract (absent vs non-numeric)."""
    price: Optional[Any] = None
    currency: Optional[str] = "USD"
    purchase_date: Optional[str] = ""
    notes: Optional[str] = ""


class SetBudgetResult(BaseModel):
    success: bool = True
    game_id: str
    price: float


class DeleteResult(BaseModel):
    success: bool = True
