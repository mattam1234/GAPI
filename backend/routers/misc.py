"""Grab-bag cluster (migrated to FastAPI).

Six small legacy domains migrated together, one ``APIRouter`` per URL prefix:

  * ``i18n_router``      — ``/api/i18n``       (UNAUTHENTICATED — locale data)
  * ``shop_router``      — ``/api/shop``
  * ``events_router``    — ``/api/events``
  * ``twitch_router``    — ``/api/twitch``
  * ``cosmetics_router`` — ``/api/cosmetics``
  * ``anticheat_router`` — ``/api/anticheat``

Mixed: three domains are now REAL persistent features; three remain faithful
legacy ports.

* ``/api/i18n`` and ``/api/i18n/{lang}`` had NO ``@require_login`` decorator in
  the legacy app — they are public locale endpoints. That is mirrored here: no
  auth dependency. The other five prefixes keep their ``@require_login`` gate.
* ``/api/shop``, ``/api/events/*`` and ``/api/cosmetics/apply-theme`` are now
  REAL persistent features backed by ``app.services.storefront_service`` and the
  ``backend/models/storefront.py`` tables (accessed via a session opened from
  ``database.SessionLocal()``). The old undefined-``gapi_gui.db_service`` /
  success-faking mock fallbacks have been removed for these three domains. The
  legacy response keys are preserved.
    - shop: lists items with per-user ``owned`` flags; purchase records a
      one-time Purchase (400 missing id, 404 unknown item, 409 already owned).
    - events: lists active events with per-user ``reward_claimed`` flags; claim
      records a once-only EventClaim (404 unknown/inactive, 409 already claimed).
    - cosmetics: apply-theme validates ``theme_id`` (400) and upserts the user's
      theme.
* The ``/api/anticheat`` handler still references a module-global ``db_service``
  that is never defined on ``gapi_gui``; its ``try/except`` catches the
  ``AttributeError`` and returns a success-faking mock response. Referenced via
  ``gapi_gui.db_service`` so that latent behaviour is preserved unchanged.
* ``/api/twitch/*`` reach the live Twitch API via ``gapi_gui._get_twitch_client``
  and the per-user picker; they return 503 when credentials are unconfigured,
  502 on Twitch auth/API errors, 500 on unexpected errors, and (for
  library-overlap) 400 when the picker is not initialised.

None of these prefixes are in the legacy ``_CACHEABLE_API_PREFIXES`` allowlist
(which only contains ``/api/permissions``, ``/api/changelog``, ``/api/health``),
so every response here received ``Cache-Control: no-store`` from the legacy
``after_request``. That header is set explicitly to preserve behaviour.

Routes:
  i18n (UNAUTHENTICATED):
    GET    /api/i18n
    GET    /api/i18n/{lang}
  shop:
    GET    /api/shop
    POST   /api/shop/purchase
  events:
    GET    /api/events/seasonal
    POST   /api/events/{event_id}/claim
  twitch:
    GET    /api/twitch/trending
    GET    /api/twitch/library-overlap
  cosmetics:
    POST   /api/cosmetics/apply-theme
  anticheat:
    GET    /api/anticheat
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

import gapi_gui
import database
from backend.dependencies import require_login
from app.services import storefront_service
from app.services.storefront_service import StorefrontError

# Importing the model module registers the storefront tables on the shared Base
# so the create_all hook in backend.main builds them.
import backend.models.storefront  # noqa: F401

i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])
shop_router = APIRouter(prefix="/api/shop", tags=["shop"])
events_router = APIRouter(prefix="/api/events", tags=["events"])
twitch_router = APIRouter(prefix="/api/twitch", tags=["twitch"])
cosmetics_router = APIRouter(prefix="/api/cosmetics", tags=["cosmetics"])
anticheat_router = APIRouter(prefix="/api/anticheat", tags=["anticheat"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


def _open_session():
    """Open a real DB session, or raise a 503-mapped StorefrontError if down."""
    if getattr(database, "SessionLocal", None) is None:
        raise StorefrontError(503, "Database not available")
    return database.SessionLocal()


# ── i18n (UNAUTHENTICATED — public locale data) ──────────────────────────────

@i18n_router.get("")
def api_i18n_list():
    """List all available locales.

    Returns a JSON object ``{"locales": [{"lang": "en", "lang_name": "English"},
    ...]}``. No authentication — mirrors the legacy public route.
    """
    g = gapi_gui
    locales = []
    try:
        for fname in sorted(g.os.listdir(g._LOCALES_DIR)):
            if not fname.endswith('.json'):
                continue
            data = g._load_locale(fname[:-5])
            if data and 'lang' in data:
                locales.append({'lang': data['lang'],
                                'lang_name': data.get('lang_name', data['lang'])})
    except Exception as exc:
        g.gui_logger.error('Error listing locales: %s', exc)
    return _ok({'locales': locales})


@i18n_router.get("/{lang}")
def api_i18n_get(lang: str):
    """Return the translation strings for *lang* (e.g. ``en``, ``es``).

    A ``404`` is returned when the requested language is not available. No
    authentication — mirrors the legacy public route.
    """
    g = gapi_gui
    data = g._load_locale(lang)
    if data is None:
        return _err(404, f"Locale '{lang}' not found")
    return _ok(data)


# ── shop ─────────────────────────────────────────────────────────────────────

@shop_router.get("")
def api_shop(username: str = Depends(require_login)):
    """List active shop items, each flagged with the caller's ownership."""
    try:
        db = _open_session()
        try:
            items = storefront_service.list_items(db, username)
        finally:
            db.close()
        return _ok({'items': items})
    except StorefrontError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading shop: %s", e)
        return _err(500, "Failed to load shop")


