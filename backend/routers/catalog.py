"""Catalog grab-bag cluster (migrated to FastAPI).

Seven small/single-route legacy domains migrated together, one ``APIRouter``
per URL prefix:

  * ``optimized_router``   — ``/api/optimized``  (performance-cached reads)
  * ``collections_router`` — ``/api/collections``
  * ``favorites_router``   — ``/api/favorites``
  * ``favorite_router``    — ``/api/favorite``
  * ``games_router``       — ``/api/games``
  * ``filters_router``     — ``/api/filters``
  * ``hltb_router``        — ``/api/hltb``

All seven prefixes are absent from the legacy ``_CACHEABLE_API_PREFIXES``
allowlist (which only contains ``/api/permissions``, ``/api/changelog``,
``/api/health``), and none of the legacy handlers set their own
``Cache-Control``, so every response here received ``Cache-Control: no-store``
from the legacy ``after_request``. That header is set explicitly to preserve
behaviour.

Faithful ports — latent legacy behaviour is preserved exactly:

* The ``/api/optimized/users``, ``/api/optimized/leaderboard`` and
  ``/api/optimized/chat/messages`` handlers reference a module-global
  ``db_service`` that is never defined on ``gapi_gui``. Referenced here via
  ``gapi_gui.db_service`` so the ``AttributeError`` still fires inside the
  ``try`` and the handler returns 500 (``{"error": "..."}``) — exactly as in
  production.
* The ``/api/collections`` handler is a pure success-faking stub returning
  hard-coded data; its ``try/except`` never trips.

Singletons are referenced via ``gapi_gui`` at CALL TIME so reassignments and
test patches are picked up.

Routes:
  optimized:
    GET    /api/optimized/users
    GET    /api/optimized/games
    GET    /api/optimized/leaderboard
    GET    /api/optimized/chat/messages
    GET    /api/optimized/games/search
  collections:
    GET    /api/collections
  favorites:
    GET    /api/favorites
  favorite:
    POST   /api/favorite/{app_id}
    DELETE /api/favorite/{app_id}
  games:
    GET    /api/games/{app_id}/similar
  filters:
    GET    /api/filters/platform-options
  hltb:
    GET    /api/hltb/{game_name}
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

optimized_router = APIRouter(prefix="/api/optimized", tags=["optimized"])
collections_router = APIRouter(prefix="/api/collections", tags=["collections"])
favorites_router = APIRouter(prefix="/api/favorites", tags=["favorites"])
favorite_router = APIRouter(prefix="/api/favorite", tags=["favorite"])
games_router = APIRouter(prefix="/api/games", tags=["games"])
filters_router = APIRouter(prefix="/api/filters", tags=["filters"])
hltb_router = APIRouter(prefix="/api/hltb", tags=["hltb"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ── optimized ────────────────────────────────────────────────────────────────

@optimized_router.get("/users")
def api_list_users_paginated(request: Request, username: str = Depends(require_login)):
    """Get paginated user list."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        page, per_page = g.performance.LazyLoadHelper.extract_pagination_params(
            request.query_params)

        db = g.db_service.get_db()  # AttributeError in prod -> caught -> 500 (preserved)

        # Count total
        total_query = "SELECT COUNT(*) FROM users"
        total = db.execute(total_query).fetchone()[0]

        # Get paginated results
        query = """
            SELECT id, username, email, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        offset = (page - 1) * per_page
        users = db.execute(query, (per_page, offset)).fetchall()

        result = g.performance.Paginator.paginate(
            [{'id': u[0], 'username': u[1], 'email': u[2], 'created_at': str(u[3])} for u in users],
            page=page,
            per_page=per_page,
            total_count=total
        )

        result['endpoint'] = 'optimized-users'
        return _ok(result)
    except Exception as e:
        g.gui_logger.error(f"Error getting paginated users: {e}")
        return _err(500, str(e))


@optimized_router.get("/games/search")
def api_search_games_optimized(request: Request, username: str = Depends(require_login)):
    """Search games with pagination and result limiting."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        query = request.query_params.get('q', '').lower()
        page, per_page = g.performance.LazyLoadHelper.extract_pagination_params(
            request.query_params)

        if not query or len(query) < 2:
            return _ok({'items': [], 'page': 1, 'total': 0})

        # Search in loaded games (optimized for client-side loading)
        p = g.ensure_picker_initialized(username)
        if not p or not p.games:
            return _ok({'items': [], 'page': 1, 'total': 0})

        # Filter games by query
        results = [game for game in p.games if query in game.get('name', '').lower()]

        result = g.performance.Paginator.paginate(
            results,
            page=page,
            per_page=per_page,
            total_count=len(results)
        )

        result['query'] = query
        return _ok(result)
    except Exception as e:
        g.gui_logger.error(f"Error searching games: {e}")
        return _err(500, str(e))


