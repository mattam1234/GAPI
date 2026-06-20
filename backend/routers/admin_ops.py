"""Admin ops / observability domain (migrated to FastAPI).

Mirrors the legacy Flask admin operational + observability routes:
  * GET  /api/admin/migrations                     (require_admin -> user_manager)
  * POST /api/admin/migrations/run
  * GET  /api/admin/audit-logs                      (require_login + app_settings_service.is_admin)
  * GET  /api/admin/audit-logs/export
  * GET  /api/admin/user-activity/{target_user}
  * GET  /api/admin/security-info
  * GET  /api/admin/api-stats
  * POST /api/admin/api-stats/reset
  * GET  /api/admin/client-errors
  * POST /api/admin/client-errors/clear
  * GET  /api/admin/db/stats
  * GET  /api/admin/db/apply-indexes
  * POST /api/admin/db/apply-indexes
  * POST /api/admin/db/archive-old-picks
  * GET  /api/admin/db/backup
  * GET  /api/admin/errors/rate
  * GET  /api/admin/email/status
  * POST /api/admin/email/test

Two admin checks are in play, mirrored exactly per legacy route:
  * Most routes were decorated with the legacy ``@require_admin`` (which gates on
    ``user_manager.is_admin``) -> :func:`require_admin_um`.
  * The audit-logs / export / user-activity routes were ``@require_login`` and did
    an INLINE ``_app_settings_service.is_admin(db, username)`` check *after* the
    audit-service availability check. The ordering matters (a non-admin still gets
    a 503 when the audit service is missing), so those routes keep the inline check
    via :func:`require_login` rather than the :func:`require_admin` dependency.

Singletons are reused from ``gapi_gui`` at CALL TIME. The legacy ``after_request``
set ``Cache-Control: no-store`` on every ``/api/*`` response (these admin routes
are not in the cacheable-prefix allowlist); that header is reproduced here via the
JSONResponse helpers / explicit headers to preserve behaviour.

The api-stats GET/reset routes read & clear ``gapi_gui._api_endpoint_stats`` under
``gapi_gui._api_stats_lock``. The legacy after_request that *populates* those stats
still runs for un-migrated Flask routes; only the admin read/reset endpoints move.

db/backup, migrations/run, db/apply-indexes and archive-old-picks perform real DB
ops; ported faithfully (tests mock the underlying service/db calls).
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login

router = APIRouter(prefix="/api/admin", tags=["admin"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


def _require_inline_admin(username: str):
    """Inline admin check mirroring the legacy audit-logs routes.

    Returns ``None`` when the user is an admin, otherwise a 403 JSONResponse.
    Gates on ``_app_settings_service.is_admin`` (NOT ``user_manager.is_admin``).
    """
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")
        return None
    finally:
        if db:
            db.close()


# ── Migrations (require_admin -> require_admin_um) ───────────────────────────

@router.get("/migrations")
def api_list_migrations(_admin: str = Depends(require_admin_um)):
    """List available admin migrations (PostgreSQL)."""
    g = gapi_gui
    migrations = []
    for key, meta in g.ADMIN_MIGRATIONS.items():
        migrations.append({
            "id": key,
            "label": meta["label"],
            "description": meta["description"],
            "sql": meta["sql"],
        })
    return _ok({"migrations": migrations})


@router.post("/migrations/run")
def api_run_migration(body: Optional[dict] = Body(default=None),
                      _admin: str = Depends(require_admin_um)):
    """Run a selected migration with optional SQL override (admin only)."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, "Database not available")

    data = body or {}
    migration_id = data.get("id")
    sql_override = data.get("sql")

    if not migration_id or migration_id not in g.ADMIN_MIGRATIONS:
        return _err(400, "Invalid migration id")

    sql = (sql_override if isinstance(sql_override, str) and sql_override.strip()
           else g.ADMIN_MIGRATIONS[migration_id]["sql"])

    db = None
    try:
        db = g.database.SessionLocal()
        g._run_sql_statements(db, sql)
        db.commit()
        db.close()
        return _ok({"message": f"Migration {migration_id} executed successfully"})
    except Exception as e:
        try:
            db.rollback()
            db.close()
        except Exception:
            pass
        g.gui_logger.exception("Migration failed: %s", e)
        return _err(500, str(e))


# ── Audit logs (require_login + inline app_settings admin check) ─────────────

@router.get("/audit-logs")
def api_get_audit_logs(request: Request, username: str = Depends(require_login)):
    """Get audit logs (admin only)."""
    g = gapi_gui
    if not g._audit_service:
        return _err(503, "Audit service not available")

    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        args = request.query_params
        page = int(args.get("page", 1))
        limit = min(int(args.get("limit", 50)), 200)
        offset = (page - 1) * limit

        filters = {}
        if args.get("action"):
            filters["action"] = args.get("action")
        if args.get("user"):
            filters["username"] = args.get("user")

        result = g._audit_service.get_audit_logs(db, limit=limit, offset=offset, filters=filters)
        result["page"] = page
        return _ok(result)
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.get("/audit-logs/export")
def api_export_audit_logs(username: str = Depends(require_login)):
    """Export audit logs as CSV (admin only)."""
    g = gapi_gui
    if not g._audit_service:
        return _err(503, "Audit service not available")

    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        csv_data = g._audit_service.export_audit_logs(db)
        return _csv_response(csv_data)
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


