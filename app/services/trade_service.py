"""Business logic for the game-trading domain.

A trade is an offer from one user (``from_user``) to another (``to_user``) to
swap game(s): ``from_user`` offers ``offered_items`` and requests
``requested_items`` (each a list of game app_ids / names). The status lifecycle
is ``pending`` -> ``accepted`` | ``declined``. Only the recipient (``to_user``)
may accept or decline, and only while the trade is still ``pending``.

Every function takes a SQLAlchemy ``db`` session as its first argument so the
caller (the FastAPI route handler) controls the session lifecycle. Validation
failures are signalled by raising :class:`TradeError`, which carries an HTTP
status code; the router maps these onto JSON error responses.

Item lists are JSON-serialised into the ``offered_items`` / ``requested_items``
text columns and parsed back out when building response dicts.
"""
import json
from typing import Any, Dict, List, Optional

from backend.models.trades import Trade

# Status constants
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"


class TradeError(Exception):
    """A trade operation failed. ``status_code`` is the HTTP status to return."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _loads(value: Optional[str]) -> List[Any]:
    """Parse a JSON list column, returning [] on empty/invalid data."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_items(items: Any) -> List[Any]:
    """Coerce an incoming items value into a clean, non-empty-aware list.

    Accepts a list, or a single scalar (wrapped into a one-element list).
    ``None`` becomes an empty list. Blank string entries are dropped.
    """
    if items is None:
        return []
    if not isinstance(items, list):
        items = [items]
    cleaned = []
    for item in items:
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
        if item is None:
            continue
        cleaned.append(item)
    return cleaned


def _to_dict(trade: Trade) -> Dict[str, Any]:
    """Serialise a Trade ORM row into the API response shape."""
    return {
        "id": str(trade.id),
        "from_user": trade.from_user,
        "to_user": trade.to_user,
        "offered_items": _loads(trade.offered_items),
        "requested_items": _loads(trade.requested_items),
        "status": trade.status,
        "message": _message_for_status(trade.status),
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "updated_at": trade.updated_at.isoformat() if trade.updated_at else None,
    }


def _message_for_status(status: str) -> str:
    """Human-readable message mirroring the legacy stub's ``message`` key."""
    return {
        STATUS_PENDING: "Trade pending",
        STATUS_ACCEPTED: "Trade accepted",
        STATUS_DECLINED: "Trade declined",
    }.get(status, "Trade")


def _user_exists(db, username: str) -> bool:
    """Return True if *username* is a known user.

    Uses ``database.user_exists`` when available; falls back to ``True`` only
    when no user-lookup helper exists at all (never the case in production).
    """
    try:
        import database
    except Exception:
        return True
    helper = getattr(database, "user_exists", None)
    if helper is None:
        return True
    return bool(helper(db, username))


def create_trade(db, from_user: str, to_user: str,
                 offered_items: Any, requested_items: Any) -> Dict[str, Any]:
    """Create a new pending trade offer.

    Raises:
        TradeError(400): self-trade, missing recipient, empty items, or
            unknown recipient.
    """
    to_user = (to_user or "").strip()
    if not to_user:
        raise TradeError(400, "Recipient (to_user) is required")
    if to_user == from_user:
        raise TradeError(400, "Cannot trade with yourself")

    offered = _normalize_items(offered_items)
    requested = _normalize_items(requested_items)
    if not offered and not requested:
        raise TradeError(400, "Trade must include at least one item")

    if not _user_exists(db, to_user):
        raise TradeError(400, "Recipient user does not exist")

    trade = Trade(
        from_user=from_user,
        to_user=to_user,
        offered_items=json.dumps(offered),
        requested_items=json.dumps(requested),
        status=STATUS_PENDING,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return _to_dict(trade)


def list_trades_for_user(db, username: str) -> List[Dict[str, Any]]:
    """Return all trades where *username* is the sender or the recipient.

    Newest first.
    """
    rows = (
        db.query(Trade)
        .filter((Trade.from_user == username) | (Trade.to_user == username))
        .order_by(Trade.created_at.desc(), Trade.id.desc())
        .all()
    )
    return [_to_dict(t) for t in rows]


def _get_owned_pending(db, trade_id: Any, username: str) -> Trade:
    """Fetch a trade and assert *username* may act on it as the recipient.

    Raises:
        TradeError(404): no such trade.
        TradeError(403): *username* is not the recipient.
        TradeError(409): trade is no longer pending.
    """
    try:
        tid = int(trade_id)
    except (ValueError, TypeError):
        raise TradeError(404, "Trade not found")

    trade = db.query(Trade).filter(Trade.id == tid).first()
    if trade is None:
        raise TradeError(404, "Trade not found")
    if trade.to_user != username:
        raise TradeError(403, "Only the recipient can respond to this trade")
    if trade.status != STATUS_PENDING:
        raise TradeError(409, f"Trade is already {trade.status}")
    return trade


def accept_trade(db, trade_id: Any, username: str) -> Dict[str, Any]:
    """Accept a pending trade as its recipient. See :func:`_get_owned_pending`."""
    trade = _get_owned_pending(db, trade_id, username)
    trade.status = STATUS_ACCEPTED
    db.commit()
    db.refresh(trade)
    return _to_dict(trade)


def decline_trade(db, trade_id: Any, username: str) -> Dict[str, Any]:
    """Decline a pending trade as its recipient. See :func:`_get_owned_pending`."""
    trade = _get_owned_pending(db, trade_id, username)
    trade.status = STATUS_DECLINED
    db.commit()
    db.refresh(trade)
    return _to_dict(trade)
