"""Backlog domain — collections + per-game status (migrated to FastAPI).

The largest slice so far. Two sub-surfaces:

  Collections (shared/personal):
    * GET    /api/backlogs
    * POST   /api/backlogs                    (201)
    * PUT    /api/backlogs/{backlog_id}
    * DELETE /api/backlogs/{backlog_id}
    * POST   /api/backlogs/{backlog_id}/leave

  Per-game status:
    * GET    /api/backlog                     (list; needs the picker)
    * GET    /api/backlog/{game_id}
    * POST   /api/backlog/{game_id}           (also PUT)
    * PUT    /api/backlog/{game_id}
    * DELETE /api/backlog/{game_id}

Reuses the legacy shared-backlog service and helpers
(`_get_shared_backlog_service`, `_serialize_backlog_summaries`,
`_parse_shared_member_usernames`) plus the per-user picker for the library
join, so the multi-user collection semantics are preserved exactly. Responses
are plain dicts to pass service-computed fields through verbatim.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

import gapi
import gapi_gui
from backend.dependencies import require_login
from backend.schemas.backlog import (
    CreateBacklogIn, SetBacklogStatusIn, UpdateBacklogIn,
)

router = APIRouter(prefix="/api", tags=["backlog"])


def _norm(value) -> str:
    return str(value or "").strip().lower()


# ── Collections ────────────────────────────────────────────────────────────

@router.get("/backlogs")
def list_collections(collection_id: Optional[str] = None,
                     username: str = Depends(require_login)):
    """List backlog collections available to the current user."""
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlogs = service.list_collections(username=username)
        active_backlog_id = service.resolve_collection_for_user(collection_id, username)
        backlogs = gapi_gui._serialize_backlog_summaries(backlogs, service, username)
    return {
        "backlogs": backlogs,
        "count": len(backlogs),
        "active_backlog_id": active_backlog_id,
    }


@router.post("/backlogs", status_code=status.HTTP_201_CREATED)
def create_collection(body: CreateBacklogIn,
                      username: str = Depends(require_login)):
    """Create a personal or shared backlog collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlog = service.create_collection(
            name=name,
            owner_username=username,
            members=members,
            is_shared=bool(body.is_shared),
        )
    return backlog


@router.put("/backlogs/{backlog_id}")
def update_collection(backlog_id: str, body: UpdateBacklogIn,
                      username: str = Depends(require_login)):
    """Rename or re-share a backlog collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlog = service.update_collection(
            collection_id=backlog_id,
            username=username,
            name=name,
            members=members,
            is_shared=bool(body.is_shared) if body.is_shared is not None else None,
        )
    if backlog is None:
        raise HTTPException(status_code=404, detail="Backlog not found")
    return backlog


@router.delete("/backlogs/{backlog_id}")
def delete_collection(backlog_id: str, username: str = Depends(require_login)):
    """Delete a backlog collection owned by the current user."""
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlog = service.get_collection(backlog_id)
        if not backlog or not service._can_access_collection(backlog, username):
            raise HTTPException(status_code=404, detail="Backlog not found")
        if _norm(backlog.get("owner")) != _norm(username):
            raise HTTPException(
                status_code=403, detail="Only the backlog owner can delete it"
            )
        if service.is_default_collection_id(backlog_id, username):
            raise HTTPException(
                status_code=400,
                detail="Your personal backlog cannot be deleted",
            )
        deleted = service.delete_collection(backlog_id, username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Backlog not found")
    return {"success": True}


@router.post("/backlogs/{backlog_id}/leave")
def leave_collection(backlog_id: str, username: str = Depends(require_login)):
    """Leave a shared backlog the current user does not own."""
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlog = service.get_collection(backlog_id)
        if not backlog or not service._can_access_collection(backlog, username):
            raise HTTPException(status_code=404, detail="Backlog not found")
        if _norm(backlog.get("owner")) == _norm(username):
            raise HTTPException(
                status_code=403,
                detail="Backlog owners must delete the backlog instead of leaving it",
            )
        left = service.leave_collection(backlog_id, username)
    if not left:
        raise HTTPException(status_code=400, detail="Unable to leave backlog")
    return {"success": True}


# ── Per-game status ────────────────────────────────────────────────────────

@router.get("/backlog")
def list_backlog(status_query: Optional[str] = Query(None, alias="status"),
                 collection_id: Optional[str] = None,
                 username: str = Depends(require_login)):
    """List backlog entries, optionally filtered by ``?status=``."""
    picker = gapi_gui.ensure_picker_initialized(username)
    if not picker:
        raise HTTPException(status_code=400, detail="Not initialized")
    status_filter = (status_query or "").strip() or None
    if status_filter and status_filter not in gapi.GamePicker.BACKLOG_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid: {list(gapi.GamePicker.BACKLOG_STATUSES)}",
        )
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        backlogs = service.list_collections(username=username)
        active_backlog_id = service.resolve_collection_for_user(collection_id, username)
        games = service.get_games(
            picker.games, status_filter,
            username=username, collection_id=active_backlog_id,
        )
        active_backlog = service.get_collection(active_backlog_id)
        backlogs = gapi_gui._serialize_backlog_summaries(backlogs, service, username)
    return {
        "games": games,
        "count": len(games),
        "backlogs": backlogs,
        "active_backlog_id": active_backlog_id,
        "active_backlog": active_backlog,
    }


@router.get("/backlog/{game_id}")
def get_backlog_status(game_id: str, collection_id: Optional[str] = None,
                       username: str = Depends(require_login)):
    """Get the backlog status for a specific game."""
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        entry = service.get_entry(game_id, username=username,
                                  collection_id=collection_id)
    if entry is None:
        return {"game_id": game_id, "status": None, "notes": ""}
    return {
        "game_id": game_id,
        "status": entry.get("status"),
        "notes": entry.get("notes", ""),
    }


@router.post("/backlog/{game_id}")
@router.put("/backlog/{game_id}")
def set_backlog_status(game_id: str, body: SetBacklogStatusIn,
                       collection_id: Optional[str] = None,
                       username: str = Depends(require_login)):
    """Set the backlog status for a game. Body: {"status": "..."}."""
    status_value = (body.status or "").strip()
    if not status_value:
        raise HTTPException(status_code=400, detail="status is required")
    notes_value = str(body.notes) if body.notes is not None else None
    cid = str(body.collection_id or "").strip() or collection_id
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        if cid:
            backlog = service.get_collection(cid)
            if not backlog or not service._can_access_collection(backlog, username):
                raise HTTPException(status_code=404, detail="Backlog not found")
        ok = service.set_status(
            game_id, status_value,
            username=username, collection_id=cid, notes=notes_value,
        )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid: {list(gapi.GamePicker.BACKLOG_STATUSES)}",
        )
    with gapi_gui.picker_lock:
        saved_entry = service.get_entry(
            game_id, username=username, collection_id=cid) or {}
    return {
        "success": True,
        "game_id": game_id,
        "status": status_value,
        "notes": saved_entry.get("notes", ""),
        "collection_id": cid,
    }


@router.delete("/backlog/{game_id}")
def delete_backlog_status(game_id: str, collection_id: Optional[str] = None,
                          username: str = Depends(require_login)):
    """Remove a game from the backlog."""
    service = gapi_gui._get_shared_backlog_service()
    with gapi_gui.picker_lock:
        if collection_id:
            backlog = service.get_collection(collection_id)
            if not backlog or not service._can_access_collection(backlog, username):
                raise HTTPException(status_code=404, detail="Backlog not found")
        removed = service.remove(game_id, username=username,
                                 collection_id=collection_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Game not in backlog")
    return {"success": True}
