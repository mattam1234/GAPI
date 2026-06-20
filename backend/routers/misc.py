"""Grab-bag cluster (migrated to FastAPI).

Six small legacy domains migrated together, one ``APIRouter`` per URL prefix:

  * ``i18n_router``      — ``/api/i18n``       (UNAUTHENTICATED — locale data)
  * ``shop_router``      — ``/api/shop``
  * ``events_router``    — ``/api/events``
  * ``twitch_router``    — ``/api/twitch``
  * ``cosmetics_router`` — ``/api/cosmetics``
  * ``anticheat_router`` — ``/api/anticheat``

Faithful ports — latent legacy behaviour is preserved exactly:

* ``/api/i18n`` and ``/api/i18n/{lang}`` had NO ``@require_login`` decorator in
  the legacy app — they are public locale endpoints. That is mirrored here: no
  auth dependency. The other five prefixes keep their ``@require_login`` gate.
* The ``/api/shop`` and ``/api/anticheat`` handlers reference a module-global
  ``db_service`` that is never defined on ``gapi_gui`` (the same undefined global
  behind trades / leaderboards 500s). Every handler wraps the access in a
  ``try/except`` and returns a success-faking mock response, so in production
  these routes never actually persist anything — they always fall through to the
  mock branch. Referenced here via ``gapi_gui.db_service`` so the
  ``AttributeError`` still fires and the mock fallback still runs.
* ``/api/events/*`` and ``/api/cosmetics/apply-theme`` are pure stubs whose
  ``try/except`` never trips (apply-theme additionally validates ``theme_id``).
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
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

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
    """Get shop items for purchase."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Get all shop items
        items_query = "SELECT id, name, icon, price, currency, premium FROM shop_items ORDER BY premium DESC"
        items = db.execute(items_query).fetchall()

        # Get user's owned items
        owned_query = "SELECT item_id FROM user_inventory WHERE user_id = ?"
        owned_ids = set(row[0] for row in db.execute(owned_query, (user.id,)).fetchall())

        result = []
        for item_id, name, icon, price, currency, premium in items:
            result.append({
                'id': str(item_id),
                'icon': icon,
                'name': name,
                'price': price,
                'currency': currency,
                'premium': premium,
                'owned': item_id in owned_ids
            })
        return _ok({'items': result})
    except Exception as e:
        g.gui_logger.error(f"Error loading shop: {e}")
        # Return mock data if DB unavailable
        items = [
            {'id': '1', 'icon': '🎨', 'name': 'Dark Neon Theme', 'price': 500, 'currency': 'xp', 'premium': False, 'owned': False},
            {'id': '2', 'icon': '👑', 'name': 'Legendary Title', 'price': 100, 'currency': 'coins', 'premium': True, 'owned': False},
        ]
        return _ok({'items': items})


@shop_router.post("/purchase")
def api_purchase_item(body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Purchase item from shop."""
    g = gapi_gui
    data = body or {}
    item_id = data.get('item_id', '')

    if not item_id:
        return _err(400, 'Item ID required')

    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Check if already owned
        owned_query = "SELECT 1 FROM user_inventory WHERE user_id = ? AND item_id = ?"
        if db.execute(owned_query, (user.id, int(item_id))).fetchone():
            return _err(400, 'Already owned')

        # Get item details
        item_query = "SELECT name FROM shop_items WHERE id = ?"
        item_result = db.execute(item_query, (int(item_id),)).fetchone()
        item_name = item_result[0] if item_result else f'Item {item_id}'

        # Add to inventory
        insert_query = "INSERT INTO user_inventory (user_id, item_id) VALUES (?, ?)"
        db.execute(insert_query, (user.id, int(item_id)))
        db.commit()

        # Broadcast shop purchase event
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.shop_purchase(
                    username=username,
                    item=item_name,
                    item_type='cosmetic'
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast shop purchase: {e}')

        return _ok({'success': True, 'message': 'Purchase successful', 'new_balance': 1000})
    except Exception as e:
        g.gui_logger.error(f"Error purchasing item: {e}")
        return _ok({'success': True, 'message': 'Purchase successful (mock)', 'new_balance': 1000})


# ── events ───────────────────────────────────────────────────────────────────

@events_router.get("/seasonal")
def api_get_seasonal_events(username: str = Depends(require_login)):
    """Get active seasonal events."""
    try:
        return _ok({
            'active_events': [
                {
                    'id': 1,
                    'name': 'Spring Festival 2026',
                    'season': 'spring',
                    'progress': 65,
                    'reward': '🌸 Spring Bloom Theme',
                    'days_left': 15,
                    'completed': False
                },
                {
                    'id': 2,
                    'name': 'Anniversary Celebration',
                    'season': 'year',
                    'progress': 100,
                    'reward': '🎂 Anniversary Badge',
                    'days_left': 5,
                    'completed': True,
                    'reward_claimed': False
                }
            ]
        })
    except Exception:
        return _ok({'active_events': []})


@events_router.post("/{event_id}/claim")
def api_claim_event_reward(event_id: str, username: str = Depends(require_login)):
    """Claim seasonal event reward."""
    try:
        return _ok({'success': True, 'message': 'Event reward claimed!', 'reward': '🎂 Anniversary Badge'})
    except Exception:
        return _ok({'success': True, 'message': 'Reward claimed (mock)'})


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
    """Apply a theme to user profile."""
    data = body or {}
    theme_id = data.get('theme_id')

    if not theme_id:
        return _err(400, 'Theme ID required')

    return _ok({'success': True, 'message': 'Theme applied'})


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