@optimized_router.get("/games")
def api_list_games_paginated(request: Request, username: str = Depends(require_login)):
    """Get paginated game library."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        page, per_page = g.performance.LazyLoadHelper.extract_pagination_params(
            request.query_params)

        # Load games (mock for now)
        p = g.ensure_picker_initialized(username)
        all_games = p.games if p else []

        result = g.performance.Paginator.paginate(
            all_games,
            page=page,
            per_page=per_page,
            total_count=len(all_games)
        )

        result['endpoint'] = 'optimized-games'
        return _ok(result)
    except Exception as e:
        g.gui_logger.error(f"Error getting paginated games: {e}")
        return _err(500, str(e))


@optimized_router.get("/leaderboard")
def api_get_leaderboard_optimized(request: Request, username: str = Depends(require_login)):
    """Get optimized leaderboard with pagination and caching."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        category = request.query_params.get('category', 'picks').lower()
        page, per_page = g.performance.LazyLoadHelper.extract_pagination_params(
            request.query_params)

        # Use cache for leaderboard (10 minute TTL)
        cache_key = f"leaderboard:{category}"
        cached_data = g.performance.get_cache().get(cache_key)

        if cached_data is not None:
            # Return from cache but still paginate
            result = g.performance.Paginator.paginate(
                cached_data,
                page=page,
                per_page=per_page,
                total_count=len(cached_data)
            )
            result['cached'] = True
            return _ok(result)

        # Query database
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> 500 (preserved)
        leaderboard = []

        if category == 'picks':
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 200
            """
        else:
            query = """
                SELECT u.username, COUNT(v.id) as value
                FROM users u
                LEFT JOIN votes v ON u.username = v.user
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 200
            """

        cursor = db.execute(query)
        for row in cursor.fetchall():
            leaderboard.append({
                'username': row[0],
                'value': row[1],
                'rank': len(leaderboard) + 1
            })

        # Cache for 10 minutes
        g.performance.get_cache().set(cache_key, leaderboard, ttl=600)

        # Paginate
        result = g.performance.Paginator.paginate(
            leaderboard,
            page=page,
            per_page=per_page,
            total_count=len(leaderboard)
        )
        result['cached'] = False
        return _ok(result)
    except Exception as e:
        g.gui_logger.error(f"Error getting optimized leaderboard: {e}")
        return _err(500, str(e))


@optimized_router.get("/chat/messages")
def api_get_chat_messages_paginated(request: Request,
                                    username: str = Depends(require_login)):
    """Get paginated chat messages."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        room = request.query_params.get('room', 'general')
        page, per_page = g.performance.LazyLoadHelper.extract_pagination_params(
            request.query_params)

        db = g.db_service.get_db()  # AttributeError in prod -> caught -> 500 (preserved)

        # Count messages
        count_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_room = ?"
        total = db.execute(count_query, (room,)).fetchone()[0]

        # Get paginated messages
        query = """
            SELECT id, username, message, created_at
            FROM chat_messages
            WHERE chat_room = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        offset = (page - 1) * per_page
        messages = db.execute(query, (room, per_page, offset)).fetchall()

        result = g.performance.Paginator.paginate(
            [{
                'id': m[0],
                'username': m[1],
                'message': m[2],
                'created_at': str(m[3])
            } for m in reversed(messages)],
            page=page,
            per_page=per_page,
            total_count=total
        )

        result['room'] = room
        return _ok(result)
    except Exception as e:
        g.gui_logger.error(f"Error getting paginated messages: {e}")
        return _err(500, str(e))


# ── collections ──────────────────────────────────────────────────────────────

@collections_router.get("")
def api_get_collections(username: str = Depends(require_login)):
    """Get cosmetic collections."""
    try:
        return _ok({
            'collections': [
                {
                    'type': 'themes',
                    'owned': 18,
                    'total': 25,
                    'completion': 72,
                    'rarity_points': 450
                },
                {
                    'type': 'titles',
                    'owned': 12,
                    'total': 30,
                    'completion': 40,
                    'rarity_points': 280
                },
                {
                    'type': 'frames',
                    'owned': 7,
                    'total': 20,
                    'completion': 35,
                    'rarity_points': 180
                },
            ],
            'total_completion': 49,
            'mastery_tier': 'Silver'
        })
    except Exception:
        return _ok({'collections': [], 'total_completion': 0})


# ── favorites ────────────────────────────────────────────────────────────────

@favorites_router.get("")
def api_favorites(username: str = Depends(require_login)):
    """Get all favorite games."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, 'Database not available')

    if not username:
        return _err(401, 'Not authenticated')

    try:
        db = g.database.SessionLocal()
        try:
            if g._db_favorites_service:
                favorite_ids = g._db_favorites_service.get_all(db, username)
            else:
                favorite_ids = g.database.get_user_favorites(db, username)

            # Get cached library to look up game details
            if g._library_service:
                cached_games = g._library_service.get_cached(db, username)
            else:
                cached_games = g.database.get_cached_library(db, username)
        finally:
            db.close()

        favorites = []
        for app_id in favorite_ids:
            game = next((gm for gm in cached_games if str(gm.get('app_id')) == str(app_id)), None)
            if game:
                favorites.append({
                    'app_id': app_id,
                    'game_id': game.get('game_id') or f"steam:{app_id}",
                    'name': game.get('name', 'Unknown'),
                    'playtime_hours': round(game.get('playtime_hours', 0), 1),
                    'platform': game.get('platform', 'steam'),
                    'tags': game.get('tags', []),
                })
            else:
                favorites.append({
                    'app_id': app_id,
                    'game_id': f"steam:{app_id}",
                    'name': f'App ID {app_id} (Not in library)',
                    'playtime_hours': 0,
                    'platform': 'steam',
                    'tags': [],
                })

        return _ok({'favorites': favorites})
    except Exception as e:
        g.gui_logger.error(f"Error loading favorites: {e}")
        return _err(500, 'Failed to load favorites')


