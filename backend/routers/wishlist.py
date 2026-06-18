"""Wishlist & sale-alerts domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/wishlist
  * POST   /api/wishlist                 (201 on success)
  * DELETE /api/wishlist/{game_id}       (game_id may contain ':' or '/')
  * GET    /api/wishlist/sales           (live Steam price check)

Reuses the per-user picker ``wishlist_service`` + ``picker_lock``. Note this
domain's legacy contract returns **400** (not 500) when the picker is not
initialised, so a local dependency preserves that rather than using the shared
``get_picker`` (which raises 500).
"""
from fastapi import APIRouter, Depends, HTTPException, status

import gapi
import gapi_gui
from backend.dependencies import require_login
from backend.schemas.wishlist import (
    AddResult, DeleteResult, SalesResult, WishlistIn, WishlistList,
)

router = APIRouter(prefix="/api", tags=["wishlist"])


def _picker(username: str = Depends(require_login)):
    """Per-user picker; 400 if not initialised (legacy wishlist contract)."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(status_code=400, detail="Not initialized")
    return p


@router.get("/wishlist", response_model=WishlistList)
def get_wishlist(picker=Depends(_picker)):
    """Return all wishlist entries."""
    with gapi_gui.picker_lock:
        entries = list(picker.wishlist_service.get_all().values())
    return WishlistList(entries=entries, count=len(entries))


@router.post("/wishlist", response_model=AddResult,
             status_code=status.HTTP_201_CREATED)
def add_to_wishlist(body: WishlistIn, picker=Depends(_picker)):
    """Add or update a game in the wishlist."""
    game_id = (body.game_id or "").strip()
    name = (body.name or "").strip()
    if not game_id:
        raise HTTPException(status_code=400, detail="game_id is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    platform = str(body.platform or "steam").strip().lower() or "steam"
    notes = str(body.notes or "")
    target_price = body.target_price
    if target_price is not None:
        try:
            target_price = float(target_price)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="target_price must be a number"
            )
    with gapi_gui.picker_lock:
        ok = picker.wishlist_service.add(
            game_id, name, platform=platform,
            target_price=target_price, notes=notes,
        )
    if not ok:
        raise HTTPException(
            status_code=400, detail="target_price must not be negative"
        )
    return AddResult(game_id=game_id)


@router.get("/wishlist/sales", response_model=SalesResult)
def check_wishlist_sales(picker=Depends(_picker)):
    """Check live Steam prices for wishlist items on sale / at target price."""
    if not picker.wishlist_service.get_all():
        return SalesResult(sales=[], checked=0)
    if not picker.steam_client or not isinstance(
        picker.steam_client, gapi.SteamAPIClient
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Steam client not available; cannot check prices",
        )
    with gapi_gui.picker_lock:
        sales = picker.wishlist_service.check_sales(picker.steam_client)
        checked = len([
            e for e in picker.wishlist_service.get_all().values()
            if e.get("platform", "steam") == "steam"
        ])
    return SalesResult(sales=sales, checked=checked, on_sale_count=len(sales))


@router.delete("/wishlist/{game_id:path}", response_model=DeleteResult)
def remove_from_wishlist(game_id: str, picker=Depends(_picker)):
    """Remove a game from the wishlist (404 if not present)."""
    with gapi_gui.picker_lock:
        removed = picker.wishlist_service.remove(game_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found in wishlist",
        )
    return DeleteResult()
