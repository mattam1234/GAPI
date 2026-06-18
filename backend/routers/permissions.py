"""Permissions domain (migrated to FastAPI) — first users-domain sub-chunk.

Mirrors the legacy Flask routes:
  * GET  /api/permissions                          (public: all perms + matrix)
  * GET  /api/users/{username}/permissions         (login: effective perms)
  * POST /api/admin/users/{username}/permissions   (admin: grant/deny/remove)
  * POST /api/admin/roles/bulk-assign              (admin: bulk role assignment)

DB-backed; the admin routes use the legacy ``@require_admin`` semantics
(user_manager.is_admin) via ``require_admin_um``.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login

router = APIRouter(prefix="/api", tags=["permissions"])


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.get("/permissions")
def permissions_list():
    """All defined permissions and the role-to-permission matrix (public).

    Public read-only data — cacheable (mirrors the legacy Flask after_request
    Cache-Control for /api/permissions).
    """
    g = gapi_gui
    return JSONResponse(
        content={
            "permissions": g.database.ALL_PERMISSIONS if g.DB_AVAILABLE else [],
            "role_matrix": g.database.PERMISSIONS if g.DB_AVAILABLE else {},
        },
        headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=120"})


@router.get("/users/{username}/permissions")
def get_user_permissions(username: str, _user: str = Depends(require_login)):
    """Effective permissions for ``username``."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        return g.database.get_user_permissions(db, username)
    except Exception as e:
        g.gui_logger.error("get_user_permissions error: %s", e)
        return _err(500, str(e))


@router.post("/admin/users/{username}/permissions")
def set_user_permissions(username: str, body: Optional[dict] = Body(default=None),
                         requester: str = Depends(require_admin_um)):
    """Grant / deny / remove a permission override for ``username``."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    permission = str(data.get("permission", "")).strip()
    action = str(data.get("action", "")).strip().lower()
    if not permission or action not in ("grant", "deny", "remove"):
        return _err(400, "Required fields: 'permission' and 'action' (grant/deny/remove)")
    if permission not in g.database.ALL_PERMISSIONS:
        return _err(400, f"Unknown permission '{permission}'")
    try:
        db = next(g.database.get_db())
        if action == "remove":
            ok = g.database.remove_user_permission_override(db, username, permission)
        else:
            ok = g.database.set_user_permission_override(
                db, username, permission,
                granted=(action == "grant"), granted_by=requester)
        if not ok:
            return _err(500, "Failed to update permission")
        return {"ok": True, "permissions": g.database.get_user_permissions(db, username)}
    except Exception as e:
        g.gui_logger.error("set_user_permissions error: %s", e)
        return _err(500, str(e))


@router.post("/admin/roles/bulk-assign")
def bulk_assign_role(body: Optional[dict] = Body(default=None),
                     requester: str = Depends(require_admin_um)):
    """Assign a role to multiple users at once."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    role = str(data.get("role", "")).strip()
    usernames = data.get("usernames", [])
    if not role:
        return _err(400, "'role' is required")
    if not isinstance(usernames, list) or len(usernames) == 0:
        return _err(400, "'usernames' must be a non-empty list")
    if len(usernames) > 200:
        return _err(400, "'usernames' may not exceed 200 entries per request")
    assigned, skipped, errors = [], [], []
    try:
        for uname in usernames:
            uname = str(uname).strip()
            if not uname:
                continue
            ok, _ = g.user_manager.update_user_roles(uname, [role], requester)
            (assigned if ok else skipped).append(uname)
        if assigned:
            g._audit("bulk_role_assign", resource_type="user_role", resource_id=role,
                     description=f'Bulk assigned role "{role}" to {len(assigned)} user(s)',
                     new_value={"role": role, "assigned": assigned, "skipped": skipped})
    except Exception as e:
        g.gui_logger.error("bulk_assign_role error: %s", e)
        errors.append({"error": str(e)})
    return {"assigned": assigned, "skipped": skipped, "errors": errors}
