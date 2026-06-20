"""Auth + first-time-setup domain (migrated to FastAPI).

The sensitive bit is the **session seam**. The legacy Flask login did
``session['username'] = username`` and logout did ``session.pop('username')``.
Those routes are now FastAPI, so they must read/write the *same* Flask session
cookie that ``backend.dependencies`` decodes — otherwise a login on the new
route wouldn't authenticate the rest of the app. We therefore sign the cookie
with Flask's own ``session_interface`` serializer and set it with Flask's
configured cookie attributes, mirroring what ``SecureCookieSessionInterface``
would have written. A user who logs in here is authenticated on every FastAPI
router and on the still-mounted Flask fallback, with no re-login.

Routes:
  GET  /api/auth/current            POST /api/auth/login   POST /api/auth/logout
  POST /api/auth/register           POST /api/auth/update-ids
  GET  /api/auth/get-ids            POST /api/auth/change-password
  GET  /api/setup/status            POST /api/setup/initial-admin
"""
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
import database
from backend.dependencies import get_current_user, require_login
from backend.ratelimit import rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])
setup_router = APIRouter(prefix="/api/setup", tags=["auth"])

# Restores the rate limits the legacy app intended (its @limiter.limit was
# commented out): 20 logins/min and 10 registrations/hour, per client IP.
_login_rate_limit = rate_limit("login", limit=20, window_seconds=60)
_register_rate_limit = rate_limit("register", limit=10, window_seconds=3600)


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


# ── Flask-compatible session cookie helpers ─────────────────────────────────

def _set_session_cookie(response, session_data: dict) -> None:
    """Write the Flask-signed session cookie onto a FastAPI response."""
    app = gapi_gui.app
    serializer = app.session_interface.get_signing_serializer(app)
    value = serializer.dumps(dict(session_data))
    cfg = app.config
    samesite = cfg.get("SESSION_COOKIE_SAMESITE") or "lax"
    response.set_cookie(
        key=cfg.get("SESSION_COOKIE_NAME") or "session",
        value=value,
        httponly=bool(cfg.get("SESSION_COOKIE_HTTPONLY", True)),
        secure=bool(cfg.get("SESSION_COOKIE_SECURE", False)),
        samesite=str(samesite).lower(),
        path=cfg.get("SESSION_COOKIE_PATH") or "/",
        domain=cfg.get("SESSION_COOKIE_DOMAIN") or None,
    )


def _clear_session_cookie(response) -> None:
    app = gapi_gui.app
    cfg = app.config
    response.delete_cookie(
        key=cfg.get("SESSION_COOKIE_NAME") or "session",
        path=cfg.get("SESSION_COOKIE_PATH") or "/",
        domain=cfg.get("SESSION_COOKIE_DOMAIN") or None,
    )


# ── Auth ────────────────────────────────────────────────────────────────────

@router.get("/current")
def auth_current(username: Optional[str] = Depends(get_current_user)):
    """Return the current logged-in user, or 401 if anonymous."""
    g = gapi_gui
    if username:
        role = g.user_manager.get_user_role(username)
        return {"username": username, "role": role,
                "roles": [role] if role else ["user"]}
    return _err(401, None) if False else JSONResponse(
        status_code=401, content={"username": None})


@router.post("/register")
def auth_register(body: Optional[dict] = Body(default=None),
                  _rl: None = Depends(_register_rate_limit)):
    """Register a new user (does not log them in)."""
    g = gapi_gui
    data = body or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    email = str(data.get("email", "")).strip()
    g.gui_logger.info("Register endpoint called for username=%s", username)
    if not username or not password:
        return _err(400, "Username and password required")
    if email and not g._is_valid_email_address(email):
        return _err(400, "Invalid email address")
    success, message = g.user_manager.register(username, password)
    if not success:
        return _err(400, message)
    g.gui_logger.info("Register result for username=%s: success", username)
    if email and g.DB_AVAILABLE:
        try:
            db = next(g.database.get_db())
            g.database.set_user_email(db, username, email)
        except Exception as _e:
            g.gui_logger.warning("Could not store email for %s: %s", username, _e)
    return {"message": message}


