"""Users domain (migrated to FastAPI, incremental).

Sub-chunk: per-user email (own account or admin).
  * GET /api/users/{username}/email
  * PUT /api/users/{username}/email

Other users-domain routes (core CRUD, suspension, reputation, …) migrate in
follow-up chunks.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login

router = APIRouter(prefix="/api/users", tags=["users"])

# Admin user-management routes live under /api/admin/users.
admin_router = APIRouter(prefix="/api/admin/users", tags=["users"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


def _self_or_admin(current: str, username: str) -> bool:
    return current == username or gapi_gui.user_manager.is_admin(current)


@router.get("/{username}/reputation")
def get_user_reputation(username: str, _user: str = Depends(require_login)):
    """Return the reputation/trust score for ``username``."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return {"username": username, "score": 100, "violation_count": 0,
                "last_updated": None, "last_action": None}
    try:
        db = next(g.database.get_db())
        rep = g.database.get_reputation(db, username)
        if not rep:
            return _err(404, f"User '{username}' not found")
        return rep
    except Exception as e:
        g.gui_logger.error("get_user_reputation error: %s", e)
        return _err(500, str(e))


@router.get("/{username}/email")
def get_user_email(username: str, current: str = Depends(require_login)):
    """Retrieve a user's email (own account or admin)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    if not _self_or_admin(current, username):
        return _err(403, "Forbidden")
    try:
        db = next(g.database.get_db())
        email = g.database.get_user_email(db, username)
        return {"username": username, "email": email or None}
    except Exception as e:
        g.gui_logger.error("get_user_email error: %s", e)
        return _err(500, str(e))


@router.put("/{username}/email")
def set_user_email(username: str, body: Optional[dict] = Body(default=None),
                   current: str = Depends(require_login)):
    """Update a user's email (own account or admin)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    if not _self_or_admin(current, username):
        return _err(403, "Forbidden")
    email = str((body or {}).get("email", "")).strip()
    if email and not g._is_valid_email_address(email):
        return _err(400, "Invalid email address")
    try:
        db = next(g.database.get_db())
        ok = g.database.set_user_email(db, username, email)
        if not ok:
            return _err(404, "User not found")
        return {"success": True, "email": email}
    except Exception as e:
        g.gui_logger.error("set_user_email error: %s", e)
        return _err(500, str(e))


# ── Admin user management (suspend / status / search) ──────────────────────

@admin_router.get("/search")
def admin_search_users(request: Request, _admin: str = Depends(require_admin_um)):
    """Search and filter users."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return {"users": [], "count": 0}
    args = request.query_params
    q = str(args.get("q", "")).strip()
    role = str(args.get("role", "")).strip()
    status = str(args.get("status", "")).strip().lower()
    try:
        limit = max(1, min(200, int(args.get("limit", 50))))
        offset = max(0, int(args.get("offset", 0)))
    except (ValueError, TypeError):
        limit, offset = 50, 0
    try:
        db = next(g.database.get_db())
        users = g.database.search_users_admin(
            db, query=q, role=role, status=status, limit=limit, offset=offset)
        return {"users": users, "count": len(users)}
    except Exception as e:
        g.gui_logger.error("admin_search_users error: %s", e)
        return _err(500, str(e))


@admin_router.post("/{username}/suspend")
def admin_suspend_user(username: str, body: Optional[dict] = Body(default=None),
                       admin: str = Depends(require_admin_um)):
    """Suspend or permanently ban a user."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    reason = str(data.get("reason", "")).strip()
    if not reason:
        return _err(400, "'reason' is required")
    duration = data.get("duration_minutes")
    if duration is not None:
        try:
            duration = int(duration)
            if duration <= 0:
                return _err(400, "'duration_minutes' must be a positive integer")
        except (ValueError, TypeError):
            return _err(400, "'duration_minutes' must be an integer")
    try:
        db = next(g.database.get_db())
        result = g.database.suspend_user(
            db, username, reason=reason, suspended_by=admin,
            duration_minutes=duration)
        if not result:
            return _err(404, f"User '{username}' not found")
        action = "suspend_user" if duration else "ban_user"
        g._audit(action, resource_type="user", resource_id=username,
                 description=f'{"Temporary suspension" if duration else "Permanent ban"}: {reason}',
                 new_value={"reason": reason, "duration_minutes": duration})
        return result
    except Exception as e:
        g.gui_logger.error("admin_suspend_user error: %s", e)
        return _err(500, str(e))


@admin_router.delete("/{username}/suspend")
def admin_unsuspend_user(username: str, _admin: str = Depends(require_admin_um)):
    """Lift a user's suspension or ban."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        ok = g.database.unsuspend_user(db, username)
        if not ok:
            return _err(404, f"User '{username}' not found or not suspended")
        g._audit("unsuspend_user", resource_type="user", resource_id=username,
                 description=f'Suspension/ban lifted for user "{username}"')
        return {"ok": True, "username": username}
    except Exception as e:
        g.gui_logger.error("admin_unsuspend_user error: %s", e)
        return _err(500, str(e))


@admin_router.get("/{username}/status")
def admin_get_user_status(username: str, _admin: str = Depends(require_admin_um)):
    """Get a user's account status."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        result = g.database.get_user_status(db, username)
        if not result:
            return _err(404, f"User '{username}' not found")
        return result
    except Exception as e:
        g.gui_logger.error("admin_get_user_status error: %s", e)
        return _err(500, str(e))


@admin_router.get("/low-reputation")
def admin_low_reputation_users(request: Request,
                               _admin: str = Depends(require_admin_um)):
    """List users at or below a reputation threshold."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return {"threshold": g.database.REPUTATION_AUTO_BAN_THRESHOLD, "users": []}
    args = request.query_params
    try:
        threshold = int(args.get("threshold", g.database.REPUTATION_AUTO_BAN_THRESHOLD))
        limit = max(1, min(200, int(args.get("limit", 50))))
    except (ValueError, TypeError):
        threshold = g.database.REPUTATION_AUTO_BAN_THRESHOLD
        limit = 50
    try:
        db = next(g.database.get_db())
        users = g.database.get_low_reputation_users(db, threshold=threshold, limit=limit)
        return {"threshold": threshold, "users": users}
    except Exception as e:
        g.gui_logger.error("admin_low_reputation_users error: %s", e)
        return _err(500, str(e))
