"""Budget-tracking domain — per-game purchase prices (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/budget
  * POST   /api/budget/{game_id}    (also PUT — upsert)
  * PUT    /api/budget/{game_id}
  * DELETE /api/budget/{game_id}    (game_id may contain ':' or '/')

Reuses the per-user picker ``budget_service`` + ``picker_lock``. Preserves the
legacy 400-on-uninitialised contract via a local dependency.
"""
from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.budget import (
    BudgetIn, BudgetSummary, DeleteResult, SetBudgetResult,
)

router = APIRouter(prefix="/api/budget", tags=["budget"])


def _picker(username: str = Depends(require_login)):
    """Per-user picker; 400 if not initialised (legacy budget contract)."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(status_code=400, detail="Not initialized")
    return p


@router.get("", response_model=BudgetSummary)
def get_budget(picker=Depends(_picker)):
    """Return all budget entries with an aggregated spending summary."""
    with gapi_gui.picker_lock:
        return picker.budget_service.get_summary(picker.games)


@router.post("/{game_id:path}", response_model=SetBudgetResult)
@router.put("/{game_id:path}", response_model=SetBudgetResult)
def set_budget(game_id: str, body: BudgetIn, picker=Depends(_picker)):
    """Set or update the purchase price for a game."""
    if "price" not in body.model_fields_set:
        raise HTTPException(status_code=400, detail="price is required")
    try:
        price = float(body.price)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="price must be a number")
    with gapi_gui.picker_lock:
        ok = picker.budget_service.set_entry(
            game_id,
            price=price,
            currency=str(body.currency if body.currency is not None else "USD"),
            purchase_date=str(body.purchase_date or ""),
            notes=str(body.notes or ""),
        )
    if not ok:
        raise HTTPException(status_code=400, detail="price must not be negative")
    return SetBudgetResult(game_id=game_id, price=price)


@router.delete("/{game_id:path}", response_model=DeleteResult)
def delete_budget(game_id: str, picker=Depends(_picker)):
    """Remove a game's budget entry (404 if none)."""
    with gapi_gui.picker_lock:
        removed = picker.budget_service.remove_entry(game_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No budget entry found for this game",
        )
    return DeleteResult()
