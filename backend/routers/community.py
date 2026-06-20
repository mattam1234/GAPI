"""Community cluster (migrated to FastAPI).

Four small legacy domains migrated together, one ``APIRouter`` per URL prefix:

  * ``guilds_router``  — ``/api/guilds``
  * ``teams_router``   — ``/api/teams``
  * ``market_router``  — ``/api/market``
  * ``system_router``  — ``/api/system``

Faithful ports — latent legacy behaviour is preserved exactly:

* The ``/api/teams`` handlers reference a module-global ``db_service`` that is
  never defined on ``gapi_gui`` (the same undefined global behind trades / the
  leaderboards 500s). Every handler wraps the access in ``try/except`` and
  returns a success-faking mock response, so in production these routes never
  actually persist anything. Referenced here via ``gapi_gui.db_service`` so the
  ``AttributeError`` still fires and the mock fallback still runs.
* The ``/api/guilds`` and ``/api/market`` handlers are pure success-faking
  stubs returning hard-coded data; their ``try/except`` never trips.
* The ``/api/system`` handlers gate on ``PERFORMANCE_AVAILABLE`` and use the
  optional ``performance`` module; ``api_clear_cache`` additionally enforces an
  inline ``username == 'admin'`` check (not the admin decorator).

All four prefixes are absent from the legacy ``_CACHEABLE_API_PREFIXES``
allowlist (which only contains ``/api/permissions``, ``/api/changelog``,
``/api/health``), so every response here received ``Cache-Control: no-store``
from the legacy ``after_request``. That header is set explicitly to preserve
behaviour.

Routes:
  guilds:
    GET    /api/guilds
    POST   /api/guilds/create
    POST   /api/guilds/{guild_id}/join
  teams:
    GET    /api/teams
    POST   /api/teams/create
    POST   /api/teams/{team_id}/join
  market:
    GET    /api/market
    POST   /api/market/sell
    POST   /api/market/{listing_id}/offer
  system:
    GET    /api/system/cache/stats
    POST   /api/system/cache/clear
    GET    /api/system/indexes
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

guilds_router = APIRouter(prefix="/api/guilds", tags=["guilds"])
teams_router = APIRouter(prefix="/api/teams", tags=["teams"])
market_router = APIRouter(prefix="/api/market", tags=["market"])
system_router = APIRouter(prefix="/api/system", tags=["system"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


# ── guilds ──────────────────────────────────────────────────────────────────

@guilds_router.get("")
def api_list_guilds(username: str = Depends(require_login)):
    """List guilds."""
    try:
        return _ok({
            'my_guild': {
                'name': 'Shadow Legends',
                'level': 15,
                'members': 48,
                'treasury': 250000,
                'role': 'officer',
                'tax_rate': 15
            },
            'recommended_guilds': [
                {'name': 'Phoenix Union', 'level': 12, 'members': 50, 'recruiting': True},
                {'name': 'Dragon Slayers', 'level': 18, 'members': 45, 'recruiting': True},
            ]
        })
    except Exception:
        return _err(500, 'Guild data unavailable')


@guilds_router.post("/create")
def api_create_guild(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Create a new guild."""
    data = body or {}
    name = data.get('name', '')

    try:
        return _ok({'success': True, 'message': f'Guild "{name}" created!', 'guild_id': 99})
    except Exception:
        return _ok({'success': True, 'message': 'Guild created (mock)'})


@guilds_router.post("/{guild_id}/join")
def api_join_guild(guild_id: str, username: str = Depends(require_login)):
    """Join a guild."""
    try:
        return _ok({'success': True, 'message': 'Guild joined successfully!'})
    except Exception:
        return _ok({'success': True, 'message': 'Joined guild (mock)'})


# ── teams ───────────────────────────────────────────────────────────────────

@teams_router.get("")
def api_get_teams(username: str = Depends(require_login)):
    """Get available teams."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Get all teams with member count
        teams_query = """
            SELECT t.id, t.name, t.leader_id, t.max_members, t.win_rate,
                   COUNT(DISTINCT tm.user_id) as member_count,
                   (SELECT COUNT(*) FROM team_memberships WHERE team_id = t.id AND user_id = ?) as is_member
            FROM teams t
            LEFT JOIN team_memberships tm ON t.id = tm.team_id
            GROUP BY t.id, t.name, t.leader_id, t.max_members, t.win_rate
            LIMIT 10
        """
        teams_rows = db.execute(teams_query, (user.id,)).fetchall()

        teams = []
        colors = ['#667eea', '#764ba2', '#f39c12', '#e74c3c', '#1abc9c']
        for idx, row in enumerate(teams_rows):
            team_id, name, leader_id, max_members, win_rate, member_count, is_member = row
            teams.append({
                'id': str(team_id),
                'name': name,
                'color': colors[idx % len(colors)],
                'members': list(range(member_count)),  # simplified
                'max_members': max_members,
                'winrate': int(win_rate) if win_rate else 50,
                'is_member': bool(is_member)
            })

        return _ok({'teams': teams})
    except Exception as e:
        g.gui_logger.error(f"Error loading teams: {e}")
        # Mock teams
        teams = [
            {'id': '1', 'name': 'Elite Gaming Squad', 'color': '#667eea', 'members': ['user1', 'user2', 'user3'], 'max_members': 5, 'winrate': 68, 'is_member': True},
        ]
        return _ok({'teams': teams})


@teams_router.post("/create")
def api_create_team(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Create a new team."""
    g = gapi_gui
    data = body or {}
    name = data.get('name', '')

    if not name:
        return _err(400, 'Team name required')

    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Create team
        insert_query = "INSERT INTO teams (name, leader_id) VALUES (?, ?)"
        result = db.execute(insert_query, (name, user.id))
        db.commit()

        team_id = result.lastrowid

        # Add creator as leader
        member_query = "INSERT INTO team_memberships (user_id, team_id, role) VALUES (?, ?, 'leader')"
        db.execute(member_query, (user.id, team_id))
        db.commit()

        # Broadcast team creation event
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_created',
                    team_name=name,
                    data={'team_id': str(team_id), 'leader': username}
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast team creation: {e}')

        return _ok({'success': True, 'message': f'Team "{name}" created', 'team_id': str(team_id)})
    except Exception as e:
        g.gui_logger.error(f"Error creating team: {e}")
        return _ok({'success': True, 'message': f'Team created (mock)', 'team_id': '4'})


