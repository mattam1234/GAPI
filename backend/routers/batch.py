"""Batch-operations domain (migrated to FastAPI).

Faithful port of the legacy Flask batch API (all POST, all @require_login):
  * POST /api/batch/tag-games        (bulk tag via _db_favorites_service)
  * POST /api/batch/change-status    (bulk backlog status via _db_favorites_service)
  * POST /api/batch/add-to-playlist  (count-only stub, no service wired)
  * POST /api/batch/delete           (count-only stub, no service wired)
  * POST /api/batch/export           (CSV/JSON export from the per-user picker)

Each bulk handler returns a per-item success count exactly as the legacy code
did ({"success": True, "<verb>": <count>}); per-item exceptions are swallowed so
a single bad id never fails the batch. State lives on ``gapi_gui`` and is
referenced at CALL TIME. The legacy ``after_request`` set
``Cache-Control: no-store`` on every ``/api/*`` response (batch paths are not in
the cacheable-prefix allowlist); that header is set explicitly here to preserve
behaviour.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/batch", tags=["batch"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content):
    return JSONResponse(content=content, headers=_NO_STORE)


@router.post("/tag-games")
def api_batch_tag_games(body: Optional[dict] = Body(default=None),
                        username: str = Depends(require_login)):
    """Bulk tag multiple games."""
    db = next(gapi_gui.database.get_db())
    try:
        data = body or {}
        game_ids = data.get("game_ids", [])
        tags = data.get("tags", [])

        if not game_ids or not tags:
            return _err(400, "game_ids and tags required")

        success_count = 0
        for app_id in game_ids:
            try:
                if gapi_gui._db_favorites_service:
                    gapi_gui._db_favorites_service.add_tags(db, username, app_id, tags)
                success_count += 1
            except Exception:
                pass

        return _ok({"success": True, "tagged": success_count})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/change-status")
def api_batch_change_status(body: Optional[dict] = Body(default=None),
                            username: str = Depends(require_login)):
    """Bulk change game status (completed, abandoned, etc.)."""
    db = next(gapi_gui.database.get_db())
    try:
        data = body or {}
        game_ids = data.get("game_ids", [])
        status = data.get("status", "")  # completed, playing, abandoned, etc.

        if not game_ids or not status:
            return _err(400, "game_ids and status required")

        success_count = 0
        for app_id in game_ids:
            try:
                # Add to backlog with status
                if gapi_gui._db_favorites_service:
                    gapi_gui._db_favorites_service.add_to_backlog(
                        db, username, app_id,
                        {"status": status, "updated_at": datetime.utcnow().isoformat()}
                    )
                success_count += 1
            except Exception:
                pass

        return _ok({"success": True, "updated": success_count})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/add-to-playlist")
def api_batch_add_to_playlist(body: Optional[dict] = Body(default=None),
                              username: str = Depends(require_login)):
    """Bulk add games to a playlist."""
    db = next(gapi_gui.database.get_db())
    try:
        data = body or {}
        game_ids = data.get("game_ids", [])
        playlist_name = data.get("playlist_name", "")

        if not game_ids or not playlist_name:
            return _err(400, "game_ids and playlist_name required")

        success_count = 0
        for app_id in game_ids:
            try:
                # This would require playlist service - for now just count
                success_count += 1
            except Exception:
                pass

        return _ok({"success": True, "added": success_count})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/delete")
def api_batch_delete_games(body: Optional[dict] = Body(default=None),
                           username: str = Depends(require_login)):
    """Bulk delete games from library or wishlist."""
    db = next(gapi_gui.database.get_db())
    try:
        data = body or {}
        game_ids = data.get("game_ids", [])
        source = data.get("source", "wishlist")  # wishlist, backlog, reviews

        if not game_ids:
            return _err(400, "game_ids required")

        success_count = 0
        for app_id in game_ids:
            try:
                if source == "wishlist":
                    if gapi_gui._db_favorites_service:
                        # Remove from wishlist
                        pass
                elif source == "backlog":
                    if gapi_gui._db_favorites_service:
                        # Remove from backlog
                        pass
                success_count += 1
            except Exception:
                pass

        return _ok({"success": True, "deleted": success_count})
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()


@router.post("/export")
def api_batch_export(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Export selected games as CSV."""
    db = next(gapi_gui.database.get_db())
    try:
        data = body or {}
        game_ids = data.get("game_ids", [])
        format_type = data.get("format", "csv")  # csv or json

        p_batch = gapi_gui.ensure_picker_initialized(username)
        if not p_batch or not p_batch.games:
            return _err(400, "No games available")

        selected_games = [
            g for g in p_batch.games
            if str(g.get("app_id")) in [str(gid) for gid in game_ids]
        ]

        if format_type == "csv":
            csv_lines = ["App ID,Name,Release Date,Price"]
            for g in selected_games:
                csv_lines.append(
                    f"{g.get('app_id')},\"{g.get('name')}\","
                    f"{g.get('release_date')},{g.get('price')}"
                )
            csv_data = "\n".join(csv_lines)
            return Response(
                content=csv_data,
                media_type="text/csv",
                headers={
                    "Content-Disposition":
                        "attachment; filename=games_export.csv",
                    "Cache-Control": "no-store",
                },
            )
        else:
            return _ok(selected_games)
    except Exception as e:
        return _err(500, str(e))
    finally:
        if db:
            db.close()
