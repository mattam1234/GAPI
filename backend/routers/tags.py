"""Tags domain — per-game personal tags (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/tags
  * GET    /api/tags/{game_id}
  * POST   /api/tags/{game_id}
  * DELETE /api/tags/{game_id}/{tag}
  * GET    /api/library/by-tag/{tag}

Reuses the per-user picker ``tag_service`` + ``picker_lock`` for identical
storage and locking. Unlike the legacy GET handlers — which swallowed errors
and returned an empty payload with a 200 — failures here surface as 500 via the
shared ``get_picker`` dependency, rather than being masked.
"""
from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import get_picker, require_login
from backend.schemas.tags import (
    AddTagResult, AllTags, GameTags, GameWithTags, LibraryByTag,
    RemoveTagResult, TagIn,
)

router = APIRouter(prefix="/api", tags=["tags"])


@router.get("/tags", response_model=AllTags)
def get_all_tags(picker=Depends(get_picker)):
    """Return all unique tags and the game_id -> tags mapping."""
    with gapi_gui.picker_lock:
        return AllTags(
            tags=picker.tag_service.all_tag_names(),
            game_tags=picker.tag_service.get_all(),
        )


@router.get("/tags/{game_id}", response_model=GameTags)
def get_game_tags(game_id: str, picker=Depends(get_picker)):
    """Return the tags for a specific game."""
    with gapi_gui.picker_lock:
        return GameTags(game_id=game_id, tags=picker.tag_service.get(game_id))


@router.post("/tags/{game_id}", response_model=AddTagResult)
def add_tag(game_id: str, body: TagIn, picker=Depends(get_picker)):
    """Add a tag to a game. Body: {"tag": "cozy"}."""
    tag = (body.tag or "").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="tag is required")
    with gapi_gui.picker_lock:
        added = picker.tag_service.add(game_id, tag)
        tags = picker.tag_service.get(game_id)
    return AddTagResult(added=added, game_id=game_id, tags=tags)


@router.delete("/tags/{game_id}/{tag}", response_model=RemoveTagResult)
def remove_tag(game_id: str, tag: str, picker=Depends(get_picker)):
    """Remove a tag from a game (404 if the tag was not present)."""
    with gapi_gui.picker_lock:
        removed = picker.tag_service.remove(game_id, tag)
        tags = picker.tag_service.get(game_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
        )
    return RemoveTagResult(game_id=game_id, tags=tags)


@router.get("/library/by-tag/{tag}", response_model=LibraryByTag)
def library_by_tag(tag: str, picker=Depends(get_picker)):
    """Return games in the user's library that carry a specific tag."""
    with gapi_gui.picker_lock:
        games = picker.tag_service.filter_by_tag(tag, picker.games)
        result = [
            GameWithTags(
                app_id=g.get("appid"),
                game_id=g.get("game_id"),
                name=g.get("name", "Unknown"),
                playtime_hours=round(g.get("playtime_forever", 0) / 60, 1),
                tags=picker.tag_service.get(
                    g.get("game_id", str(g.get("appid", "")))
                ),
            )
            for g in games
        ]
    return LibraryByTag(tag=tag, games=result, count=len(result))
