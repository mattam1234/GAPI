"""FastAPI application factory and ASGI entrypoint.

This is the strangler-fig host: migrated domains are served by native FastAPI
routers, and every path that has not been migrated yet falls through to the
legacy Flask app, mounted as a WSGI sub-application.

Run with:
    uvicorn backend.main:app --reload
    # or, in production:
    gunicorn backend.main:app -k uvicorn.workers.UvicornWorker
"""
from a2wsgi import WSGIMiddleware
from fastapi import FastAPI

import gapi_gui
from backend.routers import (
    achievements, admin_console, admin_notifications, analytics, auth, backlog,
    batch, budget,
    catalog, challenges, chat, community, downloads, duplicates, engagement,
    export, extensibility, friends, game, ignored, leaderboards, library,
    live_session, messages, misc, multiuser, notifications,
    permissions, pick, platforms, playlists, presence, profile,
    recommendations, reviews, schedule, search, sessions, social_stats, tags,
    tournaments, trades, users, voting, wishlist,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="GAPI",
        description="Game library management API (FastAPI modernization).",
        version="2.0.0",
    )

    # --- Migrated domains (native FastAPI) -------------------------------
    # Registered BEFORE the Flask fallback mount so their paths take
    # precedence over the legacy routes of the same name.
    app.include_router(analytics.router)
    app.include_router(chat.router)
    app.include_router(reviews.router)
    app.include_router(tags.router)
    app.include_router(wishlist.router)
    app.include_router(playlists.router)
    app.include_router(budget.router)
    app.include_router(ignored.router)
    app.include_router(backlog.router)
    app.include_router(batch.router)
    app.include_router(voting.router)
    app.include_router(messages.router)
    app.include_router(library.router)
    app.include_router(profile.router)
    app.include_router(sessions.router)
    app.include_router(live_session.router)
    app.include_router(schedule.router)
    app.include_router(schedule.event_router)
    app.include_router(achievements.router)
    app.include_router(challenges.router)
    app.include_router(export.router)
    app.include_router(notifications.router)
    app.include_router(presence.router)
    app.include_router(duplicates.router)
    app.include_router(multiuser.router)
    app.include_router(pick.router)
    app.include_router(game.router)
    app.include_router(friends.router)
    app.include_router(admin_notifications.router)
    app.include_router(admin_console.router)
    app.include_router(downloads.router)
    app.include_router(leaderboards.router)
    app.include_router(recommendations.router)
    app.include_router(permissions.router)
    app.include_router(search.router)
    app.include_router(social_stats.app_friends_router)
    app.include_router(social_stats.stats_router)
    app.include_router(tournaments.router)
    app.include_router(trades.router)
    app.include_router(platforms.psn_router)
    app.include_router(platforms.xbox_router)
    app.include_router(platforms.epic_router)
    app.include_router(platforms.gog_router)
    app.include_router(platforms.nintendo_router)
    app.include_router(users.router)
    app.include_router(users.admin_router)
    app.include_router(users.extra_router)
    app.include_router(auth.router)
    app.include_router(auth.setup_router)
    app.include_router(extensibility.push_router)
    app.include_router(extensibility.plugins_router)
    app.include_router(community.guilds_router)
    app.include_router(community.teams_router)
    app.include_router(community.market_router)
    app.include_router(community.system_router)
    app.include_router(engagement.creator_router)
    app.include_router(engagement.battlepass_router)
    app.include_router(engagement.referral_router)
    app.include_router(engagement.streaming_router)
    app.include_router(engagement.progression_router)
    app.include_router(engagement.ranked_router)
    app.include_router(misc.i18n_router)
    app.include_router(misc.shop_router)
    app.include_router(misc.events_router)
    app.include_router(misc.twitch_router)
    app.include_router(misc.cosmetics_router)
    app.include_router(misc.anticheat_router)
    app.include_router(catalog.optimized_router)
    app.include_router(catalog.collections_router)
    app.include_router(catalog.favorites_router)
    app.include_router(catalog.favorite_router)
    app.include_router(catalog.games_router)
    app.include_router(catalog.filters_router)
    app.include_router(catalog.hltb_router)

    # --- Legacy fallback -------------------------------------------------
    # Everything not matched above is handled by the existing Flask app.
    # Removed domain-by-domain as routers replace it (see MODERNIZATION_BRIEF).
    app.mount("/", WSGIMiddleware(gapi_gui.app))

    return app


app = create_app()
