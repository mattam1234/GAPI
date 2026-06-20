"""Social (in-app friends) + library statistics domains (migrated to FastAPI).

Two routers live in this module:

``app_friends_router`` — the in-app GAPI friends API (separate from the
Steam-backed ``/api/friends`` domain already migrated). Friend lists, sent and
received requests, plus send/respond/remove request mutations. All handlers go
through the ``database.get_db()`` generator and prefer the ``_friend_service``
singleton, falling back to the bare ``database.*`` helpers — mirroring the
legacy code exactly.

``stats_router`` — per-user library statistics and multi-user comparison. These
read the DB library cache (via ``_library_service`` or the bare helper) and the
favourites count.

All handlers reuse the legacy singletons via ``gapi_gui`` at CALL TIME so any
reassignment (tests, lazy init) is observed. The legacy ``after_request`` set
``Cache-Control: no-store`` on every ``/api/*`` response not in the cacheable
allowlist (neither ``/api/stats`` nor ``/api/app-friends`` is); that header is
preserved here via ``_NO_STORE``.

Routes:
  GET    /api/app-friends
  POST   /api/app-friends/request
  POST   /api/app-friends/respond
  POST   /api/app-friends/remove
  GET    /api/stats
  GET    /api/stats/compare/candidates
  GET    /api/stats/compare
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

app_friends_router = APIRouter(prefix="/api/app-friends", tags=["app-friends"])
stats_router = APIRouter(prefix="/api/stats", tags=["stats"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ===========================================================================
# In-app Friends API  (/api/app-friends)
# ===========================================================================

@app_friends_router.get("")
def api_app_friends(username: str = Depends(require_login)):
    """Return the current user's in-app friends, sent and received requests.

    The ``friends`` list includes ``steam_id``, ``epic_id``, ``gog_id``, and
    ``is_online`` (active within the last 5 minutes).
    """
    g = gapi_gui
    db = next(g.database.get_db())
    try:
        result = g.database.get_app_friends_with_platforms(db, username)
    finally:
        if db:
            db.close()
    return _ok(result)


@app_friends_router.post("/request")
def api_send_friend_request(body: Optional[dict] = Body(default=None),
                            username: str = Depends(require_login)):
    """Send a friend request to another GAPI user."""
    g = gapi_gui
    sender = username
    data = body or {}
    target = data.get("username", "").strip()
    if not target:
        return _err(400, "username is required")
    db = next(g.database.get_db())
    try:
        if g._friend_service:
            ok, message = g._friend_service.send_request(db, sender, target)
        else:
            ok, message = g.database.send_friend_request(db, sender, target)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True, "message": message})
    return _err(400, message)


@app_friends_router.post("/respond")
def api_respond_friend_request(body: Optional[dict] = Body(default=None),
                               username: str = Depends(require_login)):
    """Accept or decline a pending friend request."""
    g = gapi_gui
    data = body or {}
    requester = data.get("username", "").strip()
    if "accept" not in data:
        return _err(400, "accept is required")
    accept = bool(data.get("accept"))
    if not requester:
        return _err(400, "username is required")
    db = next(g.database.get_db())
    try:
        if g._friend_service:
            ok, message = g._friend_service.respond(db, username, requester, accept)
        else:
            ok, message = g.database.respond_friend_request(db, username, requester, accept)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True, "message": message})
    return _err(400, message)


@app_friends_router.post("/remove")
def api_remove_app_friend(body: Optional[dict] = Body(default=None),
                          username: str = Depends(require_login)):
    """Remove a GAPI friend."""
    g = gapi_gui
    data = body or {}
    other = data.get("username", "").strip()
    if not other:
        return _err(400, "username is required")
    db = next(g.database.get_db())
    try:
        if g._friend_service:
            ok = g._friend_service.remove(db, username, other)
        else:
            ok = g.database.remove_app_friend(db, username, other)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({"success": True})
    return _err(500, "Failed to remove friend")


# ===========================================================================
# Library statistics API  (/api/stats)
# ===========================================================================

@stats_router.get("")
def api_stats(username: str = Depends(require_login)):
    """Get library statistics from the database cache."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, "Database not available")

    try:
        db = g.database.SessionLocal()
        try:
            if g._library_service:
                cached_games = g._library_service.get_cached(db, username)
            else:
                cached_games = g.database.get_cached_library(db, username)
            if g._db_favorites_service:
                favorite_count = len(g._db_favorites_service.get_all(db, username))
            else:
                favorite_count = len(g.database.get_user_favorites(db, username))
        finally:
            db.close()

        if not cached_games:
            return _ok({
                "total_games": 0,
                "unplayed_games": 0,
                "played_games": 0,
                "unplayed_percentage": 0,
                "total_playtime": 0,
                "average_playtime": 0,
                "favorite_count": favorite_count,
                "top_games": [],
            })

        total_games = len(cached_games)
        unplayed = len([gm for gm in cached_games if gm.get("playtime_hours", 0) == 0])
        total_playtime = sum(gm.get("playtime_hours", 0) for gm in cached_games)

        # Top 10 most played
        sorted_by_playtime = sorted(
            cached_games,
            key=lambda gm: gm.get("playtime_hours", 0),
            reverse=True,
        )[:10]

        top_games = []
        for game in sorted_by_playtime:
            top_games.append({
                "name": game.get("name", "Unknown"),
                "playtime_hours": round(game.get("playtime_hours", 0), 1),
            })

        return _ok({
            "total_games": total_games,
            "unplayed_games": unplayed,
            "played_games": total_games - unplayed,
            "unplayed_percentage": round(unplayed / total_games * 100, 1) if total_games > 0 else 0,
            "total_playtime": round(total_playtime, 1),
            "average_playtime": round(total_playtime / total_games, 1) if total_games > 0 else 0,
            "favorite_count": favorite_count,
            "top_games": top_games,
        })
    except Exception as e:
        g.gui_logger.error(f"Error calculating stats: {e}")
        return _err(500, "Failed to load stats")


