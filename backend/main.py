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
    achievements, admin_notifications, analytics, auth, backlog, batch, budget,
    challenges, chat, downloads, duplicates, export, friends, game, ignored,
    leaderboards, library, live_session, messages, multiuser, notifications,
    permissions, pick, playlists, presence, profile, recommendations, reviews,
    schedule, search, sessions, tags, tournaments, trades, users, voting,
    wishlist,
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
    app.include_router(downloads.router)
    app.include_router(leaderboards.router)
    app.include_router(recommendations.router)
    app.include_router(permissions.router)
    app.include_router(search.router)
    app.include_router(tournaments.router)
    app.include_router(trades.router)
    app.include_router(users.router)
    app.include_router(users.admin_router)
    app.include_router(users.extra_router)
    app.include_router(auth.router)
    app.include_router(auth.setup_router)

    # --- Legacy fallback -------------------------------------------------
    # Everything not matched above is handled by the existing Flask app.
    # Removed domain-by-domain as routers replace it (see MODERNIZATION_BRIEF).
    app.mount("/", WSGIMiddleware(gapi_gui.app))

    return app


app = create_app()