@shop_router.post("/purchase")
def api_purchase_item(body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Purchase a one-time item from the shop."""
    g = gapi_gui
    data = body or {}
    item_id = data.get('item_id', '')

    try:
        db = _open_session()
        try:
            result = storefront_service.purchase_item(db, username, item_id)
        finally:
            db.close()
    except StorefrontError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        g.gui_logger.error("Error purchasing item: %s", e)
        return _err(500, "Failed to purchase item")

    # Best-effort realtime notification (never affects the response).
    if g.REALTIME_AVAILABLE:
        try:
            g.realtime.RealtimeEvents.shop_purchase(
                username=username,
                item=result.get('item_name', ''),
                item_type='cosmetic'
            )
        except Exception as e:  # pragma: no cover - notification is non-critical
            g.gui_logger.warning('Failed to broadcast shop purchase: %s', e)

    return _ok({'success': True, 'message': result['message'],
                'new_balance': 1000})


# ── events ───────────────────────────────────────────────────────────────────

@events_router.get("/seasonal")
def api_get_seasonal_events(username: str = Depends(require_login)):
    """List active seasonal events, each flagged with the caller's claim."""
    try:
        db = _open_session()
        try:
            events = storefront_service.list_active_events(db, username)
        finally:
            db.close()
        return _ok({'active_events': events})
    except StorefrontError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading seasonal events: %s", e)
        return _err(500, "Failed to load events")


@events_router.post("/{event_id}/claim")
def api_claim_event_reward(event_id: str, username: str = Depends(require_login)):
    """Claim a seasonal event reward (once per user per event)."""
    try:
        db = _open_session()
        try:
            result = storefront_service.claim_event(db, username, event_id)
        finally:
            db.close()
        return _ok(result)
    except StorefrontError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error claiming event reward: %s", e)
        return _err(500, "Failed to claim reward")


# ── events: real-time delivery (SSE + polling) ───────────────────────────────
# These three routes back ``static/realtime-client.js``. They existed only as
# Flask routes in ``realtime.setup_realtime_routes`` (registered on the legacy
# app), so under the FastAPI server they 404'd — which is what spammed the
# dashboard console with failed ``/api/events/poll`` and SSE requests. Ported
# here so the live FastAPI app serves them. Auth is cookie-based (``require_login``
# decodes the Flask session cookie), which works for both ``fetch`` and
# ``EventSource`` (the latter cannot send custom headers but does send cookies).

def _realtime_channels(username: str):
    """The set of polling-cache channels relevant to one user."""
    return [
        "global", f"user:{username}", "leaderboard", "activity",
        "rankings", "achievements", "sessions", "shop", "streams",
    ]


def _dedupe_events(events):
    """Drop duplicate event payloads (some events are cached on >1 channel)."""
    seen = set()
    out = []
    for ev in events:
        key = json.dumps(ev, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


@events_router.get("/poll")
def api_events_poll(since: str = Query(default=""),
                    username: str = Depends(require_login)):
    """Polling fallback for real-time updates (used when SSE is unavailable)."""
    g = gapi_gui
    now = datetime.utcnow().isoformat()
    if not getattr(g, "REALTIME_AVAILABLE", False):
        return _ok({"success": True, "events": [], "timestamp": now})
    cache = g.realtime.polling_cache
    events = []
    for channel in _realtime_channels(username):
        events.extend(cache.get_events_since(channel, since))
    return _ok({"success": True, "events": _dedupe_events(events),
                "timestamp": now})


@events_router.get("/status")
def api_events_status(username: str = Depends(require_login)):
    """Report real-time subsystem status for the calling user."""
    g = gapi_gui
    now = datetime.utcnow().isoformat()
    if not getattr(g, "REALTIME_AVAILABLE", False):
        return _ok({"user": username, "is_online": False, "connections": 0,
                    "sse_available": False, "polling_available": True,
                    "timestamp": now})
    ws = g.realtime.ws_manager
    return _ok({"user": username,
                "is_online": ws.is_user_online(username),
                "connections": ws.get_user_connection_count(username),
                "sse_available": True, "polling_available": True,
                "timestamp": now})


@events_router.get("/stream")
async def api_events_stream(request: Request,
                            username: str = Depends(require_login)):
    """Server-Sent Events stream for real-time dashboard updates.

    Async generator (no blocking ``time.sleep``) so it doesn't tie up a worker
    thread per connected client. Emits a comment heartbeat every ~15s to keep
    intermediaries (e.g. Cloudflare) from dropping an idle stream.
    """
    g = gapi_gui

    async def _generate():
        yield (f"event: connected\n"
               f"data: {json.dumps({'type': 'connected', 'username': username})}\n\n")
        if not getattr(g, "REALTIME_AVAILABLE", False):
            return
        cache = g.realtime.polling_cache
        channels = _realtime_channels(username)
        since = datetime.utcnow().isoformat()
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                break
            new_events = []
            for channel in channels:
                new_events.extend(cache.get_events_since(channel, since))
            new_events = _dedupe_events(new_events)
            if new_events:
                for ev in new_events:
                    since = ev.get("cached_at", since)
                    event_type = ev.get("type", "update")
                    yield f"event: {event_type}\ndata: {json.dumps(ev)}\n\n"
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 15:
                    yield ": keep-alive\n\n"
                    idle_ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ── twitch ───────────────────────────────────────────────────────────────────

@twitch_router.get("/trending")
def api_twitch_trending(count: int = Query(default=20),
                        username: str = Depends(require_login)):
    """Return the top games currently live on Twitch.

    Returns 503 when Twitch credentials are not configured.
    """
    g = gapi_gui
    from twitch_client import TwitchAuthError, TwitchAPIError

    client = g._get_twitch_client()
    if client is None:
        return _err(503, (
            'Twitch credentials not configured. '
            'Add twitch_client_id and twitch_client_secret to config.json '
            'or set TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET environment variables.'
        ))

    try:
        count = max(1, min(int(count), 100))
    except (ValueError, TypeError):
        count = 20

    try:
        trending = client.get_top_games(count=count)
    except TwitchAuthError as exc:
        g.gui_logger.error("Twitch auth error: %s", exc)
        return _err(502, f'Twitch authentication failed: {exc}')
    except TwitchAPIError as exc:
        g.gui_logger.error("Twitch API error: %s", exc)
        return _err(502, f'Twitch API error: {exc}')
    except Exception as exc:
        g.gui_logger.exception("Unexpected error fetching Twitch trending: %s", exc)
        return _err(500, 'Unexpected error')

    return _ok({'trending': trending})


@twitch_router.get("/library-overlap")
def api_twitch_library_overlap(count: int = Query(default=20),
                               username: str = Depends(require_login)):
    """Return user library games that are currently trending on Twitch.

    Returns 503 when Twitch credentials are not configured.
    Returns 400 when the picker is not initialised.
    """
    g = gapi_gui
    from twitch_client import TwitchAuthError, TwitchAPIError

    if not g.picker:
        return _err(400, 'Not initialized. Please log in.')

    client = g._get_twitch_client()
    if client is None:
        return _err(503, (
            'Twitch credentials not configured. '
            'Add twitch_client_id and twitch_client_secret to config.json '
            'or set TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET environment variables.'
        ))

    try:
        count = max(1, min(int(count), 100))
    except (ValueError, TypeError):
        count = 20

    try:
        trending = client.get_top_games(count=count)
    except TwitchAuthError as exc:
        g.gui_logger.error("Twitch auth error: %s", exc)
        return _err(502, f'Twitch authentication failed: {exc}')
    except TwitchAPIError as exc:
        g.gui_logger.error("Twitch API error: %s", exc)
        return _err(502, f'Twitch API error: {exc}')
    except Exception as exc:
        g.gui_logger.exception("Unexpected error fetching Twitch trending: %s", exc)
        return _err(500, 'Unexpected error')

    with g.picker_lock:
        _p = g.ensure_picker_initialized(username)
        user_games = list(_p.games) if _p and _p.games else []

    overlap = client.find_library_overlap(trending, user_games)
    return _ok({'overlap': overlap, 'trending_count': len(trending)})


# ── cosmetics ────────────────────────────────────────────────────────────────

@cosmetics_router.post("/apply-theme")
def api_apply_theme(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Validate and upsert the user's applied cosmetic theme."""
    data = body or {}
    theme_id = data.get('theme_id')

    try:
        db = _open_session()
        try:
            result = storefront_service.apply_theme(db, username, theme_id)
        finally:
            db.close()
    except StorefrontError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error applying theme: %s", e)
        return _err(500, "Failed to apply theme")

    return _ok({'success': True, 'message': result['message']})


# ── anticheat ────────────────────────────────────────────────────────────────

@anticheat_router.get("")
def api_get_anticheat_info(username: str = Depends(require_login)):
    """Get anti-cheat integrity information."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)

        # Calculate integrity score (simplified)
        picks_query = "SELECT COUNT(*) FROM picks WHERE username = ?"
        total_picks = db.execute(picks_query, (username,)).fetchone()[0]

        # Assume mostly clean picks (variance < 5%)
        flagged_count = max(0, int(total_picks * 0.01))  # 1% flagged
        integrity = 100 - (flagged_count / max(total_picks, 1) * 100)

        flagged_picks = [
            {'session': 'Game Night #42', 'variance': 8.5, 'pick': 'Portal 2'},
        ] if flagged_count > 0 else []

        return _ok({
            'integrity_score': round(integrity, 1),
            'accuracy_variance': 2.1,
            'response_time_ms': 145,
            'flagged_picks': flagged_picks
        })
    except Exception as e:
        g.gui_logger.error(f"Error getting anti-cheat info: {e}")
        return _ok({
            'integrity_score': 99.2,
            'accuracy_variance': 2.1,
            'response_time_ms': 145,
            'flagged_picks': []
        })
