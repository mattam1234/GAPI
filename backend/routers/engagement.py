"""Engagement cluster (real, persistent FastAPI features).

Six small engagement domains, one ``APIRouter`` per URL prefix:

  * ``creator_router``      — ``/api/creator``
  * ``battlepass_router``   — ``/api/battlepass``
  * ``referral_router``     — ``/api/referral``
  * ``streaming_router``    — ``/api/streaming``
  * ``progression_router``  — ``/api/progression``
  * ``ranked_router``       — ``/api/ranked``

These were previously success-faking stubs (hard-coded data + an undefined
``gapi_gui.db_service`` mock-fallback). They are now real features persisting to
per-user tables (see ``backend/models/engagement.py``) through a SQLAlchemy
session opened from ``database.SessionLocal()``. The old ``db_service`` /
mock-fallback behaviour has been removed entirely. Business rules live in
``app/services/engagement_service.py``.

Per-domain semantics
--------------------
battlepass
    ``GET /current`` returns a current season (config) + the user's xp/tier
    (lazily created with defaults). ``POST /claim/{level}`` grants a level's
    reward iff the user's tier >= level and the level has a reward and it isn't
    already claimed (404 unknown level, 403 tier too low, 409 already claimed).
creator
    ``GET /dashboard`` returns the user's creator-application status + basic
    stats. ``POST /apply`` creates/returns a pending application (idempotent).
referral
    ``GET /code`` get-or-creates the user's unique referral code.
    ``POST /use/{code}`` redeems someone's code once per user (400 self/own
    code, 404 unknown code, 409 already redeemed).
streaming
    ``GET /vods`` lists the user's stream sessions. ``POST /start`` opens a
    ``live`` session (400 missing title).
progression / ranked
    GET-only views derived from a lazily-created per-user state row.

All six prefixes are absent from the cacheable-prefix allowlist, so every
response keeps the legacy ``Cache-Control: no-store`` header (set explicitly).

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
import database
from backend.dependencies import require_login
from app.services import engagement_service
from app.services.engagement_service import EngagementError

# Importing the model module registers the engagement tables on the shared Base
# so the create_all hook in backend.main builds them.
import backend.models.engagement  # noqa: F401

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


def _open_session():
    """Open a real DB session, or raise a 503-mapped error if unavailable."""
    if getattr(database, "SessionLocal", None) is None:
        raise EngagementError(503, "Database not available")
    return database.SessionLocal()


# ── creator ─────────────────────────────────────────────────────────────────

@creator_router.get("/dashboard")
def api_creator_dashboard(username: str = Depends(require_login)):
    """Creator program dashboard (the user's application status + stats)."""
    try:
        db = _open_session()
        try:
            data = engagement_service.get_creator_dashboard(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading creator dashboard: %s", e)
        return _err(500, "Creator data not available")


@creator_router.post("/apply")
def api_apply_creator(body: Optional[dict] = Body(default=None),
                      username: str = Depends(require_login)):
    """Apply for the creator program (idempotent)."""
    try:
        db = _open_session()
        try:
            data = engagement_service.apply_creator(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error applying for creator program: %s", e)
        return _err(500, "Failed to submit application")


# ── battlepass ──────────────────────────────────────────────────────────────

@battlepass_router.get("/current")
def api_get_current_battlepass(username: str = Depends(require_login)):
    """Get current battle pass info + the user's progress."""
    try:
        db = _open_session()
        try:
            data = engagement_service.get_current_battlepass(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error getting battle pass: %s", e)
        return _err(500, "Failed to load battle pass")


@battlepass_router.post("/claim/{level}")
def api_claim_battlepass_reward(level: str, username: str = Depends(require_login)):
    """Claim a battle pass reward for a given level."""
    try:
        db = _open_session()
        try:
            data = engagement_service.claim_battlepass_reward(db, username, level)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error claiming battle pass reward: %s", e)
        return _err(500, "Failed to claim reward")


# ── referral ────────────────────────────────────────────────────────────────

@referral_router.get("/code")
def api_get_referral_code(username: str = Depends(require_login)):
    """Get (or create) the user's referral code."""
    try:
        db = _open_session()
        try:
            data = engagement_service.get_or_create_referral_code(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading referral code: %s", e)
        return _err(500, "Referral system not available")


@referral_router.post("/use/{code}")
def api_use_referral_code(code: str, username: str = Depends(require_login)):
    """Redeem a referral code (once per user)."""
    try:
        db = _open_session()
        try:
            data = engagement_service.redeem_referral_code(db, username, code)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error using referral code: %s", e)
        return _err(500, "Failed to redeem referral code")


# ── streaming ───────────────────────────────────────────────────────────────

@streaming_router.get("/vods")
def api_get_vods(username: str = Depends(require_login)):
    """Get the user's video library (VODs / stream sessions)."""
    try:
        db = _open_session()
        try:
            vods = engagement_service.list_vods(db, username)
        finally:
            db.close()
        return _ok({"vods": vods})
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading VODs: %s", e)
        return _err(500, "Failed to load VODs")


@streaming_router.post("/start")
def api_start_stream(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Start a live stream."""
    data = body or {}
    title = data.get("title", "")

    try:
        db = _open_session()
        try:
            result = engagement_service.start_stream(db, username, title)
        finally:
            db.close()
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error starting stream: %s", e)
        return _err(500, "Failed to start stream")

    # Best-effort realtime notification (never affects the response).
    g = gapi_gui
    if getattr(g, "REALTIME_AVAILABLE", False):
        try:
            g.realtime.RealtimeEvents.stream_started(
                username=username, title=result["title"],
                url=result["stream_url"])
        except Exception as e:  # pragma: no cover - notification is non-critical
            g.gui_logger.warning("Failed to broadcast stream start: %s", e)

    return _ok(result)


# ── progression ─────────────────────────────────────────────────────────────

@progression_router.get("")
def api_get_progression_paths(username: str = Depends(require_login)):
    """Get the user's progression paths (lazy-created defaults)."""
    try:
        db = _open_session()
        try:
            data = engagement_service.get_progression(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading progression: %s", e)
        return _err(500, "Failed to load progression")


# ── ranked ──────────────────────────────────────────────────────────────────

@ranked_router.get("")
def api_get_ranked(username: str = Depends(require_login)):
    """Get the user's ranked tier information (lazy-created defaults)."""
    try:
        db = _open_session()
        try:
            data = engagement_service.get_ranked(db, username)
        finally:
            db.close()
        return _ok(data)
    except EngagementError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading ranked: %s", e)
        return _err(500, "Failed to load ranked")
