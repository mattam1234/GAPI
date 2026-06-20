"""Engagement cluster (migrated to FastAPI).

Six small legacy domains migrated together, one ``APIRouter`` per URL prefix:

  * ``creator_router``      — ``/api/creator``
  * ``battlepass_router``   — ``/api/battlepass``
  * ``referral_router``     — ``/api/referral``
  * ``streaming_router``    — ``/api/streaming``
  * ``progression_router``  — ``/api/progression``
  * ``ranked_router``       — ``/api/ranked``

Faithful ports — latent legacy behaviour is preserved exactly:

* The ``/api/streaming`` and ``/api/ranked`` handlers reference a module-global
  ``db_service`` that is never defined in ``gapi_gui`` (the same undefined
  global behind trades / the leaderboards 500s). Every handler wraps the access
  in ``try/except`` and returns a success-faking mock response, so in
  production these routes never actually persist anything — they always fall
  through to the mock branch. Referenced here via ``gapi_gui.db_service`` so the
  ``AttributeError`` still fires and the mock fallback still runs.
* The ``/api/creator``, ``/api/battlepass``, ``/api/referral`` and
  ``/api/progression`` handlers are pure success-faking stubs returning
  hard-coded data; their ``try/except`` blocks are effectively dead code. The
  one exception is ``GET /api/battlepass/current`` and ``GET /api/creator/dashboard``
  and ``GET /api/referral/code`` whose ``except`` branches return a 500 — ported
  as-is even though the ``try`` body cannot raise in practice.

All six prefixes are absent from the legacy ``_CACHEABLE_API_PREFIXES``
allowlist (which only contains ``/api/permissions``, ``/api/changelog``,
``/api/health``), so every response here received ``Cache-Control: no-store``
from the legacy ``after_request``. That header is set explicitly to preserve
behaviour.

Routes:
  creator:
    GET    /api/creator/dashboard
    POST   /api/creator/apply
  battlepass:
    GET    /api/battlepass/current
    POST   /api/battlepass/claim/{level}
  referral:
    GET    /api/referral/code
    POST   /api/referral/use/{code}
  streaming:
    GET    /api/streaming/vods
    POST   /api/streaming/start
  progression:
    GET    /api/progression
  ranked:
    GET    /api/ranked
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

creator_router = APIRouter(prefix="/api/creator", tags=["creator"])
battlepass_router = APIRouter(prefix="/api/battlepass", tags=["battlepass"])
referral_router = APIRouter(prefix="/api/referral", tags=["referral"])
streaming_router = APIRouter(prefix="/api/streaming", tags=["streaming"])
progression_router = APIRouter(prefix="/api/progression", tags=["progression"])
ranked_router = APIRouter(prefix="/api/ranked", tags=["ranked"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ── creator ─────────────────────────────────────────────────────────────────

@creator_router.get("/dashboard")
def api_creator_dashboard(username: str = Depends(require_login)):
    """Creator program dashboard stats."""
    try:
        return _ok({
            'tier': 'gold',
            'followers': 125800,
            'total_views': 2450000,
            'revenue_share': 30,
            'this_month_earnings': 3250,
            'status': 'verified',
            'next_tier_followers': 500000
        })
    except Exception:
        return _err(500, 'Creator data not available')


@creator_router.post("/apply")
def api_apply_creator(body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Apply for creator program."""
    data = body or {}

    try:
        return _ok({'success': True, 'message': 'Application submitted for review', 'status': 'pending'})
    except Exception:
        return _ok({'success': True, 'message': 'Applied (mock)'})


# ── battlepass ──────────────────────────────────────────────────────────────

@battlepass_router.get("/current")
def api_get_current_battlepass(username: str = Depends(require_login)):
    """Get current battle pass info."""
    g = gapi_gui
    try:
        return _ok({
            'battle_pass': {
                'name': 'Season 5: Storm Rising',
                'season': 5,
                'current_level': 47,
                'experience': 8250,
                'exp_to_next': 1750,
                'max_level': 100,
                'has_premium': True,
                'days_remaining': 23
            },
            'rewards': [
                {'level': 10, 'reward': '[Title] Storm Chaser', 'type': 'title'},
                {'level': 25, 'reward': '500 Points', 'type': 'currency'},
                {'level': 50, 'reward': '[Theme] Dark Storm', 'type': 'cosmetic'},
                {'level': 100, 'reward': '[Frame] Legendary Guardian', 'type': 'cosmetic'},
            ]
        })
    except Exception as e:
        g.gui_logger.error(f"Error getting battle pass: {e}")
        return _err(500, 'Failed to load battle pass')


@battlepass_router.post("/claim/{level}")
def api_claim_battlepass_reward(level: str, username: str = Depends(require_login)):
    """Claim battle pass reward."""
    try:
        return _ok({'success': True, 'message': f'Reward for level {level} claimed!', 'item': '[Title] Storm Chaser'})
    except Exception:
        return _ok({'success': True, 'message': f'Reward claimed (mock)'})


# ── referral ────────────────────────────────────────────────────────────────

