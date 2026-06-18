"""Playlists domain — named game playlists (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET    /api/playlists
  * POST   /api/playlists                          (201 on success)
  * DELETE /api/playlists/{name}
  * GET    /api/playlists/{name}/games
  * POST   /api/playlists/{name}/games
  * DELETE /api/playlists/{name}/games/{game_id}

Reuses the per-user picker ``playlist_service`` + ``picker_lock``. Like the
wishlist domain, the legacy contract returns **400** when the picker is not
initialised, preserved here via a local dependency.
"""
from fastapi import APIRouter, Depends, HTTPException, status

import gapi_gui
from backend.dependencies import require_login
from backend.schemas.playlists import (
    AddGameIn, CreatePlaylistIn, CreatePlaylistResult, PlaylistGames,
    PlaylistsList, SuccessResult,
)

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


def _picker(username: str = Depends(require_login)):
    """Per-user picker; 400 if not initialised (legacy playlists contract)."""
    p = gapi_gui.ensure_picker_initialized(username)
    if not p:
        raise HTTPException(status_code=400, detail="Not initialized")
    return p


@router.get("", response_model=PlaylistsList)
def list_playlists(picker=Depends(_picker)):
    """List all playlists."""
    with gapi_gui.picker_lock:
        return PlaylistsList(playlists=picker.playlist_service.list_all())


@router.post("", response_model=CreatePlaylistResult,
             status_code=status.HTTP_201_CREATED)
def create_playlist(body: CreatePlaylistIn, picker=Depends(_picker)):
    """Create a new playlist."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    with gapi_gui.picker_lock:
        created = picker.playlist_service.create(name)
    if not created:
        raise HTTPException(status_code=409, detail="Playlist already exists")
    return CreatePlaylistResult(name=name)


@router.delete("/{name}", response_model=SuccessResult)
def delete_playlist(name: str, picker=Depends(_picker)):
    """Delete a playlist by name (404 if missing)."""
    with gapi_gui.picker_lock:
        deleted = picker.playlist_service.delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return SuccessResult()


@router.get("/{name}/games", response_model=PlaylistGames)
def get_playlist_games(name: str, picker=Depends(_picker)):
    """Get all games in a playlist (404 if the playlist does not exist)."""
    with gapi_gui.picker_lock:
        games = picker.playlist_service.get_games(name, picker.games)
    if games is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return PlaylistGames(name=name, games=games, count=len(games))


@router.post("/{name}/games", response_model=SuccessResult)
def add_to_playlist(name: str, body: AddGameIn, picker=Depends(_picker)):
    """Add a game to a playlist."""
    game_id = str(body.game_id or "").strip()
    if not game_id:
        raise HTTPException(status_code=400, detail="game_id is required")
    with gapi_gui.picker_lock:
        added = picker.playlist_service.add_game(name, game_id)
    if not added:
        raise HTTPException(
            status_code=409,
            detail="Game already in playlist or invalid playlist",
        )
    return SuccessResult()


@router.delete("/{name}/games/{game_id}", response_model=SuccessResult)
def remove_from_playlist(name: str, game_id: str, picker=Depends(_picker)):
    """Remove a game from a playlist (404 if game or playlist missing)."""
    with gapi_gui.picker_lock:
        removed = picker.playlist_service.remove_game(name, game_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Game or playlist not found")
    return SuccessResult()
