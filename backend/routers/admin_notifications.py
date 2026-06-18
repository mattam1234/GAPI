"""Admin notification domain (migrated to FastAPI).

Mirrors the legacy Flask routes (both admin-only, via user_manager.is_admin):
  * POST /api/admin/notifications/broadcast      (notify all / a subset of users)
  * POST /api/admin/notifications/send-digests   (trigger digest email delivery)

DB-backed; 503 when the DB is unavailable. send-digests also needs a configured
EmailService.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um

router = APIRouter(prefix="/api/admin/notifications", tags=["admin-notifications"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.post("/broadcast")
def broadcast(body: Optional[dict] = Body(default=None),
              _admin: str = Depends(require_admin_um)):
    """Broadcast a notification to all users or a specific subset."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    title = str(data.get("title", "")).strip()
    message = str(data.get("message", "")).strip()
    notif_type = str(data.get("type", "info")).strip()
    if notif_type not in ("info", "warning", "success", "error"):
        notif_type = "info"
    if not title or not message:
        return _err(400, "'title' and 'message' are required")
    target_usernames = data.get("usernames")
    sent = skipped = 0
    try:
        db = next(g.database.get_db())
        if target_usernames:
            usernames = [str(u).strip() for u in target_usernames if str(u).strip()]
        else:
            usernames = [u.username for u in g.database.get_all_users(db)]
        for uname in usernames:
            if g.database.create_notification(db, uname, title, message, notif_type):
                sent += 1
            else:
                skipped += 1
        return {"sent": sent, "skipped": skipped}
    except Exception as e:
        g.gui_logger.error("broadcast error: %s", e)
        return _err(500, str(e))


@router.post("/send-digests")
def send_digests(body: Optional[dict] = Body(default=None),
                 _admin: str = Depends(require_admin_um)):
    """Trigger digest email delivery for opted-in users."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    if g._email_service is None:
        return _err(503, "EmailService not loaded")
    if not g._email_service.is_configured():
        return _err(503, "SMTP not configured")

    data = body or {}
    period = str(data.get("period", "daily")).lower()
    if period not in ("daily", "weekly"):
        period = "daily"
    dry_run = bool(data.get("dry_run", False))

    sent = skipped = failed = 0
    try:
        db = next(g.database.get_db())
        for user in g.database.get_all_users(db):
            username = user.username if hasattr(user, "username") else str(user)
            prefs = g.database.get_notification_prefs(db, username)
            if not prefs.get("email_enabled"):
                skipped += 1
                continue
            freq = prefs.get("digest_frequency", "never")
            if freq not in ("daily", "weekly") or freq != period:
                skipped += 1
                continue
            email_addr = g.database.get_user_email(db, username)
            if not g._is_valid_email_address(email_addr):
                skipped += 1
                continue
            notifications = g.database.get_notifications(db, username, unread_only=True)
            if not notifications:
                skipped += 1
                continue
            if dry_run:
                sent += 1
                continue
            if g._email_service.send_digest_email(
                    email_addr, username, notifications, period=period):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "skipped": skipped, "failed": failed, "dry_run": dry_run}
    except Exception as e:
        g.gui_logger.error("send_digests error: %s", e)
        return _err(500, str(e))
