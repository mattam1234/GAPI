"""Tournaments domain — a real, persistent feature (FastAPI).

Tournaments now have a proper lifecycle and registration backed by the database
(see ``backend/models/tournaments.py`` and ``app/services/tournament_service.py``).
The previous handlers returned hardcoded mock data; these query/persist real
rows via ``database.SessionLocal`` (used inside the service).

Status lifecycle: ``upcoming`` -> ``open`` -> ``active`` -> ``completed``.
Registration is allowed only while a tournament is ``open``; registering when it
is not open or already full yields ``409``; double-registration is idempotent.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (tournaments is not cacheable); that header is preserved here.

Routes (all require login):
  GET   /api/tournaments                       — list (optional ?status= filter)
  GET   /api/tournaments/{tournament_id}       — detail + participants (+ bracket)
  POST  /api/tournaments/register/{tournament_id} — register the current user

``{tournament_id}`` is taken as a string and parsed to ``int``; a non-integer id
yields ``404`` (preserving the prior faithful behaviour of the get handler).

There is intentionally no public create route; tournaments are created via the
service (for seeding/tests). An admin-gated POST could be added later.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from app.services import tournament_service
from backend.dependencies import require_login

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


def _parse_id(tournament_id: str) -> Optional[int]:
    """Parse a path id to int, returning None when it is not an integer."""
    try:
        return int(tournament_id)
    except (TypeError, ValueError):
        return None


@router.get("")
def api_get_tournaments(request: Request, _user: str = Depends(require_login)):
    """List tournaments, optionally filtered by ``?status=`` (``all`` => every)."""
    status = request.query_params.get("status")
    try:
        tournaments = tournament_service.list_tournaments(status=status)
    except Exception as exc:  # pragma: no cover - defensive
        return _err(500, f"Failed to list tournaments: {exc}")
    return _ok({"tournaments": tournaments})


@router.get("/{tournament_id}")
def api_get_tournament(tournament_id: str, _user: str = Depends(require_login)):
    """Return tournament detail, participants, and (if active) a seeded bracket."""
    parsed = _parse_id(tournament_id)
    if parsed is None:
        return _err(404, "Tournament not found")
    try:
        return _ok(tournament_service.get_tournament(parsed))
    except tournament_service.LookupError404:
        return _err(404, "Tournament not found")
    except Exception as exc:  # pragma: no cover - defensive
        return _err(500, f"Failed to get tournament: {exc}")


@router.post("/register/{tournament_id}")
def api_register_tournament(tournament_id: str,
                            body: Optional[dict] = Body(default=None),
                            username: str = Depends(require_login)):
    """Register the current user for a tournament (must be ``open``)."""
    parsed = _parse_id(tournament_id)
    if parsed is None:
        return _err(404, "Tournament not found")
    try:
        result = tournament_service.register(parsed, username)
    except tournament_service.LookupError404:
        return _err(404, "Tournament not found")
    except tournament_service.ConflictError as exc:
        return _err(409, str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return _err(500, f"Failed to register: {exc}")
    return _ok(result)
