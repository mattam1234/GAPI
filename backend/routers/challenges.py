"""Multiplayer achievement-challenges domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * POST   /api/achievement-challenges                       (201)
  * GET    /api/achievement-challenges
  * GET    /api/achievement-challenges/{challenge_id}
  * POST   /api/achievement-challenges/{challenge_id}/join
  * PUT    /api/achievement-challenges/{challenge_id}/progress
  * DELETE /api/achievement-challenges/{challenge_id}

DB-backed via the legacy ``database`` challenge helpers; every route returns 503
when the DB is unavailable (the legacy contract).
"""
from fastapi import APIRouter, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.challenges import ChallengeProgressIn, CreateChallengeIn

router = APIRouter(prefix="/api/achievement-challenges", tags=["challenges"])


def _require_db():
    if not gapi_gui.ensure_db_available():
        raise HTTPException(status_code=503, detail="Database not available")


@router.post("", status_code=201)
def create_challenge(body: CreateChallengeIn,
                     username: str = Depends(require_login)):
    """Create a new multiplayer achievement challenge."""
    _require_db()
    title = str(body.title or "").strip()
    app_id = str(body.app_id or "").strip()
    game_name = str(body.game_name or "").strip()
    if not title or not app_id or not game_name:
        raise HTTPException(
            status_code=400, detail="title, app_id, and game_name are required")

    raw = body.target_achievement_ids
    if isinstance(raw, str):
        target_ids = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        target_ids = [str(t).strip() for t in (raw or []) if str(t).strip()]

    db = next(gapi_gui.database.get_db())
    try:
        challenge = gapi_gui.database.create_achievement_challenge(
            db, username, title, app_id, game_name,
            target_achievement_ids=target_ids or None,
            starts_at=str(body.starts_at or "").strip(),
            ends_at=str(body.ends_at or "").strip(),
        )
    finally:
        if db:
            db.close()
    if not challenge:
        raise HTTPException(status_code=500, detail="Failed to create challenge")
    return challenge


@router.get("")
def list_challenges(username: str = Depends(require_login)):
    """List challenges the current user created or joined."""
    _require_db()
    db = next(gapi_gui.database.get_db())
    try:
        return {"challenges": gapi_gui.database.get_achievement_challenges(db, username)}
    finally:
        if db:
            db.close()


@router.get("/{challenge_id}")
def get_challenge(challenge_id: str, username: str = Depends(require_login)):
    """Get a single challenge by id."""
    _require_db()
    db = next(gapi_gui.database.get_db())
    try:
        challenge = gapi_gui.database.get_achievement_challenge(db, challenge_id)
    finally:
        if db:
            db.close()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge


@router.post("/{challenge_id}/join")
def join_challenge(challenge_id: str, username: str = Depends(require_login)):
    """Join an existing challenge."""
    _require_db()
    db = next(gapi_gui.database.get_db())
    try:
        challenge = gapi_gui.database.join_achievement_challenge(
            db, challenge_id, username)
    finally:
        if db:
            db.close()
    if not challenge:
        raise HTTPException(
            status_code=404, detail="Challenge not found or could not join")
    return challenge


@router.put("/{challenge_id}/progress")
def update_progress(challenge_id: str, body: ChallengeProgressIn,
                    username: str = Depends(require_login)):
    """Update the current user's unlocked count for a challenge."""
    _require_db()
    try:
        unlocked_count = int(body.unlocked_count)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="unlocked_count must be an integer")
    db = next(gapi_gui.database.get_db())
    try:
        challenge = gapi_gui.database.record_challenge_unlock(
            db, challenge_id, username, unlocked_count)
    finally:
        if db:
            db.close()
    if not challenge:
        raise HTTPException(
            status_code=404, detail="Challenge or participant not found")
    return challenge


@router.delete("/{challenge_id}")
def cancel_challenge(challenge_id: str, username: str = Depends(require_login)):
    """Cancel a challenge (creator only)."""
    _require_db()
    db = next(gapi_gui.database.get_db())
    try:
        ok = gapi_gui.database.cancel_achievement_challenge(db, challenge_id, username)
    finally:
        if db:
            db.close()
    if not ok:
        raise HTTPException(
            status_code=404, detail="Challenge not found or permission denied")
    return {"success": True, "id": challenge_id}
