"""Session-history domain (migrated to FastAPI).

Mirrors the legacy Flask route:
  * GET /api/sessions/history

Currently a placeholder returning sample session history (not yet persisted);
behaviour is preserved verbatim. Real persistence will land here behind the
same route.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from backend.dependencies import require_login

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/history")
def session_history(username: str = Depends(require_login)):
    """Return the current user's recent session history."""
    now = datetime.now().isoformat()
    return {
        "sessions": [
            {
                "name": "Game Night",
                "played_at": now,
                "winning_pick": "Portal 2",
                "player_count": 4,
                "your_vote": True,
                "you_picked": False,
            },
            {
                "name": "Co-op Night",
                "played_at": now,
                "winning_pick": "It Takes Two",
                "player_count": 3,
                "your_vote": False,
                "you_picked": True,
            },
        ]
    }
