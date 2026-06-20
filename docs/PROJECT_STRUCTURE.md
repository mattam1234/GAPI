# Project Structure

A map of the repository. The codebase is mid-migration from a Flask monolith to
FastAPI (strangler-fig — see [MODERNIZATION_BRIEF.md](MODERNIZATION_BRIEF.md)),
so some legacy modules still live at the root by necessity; those are called out
below.

## Top level

```
GAPI/
├── backend/            # ✅ FastAPI app (the new home) — ASGI entrypoint + routers
│   ├── main.py         #    create_app(): registers routers, mounts Flask fallback
│   ├── dependencies.py #    get_db, auth (session-cookie bridge), admin guards
│   ├── routers/        #    one module per migrated domain
│   └── schemas/        #    Pydantic request/response models
├── app/                # Framework-agnostic service layer (used by BOTH stacks)
│   └── services/       #    business logic — takes a db session, returns plain data
├── tests/              # The automated pytest suite (source of truth; ~1990 tests)
├── static/             # Frontend assets (legacy single-page JS/CSS)
├── templates/          # Legacy Jinja/HTML shell
├── locales/            # i18n translation files
├── scripts/            # Operational & developer tooling
│   ├── sql/            #    raw SQL migration files
│   ├── manual_tests/   #    ad-hoc smoke/integration scripts (NOT the pytest suite)
│   └── *.py            #    db migration, setup, and maintenance scripts
├── docs/               # All project documentation (this file, briefs, guides)
├── data/               # Runtime data store
├── user_data/          # Per-user data
├── logs/               # Runtime logs
├── nginx/ systemd/     # Deployment config
├── desktop-app/  mobile-app/  browser-extension/   # Companion clients
└── .github/            # CI workflows
```

## Root-level files

**Conventional (stay at root):** `README.md`, `LICENSE`, `.gitignore`,
`.env.example`, `setup.cfg`, `requirements.txt`, `requirements-full.txt`,
`Dockerfile`, `docker-compose*.yml`, `setup.sh`.

**Runtime config (loaded by bare path — do not move):** `config.json`,
`config_template.json`, `users_template.json`.

**Legacy core modules (still at root — migrating out incrementally):**
`gapi_gui.py` (the shrinking Flask god-file), `database.py`, `gapi.py`,
`multiuser.py`, `platform_clients.py`, `performance.py`, `realtime.py`,
`discord_bot.py`, `discord_presence.py`, `twitch_client.py`,
`webhook_notifier.py`, `openapi_spec.py`.

> These are imported by bare name (`import gapi_gui`, `import database`, …)
> across the codebase and tests. They are deliberately **not** repackaged yet:
> the FastAPI migration deletes their routes domain-by-domain, and Phase 3 of the
> brief collapses what remains into `backend/`. Moving them now would churn every
> import for no durable benefit. Treat `backend/` as the destination.

## Where to add new code

- **New API endpoint?** Add/extend a router in `backend/routers/` and register it
  in `backend/main.py`. Put business logic in `app/services/`.
- **Test?** `tests/` (the only path pytest collects — see `setup.cfg`).
- **One-off script or migration?** `scripts/` (`scripts/sql/` for raw SQL).
