"""Tournaments domain (migrated to FastAPI).

Tournament brackets / registration. These handlers are mock implementations in
the legacy app (no DB/service layer) and are faithfully ported here, preserving
the exact response bodies, status codes, and behaviour.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (tournaments is not in the cacheable-prefix allowlist); that header is
set explicitly here to preserve behaviour.

Routes:
  GET   /api/tournaments
  GET   /api/tournaments/{tournament_id}
  POST  /api/tournaments/register/{tournament_id}

NOTE on the GET list: the legacy module defined TWO view functions bound to the
same ``GET /api/tournaments`` rule — ``api_get_tournaments`` (registered first)
and ``api_list_tournaments`` (registered later, hence unreachable dead code).
Werkzeug dispatches the path to the first-registered rule, so the live behaviour
is ``api_get_tournaments`` (the "Spring Showdown / Weekend Bash" list with
status filtering). That is what is reproduced here; the dead duplicate is dropped.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


@router.get("")
def api_get_tournaments(request: Request, _user: str = Depends(require_login)):
    """Get active, upcoming, or completed tournaments."""
    status = request.query_params.get("status", "active").lower()

    tournaments = [
        {'id': '1', 'name': 'Spring Showdown', 'type': 'Single Elimination', 'participants': 8, 'max_participants': 16, 'status': 'active', 'winner': None},
        {'id': '2', 'name': 'Weekend Bash', 'type': 'Round Robin', 'participants': 12, 'max_participants': 12, 'status': 'active', 'winner': None},
        {'id': '3', 'name': 'Summer Championship', 'type': 'Double Elimination', 'participants': 0, 'max_participants': 32, 'status': 'upcoming', 'winner': None},
        {'id': '4', 'name': 'Winter League', 'type': 'Single Elimination', 'participants': 8, 'max_participants': 8, 'status': 'completed', 'winner': 'ProGamer42'},
    ]

    if status != 'all':
        tournaments = [t for t in tournaments if t['status'] == status]

    return _ok({'tournaments': tournaments})


@router.get("/{tournament_id}")
def api_get_tournament(tournament_id: str, username: str = Depends(require_login)):
    """Get tournament bracket and details."""
    try:
        return _ok({
            'tournament': {
                'id': int(tournament_id),
                'name': 'Spring Championship 2026',
                'status': 'active',
                'round': 'Quarterfinals',
                'user_position': 8
            },
            'bracket': [
                {'user': 'ProPlayer1', 'seed': 1, 'wins': 2},
                {'user': username, 'seed': 16, 'wins': 1},
                {'user': 'NoobMaster', 'seed': 8, 'wins': 1},
            ]
        })
    except Exception:
        return _err(404, 'Tournament not found')


@router.post("/register/{tournament_id}")
def api_register_tournament(tournament_id: str,
                            body: Optional[dict] = Body(default=None),
                            _user: str = Depends(require_login)):
    """Register for tournament."""
    try:
        return _ok({'success': True, 'message': 'Tournament registration successful', 'bracket_position': 32})
    except Exception:
        return _ok({'success': True, 'message': 'Registered (mock)'})
