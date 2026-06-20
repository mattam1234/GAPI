"""Admin console cluster (migrated to FastAPI).

Three legacy admin sub-domains under ``/api/admin``, served from one router:

  * Discord bot management — start/stop/restart a managed ``discord_bot.py``
    subprocess, inspect status/stats/diagnostics, read/write ``config.json``,
    and CRUD the Discord→Steam user mappings stored on the primary users table.
  * Moderation + profanity filter — list pending reports, take moderation
    actions, read/update the profanity word list (via ``_moderation_service``).
  * App settings + password-reset requests — admin-controlled settings (plus a
    PUBLIC unauthenticated subset) and the password-reset request inbox.

Auth (mirrors the legacy decorators EXACTLY):

  * The Discord-bot and password-reset routes were ``@require_admin`` decorated
    (``user_manager.is_admin``) -> :func:`require_admin_um`.
  * The moderation/profanity/settings routes were ``@require_login`` decorated
    and performed their OWN ``_app_settings_service.is_admin(db, username)``
    check INLINE (returning 503 for a missing service BEFORE the admin check,
    then 403). That ordering is reproduced inline rather than via a dependency
    so the exact status-code sequence is preserved.
  * ``GET /api/admin/settings/public`` had NO decorator at all — it is
    UNAUTHENTICATED (announcement / feature flags for the login screen).

None of these paths are in the legacy ``_CACHEABLE_API_PREFIXES`` allowlist
(``/api/permissions``, ``/api/changelog``, ``/api/health``), so every response
received ``Cache-Control: no-store`` from the legacy ``after_request``. That is
replicated via the ``_NO_STORE`` header on every response.

Faithful ports: the Discord-bot subprocess management, config-file IO, and DB
mutations are reproduced via ``gapi_gui.*`` at call time (so the same module
singletons / locks are shared with the legacy app). Tests must mock the bot
manager — no real subprocess is spawned.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_admin_um, require_login

router = APIRouter(prefix="/api/admin", tags=["admin"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ───────────────────────────────────────────────────────────────────────────
# Moderation + profanity filter (@require_login + inline admin check)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/moderation/reports")
def api_get_reports(request: Request, _user: str = Depends(require_login)):
    """Get pending moderation reports (admin only)."""
    g = gapi_gui
    if not g._moderation_service:
        return _err(503, "Moderation service not available")

    username = g.get_current_username()
    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        page = int(request.query_params.get("page", 1))
        limit = min(int(request.query_params.get("limit", 20)), 100)
        offset = (page - 1) * limit

        result = g._moderation_service.get_pending_reports(db, limit, offset)
        result["page"] = page
        return _ok(result)
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/moderation/action")
def api_moderation_action(body: Optional[dict] = Body(default=None),
                          _user: str = Depends(require_login)):
    """Take a moderation action on a report (admin only)."""
    g = gapi_gui
    if not g._moderation_service:
        return _err(503, "Moderation service not available")

    username = g.get_current_username()
    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        data = body or {}
        report_id = data.get("report_id")
        action = data.get("action")  # warn, mute, ban, dismiss
        duration = data.get("duration")
        notes = data.get("notes")

        ok = g._moderation_service.take_moderation_action(
            db, report_id, username, action, notes, duration
        )
        return _ok({"success": ok})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.get("/profanity-filter")
def api_get_profanity_filter(_user: str = Depends(require_login)):
    """Get current profanity filter words (admin only)."""
    g = gapi_gui
    if not g._moderation_service:
        return _err(503, "Moderation service not available")

    username = g.get_current_username()
    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        words = g._moderation_service.get_profanity_filter(db)
        return _ok({"words": words})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/profanity-filter")
def api_update_profanity_filter(body: Optional[dict] = Body(default=None),
                                _user: str = Depends(require_login)):
    """Add a word to profanity filter (admin only)."""
    g = gapi_gui
    if not g._moderation_service:
        return _err(503, "Moderation service not available")

    username = g.get_current_username()
    db = next(g.database.get_db())
    try:
        if not (g._app_settings_service and g._app_settings_service.is_admin(db, username)):
            return _err(403, "Admin access required")

        data = body or {}
        action = data.get("action", "add")  # add or remove
        word = data.get("word", "").strip().lower()

        if not word:
            return _err(400, "Word required")

        if action == "remove":
            ok = g._moderation_service.remove_profanity_word(db, word)
        else:
            severity = data.get("severity", 1)
            auto_action = data.get("auto_action", "flag")
            ok = g._moderation_service.add_profanity_word(db, word, severity, auto_action, username)

        return _ok({"success": ok})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


# ───────────────────────────────────────────────────────────────────────────
# App settings (@require_login + inline admin check) + PUBLIC subset
# ───────────────────────────────────────────────────────────────────────────

@router.get("/settings")
def api_get_app_settings(_user: str = Depends(require_login)):
    """Return all admin-controlled app settings (admin only)."""
    g = gapi_gui
    username = g.get_current_username()
    if not username:
        return _err(401, "Not authenticated")

    # Ensure username is a string
    username_str = str(username) if username else None
    if not username_str or username_str == "None":
        return _err(401, "Invalid user")

    db_check = next(g.database.get_db())
    try:
        if g._app_settings_service:
            is_admin = g._app_settings_service.is_admin(db_check, username_str)
        else:
            is_admin = "admin" in g.database.get_user_roles(db_check, username_str)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, "Admin access required")
    db = next(g.database.get_db())
    try:
        if g._app_settings_service:
            settings = g._app_settings_service.get_with_meta(db)
        else:
            settings = g.database.get_settings_with_meta(db)
    finally:
        if db:
            db.close()
    return _ok({"settings": settings})


@router.post("/settings")
def api_save_app_settings(body: Optional[dict] = Body(default=None),
                          _user: str = Depends(require_login)):
    """Save one or more app settings (admin only)."""
    g = gapi_gui
    username = g.get_current_username()
    if not username:
        return _err(401, "Not authenticated")

    # Ensure username is a string
    username_str = str(username) if username else None
    if not username_str or username_str == "None":
        return _err(401, "Invalid user")

    db_check = next(g.database.get_db())
    try:
        if g._app_settings_service:
            is_admin = g._app_settings_service.is_admin(db_check, username_str)
        else:
            is_admin = "admin" in g.database.get_user_roles(db_check, username_str)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, "Admin access required")
    data = body or {}
    updates = data.get("settings", {})
    if not isinstance(updates, dict) or not updates:
        return _err(400, "settings dict is required")
    db = next(g.database.get_db())
    try:
        if g._app_settings_service:
            ok = g._app_settings_service.save(db, updates, updated_by=username_str)
        else:
            ok = g.database.set_app_settings(db, updates, updated_by=username_str)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True})
    return _err(500, "Failed to save settings")


@router.get("/settings/public")
def api_public_settings():
    """Return safe public-facing settings (no auth required)."""
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        if g._app_settings_service:
            announcement = g._app_settings_service.get(db, "announcement", "")
            chat_enabled = g._app_settings_service.get(db, "chat_enabled", "true")
            leaderboard_public = g._app_settings_service.get(db, "leaderboard_public", "true")
            plugins_enabled = g._app_settings_service.get(db, "plugins_enabled", "true")
        else:
            announcement = g.database.get_app_setting(db, "announcement", "")
            chat_enabled = g.database.get_app_setting(db, "chat_enabled", "true")
            leaderboard_public = g.database.get_app_setting(db, "leaderboard_public", "true")
            plugins_enabled = g.database.get_app_setting(db, "plugins_enabled", "true")
    finally:
        if db:
            db.close()
    return _ok({
        "announcement": announcement,
        "chat_enabled": chat_enabled == "true",
        "leaderboard_public": leaderboard_public == "true",
        "plugins_enabled": plugins_enabled == "true",
    })


# ───────────────────────────────────────────────────────────────────────────
# Password reset requests (@require_admin -> require_admin_um)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/password-reset-requests")
def api_admin_password_reset_requests(_admin: str = Depends(require_admin_um)):
    """List pending password reset requests (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    try:
        db = g.database.SessionLocal()
        rows = (
            db.query(g.database.PasswordResetRequest)
            .order_by(g.database.PasswordResetRequest.requested_at.desc())
            .all()
        )
        result = [
            {
                "id": r.id,
                "username": r.username,
                "requested_at": r.requested_at.isoformat() if r.requested_at else None,
                "status": r.status,
                "dismissed_by": r.dismissed_by,
                "dismissed_at": r.dismissed_at.isoformat() if r.dismissed_at else None,
            }
            for r in rows
        ]
        db.close()
        return _ok({"requests": result})
    except Exception as e:
        g.gui_logger.exception("Error fetching password reset requests: %s", e)
        return _err(500, "Failed to fetch requests")


@router.post("/password-reset-requests/{request_id}/dismiss")
def api_admin_password_reset_dismiss(request_id: int,
                                     _admin: str = Depends(require_admin_um)):
    """Mark a password reset request as dismissed (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, "Database not available")
    admin_user = g.get_current_username()
    try:
        db = g.database.SessionLocal()
        entry = db.query(g.database.PasswordResetRequest).filter(
            g.database.PasswordResetRequest.id == request_id
        ).first()
        if not entry:
            db.close()
            return _err(404, "Request not found")
        entry.status = "dismissed"
        entry.dismissed_by = admin_user
        entry.dismissed_at = g.datetime.now(g.timezone.utc).replace(tzinfo=None)
        db.commit()
        db.close()
        return _ok({"message": "Request dismissed"})
    except Exception as e:
        g.gui_logger.exception("Error dismissing password reset request: %s", e)
        return _err(500, "Failed to dismiss request")


# ───────────────────────────────────────────────────────────────────────────
# Discord bot management (@require_admin -> require_admin_um)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/discord-bot/status")
def api_discord_bot_status(_admin: str = Depends(require_admin_um)):
    """Return the current status of the Discord bot process (admin only)."""
    g = gapi_gui
    with g._discord_bot_lock:
        running = g._discord_bot_is_running()
        pid = g._discord_bot_process.pid if running else None
        log = list(g._discord_bot_log_lines)
    return _ok({"running": running, "pid": pid, "log": log})


@router.post("/discord-bot/start")
def api_discord_bot_start(body: Optional[dict] = Body(default=None),
                          _admin: str = Depends(require_admin_um)):
    """Start the Discord bot process (admin only)."""
    g = gapi_gui
    data = body or {}
    try:
        config_path = g._validate_repo_config_path(
            data.get("config_path", g.DEFAULT_CONFIG_PATH))
    except ValueError:
        return _err(400, "Invalid config_path")

    started, proc, error = g._start_managed_discord_bot(config_path)
    if not started:
        if error == "Discord bot is already running":
            return _err(409, error)
        return _err(500, error)
    return _ok({"started": True, "pid": proc.pid})


@router.post("/discord-bot/stop")
def api_discord_bot_stop(_admin: str = Depends(require_admin_um)):
    """Stop the Discord bot process (admin only)."""
    g = gapi_gui
    with g._discord_bot_lock:
        if not g._discord_bot_is_running():
            return _err(409, "Discord bot is not running")

        proc = g._discord_bot_process
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except g.subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except OSError:
            pass
        g._discord_bot_process = None

    return _ok({"stopped": True})


@router.get("/discord-bot/stats")
def api_discord_bot_stats(_admin: str = Depends(require_admin_um)):
    """Return Discord bot statistics from DB-backed linked users (admin only)."""
    g = gapi_gui
    linked_users = len(g._get_discord_linked_users_from_db())
    config_exists = bool(g.DB_AVAILABLE and g.ensure_db_available())

    with g._discord_bot_lock:
        running = g._discord_bot_is_running()

    return _ok({
        "running": running,
        "linked_users": linked_users,
        "config_exists": config_exists,
    })


@router.get("/discord-bot/config")
def api_discord_bot_get_config(_admin: str = Depends(require_admin_um)):
    """Return Discord bot configuration (admin only)."""
    g = gapi_gui
    config_path = g.DEFAULT_CONFIG_PATH
    if not g.os.path.exists(config_path):
        return _ok({"config_exists": False, "discord_token_set": False,
                    "steam_api_key_set": False})
    try:
        with open(config_path, "r") as fh:
            cfg = g.json.load(fh)
    except (g.json.JSONDecodeError, IOError):
        return _err(500, "Failed to read config.json")

    token = cfg.get("discord_bot_token", "")
    steam_key = cfg.get("steam_api_key", "")
    return _ok({
        "config_exists": True,
        "discord_token_set": bool(token),
        "steam_api_key_set": bool(steam_key),
    })


@router.post("/discord-bot/config")
def api_discord_bot_save_config(body: Optional[dict] = Body(default=None),
                                _admin: str = Depends(require_admin_um)):
    """Save Discord bot token, client ID, and/or Steam API key (admin only)."""
    g = gapi_gui
    data = body or {}
    token = data.get("discord_bot_token", "").strip()
    client_id = data.get("discord_bot_client_id", "").strip()
    steam_key = data.get("steam_api_key", "").strip()

    if not token and not client_id and not steam_key:
        return _err(400, "Provide at least one value: discord_bot_token, "
                         "discord_bot_client_id, or steam_api_key")

    config_path = g.DEFAULT_CONFIG_PATH
    cfg = {}
    if g.os.path.exists(config_path):
        try:
            with open(config_path, "r") as fh:
                cfg = g.json.load(fh)
        except (g.json.JSONDecodeError, IOError):
            pass

    if token:
        cfg["discord_bot_token"] = token
    if client_id:
        cfg["discord_bot_client_id"] = client_id
    if steam_key:
        cfg["steam_api_key"] = steam_key

    try:
        g.gapi._atomic_write_json(config_path, cfg)
    except IOError as exc:
        return _err(500, f"Failed to save config: {exc}")

    return _ok({"saved": True})


@router.post("/discord-bot/restart")
def api_discord_bot_restart(body: Optional[dict] = Body(default=None),
                            _admin: str = Depends(require_admin_um)):
    """Restart the Discord bot process (admin only)."""
    g = gapi_gui
    data = body or {}
    try:
        config_path = g._validate_repo_config_path(
            data.get("config_path", g.DEFAULT_CONFIG_PATH))
    except ValueError:
        return _err(400, "Invalid config_path")

    with g._discord_bot_lock:
        # Terminate existing process if running
        if g._discord_bot_is_running():
            proc = g._discord_bot_process
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except g.subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except OSError:
                pass
            g._discord_bot_process = None

    started, proc, error = g._start_managed_discord_bot(config_path)
    if not started:
        return _err(500, error)
    return _ok({"restarted": True, "pid": proc.pid})


@router.get("/discord-bot/users")
def api_discord_bot_list_users(_admin: str = Depends(require_admin_um)):
    """List all Discord-linked users stored in the database (admin only)."""
    g = gapi_gui
    return _ok({"users": g._get_discord_linked_users_from_db()})


@router.post("/discord-bot/users")
def api_discord_bot_add_user(body: Optional[dict] = Body(default=None),
                             _admin: str = Depends(require_admin_um)):
    """Add or update a Discord->Steam mapping (admin only)."""
    g = gapi_gui
    data = body or {}
    discord_id = str(data.get("discord_id", "")).strip()
    steam_id = str(data.get("steam_id", "")).strip()
    username = str(data.get("username", "")).strip()

    if not discord_id or not steam_id:
        return _err(400, "discord_id and steam_id are required")
    if not discord_id.isdigit():
        return _err(400, "discord_id must be numeric")
    if not steam_id.isdigit():
        return _err(400, "steam_id must be numeric")

    if not g.DB_AVAILABLE or not g.ensure_db_available():
        return _err(503, "Database not available")

    db = None
    try:
        db = g.database.SessionLocal()
        user = db.query(g.database.User).filter(g.database.User.steam_id == steam_id).first()
        if not user and username:
            user = g.database.get_user_by_username(db, username)
        if not user:
            return _err(404, "User with matching Steam ID or username not found")
        user.discord_id = discord_id
        if not getattr(user, "steam_id", None):
            user.steam_id = steam_id
        db.commit()
    except Exception as exc:
        if db:
            db.rollback()
        g.gui_logger.warning("Failed to save Discord mapping: %s", exc)
        return _err(500, "Failed to save Discord mapping")
    finally:
        if db:
            db.close()

    return _ok({"saved": True, "discord_id": discord_id, "steam_id": steam_id})


@router.delete("/discord-bot/users/{discord_id}")
def api_discord_bot_remove_user(discord_id: str,
                                _admin: str = Depends(require_admin_um)):
    """Remove a Discord->Steam mapping from the database (admin only)."""
    g = gapi_gui
    if not g.DB_AVAILABLE or not g.ensure_db_available():
        return _err(503, "Database not available")
    db = None
    try:
        db = g.database.SessionLocal()
        user = g.database.get_user_by_discord_id(db, discord_id)
        if not user:
            return _err(404, "User not found")
        user.discord_id = None
        db.commit()
        return _ok({"removed": True})
    except Exception as exc:
        if db:
            db.rollback()
        g.gui_logger.warning("Failed to remove Discord mapping: %s", exc)
        return _err(500, "Failed to remove user")
    finally:
        if db:
            db.close()


@router.get("/discord-bot/diagnostics")
def api_discord_bot_diagnostics(_admin: str = Depends(require_admin_um)):
    """Get Discord bot diagnostics and environment info (admin only)."""
    g = gapi_gui
    import sys
    config_path = "config.json"

    # Check Steam API key source
    steam_key_from_env = g.os.getenv("STEAM_API_KEY")
    steam_key_source = "missing"
    steam_key_set = False

    if steam_key_from_env:
        steam_key_source = "env"
        steam_key_set = True
    elif g.os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = g.json.load(f)
                if cfg.get("steam_api_key"):
                    steam_key_source = "config"
                    steam_key_set = True
        except (g.json.JSONDecodeError, IOError):
            pass

    # Check Discord token
    discord_token_set = False
    if g.os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = g.json.load(f)
                discord_token_set = bool(cfg.get("discord_bot_token"))
        except (g.json.JSONDecodeError, IOError):
            pass

    # Generate bot invite URL (requires bot client ID from config)
    bot_invite_url = None
    if g.os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = g.json.load(f)
                client_id = cfg.get("discord_bot_client_id")
                if client_id:
                    permissions = 2147487744
                    bot_invite_url = (
                        f"https://discord.com/api/oauth2/authorize?client_id={client_id}"
                        f"&permissions={permissions}&scope=bot%20applications.commands"
                    )
        except (g.json.JSONDecodeError, IOError):
            pass

    return _ok({
        "steam_api_key_source": steam_key_source,
        "steam_api_key_set": steam_key_set,
        "discord_token_set": discord_token_set,
        "config_file_exists": g.os.path.exists(config_path),
        "discord_config_exists": bool(g.DB_AVAILABLE and g.ensure_db_available()),
        "bot_invite_url": bot_invite_url,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    })