@router.post("/login")
def auth_login(body: Optional[dict] = Body(default=None),
               _rl: None = Depends(_login_rate_limit)):
    """Authenticate a user and establish the Flask session cookie."""
    g = gapi_gui
    data = body or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    g.gui_logger.info("Login endpoint called for username=%s", username)
    if not username or not password:
        return _err(400, "Username and password required")

    success, message = g.user_manager.login(username, password)
    if not success:
        g._audit("login", resource_type="auth", resource_id=username,
                 description="Login failed", actor=username, status="failure",
                 error=message)
        return _err(401, message)

    g.gui_logger.info("User logged in: %s", username)
    g._audit("login", resource_type="auth", resource_id=username,
             description="Login successful", actor=username)

    # Resolve platform IDs (prefer DB, fall back to JSON store) to decide whether
    # to kick off the background Steam library sync.
    user_ids = g.user_manager.get_user_ids(username)
    if g.DB_AVAILABLE:
        try:
            db = g.database.SessionLocal()
            try:
                if g._user_service:
                    db_ids = g._user_service.get_platform_ids(db, username)
                else:
                    db_user = g.database.get_user_by_username(db, username)
                    db_ids = {
                        "steam_id": getattr(db_user, "steam_id", None) or "",
                        "epic_id": getattr(db_user, "epic_id", None) or "",
                        "gog_id": getattr(db_user, "gog_id", None) or "",
                    } if db_user else {}
            finally:
                db.close()
            for key in ("steam_id", "epic_id", "gog_id"):
                if db_ids.get(key):
                    user_ids[key] = db_ids[key]
        except Exception as e:
            g.gui_logger.exception("Failed to read user IDs from DB for %s: %s",
                                   username, e)

    if user_ids.get("steam_id"):
        def init_library_async():
            try:
                if user_ids.get("steam_id") and not g.gapi.is_placeholder_value(
                        user_ids["steam_id"]):
                    g.gui_logger.info(f"Triggering library sync for {username}")
                    ok, msg = g.sync_library_to_db(username, force=False)
                    if ok:
                        g.gui_logger.info(f"Library sync completed for {username}: {msg}")
                    else:
                        g.gui_logger.warning(f"Library sync failed for {username}: {msg}")
                else:
                    g.gui_logger.info(
                        f"No valid Steam ID for {username}, skipping library sync")
            except Exception as e:
                g.gui_logger.error("Error in background library sync: %s", e)

        threading.Thread(target=init_library_async, daemon=True).start()

    resp = JSONResponse(content={"message": "Login successful", "username": username})
    _set_session_cookie(resp, {"username": username})
    return resp


@router.post("/logout")
def auth_logout(username: Optional[str] = Depends(get_current_user)):
    """Log out: clear the session cookie and reset per-user state."""
    g = gapi_gui
    g.gui_logger.info("User logged out: %s", username)
    g._audit("logout", resource_type="auth", resource_id=username,
             description="User logged out", actor=username)

    with g.picker_lock:
        g.picker = None
    with g.multi_picker_lock:
        g.multi_picker = None

    rpc = getattr(g, "_discord_rpc", None)
    if rpc and getattr(rpc, "enabled", False):
        rpc.clear()

    resp = JSONResponse(content={"message": "Logged out successfully"})
    _clear_session_cookie(resp)
    return resp