@stats_router.get("/compare/candidates")
def api_stats_compare_candidates(request: Request,
                                 username: str = Depends(require_login)):
    """Return users available for comparison, filtered by scope.

    Query params:
      scope: 'all' (default) | 'friends' | 'me_and_friends'
    """
    g = gapi_gui
    current = username
    scope = request.query_params.get("scope", "all")

    if not g.ensure_db_available():
        return _ok({"users": [], "current_user": current})

    try:
        db = g.database.SessionLocal()
        try:
            if scope in ("friends", "me_and_friends"):
                friends_data = g.database.get_app_friends(db, current)
                friend_usernames = [f["username"] for f in friends_data.get("friends", [])]
                if scope == "me_and_friends":
                    candidates = [current] + friend_usernames
                else:
                    candidates = friend_usernames
                users = [{"username": u} for u in candidates]
            else:
                # all: return all users who have a cached library
                all_users = g.user_manager.get_all_users()
                users = [{"username": u["username"]} for u in all_users if u.get("username")]
        finally:
            db.close()

        return _ok({"users": users, "current_user": current})
    except Exception as e:
        g.gui_logger.error(f"Error fetching compare candidates: {e}")
        return _ok({"users": [], "current_user": current})


@stats_router.get("/compare")
def api_stats_compare(request: Request, username: str = Depends(require_login)):
    """Compare statistics across multiple users using the per-user DB cache."""
    g = gapi_gui
    users_param = request.query_params.get("users", "")
    if not users_param:
        return _err(400, "No users specified")

    usernames = [u.strip() for u in users_param.split(",") if u.strip()]
    if not usernames:
        return _err(400, "Invalid users parameter")

    if not g.ensure_db_available():
        return _err(503, "Database not available")

    comparison_data = {
        "users": [],
        "comparison_metrics": {},
    }

    try:
        db = g.database.SessionLocal()
        try:
            # Collect per-user library data and stats from the DB cache
            user_game_ids: dict = {}
            for uname in usernames:
                try:
                    if g._library_service:
                        cached_games = g._library_service.get_cached(db, uname)
                    else:
                        cached_games = g.database.get_cached_library(db, uname)

                    total = len(cached_games)
                    unplayed = len([gm for gm in cached_games if gm.get("playtime_hours", 0) == 0])
                    total_playtime = sum(gm.get("playtime_hours", 0) for gm in cached_games)
                    avg_playtime = total_playtime / total if total > 0 else 0

                    top_games = sorted(
                        cached_games,
                        key=lambda gm: gm.get("playtime_hours", 0),
                        reverse=True,
                    )[:5]

                    # Collect canonical game keys for shared-game analysis
                    user_game_ids[uname] = set(
                        gm.get("app_id") or gm.get("name", "")
                        for gm in cached_games
                        if gm.get("app_id") or gm.get("name")
                    )

                    comparison_data["users"].append({
                        "username": uname,
                        "total_games": total,
                        "unplayed_games": unplayed,
                        "played_games": total - unplayed,
                        "unplayed_percentage": round(unplayed / total * 100, 1) if total > 0 else 0,
                        "total_playtime": round(total_playtime, 1),
                        "average_playtime": round(avg_playtime, 1),
                        "top_games": [
                            {
                                "name": gm.get("name", "Unknown"),
                                "playtime_hours": round(gm.get("playtime_hours", 0), 1),
                            }
                            for gm in top_games
                        ],
                    })

                except Exception as e:
                    g.gui_logger.warning(f"Error loading stats for user {uname}: {e}")
                    user_game_ids[uname] = set()
                    comparison_data["users"].append({
                        "username": uname,
                        "error": str(e),
                        "total_games": 0,
                        "unplayed_games": 0,
                        "played_games": 0,
                        "total_playtime": 0,
                        "average_playtime": 0,
                    })
        finally:
            db.close()

        # Compute aggregate comparison metrics
        valid_users = [u for u in comparison_data["users"] if "error" not in u]
        if valid_users:
            total_games_list = [u["total_games"] for u in valid_users]
            playtime_list = [u["total_playtime"] for u in valid_users]

            # Shared games: present in ALL compared users' libraries
            if user_game_ids:
                all_id_sets = list(user_game_ids.values())
                shared_ids = all_id_sets[0].intersection(*all_id_sets[1:]) if len(all_id_sets) > 1 else set()
                total_unique = len(set().union(*all_id_sets)) if all_id_sets else 0
            else:
                shared_ids = set()
                total_unique = 0

            comparison_data["comparison_metrics"] = {
                "most_games": max(total_games_list),
                "least_games": min(total_games_list),
                "avg_games": round(sum(total_games_list) / len(total_games_list), 1),
                "most_playtime": max(playtime_list),
                "least_playtime": min(playtime_list),
                "avg_playtime": round(sum(playtime_list) / len(playtime_list), 1),
                "total_unique_games": total_unique,
                "shared_game_count": len(shared_ids),
            }

        return _ok(comparison_data)

    except Exception as e:
        g.gui_logger.error(f"Error comparing stats: {e}")
        return _err(500, "Failed to compare statistics")
