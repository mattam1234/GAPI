"""Users domain (migrated to FastAPI).

Covers per-user email, reputation, admin suspension/status/search, and the
core user-management CRUD (add/update/remove/role/roles/delete/list/profile).
With this chunk the users domain is fully on FastAPI; no /api/users* routes
remain in Flask.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login

router = APIRouter(prefix="/api/users", tags=["users"])

# Admin user-management routes live under /api/admin/users.
admin_router = APIRouter(prefix="/api/admin/users", tags=["users"])

# Routes that don't share the /api/users prefix (/api/roles, /api/user/profile).
extra_router = APIRouter(tags=["users"])


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


# ── Core user management (admin, @require_admin -> require_admin_um) ─────────

@router.post("/add")
def add_user(body: Optional[dict] = Body(default=None),
             _admin: str = Depends(require_admin_um)):
    """Add a new user to the multi-user picker."""
    g = gapi_gui
    if not g.multi_picker:
        return _err(400, "Multi-user picker not initialized")
    data = body or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    steam_id = str(data.get("steam_id", "")).strip()
    discord_id = str(data.get("discord_id", "")).strip()
    if not name:
        return _err(400, "Name is required")
    if not steam_id:
        return _err(400, "Steam ID is required")
    with g.multi_picker_lock:
        success = g.multi_picker.add_user(
            name=name, steam_id=steam_id, email=email, discord_id=discord_id)
        if not success:
            return _err(400, "User already exists")
        # Reload from disk so the returned record reflects what was saved.
        g.multi_picker.load_users()
        new_user = next((u for u in g.multi_picker.users if u["name"] == name), None)
        return {"success": True,
                "message": f"User {name} added successfully",
                "user": new_user}


@router.post("/update")
def update_user(body: Optional[dict] = Body(default=None),
                _admin: str = Depends(require_admin_um)):
    """Update an existing multi-user-picker user."""
    g = gapi_gui
    if not g.multi_picker:
        return _err(400, "Multi-user picker not initialized")
    data = body or {}
    identifier = str(data.get("identifier", "")).strip()
    updates = data.get("updates", {})
    if not identifier:
        return _err(400, "Identifier is required")
    if not updates:
        return _err(400, "No updates provided")
    with g.multi_picker_lock:
        success = g.multi_picker.update_user(identifier, **updates)
        if not success:
            return _err(404, "User not found")
        return {"success": True, "message": "User updated successfully"}


@router.post("/remove")
def remove_user(body: Optional[dict] = Body(default=None),
                _admin: str = Depends(require_admin_um)):
    """Remove a user from the multi-user picker."""
    g = gapi_gui
    if not g.multi_picker:
        return _err(400, "Multi-user picker not initialized")
    data = body or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return _err(400, "Name is required")
    with g.multi_picker_lock:
        success = g.multi_picker.remove_user(name)
        if not success:
            return _err(404, "User not found")
        return {"success": True, "message": f"User {name} removed successfully"}


@router.post("/role")
def update_user_role(body: Optional[dict] = Body(default=None),
                     admin: str = Depends(require_admin_um)):
    """Set a single role for a user."""
    g = gapi_gui
    data = body or {}
    username = str(data.get("username", "")).strip()
    role = str(data.get("role", "")).strip()
    if not username or not role:
        return _err(400, "Username and role required")
    success, message = g.user_manager.update_user_role(username, role, admin)
    if not success:
        return _err(400, message)
    return {"message": message}


@router.post("/roles")
def update_user_roles(body: Optional[dict] = Body(default=None),
                      admin: str = Depends(require_admin_um)):
    """Set the full list of roles for a user."""
    g = gapi_gui
    data = body or {}
    username = str(data.get("username", "")).strip()
    roles = data.get("roles", [])
    if not username or not isinstance(roles, list):
        return _err(400, "Username and roles list required")
    success, message = g.user_manager.update_user_roles(username, roles, admin)
    if not success:
        return _err(400, message)
    return {"message": message}


@router.delete("/delete/{username}")
def delete_user(username: str, admin: str = Depends(require_admin_um)):
    """Delete a user account."""
    g = gapi_gui
    success, message = g.user_manager.delete_user(username, admin)
    if not success:
        return _err(400, message)
    return {"message": message}


@router.get("/list")
def list_users_with_stats(_user: str = Depends(require_login)):
    """List all users with basic pick/vote stats.

    NOTE: faithfully preserves a latent production bug — the legacy handler
    referenced a module-global ``db_service`` that is never defined in
    ``gapi_gui`` (the same undefined global behind the leaderboards/`/ai`
    500s), so this endpoint always raised ``NameError`` -> 500. Reproduced via
    ``gapi_gui.db_service``; the surrounding query/shaping is preserved so the
    route works the moment a real ``db_service`` is wired.
    """
    g = gapi_gui
    try:
        users = g.user_manager.get_all_users()
        db = g.db_service.get_db()  # NameError in prod -> caught -> 500 (preserved)
        user_list = []
        for user in users:
            if not user.get("username"):
                continue
            picks_cursor = db.execute(
                "SELECT COUNT(*) FROM picks WHERE user = ?", (user["username"],))
            votes_cursor = db.execute(
                "SELECT COUNT(*) FROM votes WHERE user = ?", (user["username"],))
            picks_count = picks_cursor.fetchone()[0] if picks_cursor else 0
            votes_count = votes_cursor.fetchone()[0] if votes_cursor else 0
            user_list.append({
                "username": user["username"],
                "created_at": user.get("created_at"),
                "stats": {"picks": picks_count, "votes": votes_count, "sessions": 0},
            })
        return {"users": user_list}
    except Exception as e:
        g.gui_logger.error("list_users error: %s", e)
        return _err(500, f"Failed to list users: {str(e)}")


@router.get("/{username}/profile")
def get_user_profile(username: str, _user: str = Depends(require_login)):
    """Return a detailed profile (stats + derived achievements) for a user.

    Like :func:`list_users_with_stats`, the stats block depends on the
    never-defined ``db_service``: a *missing* user 404s (checked first), an
    *existing* user 500s in production (preserved). Starlette already URL-decodes
    the path param, so the legacy ``unquote`` is unnecessary.
    """
    g = gapi_gui
    try:
        users = g.user_manager.get_all_users()
        user_data = next((u for u in users if u.get("username") == username), None)
        if not user_data:
            return _err(404, "User not found")
        db = g.db_service.get_db()  # NameError in prod -> caught -> 500 (preserved)
        picks_count = db.execute(
            "SELECT COUNT(*) FROM picks WHERE user = ?", (username,)).fetchone()[0]
        votes_count = db.execute(
            "SELECT COUNT(*) FROM votes WHERE user = ?", (username,)).fetchone()[0]
        sessions_count = db.execute(
            "SELECT COUNT(*) FROM live_sessions WHERE host = ?", (username,)).fetchone()[0]
        accuracy_query = """
            SELECT
                CAST(COUNT(CASE WHEN v.pick_id IN (
                    SELECT pick_id FROM votes
                    GROUP BY pick_id ORDER BY COUNT(*) DESC LIMIT 1
                ) THEN 1 END) * 100.0 /
                NULLIF(COUNT(v.id), 0) AS INTEGER)
            FROM votes v WHERE v.user = ?
        """
        accuracy = db.execute(accuracy_query, (username,)).fetchone()[0]
        achievements = []
        if picks_count >= 10:
            achievements.append({"icon": "🎲", "name": "First 10 Picks"})
        if picks_count >= 50:
            achievements.append({"icon": "🎯", "name": "50 Picks Expert"})
        if votes_count >= 25:
            achievements.append({"icon": "⚖️", "name": "Decision Maker"})
        if sessions_count >= 5:
            achievements.append({"icon": "🎭", "name": "Session Host"})
        if accuracy >= 80:
            achievements.append({"icon": "🎪", "name": "Voting Legend"})
        return {
            "username": username,
            "status": "Active player",
            "created_at": user_data.get("created_at"),
            "stats": {
                "sessions_hosted": sessions_count,
                "picks": picks_count,
                "votes": votes_count,
                "accuracy": accuracy,
            },
            "achievements": achievements,
        }
    except Exception as e:
        g.gui_logger.error("get_user_profile error: %s", e)
        return _err(500, f"Failed to get user profile: {str(e)}")


# ── /api/roles and /api/user/profile (singular — outside the /api/users tree) ─

@extra_router.get("/api/roles")
def list_roles(_admin: str = Depends(require_admin_um)):
    """List available roles."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = g.database.SessionLocal()
        try:
            if g._user_service:
                roles = g._user_service.get_all_roles(db)
            else:
                roles = g.database.get_roles(db)
        finally:
            db.close()
        return {"roles": roles}
    except Exception as e:
        g.gui_logger.exception("Error listing roles: %s", e)
        return _err(500, str(e))


@extra_router.post("/api/user/profile")
def update_my_profile(body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Update the current user's profile card (display_name / bio / avatar_url)."""
    g = gapi_gui
    data = body or {}
    db = next(g.database.get_db())
    try:
        if g._leaderboard_service:
            ok = g._leaderboard_service.update_profile(
                db, username,
                display_name=data.get("display_name"),
                bio=data.get("bio"),
                avatar_url=data.get("avatar_url"))
        else:
            ok = g.database.update_user_profile(
                db, username,
                display_name=data.get("display_name"),
                bio=data.get("bio"),
                avatar_url=data.get("avatar_url"))
    finally:
        if db:
            db.close()
    if ok:
        return {"success": True}
    return _err(500, "Failed to update profile")
