"""Voting domain — multi-user game-vote sessions (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * POST /api/voting/create                 (201)
  * POST /api/voting/{session_id}/vote
  * GET  /api/voting/{session_id}/status
  * POST /api/voting/{session_id}/close

Reuses the legacy ``multi_picker`` + ``multi_picker_lock`` + ``_ensure_multi_picker``
machinery, so voting sessions are shared with any remaining legacy code paths.
Responses are plain dicts (session.to_dict() / close payload) to pass shapes
through verbatim.
"""
import random

from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.voting import CastVoteIn, CreateVotingIn

router = APIRouter(prefix="/api/voting", tags=["voting"])


def get_multi_picker(username: str = Depends(require_login)):
    """Ensure and return the multi-user picker; 400 if unavailable."""
    gapi_gui._ensure_multi_picker()
    mp = gapi_gui.multi_picker
    if not mp:
        raise HTTPException(status_code=400,
                            detail="Multi-user picker not initialized")
    return mp


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create_voting(body: CreateVotingIn, mp=Depends(get_multi_picker)):
    """Create a voting session from the users' common games."""
    user_names = body.users or None
    num_candidates = min(int(body.num_candidates), 10)
    voting_method = body.voting_method
    if voting_method not in ("plurality", "ranked_choice"):
        raise HTTPException(
            status_code=400,
            detail="voting_method must be 'plurality' or 'ranked_choice'",
        )

    with gapi_gui.multi_picker_lock:
        common_games = mp.find_common_games(user_names)
        if not common_games:
            raise HTTPException(
                status_code=404,
                detail="No common games found for selected users",
            )
        if body.coop_only:
            common_games = mp.filter_coop_games(common_games)
        if not common_games:
            raise HTTPException(
                status_code=404,
                detail="No common co-op games found for selected users",
            )
        candidates = random.sample(
            common_games, min(num_candidates, len(common_games)))
        voters = user_names if user_names else [u["name"] for u in mp.users]
        session = mp.create_voting_session(
            candidates, voters=voters,
            duration=body.duration, voting_method=voting_method,
        )
    return session.to_dict()


@router.post("/{session_id}/vote")
def cast_vote(session_id: str, body: CastVoteIn, mp=Depends(get_multi_picker)):
    """Cast a vote in an active session (plurality or ranked-choice)."""
    user_name = (body.user_name or "").strip()
    if not user_name:
        raise HTTPException(status_code=400, detail="user_name is required")

    with gapi_gui.multi_picker_lock:
        session = mp.get_voting_session(session_id)
        if session is None:
            raise HTTPException(status_code=404,
                                detail="Voting session not found")
        if session.voting_method == "ranked_choice":
            ranking = body.ranking
            if not isinstance(ranking, list) or not ranking:
                raise HTTPException(
                    status_code=400,
                    detail="ranking (list of app IDs) is required for "
                           "ranked_choice voting",
                )
            success, message = session.cast_vote(user_name, ranking)
        else:
            app_id = str(body.app_id or "").strip()
            if not app_id:
                raise HTTPException(status_code=400, detail="app_id is required")
            success, message = session.cast_vote(user_name, app_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.get("/{session_id}/status")
def voting_status(session_id: str, mp=Depends(get_multi_picker)):
    """Return current status and tallies for a voting session."""
    with gapi_gui.multi_picker_lock:
        session = mp.get_voting_session(session_id)
        if session is None:
            raise HTTPException(status_code=404,
                                detail="Voting session not found")
        return session.to_dict()


@router.post("/{session_id}/close")
def close_voting(session_id: str, mp=Depends(get_multi_picker)):
    """Close a voting session and return the winner."""
    with gapi_gui.multi_picker_lock:
        session = mp.get_voting_session(session_id)
        if session is None:
            raise HTTPException(status_code=404,
                                detail="Voting session not found")
        winner = mp.close_voting_session(session_id)
        session_data = session.to_dict()

    if not winner:
        raise HTTPException(status_code=500,
                            detail="Could not determine a winner")

    app_id = winner.get("appid") or winner.get("app_id") or winner.get("game_id")
    response = {
        "winner": {
            "app_id": app_id,
            "name": winner.get("name", "Unknown"),
            "playtime_hours": round(winner.get("playtime_forever", 0) / 60, 1),
            "steam_url": f"https://store.steampowered.com/app/{app_id}/" if app_id else None,
            "steamdb_url": f"https://steamdb.info/app/{app_id}/" if app_id else None,
        },
        "voting_method": session_data.get("voting_method", "plurality"),
        "vote_counts": session_data.get("vote_counts", {}),
        "total_votes": session_data.get("total_votes", 0),
    }
    if session_data.get("voting_method") == "ranked_choice":
        response["irv_rounds"] = session_data.get("irv_rounds", [])
    return response
