"""Trades domain (real, persistent FastAPI feature).

A *trade* is an offer from one user to another to swap game(s): the proposer
(``from_user``) offers ``offered_items`` and requests ``requested_items`` (each
a list of game app_ids / names). Status lifecycle:

    pending  ->  accepted | declined

Rules enforced:
  * The recipient (``to_user``) must be an existing user; the proposer may not
    trade with themselves; a trade must contain at least one item (400).
  * Only the recipient may accept or decline a trade (403), and only while it
    is still ``pending`` (409). Acting on a non-existent trade is a 404.
  * ``GET /api/trades`` lists every trade where the caller is sender *or*
    recipient.

Persistence is real: trades live in the ``trades`` table (see
``backend/models/trades.py``), accessed through a SQLAlchemy session opened from
``database.SessionLocal()``. The old undefined-``gapi_gui.db_service`` /
mock-fallback behaviour has been removed entirely.

Every ``/api/trades`` response keeps the legacy ``Cache-Control: no-store``
header (trades is not in the cacheable-prefix allowlist).

Routes:
  GET    /api/trades
  POST   /api/trades/create
  POST   /api/trades/{trade_id}/accept
  POST   /api/trades/{trade_id}/decline
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
import database
from backend.dependencies import require_login
from app.services import trade_service
from app.services.trade_service import TradeError

# Importing the model module registers Trade on the shared Base so the
# create_all hook in backend.main builds the table.
import backend.models.trades  # noqa: F401

router = APIRouter(prefix="/api/trades", tags=["trades"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


def _open_session():
    """Open a real DB session, or raise a 503-mapped TradeError if unavailable."""
    if getattr(database, "SessionLocal", None) is None:
        raise TradeError(503, "Database not available")
    return database.SessionLocal()


@router.get("")
def api_get_trades(username: str = Depends(require_login)):
    """List trades where the current user is the sender or the recipient."""
    try:
        db = _open_session()
        try:
            trades = trade_service.list_trades_for_user(db, username)
        finally:
            db.close()
        return _ok({"trades": trades})
    except TradeError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading trades: %s", e)
        return _err(500, "Failed to load trades")


@router.post("/create")
def api_create_trade(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Propose a trade to another user."""
    data = body or {}
    # Recipient may be supplied as 'to_user' (new) or 'username' (legacy key).
    to_user = data.get("to_user") or data.get("username") or ""
    offered_items = data.get("offered_items")
    requested_items = data.get("requested_items")

    try:
        db = _open_session()
        try:
            trade = trade_service.create_trade(
                db, from_user=username, to_user=to_user,
                offered_items=offered_items, requested_items=requested_items)
        finally:
            db.close()
    except TradeError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error creating trade: %s", e)
        return _err(500, "Failed to create trade")

    # Best-effort realtime notification (never affects the response).
    _notify(to_user=trade["to_user"], from_user=username,
            trade_id=trade["id"], offer="New trade offer")

    return _ok(trade, status_code=201)


@router.post("/{trade_id}/accept")
def api_accept_trade(trade_id: str, username: str = Depends(require_login)):
    """Accept a pending trade (recipient only)."""
    try:
        db = _open_session()
        try:
            trade = trade_service.accept_trade(db, trade_id, username)
        finally:
            db.close()
    except TradeError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error accepting trade: %s", e)
        return _err(500, "Failed to accept trade")

    _notify(to_user=trade["from_user"], from_user=username,
            trade_id=trade["id"], offer="Trade accepted")
    return _ok(trade)


@router.post("/{trade_id}/decline")
def api_decline_trade(trade_id: str, username: str = Depends(require_login)):
    """Decline a pending trade (recipient only)."""
    try:
        db = _open_session()
        try:
            trade = trade_service.decline_trade(db, trade_id, username)
        finally:
            db.close()
    except TradeError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error declining trade: %s", e)
        return _err(500, "Failed to decline trade")

    _notify(to_user=trade["from_user"], from_user=username,
            trade_id=trade["id"], offer="Trade declined")
    return _ok(trade)


def _notify(*, to_user: str, from_user: str, trade_id: str, offer: str) -> None:
    """Best-effort realtime trade notification; failures are swallowed."""
    g = gapi_gui
    if not getattr(g, "REALTIME_AVAILABLE", False):
        return
    try:
        g.realtime.RealtimeEvents.trade_notification(
            to_user=to_user, from_user=from_user,
            trade_id=str(trade_id), offer=offer)
    except Exception as e:  # pragma: no cover - notification is non-critical
        g.gui_logger.warning("Failed to broadcast trade notification: %s", e)
