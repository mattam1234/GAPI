"""Extensibility domains (migrated to FastAPI): push + plugins.

Two routers live in this module:

  * ``push_router``    – Web Push notifications (``/api/push``)
  * ``plugins_router`` – Plugins / addons registry (``/api/plugins``)

Both reuse the legacy singletons (``_push_service``, ``_plugin_service``) and
the ``database`` helpers via ``gapi_gui`` at CALL TIME so reassignments are
picked up. Auth mirrors the legacy decorators exactly: every legacy handler was
``@require_login`` (the admin gate inside the plugins handlers is a manual
``is_admin`` check that runs after login, returning 403), so each route here
depends on :func:`require_login` and reproduces the manual admin check.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (neither push nor plugins is in the cacheable-prefix allowlist); that
header is set explicitly here to preserve behaviour.

Routes (push):
  GET    /api/push/vapid-public-key   (no auth)
  POST   /api/push/subscribe
  DELETE /api/push/unsubscribe
  GET    /api/push/subscriptions

Routes (plugins):
  GET    /api/plugins
  POST   /api/plugins
  PUT    /api/plugins/{plugin_id}
  DELETE /api/plugins/{plugin_id}
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

push_router = APIRouter(prefix="/api/push", tags=["push"])
plugins_router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ── Web Push Notifications ──────────────────────────────────────────────────

@push_router.get("/vapid-public-key")
def api_push_vapid_public_key():
    """Return the server VAPID public key needed to subscribe for push."""
    g = gapi_gui
    if g._push_service:
        return _ok({
            "public_key": g._push_service.get_public_key(),
            "configured": g._push_service.is_configured(),
        })
    return _ok({"public_key": "", "configured": False})


@push_router.post("/subscribe")
def api_push_subscribe(request: Request, body: Optional[dict] = Body(default=None),
                       username: str = Depends(require_login)):
    """Register (or refresh) a browser push subscription for the current user."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    endpoint = str(data.get("endpoint", "")).strip()
    keys = data.get("keys") or {}
    p256dh = str(keys.get("p256dh", "")).strip()
    auth = str(keys.get("auth", "")).strip()
    if not endpoint or not p256dh or not auth:
        return _err(400, "'endpoint', 'keys.p256dh', and 'keys.auth' are required")
    user_agent = request.headers.get("User-Agent", "")[:500]
    try:
        db = next(g.database.get_db())
        ok = g.database.add_push_subscription(
            db, username, endpoint, p256dh, auth, user_agent=user_agent
        )
    except Exception as e:
        g.gui_logger.error("api_push_subscribe error: %s", e)
        return _err(500, "Internal server error")
    if ok:
        return _ok({"subscribed": True}, status_code=201)
    return _err(500, "Failed to save subscription")


@push_router.delete("/unsubscribe")
def api_push_unsubscribe(body: Optional[dict] = Body(default=None),
                         username: str = Depends(require_login)):
    """Remove a push subscription for the current user."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    endpoint = str(data.get("endpoint", "")).strip()
    if not endpoint:
        return _err(400, "'endpoint' is required")
    try:
        db = next(g.database.get_db())
        removed = g.database.remove_push_subscription(db, username, endpoint)
    except Exception as e:
        g.gui_logger.error("api_push_unsubscribe error: %s", e)
        return _err(500, "Internal server error")
    if removed:
        return _ok({"unsubscribed": True})
    return _err(404, "Subscription not found")


@push_router.get("/subscriptions")
def api_push_subscriptions(username: str = Depends(require_login)):
    """List push subscriptions for the current user."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({"subscriptions": [], "count": 0})
    try:
        db = next(g.database.get_db())
        subs = g.database.get_user_push_subscriptions(db, username)
    except Exception as e:
        g.gui_logger.error("api_push_subscriptions error: %s", e)
        return _err(500, "Internal server error")
    # Omit p256dh / auth from the public listing (sensitive key material)
    safe = [
        {
            "id": s["id"],
            "endpoint": s["endpoint"],
            "user_agent": s["user_agent"],
            "created_at": s["created_at"],
        }
        for s in subs
    ]
    return _ok({"subscriptions": safe, "count": len(safe)})


# ── Plugins / Addons ────────────────────────────────────────────────────────

@plugins_router.get("")
def api_get_plugins(username: str = Depends(require_login)):
    """Return all registered plugins."""
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        if g._plugin_service:
            plugins = g._plugin_service.get_all(db)
        else:
            plugins = g.database.get_plugins(db)
    finally:
        if db:
            db.close()
    return _ok({"plugins": plugins})


@plugins_router.post("")
def api_register_plugin(body: Optional[dict] = Body(default=None),
                        username: str = Depends(require_login)):
    """Register or update a plugin (admin only)."""
    g = gapi_gui
    db_check = next(g.database.get_db())
    try:
        if g._plugin_service:
            is_admin = g._plugin_service.is_admin(db_check, username)
        else:
            is_admin = "admin" in g.database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, "Admin access required")
    data = body or {}
    name = data.get("name", "").strip()
    if not name:
        return _err(400, "name is required")
    db = next(g.database.get_db())
    try:
        if g._plugin_service:
            ok = g._plugin_service.register(
                db, name,
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                config=data.get("config"),
            )
        else:
            ok = g.database.register_plugin(
                db, name=name,
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                config=data.get("config"),
            )
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True}, status_code=201)
    return _err(500, "Failed to register plugin")


@plugins_router.put("/{plugin_id}")
def api_toggle_plugin(plugin_id: int, body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Enable or disable a plugin (admin only)."""
    g = gapi_gui
    db_check = next(g.database.get_db())
    try:
        if g._plugin_service:
            is_admin = g._plugin_service.is_admin(db_check, username)
        else:
            is_admin = "admin" in g.database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, "Admin access required")
    data = body or {}
    enabled = bool(data.get("enabled", True))
    db = next(g.database.get_db())
    try:
        if g._plugin_service:
            ok = g._plugin_service.toggle(db, plugin_id, enabled)
        else:
            ok = g.database.toggle_plugin(db, plugin_id, enabled)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True})
    return _err(404, "Plugin not found")


@plugins_router.delete("/{plugin_id}")
def api_delete_plugin(plugin_id: int, username: str = Depends(require_login)):
    """Permanently delete a registered plugin (admin only)."""
    g = gapi_gui
    db_check = next(g.database.get_db())
    try:
        if g._plugin_service:
            is_admin = g._plugin_service.is_admin(db_check, username)
        else:
            is_admin = "admin" in g.database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, "Admin access required")
    db = next(g.database.get_db())
    try:
        ok = g.database.delete_plugin(db, plugin_id)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True})
    return _err(404, "Plugin not found")