# ── favorite ─────────────────────────────────────────────────────────────────

@favorite_router.post("/{app_id}")
@favorite_router.delete("/{app_id}")
def api_toggle_favorite(app_id: int, request: Request,
                        username: str = Depends(require_login)):
    """Add or remove a game from favorites."""
    g = gapi_gui
    if not g.ensure_db_available():
        return _err(503, 'Database not available')

    if not username:
        return _err(401, 'Not authenticated')

    try:
        db = g.database.SessionLocal()
        try:
            if request.method == 'POST':
                if g._db_favorites_service:
                    success = g._db_favorites_service.add(db, username, str(app_id))
                else:
                    success = g.database.add_favorite(db, username, str(app_id))
                if success:
                    return _ok({'success': True, 'action': 'added'})
                else:
                    return _err(500, 'Failed to add favorite')
            else:
                if g._db_favorites_service:
                    success = g._db_favorites_service.remove(db, username, str(app_id))
                else:
                    success = g.database.remove_favorite(db, username, str(app_id))
                if success:
                    return _ok({'success': True, 'action': 'removed'})
                else:
                    return _err(500, 'Failed to remove favorite')
        finally:
            db.close()
    except Exception as e:
        g.gui_logger.error(f"Error toggling favorite: {e}")
        return _err(500, 'Failed to toggle favorite')


# ── games ────────────────────────────────────────────────────────────────────

@games_router.get("/{app_id}/similar")
def api_similar_games(app_id: str, request: Request,
                      username: str = Depends(require_login)):
    """Return games similar to *app_id* based on genre/tag overlap (login required).

    Query parameters:
      ``platform``  – game platform (default ``'steam'``)
      ``limit``     – max results (default 10, max 50)
    """
    g = gapi_gui
    if not g.DB_AVAILABLE:
        return _ok({'app_id': app_id, 'similar': []})
    platform = request.query_params.get('platform', 'steam').strip().lower()
    try:
        limit = max(1, min(50, int(request.query_params.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10
    try:
        db = next(g.database.get_db())
        similar = g.database.get_similar_games(db, app_id, platform=platform, limit=limit)
        return _ok({'app_id': app_id, 'platform': platform, 'similar': similar})
    except Exception as e:
        g.gui_logger.error('api_similar_games error: %s', e)
        return _err(500, str(e))


# ── filters ──────────────────────────────────────────────────────────────────

@filters_router.get("/platform-options")
def api_filter_platform_options(request: Request,
                                username: str = Depends(require_login)):
    """Return platform/device filter options limited to user-configured platforms."""
    g = gapi_gui

    users_param = request.query_params.get('users', '').strip()
    requested_users = [u.strip() for u in users_param.split(',') if u.strip()] if users_param else []
    usernames = requested_users or ([username] if username else [])

    platforms = g._collect_available_platforms(usernames)
    platform_items = [
        {
            'value': platform,
            'label': platform.title(),
            'device': g.classify_device_for_platform(platform)
        }
        for platform in platforms
    ]

    device_values = sorted({
        item['device'] for item in platform_items if item['device'] in {'pc', 'console'}
    })
    device_items = [
        {
            'value': device,
            'label': 'PC' if device == 'pc' else 'Console'
        }
        for device in device_values
    ]

    return _ok({
        'platforms': platform_items,
        'devices': device_items
    })


# ── hltb ─────────────────────────────────────────────────────────────────────

@hltb_router.get("/{game_name:path}")
def api_get_hltb(game_name: str, username: str = Depends(require_login)):
    """Return HowLongToBeat completion-time estimates for *game_name*.

    Uses the ``howlongtobeatpy`` library (optional). If the library is not
    installed or the HLTB website is unreachable, returns HTTP 503.
    """
    g = gapi_gui
    data = g.gapi.get_hltb_data(game_name)
    if data is None:
        return _err(503, 'No HLTB data available for this game')
    return _ok(data)
