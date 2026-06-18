"""Direct-messaging domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET  /api/messages/conversations
  * GET  /api/messages/{username}
  * POST /api/messages/{username}

DB-backed: reuses the legacy ``database`` DM helpers, gated on
``DB_AVAILABLE`` + ``ensure_db_available()``. When the DB is unavailable the
legacy endpoints degrade gracefully (empty lists / echo) rather than erroring;
that contract is preserved.

Note: the static ``/conversations`` route is declared before the
``/{username}`` route so it is not shadowed by the path parameter.
"""
from fastapi import APIRouter, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.messages import SendMessageIn

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _db_ready() -> bool:
    return bool(gapi_gui.DB_AVAILABLE and gapi_gui.ensure_db_available())


@router.get("/conversations")
def get_conversations(username: str = Depends(require_login)):
    """List the current user's DM conversations."""
    if _db_ready():
        db = next(gapi_gui.database.get_db())
        try:
            return {"conversations": gapi_gui.database.get_dm_conversations(db, username)}
        finally:
            if db:
                db.close()
    return {"conversations": []}


@router.get("/{other_username}")
def get_messages(other_username: str, current: str = Depends(require_login)):
    """Get the DM thread between the current user and ``other_username``."""
    try:
        if _db_ready():
            db = next(gapi_gui.database.get_db())
            try:
                return {
                    "messages": gapi_gui.database.get_direct_messages(
                        db, current, other_username)
                }
            finally:
                if db:
                    db.close()
        return {"messages": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{other_username}")
def send_message(other_username: str, body: SendMessageIn,
                 current: str = Depends(require_login)):
    """Send a direct message to ``other_username``."""
    try:
        msg = (body.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Message required")
        if _db_ready():
            db = next(gapi_gui.database.get_db())
            try:
                result = gapi_gui.database.create_direct_message(
                    db, current, other_username, msg)
                if result:
                    return {"success": True, "message": result}
                raise HTTPException(status_code=500, detail="Failed to send message")
            finally:
                if db:
                    db.close()
        return {"success": True, "message": {"sender": current, "message": msg}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
