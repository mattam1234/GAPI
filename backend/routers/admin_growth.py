"""Admin growth domain (migrated to FastAPI).

Faithful port of the legacy Flask admin "growth" routes — all gated by the
legacy ``@require_admin`` decorator (``app_settings_service.is_admin``), hence
:func:`require_admin` here (NOT ``require_admin_um``):

A/B tests (recommendation experiments):
  * POST  /api/admin/ab-tests
  * GET   /api/admin/ab-tests
  * PATCH /api/admin/ab-tests/{experiment_id}

User groups:
  * POST   /api/admin/user-groups
  * GET    /api/admin/user-groups
  * DELETE /api/admin/user-groups/{group_id}
  * POST   /api/admin/user-groups/{group_id}/members
  * GET    /api/admin/user-groups/{group_id}/members
  * DELETE /api/admin/user-groups/{group_id}/members/{username}

Push broadcast:
  * POST   /api/admin/push/broadcast

All legacy singletons (``database``, ``_push_service``, ``gui_logger``,
``get_current_username``, ``_audit``) are referenced via ``gapi_gui.*`` at CALL
TIME so reassignments are picked up. The legacy ``after_request`` set
``Cache-Control: no-store`` on every ``/api/*`` response (none of these paths are
in the cacheable-prefix allowlist); that header is replicated explicitly here.

The A/B-test handlers delegate to ``database.*`` experiment helpers which carry a
SQLAlchemy ``Query.get()`` deprecation in the legacy layer — ported faithfully,
not fixed. Member-add ordering: the longer ``/members`` paths are declared before
the bare ``/{group_id}`` path to avoid route-matching ambiguity.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ── A/B testing (recommendation experiments) ────────────────────────────────

@router.post("/ab-tests")
def api_create_ab_test(body: Optional[dict] = Body(default=None),
                       _admin: str = Depends(require_admin)):
    """Create a new recommendation A/B experiment (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    name = str(data.get("name", "")).strip()
    variants = data.get("variants", [])
    description = str(data.get("description", "")).strip()
    if not name:
        return _err(400, "'name' is required")
    if not isinstance(variants, list) or len(variants) < 2:
        return _err(400, "'variants' must be a list with at least 2 entries")
    try:
        db = next(g.database.get_db())
        exp = g.database.create_experiment(
            db, name=name, variants=variants, description=description,
            created_by=g.get_current_username(),
        )
        if not exp:
            return _err(409, "Failed to create experiment (name may already exist)")
        return _ok(exp, 201)
    except Exception as e:
        g.gui_logger.error("api_create_ab_test error: %s", e)
        return _err(500, str(e))


@router.get("/ab-tests")
def api_list_ab_tests(_admin: str = Depends(require_admin)):
    """List all recommendation A/B experiments with variant assignment counts."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"experiments": []})
    try:
        db = next(g.database.get_db())
        exps = g.database.list_experiments(db)
        for exp in exps:
            exp["variant_counts"] = g.database.get_experiment_variant_counts(db, exp["id"])
        return _ok({"experiments": exps})
    except Exception as e:
        g.gui_logger.error("api_list_ab_tests error: %s", e)
        return _err(500, str(e))


@router.patch("/ab-tests/{experiment_id}")
def api_update_ab_test(experiment_id: int, body: Optional[dict] = Body(default=None),
                       _admin: str = Depends(require_admin)):
    """Update the status of a recommendation A/B experiment (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    status = str(data.get("status", "")).strip().lower()
    valid_statuses = ("draft", "active", "paused", "concluded")
    if status not in valid_statuses:
        return _err(400, f"'status' must be one of: {', '.join(valid_statuses)}")
    try:
        db = next(g.database.get_db())
        updated = g.database.update_experiment_status(db, experiment_id, status)
        if not updated:
            return _err(404, "Experiment not found")
        return _ok(updated)
    except Exception as e:
        g.gui_logger.error("api_update_ab_test error: %s", e)
        return _err(500, str(e))


# ── User groups ─────────────────────────────────────────────────────────────

@router.post("/user-groups")
def api_create_user_group(body: Optional[dict] = Body(default=None),
                          _admin: str = Depends(require_admin)):
    """Create a new user group (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return _err(400, "'name' is required")
    description = str(data.get("description", "")).strip()
    try:
        db = next(g.database.get_db())
        grp = g.database.create_user_group(db, name=name, description=description,
                                           created_by=g.get_current_username())
        if not grp:
            return _err(409, "Failed to create group (name may already exist)")
        g._audit("create_user_group", resource_type="user_group",
                 resource_id=str(grp.get("id")),
                 description=f'Created user group "{name}"')
        return _ok(grp, 201)
    except Exception as e:
        g.gui_logger.error("api_create_user_group error: %s", e)
        return _err(500, str(e))


@router.get("/user-groups")
def api_list_user_groups(_admin: str = Depends(require_admin)):
    """List all user groups with member counts (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"groups": []})
    try:
        db = next(g.database.get_db())
        groups = g.database.list_user_groups(db)
        return _ok({"groups": groups})
    except Exception as e:
        g.gui_logger.error("api_list_user_groups error: %s", e)
        return _err(500, str(e))


# Longer/literal /members paths declared before the bare /{group_id} path.

@router.post("/user-groups/{group_id}/members")
def api_add_group_member(group_id: int, body: Optional[dict] = Body(default=None),
                         _admin: str = Depends(require_admin)):
    """Add a user to a user group (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    username = str(data.get("username", "")).strip()
    if not username:
        return _err(400, "'username' is required")
    try:
        db = next(g.database.get_db())
        result = g.database.add_group_member(db, group_id, username,
                                             added_by=g.get_current_username())
        if not result.get("ok"):
            status = 409 if "Already a member" in result.get("error", "") else 404
            return _ok(result, status)
        g._audit("add_group_member", resource_type="user_group",
                 resource_id=str(group_id),
                 description=f'Added "{username}" to group {group_id}')
        return _ok(result, 201)
    except Exception as e:
        g.gui_logger.error("api_add_group_member error: %s", e)
        return _err(500, str(e))


@router.get("/user-groups/{group_id}/members")
def api_get_group_members(group_id: int, _admin: str = Depends(require_admin)):
    """Get the list of members for a user group (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"group_id": group_id, "members": []})
    try:
        db = next(g.database.get_db())
        members = g.database.get_group_members(db, group_id)
        return _ok({"group_id": group_id, "members": members})
    except Exception as e:
        g.gui_logger.error("api_get_group_members error: %s", e)
        return _err(500, str(e))


