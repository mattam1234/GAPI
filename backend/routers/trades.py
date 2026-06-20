"""Trades domain (migrated to FastAPI).

The legacy trading-system handlers all reference a module-global ``db_service``
that is never defined in ``gapi_gui`` (the same undefined global behind the
leaderboards / ``/api/users/list`` 500s). Every handler is wrapped in a
``try/except`` that catches the resulting ``NameError`` and returns a
success-faking mock response, so in production these routes never actually
persist anything — they always fall through to the mock branch. That behaviour
is preserved faithfully here: ``db_service`` is referenced via
``gapi_gui.db_service`` so the ``NameError`` still fires and the mock fallback
still runs.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (trades is not in the cacheable-prefix allowlist); that header is set
explicitly here to preserve behaviour.

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
from backend.dependencies import require_login

router = APIRouter(prefix="/api/trades", tags=["trades"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


@router.get("")
def api_get_trades(username: str = Depends(require_login)):
    """Get pending trade offers."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # NameError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        trades_query = """
            SELECT t.id, u.username, t.offer_description
            FROM trade_offers t
            JOIN users u ON t.from_user_id = u.id
            WHERE t.to_user_id = ? AND t.status = 'pending'
            ORDER BY t.created_at DESC
        """
        trades_rows = db.execute(trades_query, (user.id,)).fetchall()

        trades = []
        for trade_id, from_user, offer in trades_rows:
            trades.append({
                'id': str(trade_id),
                'from_user': from_user,
                'offer': offer
            })

        return _ok({'trades': trades})
    except Exception as e:
        g.gui_logger.error(f"Error loading trades: {e}")
        # Mock fallback
        trades = [
            {'id': '1', 'from_user': 'gamer123', 'offer': 'Portal 2 for Elden Ring'},
        ]
        return _ok({'trades': trades})


@router.post("/create")
def api_create_trade(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Create a trade offer."""
    g = gapi_gui
    data = body or {}
    target = data.get('username', '')
    offer = data.get('offer', '')

    if not all([target, offer]):
        return _err(400, 'All fields required')

    try:
        db = g.db_service.get_db()  # NameError in prod -> caught -> mock (preserved)
        from_user = g.db_service.get_current_user(username)
        to_user = g.db_service.get_user_by_username(target)

        if not to_user:
            return _err(404, 'User not found')

        insert_query = """
            INSERT INTO trade_offers (from_user_id, to_user_id, offer_description)
            VALUES (?, ?, ?)
        """
        result = db.execute(insert_query, (from_user.id, to_user.id, offer))
        db.commit()

        trade_id = result.lastrowid

        # Broadcast trade notification
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.trade_notification(
                    to_user=target,
                    from_user=username,
                    trade_id=str(trade_id),
                    offer=offer
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast trade notification: {e}')

        return _ok({'success': True, 'message': f'Trade offer sent to {target}'})
    except Exception as e:
        g.gui_logger.error(f"Error creating trade: {e}")
        return _ok({'success': True, 'message': f'Trade offer sent (mock)'})


@router.post("/{trade_id}/accept")
def api_accept_trade(trade_id: str, username: str = Depends(require_login)):
    """Accept a trade offer."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # NameError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Get trade details for notification
        trade_query = "SELECT from_user_id, offer_description FROM trade_offers WHERE id = ? AND to_user_id = ?"
        trade_result = db.execute(trade_query, (int(trade_id), user.id)).fetchone()

        # Update trade status
        update_query = "UPDATE trade_offers SET status = 'accepted' WHERE id = ? AND to_user_id = ?"
        db.execute(update_query, (int(trade_id), user.id))
        db.commit()

        # Get from_user username for notification
        if trade_result:
            from_user_id = trade_result[0]
            offer = trade_result[1]
            from_user_query = "SELECT username FROM users WHERE id = ?"
            from_user_result = db.execute(from_user_query, (from_user_id,)).fetchone()
            if from_user_result:
                from_username = from_user_result[0]

                # Broadcast trade acceptance
                if g.REALTIME_AVAILABLE:
                    try:
                        g.realtime.RealtimeEvents.trade_notification(
                            to_user=from_username,
                            from_user=username,
                            trade_id=str(trade_id),
                            offer=offer
                        )
                    except Exception as e:
                        g.gui_logger.warning(f'Failed to broadcast trade acceptance: {e}')

        return _ok({'success': True, 'message': 'Trade accepted'})
    except Exception as e:
        g.gui_logger.error(f"Error accepting trade: {e}")
        return _ok({'success': True, 'message': 'Trade accepted (mock)'})


@router.post("/{trade_id}/decline")
def api_decline_trade(trade_id: str, username: str = Depends(require_login)):
    """Decline a trade offer."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # NameError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Get trade details for notification
        trade_query = "SELECT from_user_id, offer_description FROM trade_offers WHERE id = ? AND to_user_id = ?"
        trade_result = db.execute(trade_query, (int(trade_id), user.id)).fetchone()

        # Update trade status
        update_query = "UPDATE trade_offers SET status = 'declined' WHERE id = ? AND to_user_id = ?"
        db.execute(update_query, (int(trade_id), user.id))
        db.commit()

        # Broadcast trade decline if needed
        if g.REALTIME_AVAILABLE and trade_result:
            try:
                from_user_id = trade_result[0]
                from_user_query = "SELECT username FROM users WHERE id = ?"
                from_user_result = db.execute(from_user_query, (from_user_id,)).fetchone()
                if from_user_result:
                    g.realtime.RealtimeEvents.trade_notification(
                        to_user=from_user_result[0],
                        from_user=username,
                        trade_id=str(trade_id),
                        offer='Trade declined'
                    )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast trade decline: {e}')

        return _ok({'success': True, 'message': 'Trade declined'})
    except Exception as e:
        g.gui_logger.error(f"Error declining trade: {e}")
        return _ok({'success': True, 'message': 'Trade declined (mock)'})
