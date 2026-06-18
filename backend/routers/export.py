"""Data-export domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET /api/export/library     (full library as CSV)
  * GET /api/export/favorites   (favorites as CSV)
  * GET /api/export/user-data   (all persisted user data as a JSON backup)

The CSV routes are picker-backed; the user-data export is DB-backed. The
companion POST /api/import/user-data (dual JSON/multipart upload) remains in
Flask for now (needs python-multipart + UploadFile handling).
"""
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Response

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/export", tags=["export"])


def _csv_response(rows, fieldnames, filename):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=out.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _picker_with_games(username):
    p = gapi_gui.ensure_picker_initialized(username)
    if not p or not p.games:
        raise HTTPException(status_code=400, detail="Library not loaded")
    return p


@router.get("/library")
def export_library(username: str = Depends(require_login)):
    """Download the full game library as CSV."""
    p = _picker_with_games(username)
    with gapi_gui.picker_lock:
        rows = []
        for game in sorted(p.games, key=lambda g: g.get("name", "").lower()):
            app_id = game.get("appid") or game.get("id") or ""
            game_id = game.get("game_id", f"steam:{app_id}")
            review = p.review_service.get(game_id) or {}
            rows.append({
                "app_id": app_id,
                "name": game.get("name", ""),
                "platform": game.get("platform", "steam"),
                "playtime_hours": round(game.get("playtime_forever", 0) / 60, 1),
                "is_favorite": "yes" if p.favorites_service.contains(game_id) else "no",
                "backlog_status": (
                    gapi_gui._get_shared_backlog_service().get_status(
                        game_id, username=username) if game_id else "") or "",
                "tags": ",".join(p.tag_service.get(game_id)),
                "review_rating": review.get("rating", ""),
                "review_notes": review.get("notes", ""),
            })
    return _csv_response(
        rows,
        ["app_id", "name", "platform", "playtime_hours", "is_favorite",
         "backlog_status", "tags", "review_rating", "review_notes"],
        "gapi_library.csv")


@router.get("/favorites")
def export_favorites(username: str = Depends(require_login)):
    """Download the favorites list as CSV."""
    p = _picker_with_games(username)
    with gapi_gui.picker_lock:
        rows = []
        for game in p.games:
            game_id = game.get("game_id", "")
            app_id = game.get("appid") or game.get("id") or ""
            if not p.favorites_service.contains(game_id):
                continue
            review = p.review_service.get(game_id) or {}
            rows.append({
                "app_id": app_id,
                "name": game.get("name", ""),
                "platform": game.get("platform", "steam"),
                "playtime_hours": round(game.get("playtime_forever", 0) / 60, 1),
                "tags": ",".join(p.tag_service.get(game_id)),
                "review_rating": review.get("rating", ""),
                "review_notes": review.get("notes", ""),
            })
        rows.sort(key=lambda r: r["name"].lower())
    return _csv_response(
        rows,
        ["app_id", "name", "platform", "playtime_hours", "tags",
         "review_rating", "review_notes"],
        "gapi_favorites.csv")


@router.get("/user-data")
def export_user_data(username: str = Depends(require_login)):
    """Export all persisted data for the current user as a JSON backup."""
    db = next(gapi_gui.database.get_db())
    try:
        export = gapi_gui.database.get_user_data_export(db, username)
    finally:
        if db:
            db.close()
    if not export:
        raise HTTPException(status_code=404, detail="No data found for user")
    payload = json.dumps(export, indent=2, default=str)
    return Response(
        content=payload, media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="gapi_{username}_backup.json"'})