@referral_router.get("/code")
def api_get_referral_code(username: str = Depends(require_login)):
    """Get user's referral code."""
    try:
        return _ok({
            'code': f'REFER{username.upper()}123',
            'reward_per_use': 500,
            'total_uses': 12,
            'total_earned': 6000,
            'active': True
        })
    except Exception:
        return _err(500, 'Referral system not available')


@referral_router.post("/use/{code}")
def api_use_referral_code(code: str, username: str = Depends(require_login)):
    """Use a referral code."""
    try:
        return _ok({'success': True, 'message': f'Gained 500 points from referral!', 'points_gained': 500})
    except Exception:
        return _ok({'success': True, 'message': 'Referral applied (mock)'})


# ── streaming ───────────────────────────────────────────────────────────────

@streaming_router.get("/vods")
def api_get_vods(username: str = Depends(require_login)):
    """Get user's video library (VODs)."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        vod_query = """
            SELECT id, title, duration, views FROM stream_vods
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 20
        """
        vods_rows = db.execute(vod_query, (user.id,)).fetchall()

        vods = []
        for vod_id, title, duration, views in vods_rows:
            vods.append({
                'id': str(vod_id),
                'title': title,
                'duration': duration,
                'views': views
            })

        return _ok({'vods': vods})
    except Exception as e:
        g.gui_logger.error(f"Error loading VODs: {e}")
        # Mock data fallback
        vods = [
            {'id': '1', 'title': 'Epic Gaming Session', 'duration': '2:45:30', 'views': 234},
            {'id': '2', 'title': 'Tournament Highlights', 'duration': '1:15:45', 'views': 567},
        ]
        return _ok({'vods': vods})


@streaming_router.post("/start")
def api_start_stream(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Start a live stream."""
    g = gapi_gui
    data = body or {}
    title = data.get('title', '')

    if not title:
        return _err(400, 'Stream title required')

    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Create stream VOD record
        insert_query = "INSERT INTO stream_vods (user_id, title, duration, vod_url) VALUES (?, ?, ?, ?)"
        db.execute(insert_query, (user.id, title, '0:00:00', 'rtmp://twitch.tv/...'))
        db.commit()

        # Broadcast stream started event
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.stream_started(
                    username=username,
                    title=title,
                    url='rtmp://twitch.tv/...'
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast stream start: {e}')

        return _ok({'success': True, 'message': 'Stream started', 'stream_url': 'rtmp://twitch.tv/...'})
    except Exception as e:
        g.gui_logger.error(f"Error starting stream: {e}")
        return _ok({'success': True, 'message': 'Stream started (mock)', 'stream_url': 'rtmp://twitch.tv/...'})


# ── progression ─────────────────────────────────────────────────────────────

@progression_router.get("")
def api_get_progression_paths(username: str = Depends(require_login)):
    """Get available progression paths."""
    try:
        return _ok({
            'paths': [
                {
                    'id': 1,
                    'name': 'Competitive Player',
                    'description': 'Master competitive gameplay',
                    'current_step': 5,
                    'total_steps': 10,
                    'progress': 50,
                    'next_reward': '[Title] Rank Master'
                },
                {
                    'id': 2,
                    'name': 'Streamer Path',
                    'description': 'Build your streaming career',
                    'current_step': 2,
                    'total_steps': 10,
                    'progress': 20,
                    'next_reward': '[Frame] Broadcaster Elite'
                },
                {
                    'id': 3,
                    'name': 'Collector',
                    'description': 'Collect all cosmetics',
                    'current_step': 8,
                    'total_steps': 15,
                    'progress': 53,
                    'next_reward': '[Theme] Collector\'s Gold'
                },
            ]
        })
    except Exception:
        return _ok({'paths': []})


# ── ranked ──────────────────────────────────────────────────────────────────

@ranked_router.get("")
def api_get_ranked(username: str = Depends(require_login)):
    """Get ranked tier information."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Get or create ranked rating
        ranked_query = "SELECT tier, tier_level FROM ranked_ratings WHERE user_id = ?"
        ranked = db.execute(ranked_query, (user.id,)).fetchone()

        if ranked:
            tier, tier_level = ranked
        else:
            tier, tier_level = 'bronze', 1

        tiers = ['Bronze', 'Silver', 'Gold', 'Diamond', 'Master']
        tier_index = tiers.index(tier.capitalize()) if tier.lower() in [t.lower() for t in tiers] else 0

        return _ok({
            'current_tier_index': tier_index,
            'current_rank': f'{tier.capitalize()} {tier_level}',
            'current_rank_emoji': ['🥚', '🥈', '🥇', '💎', '👑'][tier_index],
            'rating_points': 2450,
            'rating_points_needed': 3000,
            'tiers': tiers
        })
    except Exception as e:
        g.gui_logger.error(f"Error loading ranked: {e}")
        return _ok({
            'current_tier_index': 1,
            'current_rank': 'Silver II',
            'current_rank_emoji': '🥈',
            'rating_points': 2450,
            'rating_points_needed': 3000,
            'tiers': ['Bronze', 'Silver', 'Gold', 'Diamond', 'Master']
        })
