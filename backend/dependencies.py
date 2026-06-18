"""Shared FastAPI dependencies: DB session and authentication.

Auth bridges the legacy Flask app: the FastAPI auth dependency decodes the very
same Flask session cookie using Flask's own ``session_interface`` and secret
key. A user logged in through the legacy login endpoint is therefore
authenticated on new FastAPI routes with no re-login and no shared session
store. See ``docs/MODERNIZATION_BRIEF.md`` §3.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

# Reuse the legacy app's already-initialised singletons as the single source of
# truth for the secret key, DB engine, and service layer during migration.
import gapi_gui
import database

_flask_app = gapi_gui.app


def get_db():
    """Yield a SQLAlchemy session, closing it when the request finishes."""
    if getattr(database, "SessionLocal", None) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_flask_session(request: Request) -> dict:
    """Decode the Flask session cookie, returning {} when absent or invalid."""
    cookie_name = _flask_app.config.get("SESSION_COOKIE_NAME") or "session"
    raw = request.cookies.get(cookie_name)
    if not raw:
        return {}
    serializer = _flask_app.session_interface.get_signing_serializer(_flask_app)
    if serializer is None:
        return {}
    try:
        return serializer.loads(raw) or {}
    except Exception:
        # Bad signature / tampered / expired cookie -> treated as anonymous.
        return {}


def get_current_user(request: Request) -> Optional[str]:
    """Return the logged-in username, or ``None`` if anonymous."""
    data = _load_flask_session(request)
    username = data.get("username")
    return str(username) if username else None


def require_login(username: Optional[str] = Depends(get_current_user)) -> str:
    """Require an authenticated user; 401 otherwise."""
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in"
        )
    return username


def get_picker(username: str = Depends(require_login)):
    """Return the per-user GamePicker, reusing the legacy initializer.

    Many domains (reviews, tags, …) store their data on the per-user picker;
    this bridges to that machinery during the migration. 500 if it can't init.
    """
    picker = gapi_gui.ensure_picker_initialized(username)
    if not picker:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Picker not initialized",
        )
    return picker


def require_admin(
    username: str = Depends(require_login),
    db=Depends(get_db),
) -> str:
    """Require an admin user; 403 otherwise.

    Mirrors the legacy analytics/admin endpoints, which gate on
    ``app_settings_service.is_admin(db, username)``.
    """
    svc = gapi_gui._app_settings_service
    if not (svc and svc.is_admin(db, username)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return username