@router.delete("/user-groups/{group_id}/members/{username}")
def api_remove_group_member(group_id: int, username: str,
                            _admin: str = Depends(require_admin)):
    """Remove a user from a user group (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        ok = g.database.remove_group_member(db, group_id, username)
        if not ok:
            return _err(404, "Member not found in group")
        g._audit("remove_group_member", resource_type="user_group",
                 resource_id=str(group_id),
                 description=f'Removed "{username}" from group {group_id}')
        return _ok({"ok": True})
    except Exception as e:
        g.gui_logger.error("api_remove_group_member error: %s", e)
        return _err(500, str(e))


@router.delete("/user-groups/{group_id}")
def api_delete_user_group(group_id: int, _admin: str = Depends(require_admin)):
    """Delete a user group and all memberships (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        ok = g.database.delete_user_group(db, group_id)
        if not ok:
            return _err(404, "Group not found")
        g._audit("delete_user_group", resource_type="user_group",
                 resource_id=str(group_id),
                 description=f"Deleted user group {group_id}")
        return _ok({"ok": True})
    except Exception as e:
        g.gui_logger.error("api_delete_user_group error: %s", e)
        return _err(500, str(e))


# ── Push broadcast ──────────────────────────────────────────────────────────

@router.post("/push/broadcast")
def api_admin_push_broadcast(body: Optional[dict] = Body(default=None),
                             _admin: str = Depends(require_admin)):
    """Send a push notification to all opted-in subscribers (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    title = str(data.get("title", "")).strip()
    push_body = str(data.get("body", "")).strip()
    url = str(data.get("url", "/")).strip() or "/"
    dry_run = str(data.get("dry_run", "false")).lower() in ("true", "1", "yes")
    if not title or not push_body:
        return _err(400, "'title' and 'body' are required")
    if not g._push_service:
        return _err(503, "Push notification service not available")
    try:
        db = next(g.database.get_db())
        result = g._push_service.broadcast(
            db, title, push_body, url=url, db_module=g.database, dry_run=dry_run
        )
    except Exception as e:
        g.gui_logger.error("api_admin_push_broadcast error: %s", e)
        return _err(500, "Internal server error")
    return _ok(result)
