"""Users domain (migrated to FastAPI, incremental).

Sub-chunk: per-user email (own account or admin).
  * GET /api/users/{username}/email
  * PUT /api/users/{username}/email

Other users-domain routes (core CRUD, suspension, reputation, …) migrate in
follow-up chunks.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/users", tags=["users"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


def _self_or_admin(current: str, username: str) -> bool:
    return current == username or gapi_gui.user_manager.is_admin(current)


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