@teams_router.post("/{team_id}/join")
def api_join_team(team_id: str, username: str = Depends(require_login)):
    """Join a team."""
    g = gapi_gui
    try:
        db = g.db_service.get_db()  # AttributeError in prod -> caught -> mock (preserved)
        user = g.db_service.get_current_user(username)

        # Add user to team
        insert_query = "INSERT INTO team_memberships (user_id, team_id, role) VALUES (?, ?, 'member')"
        db.execute(insert_query, (user.id, int(team_id)))
        db.commit()

        # Get team name for notification
        team_query = "SELECT name FROM teams WHERE id = ?"
        team_result = db.execute(team_query, (int(team_id),)).fetchone()
        team_name = team_result[0] if team_result else f'Team {team_id}'

        # Broadcast team join event
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_joined',
                    team_name=team_name,
                    data={'team_id': str(team_id), 'member': username}
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast team join: {e}')

        return _ok({'success': True, 'message': 'Joined team successfully'})
    except Exception as e:
        g.gui_logger.error(f"Error joining team: {e}")
        return _ok({'success': True, 'message': 'Joined team (mock)'})


# ── market ──────────────────────────────────────────────────────────────────

@market_router.get("")
def api_market_list(category: str = Query(default='all'),
                    username: str = Depends(require_login)):
    """Browse trading market."""
    try:
        return _ok({
            'listings': [
                {
                    'id': 1,
                    'seller': 'SkylarMint',
                    'item': '[Theme] Midnight Blue',
                    'rarity': 'epic',
                    'price': 2500,
                    'listed_days': 3
                },
                {
                    'id': 2,
                    'seller': 'ProGamer42',
                    'item': '[Title] Master of Chaos',
                    'rarity': 'legendary',
                    'price': 5000,
                    'listed_days': 1
                },
            ]
        })
    except Exception:
        return _ok({'listings': []})


@market_router.post("/sell")
def api_market_sell(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """List item for sale."""
    data = body or {}

    try:
        item = data.get('item', '')
        price = data.get('price', 0)
        return _ok({'success': True, 'message': f'Item listed for {price} points!', 'listing_id': 123})
    except Exception:
        return _ok({'success': True, 'message': 'Listed (mock)'})


@market_router.post("/{listing_id}/offer")
def api_market_offer(listing_id: str, body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Make offer on marketplace item."""
    data = body or {}
    offer_price = data.get('offer_price', 0)

    try:
        return _ok({'success': True, 'message': f'Offer of {offer_price} points submitted!', 'offer_id': 456})
    except Exception:
        return _ok({'success': True, 'message': 'Offer made (mock)'})


# ── system ──────────────────────────────────────────────────────────────────

@system_router.get("/cache/stats")
def api_cache_stats(username: str = Depends(require_login)):
    """Get cache statistics and performance metrics."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        cache = g.performance.get_cache()
        monitor = g.performance.get_monitor()

        return _ok({
            'cache': cache.stats(),
            'performance': monitor.get_all_stats(),
            'timestamp': g.datetime.utcnow().isoformat()
        })
    except Exception as e:
        g.gui_logger.error(f"Error getting cache stats: {e}")
        return _err(500, 'Failed to get stats')


@system_router.post("/cache/clear")
def api_clear_cache(username: str = Depends(require_login)):
    """Clear all cache (admin only)."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        # Simple admin check
        if username != 'admin':
            return _err(403, 'Unauthorized')

        cache = g.performance.get_cache()
        cache.clear()

        return _ok({'success': True, 'message': 'Cache cleared'})
    except Exception as e:
        return _err(500, str(e))


@system_router.get("/indexes")
def api_get_index_suggestions(username: str = Depends(require_login)):
    """Get database index suggestions for optimization."""
    g = gapi_gui
    if not g.PERFORMANCE_AVAILABLE:
        return _err(503, 'Performance module not available')

    try:
        suggestions = g.performance.IndexAnalyzer.analyze_query_bottlenecks()
        return _ok({
            'suggestions': suggestions,
            'count': len(suggestions),
            'description': 'Run these SQL queries to optimize database performance'
        })
    except Exception as e:
        return _err(500, str(e))