def _csv_response(csv_data):
    from fastapi.responses import Response
    headers = dict(_NO_STORE)
    headers["Content-Disposition"] = "attachment; filename=audit_logs.csv"
    return Response(content=csv_data, media_type="text/csv", headers=headers)


@router.get("/user-activity/{target_user}")
def api_get_user_activity(target_user: str, request: Request,
                          username: str = Depends(require_login)):
    """Get activity history for a user (admin only)."""
    g = gapi_gui
    if not g._audit_service:
        return _err(503, "Audit service not available")

    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        limit = min(int(request.query_params.get("limit", 50)), 200)
        activity = g._audit_service.get_user_activity(db, target_user, limit)
        return _ok({"user": target_user, "activity": activity})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


# ── Security info (require_admin -> require_admin_um) ─────────────────────────

@router.get("/security-info")
def api_admin_security_info(_admin: str = Depends(require_admin_um)):
    """Return the active security feature flags (admin only)."""
    g = gapi_gui
    return _ok({
        "compression_enabled": g._COMPRESS_AVAILABLE,
        "rate_limiting_enabled": g._LIMITER_AVAILABLE,
        "security_headers_enabled": True,
    })


# ── API usage stats (require_admin -> require_admin_um) ───────────────────────

@router.get("/api-stats")
def api_admin_api_stats(_admin: str = Depends(require_admin_um)):
    """Return per-endpoint call counts and latency statistics (admin only)."""
    g = gapi_gui
    with g._api_stats_lock:
        rows = [
            {
                "endpoint": ep,
                "calls": s["calls"],
                "errors": s["errors"],
                "avg_ms": round(s["total_ms"] / s["calls"], 2) if s["calls"] else 0.0,
                "min_ms": round(s["min_ms"], 2) if s["min_ms"] is not None else 0.0,
                "max_ms": round(s["max_ms"], 2),
                "total_ms": round(s["total_ms"], 2),
            }
            for ep, s in g._api_endpoint_stats.items()
        ]
    rows.sort(key=lambda r: r["calls"], reverse=True)
    return _ok({"stats": rows, "endpoint_count": len(rows)})


@router.post("/api-stats/reset")
def api_admin_api_stats_reset(_admin: str = Depends(require_admin_um)):
    """Reset all in-memory API usage counters (admin only)."""
    g = gapi_gui
    with g._api_stats_lock:
        g._api_endpoint_stats.clear()
    return _ok({"reset": True})


# ── Client-side error reports (require_admin -> require_admin_um) ─────────────

@router.get("/client-errors")
def api_admin_client_errors(request: Request, _admin: str = Depends(require_admin_um)):
    """Return recent client-side error reports (admin only)."""
    g = gapi_gui
    try:
        limit = min(int(request.query_params.get("limit", 50)), g._CLIENT_ERROR_MAX)
    except (ValueError, TypeError):
        limit = 50
    with g._client_errors_lock:
        total = len(g._client_errors)
        recent = list(reversed(
            list(g._client_errors)[-limit:] if limit < total else g._client_errors))
    return _ok({"errors": recent, "total_stored": total})


@router.post("/client-errors/clear")
def api_admin_client_errors_clear(_admin: str = Depends(require_admin_um)):
    """Clear the client-side error ring buffer (admin only)."""
    g = gapi_gui
    with g._client_errors_lock:
        g._client_errors.clear()
    return _ok({"cleared": True})


# ── Database maintenance (require_admin -> require_admin_um) ──────────────────

