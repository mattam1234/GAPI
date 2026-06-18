"""Notification preferences + history domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET /api/notifications/preferences
  * PUT /api/notifications/preferences
  * GET /api/notifications/history

DB-backed via the legacy ``database`` notification helpers. Preferences return
503 when the DB is down; history degrades to an empty page (200). The admin
broadcast/send routes under /api/notifications/* remain in Flask.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/preferences")
def get_preferences(username: str = Depends(require_login)):
    """Return the current user's notification preferences."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        db = next(gapi_gui.database.get_db())
        return gapi_gui.database.get_notification_prefs(db, username)
    except Exception as e:
        gapi_gui.gui_logger.error("get_preferences error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/preferences")
def set_preferences(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Update the current user's notification preferences."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    data = body or {}
    try:
        db = next(gapi_gui.database.get_db())
        updated = gapi_gui.database.set_notification_prefs(db, username, data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to save preferences")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        gapi_gui.gui_logger.error("set_preferences error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def history(request: Request, username: str = Depends(require_login)):
    """Return paginated notification history for the current user."""
    if not gapi_gui.DB_AVAILABLE:
        return {"notifications": [], "total": 0}
    args = request.query_params
    try:
        limit = max(1, min(200, int(args.get("limit", 50))))
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = max(0, int(args.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0
    unread_only = str(args.get("unread", "")).lower() in ("true", "1", "yes")
    try:
        db = next(gapi_gui.database.get_db())
        notifications = gapi_gui.database.get_notifications(
            db, username, unread_only=unread_only)
        total = len(notifications)
        page = notifications[offset: offset + limit]
        return {"notifications": page, "total": total}
    except Exception as e:
        gapi_gui.gui_logger.error("history error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