@router.post("/update-ids")
def auth_update_ids(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Update the current user's platform IDs."""
    g = gapi_gui
    data = body or {}
    steam_id = str(data.get("steam_id", "")).strip()
    epic_id = str(data.get("epic_id", "")).strip()
    gog_id = str(data.get("gog_id", "")).strip()
    discord_id = str(data.get("discord_id", "")).strip()

    success = g.user_manager.update_user_ids(
        username, steam_id, epic_id, gog_id, discord_id=discord_id)
    if not success:
        return _err(400, "Failed to update IDs")
    # NOTE: faithful to legacy ordering — the numeric check runs AFTER the update.
    if discord_id and not discord_id.isdigit():
        return _err(400, "Discord ID must be numeric")

    if g.DB_AVAILABLE and discord_id:
        try:
            db = g.database.SessionLocal()
            try:
                joined_sessions = g.database.complete_pending_discord_session_joins_for_user(
                    db, discord_id, username)
            finally:
                db.close()
            for joined_session_id in joined_sessions:
                try:
                    db = g.database.SessionLocal()
                    try:
                        linked_session = g.database.get_linked_pick_session(db, joined_session_id)
                        if linked_session:
                            g._sse_publish(
                                joined_session_id, "session",
                                g._attach_live_session_common_count(
                                    g.database.linked_pick_session_to_dict(db, linked_session)),
                            )
                    finally:
                        db.close()
                except Exception:
                    pass
        except Exception as exc:
            g.gui_logger.warning(
                "Failed to complete pending Discord joins for %s: %s", username, exc)

    user_ids = g.user_manager.get_user_ids(username)
    if user_ids.get("steam_id") and not g.gapi.is_placeholder_value(user_ids["steam_id"]):
        def sync_async():
            try:
                g.gui_logger.info(f"Syncing library after ID update for {username}")
                ok, msg = g.sync_library_to_db(username, force=True)
                if ok:
                    g.gui_logger.info(f"Library sync completed: {msg}")
                else:
                    g.gui_logger.warning(f"Library sync failed: {msg}")
            except Exception as e:
                g.gui_logger.error(f"Error in background sync: {e}")

        threading.Thread(target=sync_async, daemon=True).start()

    return {"message": "Platform IDs updated successfully"}


@router.get("/get-ids")
def auth_get_ids(username: str = Depends(require_login)):
    """Return the current user's platform IDs."""
    g = gapi_gui
    user_ids = g.user_manager.get_user_ids(username)
    if g.DB_AVAILABLE:
        try:
            db = g.database.SessionLocal()
            try:
                if g._user_service:
                    db_ids = g._user_service.get_platform_ids(db, username)
                else:
                    db_user = g.database.get_user_by_username(db, username)
                    db_ids = {
                        "steam_id": getattr(db_user, "steam_id", None) or "",
                        "epic_id": getattr(db_user, "epic_id", None) or "",
                        "gog_id": getattr(db_user, "gog_id", None) or "",
                    } if db_user else {}
            finally:
                db.close()
            for key in ("steam_id", "epic_id", "gog_id"):
                if db_ids.get(key):
                    user_ids[key] = db_ids[key]
        except Exception as e:
            g.gui_logger.exception("Failed to read IDs from DB for %s: %s", username, e)

    user_ids["discord_id"] = user_ids.get("discord_id", "")
    if g.DB_AVAILABLE and not user_ids["discord_id"]:
        try:
            db = g.database.SessionLocal()
            try:
                db_user = g.database.get_user_by_username(db, username)
                if db_user and getattr(db_user, "discord_id", None):
                    user_ids["discord_id"] = str(db_user.discord_id)
            finally:
                db.close()
        except Exception as e:
            g.gui_logger.warning("Failed to resolve discord_id for %s: %s", username, e)

    return user_ids


@router.post("/change-password")
def auth_change_password(body: Optional[dict] = Body(default=None),
                         username: str = Depends(require_login)):
    """Change the current user's password."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    current_password = str(data.get("current_password", "")).strip()
    new_password = str(data.get("new_password", "")).strip()
    if not current_password or not new_password:
        return _err(400, "Current password and new password are required")
    if len(new_password) < 6:
        return _err(400, "New password must be at least 6 characters")
    try:
        db = g.database.SessionLocal()
        try:
            if not g.database.verify_user_password(db, username, current_password):
                return _err(401, "Current password is incorrect")
            user = g.database.get_user_by_username(db, username)
            if not user:
                return _err(404, "User not found")
            user.password = g.database.hash_password(new_password)
            user.updated_at = datetime.utcnow()
            db.commit()
            g.gui_logger.info(f"Password changed successfully for user: {username}")
            return {"message": "Password changed successfully"}
        finally:
            db.close()
    except Exception as e:
        g.gui_logger.exception(f"Error changing password for {username}: {e}")
        return _err(500, "Failed to change password")


# ── First-time setup ────────────────────────────────────────────────────────

@setup_router.get("/status")
def setup_status():
    """Report whether initial admin setup is required."""
    g = gapi_gui
    if not g.ensure_db_available():
        return JSONResponse(status_code=503,
                            content={"needs_setup": False, "error": "Database not available"})
    try:
        db = g.database.SessionLocal()
        try:
            count = g._user_service.get_count(db) if g._user_service \
                else g.database.get_user_count(db)
        finally:
            db.close()
        return {"needs_setup": count == 0}
    except Exception as e:
        g.gui_logger.exception("Setup status check failed: %s", e)
        return JSONResponse(status_code=500,
                            content={"needs_setup": False, "error": str(e)})


@setup_router.post("/initial-admin")
def setup_initial_admin(body: Optional[dict] = Body(default=None)):
    """Create the initial admin user if no users exist."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, "Database not available")
    data = body or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    if not username or not password:
        return _err(400, "Username and password required")
    try:
        db = g.database.SessionLocal()
        try:
            count = g._user_service.get_count(db) if g._user_service \
                else g.database.get_user_count(db)
            if count > 0:
                return _err(409, "Users already exist")
            if g._user_service:
                user = g._user_service.create_admin(db, username, password)
            else:
                user = g.database.create_or_update_user(
                    db, username, password, "", "", "", role="admin", roles=["admin"])
        finally:
            db.close()
        if user:
            return JSONResponse(status_code=201, content={"message": "Initial admin created"})
        return _err(500, "Failed to create admin")
    except Exception as e:
        g.gui_logger.exception("Initial admin setup failed: %s", e)
        return _err(500, str(e))
