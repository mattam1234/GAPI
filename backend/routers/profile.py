"""User-profile domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET  /api/profile/me
  * POST /api/profile/update

These are currently lightweight placeholder handlers (the profile fields are not
yet persisted); the behaviour is preserved verbatim. When real persistence is
added it lands here, behind the same routes.
"""
from fastapi import APIRouter, Depends

import gapi_gui  # noqa: F401  (kept for parity / future persistence hooks)
from backend.dependencies import require_login
from backend.schemas.profile import MyProfile, ProfileUpdateResult

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/me", response_model=MyProfile)
def get_my_profile(username: str = Depends(require_login)):
    """Return the current user's profile."""
    return MyProfile(
        username=username,
        bio="Passionate gamer",
        status="Playing games",
        favorite_game="Portal 2",
        is_private=False,
    )


@router.post("/update", response_model=ProfileUpdateResult)
def update_my_profile(username: str = Depends(require_login)):
    """Update the current user's profile (placeholder; not yet persisted)."""
    return ProfileUpdateResult(success=True, message="Profile updated")
