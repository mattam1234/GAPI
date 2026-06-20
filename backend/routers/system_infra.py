"""Infra / system single-route endpoints (migrated to FastAPI).

A grab-bag of ~11 cross-cutting INFRA/SYSTEM routes that each lived alone in the
legacy Flask layer. They share no URL prefix, so they're served by a single
prefix-less ``router`` that declares each full path explicitly.

Faithful ports — legacy auth, status codes, and body shapes are preserved
exactly, including latent bugs:

* ``/api/platform/status`` reads the module-global ``picker`` directly (via
  ``gapi_gui.picker``); when it's ``None`` the handler still works (empty
  clients).

Cache-Control (mirrors the legacy ``_add_cache_control`` after_request +
``_CACHEABLE_API_PREFIXES`` = /api/permissions, /api/changelog, /api/health):

* ``GET /api/health`` and ``GET /api/changelog`` are in the cacheable allowlist,
  so on a 200 GET they received ``public, max-age=60, stale-while-revalidate=120``
  — replicated here exactly.
* Every other route here received ``no-store`` from the legacy after_request;
  set explicitly via ``_NO_STORE``.

Auth:

* UNAUTHENTICATED (no legacy decorator): GET /api/health, GET /api/status,
  GET /api/changelog, GET /api/csrf-token, POST /api/errors/report,
  POST /api/password-reset-request.
* require_login: GET /api/history, POST /api/moderation/report,
  GET /api/platform/status, GET /api/user/{username}/card,
  GET /api/user-profile/{username}.

Routes:
  GET  /api/health
  GET  /api/status
  GET  /api/changelog
  GET  /api/csrf-token
  POST /api/errors/report
  GET  /api/history
  POST /api/moderation/report
  POST /api/password-reset-request
  GET  /api/platform/status
  GET  /api/user/{username}/card
  GET  /api/user-profile/{username}
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import get_current_user, require_login

router = APIRouter(tags=["system-infra"])

_NO_STORE = {"Cache-Control": "no-store"}
# Mirrors the legacy cacheable-allowlist header for GET 200 on
# /api/health and /api/changelog.
_CACHEABLE = {"Cache-Control": "public, max-age=60, stale-while-revalidate=120"}


def _err(status_code, message, headers=None):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=headers or _NO_STORE)


def _ok(content, status_code=200, headers=None):
    return JSONResponse(status_code=status_code, content=content,
                        headers=headers or _NO_STORE)


# ── health / status (unauthenticated) ───────────────────────────────────────

@router.get("/api/health")
def api_health(username: Optional[str] = Depends(get_current_user)):
    """Public lightweight health endpoint for external clients."""
    return _ok({
        'ok': True,
        'status': 'healthy',
        'authenticated': bool(username),
        'current_user': username if username else None,
    }, headers=_CACHEABLE)


@router.get("/api/status")
def api_status(username: Optional[str] = Depends(get_current_user)):
    """Get application status."""
    if not username:
        return _ok({
            'ready': False,
            'logged_in': False,
            'message': 'Please log in',
        })

    p = gapi_gui.ensure_picker_initialized(username)

    if p is None:
        return _ok({
            'ready': False,
            'logged_in': True,
            'message': 'Loading games...',
        })

    return _ok({
        'ready': True,
        'logged_in': True,
        'current_user': username,
        'is_admin': gapi_gui.user_manager.is_admin(username),
        'total_games': len(p.games) if p.games else 0,
        'favorites': len(p.favorites) if p.favorites else 0,
    })


# ── changelog (unauthenticated, cacheable) ──────────────────────────────────

@router.get("/api/changelog")
def api_changelog(limit: Optional[str] = Query(default=None)):
    """Return a structured API changelog.

    Query params:
      ``limit`` – max versions to return (default all)
    """
    g = gapi_gui
    changelog = g._API_CHANGELOG
    try:
        n = int(limit) if limit is not None else len(changelog)
        n = max(1, min(n, len(changelog)))
    except (ValueError, TypeError):
        n = len(changelog)
    return _ok({
        'changelog': changelog[:n],
        'total_versions': len(changelog),
    }, headers=_CACHEABLE)


# ── csrf token (unauthenticated) ────────────────────────────────────────────

@router.get("/api/csrf-token")
def api_get_csrf_token():
    """Issue (or refresh) a CSRF token for the current browser session.

    Sets a ``csrf_token`` cookie (SameSite=Lax, HttpOnly=False so JavaScript
    can read it) and returns the same value in the JSON body.
    """
    g = gapi_gui
    token = g._generate_csrf_token()
    resp = _ok({'token': token})
    _csrf_secure = g.os.environ.get('GAPI_CSRF_SECURE', '').lower() in ('1', 'true', 'yes')
    resp.set_cookie(
        key=g._CSRF_COOKIE_NAME,
        value=token,
        samesite='Lax',
        httponly=False,     # must be readable by JS to send as header
        secure=_csrf_secure,
        max_age=86400,      # 1 day
        path='/',
    )
    return resp


# ── client error reporting (unauthenticated) ────────────────────────────────

@router.post("/api/errors/report")
def api_errors_report(request: Request,
                      body: Optional[dict] = Body(default=None),
                      username: Optional[str] = Depends(get_current_user)):
    """Accept a JavaScript error report from the browser.

    Stored in a fixed-size ring buffer (most recent ``_CLIENT_ERROR_MAX``
    entries) and logged at WARNING level. Returns 201.
    """
    g = gapi_gui
    data = body or {}
    entry = {
        'timestamp': g.datetime.now(g.timezone.utc).isoformat(),
        'message': str(data.get('message', ''))[:500],
        'stack': str(data.get('stack', ''))[:2000],
        'url': str(data.get('url', ''))[:500],
        'line': data.get('line'),
        'col': data.get('col'),
        'user_agent': str(
            data.get('user_agent') or request.headers.get('User-Agent', '')
        )[:300],
        'username': username,
    }
    g.gui_logger.warning('Client-side error reported: %s at %s',
                         entry['message'], entry['url'])
    with g._client_errors_lock:
        g._client_errors.append(entry)
    return _ok({'recorded': True}, status_code=201)


# ── pick history (require_login) ────────────────────────────────────────────

@router.get("/api/history")
def api_history(username: str = Depends(require_login)):
    """Return recent pick history for mobile client compatibility."""
    g = gapi_gui
    p = g.ensure_picker_initialized(username)
    if p is None:
        return _ok({'history': []})

    games_by_id = {
        str(game.get('game_id')): game
        for game in (p.games or [])
        if game.get('game_id')
    }

    entries = []
    recent_ids = list(p.history[-50:]) if getattr(p, 'history', None) else []
    now_iso = g.datetime.now(g.timezone.utc).isoformat()
    for idx, game_id in enumerate(reversed(recent_ids), start=1):
        game = games_by_id.get(str(game_id), {})
        platform = game.get('platform', '')
        app_id = game.get('appid')
        if not platform and isinstance(game_id, str) and ':' in game_id:
            platform = game_id.split(':', 1)[0]
        if app_id is None and isinstance(game_id, str) and ':' in game_id:
            app_id = game_id.split(':', 1)[1]
        entries.append({
            'id': idx,
            'game_name': game.get('name') or str(game_id),
            'game_id': str(game_id),
            'platform': platform or 'steam',
            'picked_at': now_iso,
            'playtime_at_pick': int(game.get('playtime_forever', 0) or 0),
            'app_id': app_id,
        })

    return _ok({'history': entries})


# ── moderation report (require_login) ───────────────────────────────────────

@router.post("/api/moderation/report")
def api_report_content(body: Optional[dict] = Body(default=None),
                       username: str = Depends(require_login)):
    """Report user content for moderation."""
    g = gapi_gui
    if not g._moderation_service:
        return _err(503, 'Moderation service not available')

    db = next(g.database.get_db())
    try:
        data = body or {}
        report_type = data.get('type', 'user')  # user, chat, review
        reason = data.get('reason', '')
        description = data.get('description', '')
        reported_user = data.get('reported_user')
        resource_id = data.get('resource_id')

        if not reason:
            return _err(400, 'Reason required')

        report_id = g._moderation_service.report_user_content(
            db, username, report_type, reason, description, reported_user, resource_id
        )
        return _ok({'success': bool(report_id), 'report_id': report_id})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


# ── password reset request (unauthenticated) ────────────────────────────────

@router.post("/api/password-reset-request")
def api_password_reset_request(body: Optional[dict] = Body(default=None)):
    """Submit a password reset request (public, no authentication required)."""
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _err(503, 'Database not available')
    data = body or {}
    username = (data.get('username') or '').strip()
    if not username:
        return _err(400, 'Username is required')
    try:
        db = g.database.SessionLocal()
        user = db.query(g.database.User).filter(
            g.database.User.username == username).first()
        if not user:
            db.close()
            # Generic response to avoid username enumeration
            return _ok({'message': 'If that username exists, your request has been recorded.'})
        entry = g.database.PasswordResetRequest(username=username)
        db.add(entry)
        db.commit()
        db.close()
        g.gui_logger.info('Password reset requested for user: %s', username)
        return _ok({'message': 'Password reset request submitted. An admin will contact you.'})
    except Exception as e:
        g.gui_logger.exception('Error creating password reset request: %s', e)
        return _err(500, 'Failed to submit request')


# ── platform status (require_login) ─────────────────────────────────────────

@router.get("/api/platform/status")
def api_platform_status(username: str = Depends(require_login)):
    """Return authentication / configuration status of all connected platforms."""
    g = gapi_gui
    from platform_clients import (EpicOAuthClient, GOGOAuthClient, XboxAPIClient,
                                  PSNClient, NintendoEShopClient)
    clients = g.picker.clients if g.picker else {}
    status: Dict[str, Any] = {}

    # Steam
    steam = clients.get('steam')
    status['steam'] = {
        'configured': steam is not None,
        'authenticated': steam is not None,
    }

    # Epic
    epic = clients.get('epic')
    status['epic'] = {
        'configured': epic is not None,
        'authenticated': isinstance(epic, EpicOAuthClient) and epic.is_authenticated,
    }

    # GOG
    gog = clients.get('gog')
    status['gog'] = {
        'configured': gog is not None,
        'authenticated': isinstance(gog, GOGOAuthClient) and gog.is_authenticated,
    }

    # Xbox
    xbox = clients.get('xbox')
    status['xbox'] = {
        'configured': xbox is not None,
        'authenticated': isinstance(xbox, XboxAPIClient) and xbox._xsts_token is not None,
    }

    # PSN
    psn = clients.get('psn')
    status['psn'] = {
        'configured': psn is not None,
        'authenticated': isinstance(psn, PSNClient) and psn.is_authenticated,
    }

    # Nintendo (catalog only — always "authenticated" when configured)
    nintendo = clients.get('nintendo')
    status['nintendo'] = {
        'configured': nintendo is not None,
        'authenticated': isinstance(nintendo, NintendoEShopClient),
        'note': 'catalog only — no library API available',
    }

    return _ok({'platforms': status})


# ── user card (require_login) ───────────────────────────────────────────────

@router.get("/api/user/{username}/card")
def api_user_card(username: str, _user: str = Depends(require_login)):
    """Return the profile card for *username*."""
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        if g._leaderboard_service:
            card = g._leaderboard_service.get_user_card(db, username)
        else:
            card = g.database.get_user_card(db, username)
    finally:
        if db:
            db.close()
    if not card:
        return _err(404, 'User not found')
    return _ok(card)


# ── user profile card (require_login) ───────────────────────────────────────

@router.get("/api/user-profile/{username}")
def api_get_user_profile(username: str, _user: str = Depends(require_login)):
    """Get user profile card (display name, bio, avatar, stats, roles, etc)."""
    g = gapi_gui
    if not username:
        return _err(400, 'username is required')

    db = next(g.database.get_db())
    try:
        user_card = g.database.get_user_card(db, username)
        if not user_card:
            return _err(404, f'User "{username}" not found')
        return _ok(user_card)
    finally:
        if db:
            db.close()
