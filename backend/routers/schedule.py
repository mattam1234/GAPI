"""Schedule domain — migrated to FastAPI in chunks (this is chunk 1).

Chunk 1 — schedule collections (shared/personal), analogous to backlog
collections:
  * GET    /api/schedules
  * POST   /api/schedules                    (201)
  * PUT    /api/schedules/{schedule_id}
  * DELETE /api/schedules/{schedule_id}

Reuses the per-user picker ``schedule_service`` + ``picker_lock`` and the shared
``_parse_shared_member_usernames`` helper. 400 when the picker is not
initialised (legacy schedule contract). Responses are plain dicts.

Follow-up chunks (still in Flask for now): event CRUD + RSVP
(/api/schedule[...]), fuzzy search, Discord events, and iCal export.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.schedule import CreateScheduleIn, UpdateScheduleIn

router = APIRouter(prefix="/api/schedules", tags=["schedule"])


def _picker(username: str = Depends(require_login)):
    """Per-user picker; 400 if not initialised (legacy schedule contract)."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(status_code=400, detail="Not initialized")
    return p


def _norm(value) -> str:
    return str(value or "").strip().lower()


@router.get("")
def list_schedules(schedule_id: Optional[str] = None,
                   username: str = Depends(require_login),
                   picker=Depends(_picker)):
    """List schedule collections available to the current user."""
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        schedules = svc.list_schedules(username=username)
        active_schedule_id = svc.resolve_schedule_for_user(schedule_id, username)
    return {
        "schedules": schedules,
        "count": len(schedules),
        "active_schedule_id": active_schedule_id,
    }


@router.post("", status_code=201)
def create_schedule(body: CreateScheduleIn,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Create a personal or shared schedule collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    with gapi_gui.picker_lock:
        schedule = picker.schedule_service.create_schedule(
            name=name, owner_username=username,
            members=members, is_shared=bool(body.is_shared),
        )
    return schedule


@router.put("/{schedule_id}")
def update_schedule(schedule_id: str, body: UpdateScheduleIn,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Rename or re-share a schedule collection."""
    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    members = gapi_gui._parse_shared_member_usernames(body.members or [])
    with gapi_gui.picker_lock:
        schedule = picker.schedule_service.update_schedule(
            schedule_id=schedule_id, username=username, name=name,
            members=members,
            is_shared=bool(body.is_shared) if body.is_shared is not None else None,
        )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str,
                    username: str = Depends(require_login),
                    picker=Depends(_picker)):
    """Delete a schedule collection owned by the current user."""
    safe_id = str(schedule_id or "").strip()
    if not safe_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    default_id = f"personal:{_norm(username)}"
    svc = picker.schedule_service
    with gapi_gui.picker_lock:
        schedule = svc.get_schedule(safe_id)
        if not schedule or not svc._can_access_schedule(schedule, username):
            raise HTTPException(status_code=404, detail="Schedule not found")
        if _norm(schedule.get("owner")) != _norm(username):
            raise HTTPException(
                status_code=403, detail="Only the schedule owner can delete it")
        if safe_id == default_id:
            raise HTTPException(
                status_code=400,
                detail="Your personal schedule cannot be deleted")
        deleted = svc.remove_schedule(safe_id, username=username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True}
