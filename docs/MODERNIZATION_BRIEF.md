# GAPI Modernization Brief

**Status:** Approved direction — full modern rewrite, backend first.
**Owner:** core team
**Last updated:** 2026-06-18

This is the plan of record for modernizing GAPI. It captures the current state,
the target architecture, and the **incremental** path between them. Nothing in
the existing app is deleted until its replacement is shipped and test-covered.

---

## 1. Current state (measured, not estimated)

| File | LOC | Role | Problem |
|------|-----|------|---------|
| `gapi_gui.py` | 18,090 | 337 Flask routes + init + globals | God file; no blueprints |
| `static/main.js` | 11,638 | Entire frontend | Single-file monolith |
| `database.py` | 5,769 | ORM models + data-access helpers | Mixed concerns, large |
| `static/style.css` | 4,643 | All styling | Monolithic |
| `templates/index.html` | 2,987 | Single-page shell | One giant template |
| `openapi_spec.py` | 2,249 | Hand-written OpenAPI | Drifts from real routes |

**What is already healthy:**

- `app/services/` holds **30+ service classes** (analytics, schedule, reviews,
  achievements, moderation, …). Business logic is largely **already extracted**
  and is **framework-agnostic** — every service takes a SQLAlchemy `db` session
  and returns plain data. These port to any HTTP layer unchanged.
- `gapi_gui.py` is internally divided into ~50 clearly-labelled domain sections
  (Auth, Reviews, Tags, Scheduler, Playlists, Backlog, Budget, Wishlist,
  Achievements, Recommendations, Leaderboards, Chat, Live Sessions, Analytics,
  Moderation, Batch ops, …). The migration seams are already drawn.

**Implication:** the rewrite is overwhelmingly an **HTTP-layer + schema** effort,
not a logic rewrite. We keep the ORM and the service layer; we replace the route
layer and the frontend.

---

## 2. Target architecture

### Backend — FastAPI

```
backend/
  main.py                 # create_app(): FastAPI, router registration, Flask WSGI fallback mount
  config.py               # Settings (env-driven), shared with legacy where needed
  dependencies.py         # get_db(), get_current_user(), require_login(), require_admin()
  schemas/                # Pydantic request/response models, one module per domain
    analytics.py
    ...
  routers/                # FastAPI routers, one module per domain (mirrors app/services/)
    analytics.py
    ...
  services/  -> reuse app/services/ (no fork)
```

- **Sync routes** (`def`, not `async def`) so the existing sync SQLAlchemy
  services run directly in FastAPI's threadpool. No data-layer rewrite, no async
  driver migration. Async can be adopted later, per-domain, if a hotspot needs it.
- **Pydantic v2** response models give us **auto-generated OpenAPI** at `/docs`,
  retiring the hand-maintained `openapi_spec.py`.
- **Reuse the existing service singletons and ORM** — one source of truth for
  business logic and DB access during the entire migration.

### Frontend — component framework (Phase 2, after backend)

- A real build step (Vite) + component framework (React/Vue/Svelte — TBD when we
  start Phase 2), replacing the 11.6k-line `main.js` and the single `index.html`.
- Consumes the FastAPI OpenAPI schema for typed API clients.
- Out of scope for the current (backend-first) phase; tracked here for context.

---

## 3. Migration strategy — strangler fig (single process)

We do **not** run two servers. FastAPI becomes the ASGI entrypoint and **mounts
the legacy Flask app as a WSGI fallback** (`a2wsgi.WSGIMiddleware`):

```
incoming request
   │
   ├─ matches a migrated FastAPI router?  ──► served by FastAPI (new code)
   │
   └─ otherwise                            ──► falls through to mounted Flask app (legacy)
```

- FastAPI routers are registered **before** the catch-all Flask mount, so a
  migrated path wins automatically. Clients keep using the **same URLs** — no
  coordinated frontend change per domain.
- **Auth is shared for free:** the FastAPI auth dependency decodes the *same*
  Flask session cookie using Flask's own `session_interface` and secret key.
  A user logged in via the legacy login endpoint is authenticated on new routes,
  and vice-versa. No session store change, no re-login.
- **Deploy change:** `gunicorn gapi_gui:app` → `gunicorn backend.main:app -k uvicorn.workers.UvicornWorker` (or `uvicorn backend.main:app`). The Dockerfile CMD is updated once, at cutover of the first slice.

### Per-domain migration loop

For each domain (≈50), repeat:

1. Add Pydantic schemas in `backend/schemas/<domain>.py`.
2. Add a FastAPI router in `backend/routers/<domain>.py` that reuses the existing
   `<Domain>Service`, mirroring the legacy routes' paths and behavior.
3. Port the legacy tests (or add new ones) against the FastAPI `TestClient`;
   assert response parity with the legacy endpoint.
4. Register the router; the legacy Flask routes for that domain become dead and
   are deleted from `gapi_gui.py` in the **same** PR.
5. Ship. Repeat.

The god file shrinks domain-by-domain; at the end `gapi_gui.py` holds only app
init (which then collapses into `backend/`).

### Phase ordering (backend)

- **Phase 0 — Foundation (this PR):** `backend/` scaffold, DB + auth dependencies,
  Flask WSGI fallback, and the **Analytics** domain migrated as the proof slice
  (small, self-contained, admin-gated — exercises auth, DB, service reuse, schema).
- **Phase 1 — Leaf domains:** read-mostly, low-coupling domains (reviews, tags,
  wishlist, backlog, leaderboards, analytics-adjacent).
- **Phase 2 — Core domains:** auth/setup, picks, schedule, achievements, chat.
- **Phase 3 — Retire legacy:** delete `openapi_spec.py` (auto-generated now),
  collapse remaining init into `backend/`, remove Flask.
- **Phase 4 — Frontend rewrite** (separate brief).

---

## 4. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Auth/session mismatch between Flask and FastAPI | Decode the *same* Flask cookie via Flask's `session_interface`; covered by tests. |
| Behavioral drift during a route move | Each slice asserts parity against the legacy endpoint before the legacy route is deleted. |
| Two admin checks exist (`user_manager.is_admin` vs `app_settings_service.is_admin`) | New dependencies mirror whichever check the *specific* legacy route used; documented per router. |
| Mount ordering bugs (legacy shadows new) | FastAPI routers registered before the WSGI mount; a test asserts a migrated path is served by FastAPI and an unmigrated one falls through to Flask. |
| Heavy `gapi_gui` import side-effects | Acceptable during strangler (Flask app must init anyway); removed in Phase 3. |

---

## 5. Definition of done (backend rewrite)

- All 337 routes served by FastAPI routers; `gapi_gui.py` route definitions gone.
- OpenAPI auto-generated; `openapi_spec.py` deleted.
- Full test suite green against the FastAPI app; legacy parity tests retired only
  after their FastAPI equivalents pass.
- Single ASGI entrypoint; Dockerfile/CI updated.

---

## 6. Migration log

Domains served natively by FastAPI (legacy Flask routes deleted):

| Domain | Routes | Router | Tests |
|--------|--------|--------|-------|
| Analytics | `/api/analytics/dashboard`, `/export` | `backend/routers/analytics.py` | `tests/test_backend_foundation.py` |
| Reviews | `GET/POST/PUT/DELETE /api/reviews[/{id}]` | `backend/routers/reviews.py` | `tests/test_backend_reviews.py` |

**Next candidates (leaf domains):** tags, wishlist, backlog, leaderboards.
</content>
