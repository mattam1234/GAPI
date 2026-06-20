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
* The ``/api/guilds`` handlers are real, persistent features backed by the
  ``backend.models.community`` ORM models and ``community_service``.
* The ``/api/market`` handlers are a real, persistent feature backed by the
  ``backend.models.market`` ORM models and ``app.services.market_service``. A
  listing has a seller, item, integer coin price, optional category, and status
  ``active`` -> ``sold`` | ``cancelled``. ``sell`` creates an ``active`` listing
  (400 on missing item / invalid price); ``offer`` records a buyer's coin offer
  on a listing (404 if the listing is missing; 400 if the buyer is the seller or
  the listing is not active); ``GET /api/market`` lists active listings,
  optionally filtered by the ``category`` query param.
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

import database
import gapi_gui
from backend.dependencies import require_login
# Importing the model module registers the community ORM models on the shared
# Base so the create_all hook in backend.main creates their tables.
from backend.models import community as community_models  # noqa: F401
# Importing the market model module registers its ORM models on the shared Base.
from backend.models import market as market_models  # noqa: F401
from app.services import community_service
from app.services import market_service
from app.services.market_service import MarketError

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
    """List guilds: the user's own guild plus recommendations."""
    db = database.SessionLocal()
    try:
        data = community_service.list_guilds_for_user(db, username)
        return _ok(data)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading guilds: %s", e)
        return _err(500, 'Guild data unavailable')
    finally:
        db.close()


@guilds_router.post("/create")
def api_create_guild(body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Create a new guild (creator auto-joins as owner)."""
    data = body or {}
    name = str(data.get('name', '') or '').strip()
    description = str(data.get('description', '') or '')

    db = database.SessionLocal()
    try:
        guild = community_service.create_guild(db, username, name, description)
        return _ok({'success': True, 'message': f'Guild "{guild.name}" created!',
                    'guild_id': guild.id})
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:
        gapi_gui.gui_logger.error("Error creating guild: %s", e)
        return _err(500, 'Failed to create guild')
    finally:
        db.close()


@guilds_router.post("/{guild_id}/join")
def api_join_guild(guild_id: int, username: str = Depends(require_login)):
    """Join a guild (idempotent)."""
    db = database.SessionLocal()
    try:
        community_service.join_guild(db, guild_id, username)
        return _ok({'success': True, 'message': 'Guild joined successfully!'})
    except LookupError:
        return _err(404, 'Guild not found')
    except Exception as e:
        gapi_gui.gui_logger.error("Error joining guild: %s", e)
        return _err(500, 'Failed to join guild')
    finally:
        db.close()


# ── teams ───────────────────────────────────────────────────────────────────

@teams_router.get("")
def api_get_teams(username: str = Depends(require_login)):
    """Get available teams with membership info for the current user."""
    db = database.SessionLocal()
    try:
        teams = community_service.list_teams_for_user(db, username)
        return _ok({'teams': teams})
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading teams: %s", e)
        return _ok({'teams': []})
    finally:
        db.close()


@teams_router.post("/create")
def api_create_team(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Create a new team (creator auto-joins as a member)."""
    g = gapi_gui
    data = body or {}
    name = str(data.get('name', '') or '').strip()

    if not name:
        return _err(400, 'Team name required')

    db = database.SessionLocal()
    try:
        team = community_service.create_team(db, username, name)
        team_id = str(team.id)

        # Broadcast team creation event (preserved best-effort behaviour).
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_created',
                    team_name=team.name,
                    data={'team_id': team_id, 'leader': username}
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast team creation: {e}')

        return _ok({'success': True, 'message': f'Team "{team.name}" created',
                    'team_id': team_id})
    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:
        g.gui_logger.error(f"Error creating team: {e}")
        return _err(500, 'Failed to create team')
    finally:
        db.close()


@teams_router.post("/{team_id}/join")
def api_join_team(team_id: int, username: str = Depends(require_login)):
    """Join a team (idempotent)."""
    g = gapi_gui
    db = database.SessionLocal()
    try:
        team = community_service.join_team(db, team_id, username)

        # Broadcast team join event (preserved best-effort behaviour).
        if g.REALTIME_AVAILABLE:
            try:
                g.realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_joined',
                    team_name=team.name,
                    data={'team_id': str(team_id), 'member': username}
                )
            except Exception as e:
                g.gui_logger.warning(f'Failed to broadcast team join: {e}')

        return _ok({'success': True, 'message': 'Joined team successfully'})
    except LookupError:
        return _err(404, 'Team not found')
    except Exception as e:
        g.gui_logger.error(f"Error joining team: {e}")
        return _err(500, 'Failed to join team')
    finally:
        db.close()


# ── market ──────────────────────────────────────────────────────────────────

@market_router.get("")
def api_market_list(category: str = Query(default='all'),
                    username: str = Depends(require_login)):
    """List active marketplace listings, optionally filtered by category.

    The ``category`` query param defaults to the legacy sentinel ``'all'``,
    which (along with blank/missing) means "no filter".
    """
    db = database.SessionLocal()
    try:
        listings = market_service.list_listings(db, category=category)
        return _ok({'listings': listings})
    except MarketError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error loading market listings: %s", e)
        return _err(500, 'Failed to load listings')
    finally:
        db.close()


@market_router.post("/sell")
def api_market_sell(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Create an active listing for sale (400 on missing item / invalid price)."""
    data = body or {}
    item = data.get('item')
    price = data.get('price')
    category = data.get('category')

    db = database.SessionLocal()
    try:
        listing = market_service.create_listing(
            db, seller=username, item=item, price=price, category=category)
        return _ok({
            'success': True,
            'message': f'Item listed for {listing["price"]} coins!',
            'listing_id': listing['id'],
            'listing': listing,
        }, status_code=201)
    except MarketError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error creating listing: %s", e)
        return _err(500, 'Failed to create listing')
    finally:
        db.close()


@market_router.post("/{listing_id}/offer")
def api_market_offer(listing_id: str, body: Optional[dict] = Body(default=None),
                     username: str = Depends(require_login)):
    """Record a buyer's offer on a listing.

    Accepts the offered amount as ``amount`` (new) or ``offer_price`` (legacy).
    404 if the listing is missing; 400 if the buyer is the seller, the listing
    is not active, or the amount is invalid.
    """
    data = body or {}
    amount = data.get('amount', data.get('offer_price'))

    db = database.SessionLocal()
    try:
        offer = market_service.make_offer(
            db, listing_id=listing_id, buyer=username, amount=amount)
        return _ok({
            'success': True,
            'message': f'Offer of {offer["amount"]} coins submitted!',
            'offer_id': offer['id'],
            'offer': offer,
        }, status_code=201)
    except MarketError as e:
        return _err(e.status_code, e.message)
    except Exception as e:
        gapi_gui.gui_logger.error("Error making offer: %s", e)
        return _err(500, 'Failed to make offer')
    finally:
        db.close()


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