@router.get("/db/stats")
def api_admin_db_stats(_admin: str = Depends(require_admin_um)):
    """Return per-table row counts and total database size (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return JSONResponse(
            status_code=503,
            content={"error": "Database not available", "db_available": False},
            headers=_NO_STORE)
    try:
        db = next(g.database.get_db())
        tables = g.database.get_table_stats(db)
        total_size = g.database.get_db_size_bytes()
        return _ok({
            "tables": tables,
            "total_size_bytes": total_size,
            "db_available": True,
        })
    except Exception as e:
        g.gui_logger.error("api_admin_db_stats error: %s", e)
        return _err(500, str(e))


@router.get("/db/apply-indexes")
def api_admin_db_apply_indexes_dryrun(_admin: str = Depends(require_admin_um)):
    """Dry-run: list recommended indexes that are not yet present (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        result = g.database.apply_indexes(db, dry_run=True)
        return _ok(result)
    except Exception as e:
        g.gui_logger.error("api_admin_db_apply_indexes_dryrun error: %s", e)
        return _err(500, str(e))


@router.post("/db/apply-indexes")
def api_admin_db_apply_indexes(_admin: str = Depends(require_admin_um)):
    """Create all missing recommended indexes (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = next(g.database.get_db())
        result = g.database.apply_indexes(db, dry_run=False)
        return _ok(result)
    except Exception as e:
        g.gui_logger.error("api_admin_db_apply_indexes error: %s", e)
        return _err(500, str(e))


@router.post("/db/archive-old-picks")
def api_admin_db_archive_old_picks(body: Optional[dict] = Body(default=None),
                                   _admin: str = Depends(require_admin_um)):
    """Delete pick and completed live-session records older than N days (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    data = body or {}
    try:
        days = max(1, int(data.get("days", 365)))
    except (ValueError, TypeError):
        days = 365
    try:
        db = next(g.database.get_db())
        result = g.database.archive_old_picks(db, days=days)
        return _ok(result)
    except Exception as e:
        g.gui_logger.error("api_admin_db_archive_old_picks error: %s", e)
        return _err(500, str(e))


@router.get("/db/backup")
def api_admin_db_backup(_admin: str = Depends(require_admin_um)):
    """Download a database backup (admin only).

    For SQLite databases: streams the database file as an attachment.
    For PostgreSQL or other engines: returns connection info and instructions.
    """
    import os
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        dialect = g.database.engine.dialect.name if g.database.engine else "unknown"
        if dialect == "sqlite":
            db_url = str(g.database.engine.url)
            path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
            if not path or not os.path.exists(path):
                return JSONResponse(
                    status_code=404,
                    content={"error": "SQLite file not found", "path": path},
                    headers=_NO_STORE)
            import datetime as _dt
            stamp = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            download_name = f"gapi_backup_{stamp}.db"
            headers = dict(_NO_STORE)
            headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
            headers["Content-Length"] = str(os.path.getsize(path))
            return StreamingResponse(
                g._stream_file(path),
                media_type="application/octet-stream",
                headers=headers,
            )
        else:
            return _ok({
                "message": (
                    f"Automated backup download is only supported for SQLite. "
                    f"For {dialect}, use the appropriate dump tool "
                    f"(e.g., pg_dump for PostgreSQL) against your database server."
                ),
                "dialect": dialect,
            })
    except Exception as e:
        g.gui_logger.error("api_admin_db_backup error: %s", e)
        return _err(500, str(e))


# ── Error-rate dashboard (require_admin -> require_admin_um) ──────────────────

@router.get("/errors/rate")
def api_admin_error_rate(_admin: str = Depends(require_admin_um)):
    """Return client-side error counts bucketed by hour for the last 24h (admin only)."""
    g = gapi_gui
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    buckets = [
        {"hour": (now - timedelta(hours=23 - i)).strftime("%Y-%m-%dT%H:00Z"), "count": 0}
        for i in range(24)
    ]
    total_24h = 0
    with g._client_errors_lock:
        errors_snapshot = list(g._client_errors)
        total_all = len(errors_snapshot)
    for err in errors_snapshot:
        ts_str = err.get("timestamp", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", ""))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if ts < cutoff:
            continue
        total_24h += 1
        diff_hours = int((now - ts).total_seconds() // 3600)
        slot = 23 - min(diff_hours, 23)
        buckets[slot]["count"] += 1
    return _ok({
        "buckets": buckets,
        "total_24h": total_24h,
        "total_all": total_all,
    })


# ── Email management (require_admin -> require_admin_um) ──────────────────────

@router.get("/email/status")
def api_admin_email_status(_admin: str = Depends(require_admin_um)):
    """Return the current email service configuration status (admin only)."""
    g = gapi_gui
    if g._email_service is None:
        return _ok({"configured": False, "error": "EmailService not loaded"})
    return _ok(g._email_service.config_info())


@router.post("/email/test")
def api_admin_email_test(body: Optional[dict] = Body(default=None),
                         _admin: str = Depends(require_admin_um)):
    """Send a test email to verify SMTP configuration (admin only)."""
    g = gapi_gui
    if g._email_service is None:
        return _ok({"success": False, "message": "EmailService not loaded"}, status_code=503)
    if not g._email_service.is_configured():
        return _ok({
            "success": False,
            "message": "SMTP is not configured. Set SMTP_HOST in your environment.",
        }, status_code=503)
    data = body or {}
    to_address = str(data.get("to", "")).strip()
    if not g._is_valid_email_address(to_address):
        return _ok({"success": False, "message": 'Invalid or missing "to" address'},
                   status_code=400)
    ok = g._email_service.send_test_email(to_address)
    return _ok({
        "success": ok,
        "to": to_address,
        "message": "Test email sent successfully." if ok else "Failed to send test email.",
    })
