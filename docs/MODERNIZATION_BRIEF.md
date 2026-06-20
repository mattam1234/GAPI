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
| Tags | `/api/tags[...]`, `/api/library/by-tag/{tag}` | `backend/routers/tags.py` | `tests/test_backend_tags.py` |
| Wishlist | `/api/wishlist[...]`, `/api/wishlist/sales` | `backend/routers/wishlist.py` | `tests/test_backend_wishlist.py` |
| Playlists | `/api/playlists[...]` (+ games) | `backend/routers/playlists.py` | `tests/test_backend_playlists.py` |
| Budget | `/api/budget[...]` | `backend/routers/budget.py` | `tests/test_backend_budget.py` |
| Ignored-games | `/api/ignored-games` (list + toggle) | `backend/routers/ignored.py` | `tests/test_backend_ignored.py` |
| Backlog | `/api/backlogs[...]` (collections) + `/api/backlog[...]` (status) | `backend/routers/backlog.py` | `tests/test_backend_backlog.py` + ported `tests/test_backlog_collections.py` |
| Voting | `/api/voting/[create\|{id}/vote\|status\|close]` | `backend/routers/voting.py` | `tests/test_backend_voting.py` |
| Messages (DM) | `/api/messages/conversations`, `/api/messages/{user}` | `backend/routers/messages.py` | `tests/test_backend_messages.py` |
| Library compare | `/api/library/compare/{username}` | `backend/routers/library.py` | `tests/test_backend_library.py` |
| Profile | `/api/profile/me`, `/api/profile/update` | `backend/routers/profile.py` | `tests/test_backend_profile.py` |
| Sessions | `/api/sessions/history` | `backend/routers/sessions.py` | `tests/test_backend_sessions.py` |
| Schedule (chunk 1) | `/api/schedules` collections (list/create/update/delete) | `backend/routers/schedule.py` (`router`) | `tests/test_backend_schedule.py` |
| Schedule (chunk 2) | `GET /api/schedule`, `PUT /api/schedule/{id}`, `POST /api/schedule/{id}/rsvp` | `backend/routers/schedule.py` (`event_router`) | ported `test_schedule_rsvp_validation.py` + `test_achievement_schedule.py` classes |
| Schedule (chunk 3) | `/api/schedule/search-games`, `/search-attendees`, `/common-games`, `/common-games/random` | `backend/routers/schedule.py` (`event_router`) | ported `test_achievement_schedule.py::TestScheduleCommonGamePickerRoutes` (search helpers already unit-tested) |
| Schedule (chunk 4a) | `GET /api/schedule/ical-sync-info`, `GET /api/schedule/export.ics` (token or session auth) | `backend/routers/schedule.py` (`event_router`) | ported `test_schedule_ical_export.py` + `test_achievement_schedule.py::TestScheduleIcalSyncRoutes` |
| Schedule (chunk 4b) | `GET /api/schedule/discord-guilds`, `POST /api/schedule/{id}/create-discord-event` | `backend/routers/schedule.py` (`event_router`) | ported `test_schedule_discord_event.py` + new `test_backend_discord_guilds.py` |
| Schedule (chunk 4c) | `POST /api/schedule` (create), `DELETE /api/schedule/{id}` (with inline Discord create/cancel) | `backend/routers/schedule.py` (`event_router`) | `tests/test_backend_schedule_events.py` |

**✅ Schedule domain fully migrated** (all 17 routes). No `/api/schedule*` routes
remain in Flask.

| Achievements (hunts) | `GET /api/achievements`, `POST /api/achievement-hunt`, `PUT /api/achievement-hunt/{id}` | `backend/routers/achievements.py` | `tests/test_backend_achievements.py` |
| Achievement challenges | `/api/achievement-challenges[/{id}][/join\|/progress]` (6 routes) | `backend/routers/challenges.py` | `tests/test_backend_challenges.py` |
| Data export | `GET /api/export/[library\|favorites\|user-data]` | `backend/routers/export.py` | `tests/test_backend_export.py` |
| Notification prefs/history | `GET/PUT /api/notifications/preferences`, `GET /api/notifications/history` | `backend/routers/notifications.py` | ported 3 classes in `test_permissions_notifprefs.py` |
| Presence | `POST /api/presence`, `/presence/update`, `/presence/clear` | `backend/routers/presence.py` | `tests/test_backend_presence_duplicates.py` |
| Duplicate detection | `GET /api/duplicates` | `backend/routers/duplicates.py` | `tests/test_backend_presence_duplicates.py` |
| Multi-user pick | `POST /api/multiuser/pick` | `backend/routers/multiuser.py` | `tests/test_backend_multiuser.py` |

| Pick (core) | `POST /api/pick` (the 314-line god-handler) | `backend/routers/pick.py` | `tests/test_backend_pick.py` + ported `test_analytics_service.py::TestPickAuditWiring` |
| Game details | `GET /api/game/{app_id}/details` | `backend/routers/game.py` | `tests/test_backend_game.py` |
| Friends | `GET /api/friends`, add/remove/follow | `backend/routers/friends.py` | `tests/test_backend_friends.py` |
| Admin notifications | `POST /api/admin/notifications/[broadcast\|send-digests]` | `backend/routers/admin_notifications.py` | ported broadcast/digest classes + `tests/test_backend_admin_notifications.py` |
| Leaderboards | `GET /api/leaderboards`, `/seasonal`, `/api/leaderboard` | `backend/routers/leaderboards.py` | `tests/test_backend_leaderboards.py` |
| Recommendations | `GET /api/recommendations[/ml\|/smart\|/variant\|/ai]` (5 routes) | `backend/routers/recommendations.py` | `tests/test_backend_recommendations.py` + ported ML/smart/variant classes |
| Permissions (users chunk 1) | `GET /api/permissions`, `GET /api/users/{u}/permissions`, `POST /api/admin/users/{u}/permissions`, `POST /api/admin/roles/bulk-assign` | `backend/routers/permissions.py` | ported 4 classes in `test_permissions_notifprefs.py` |

**Cache-Control carried over:** the legacy Flask `after_request` set
`Cache-Control: public, max-age=60, stale-while-revalidate=120` on cacheable API
prefixes (incl. `/api/permissions`). The FastAPI handler sets the same header
explicitly so the public-cacheability contract is preserved.

**✅ users domain fully migrated** (multi-chunk). Done across chunks 1–5:
permissions, per-user email, admin suspension/status/search, reputation, and the
core user-management CRUD — `add`/`update`/`remove` (multi-picker), `role`/`roles`/
`delete` (user_manager), `GET /api/roles`, `GET /api/users/list`,
`GET /api/users/{username}/profile`, and `POST /api/user/profile`
(`backend/routers/users.py`: `router` + `admin_router` + `extra_router`). No
`/api/users*`, `/api/roles`, or `/api/user/profile` routes remain in Flask — the
deprecated `/api/users/legacy` (multi_picker dump) is intentionally left behind.

**Latent bug preserved (users list/profile):** `GET /api/users/list` and
`GET /api/users/{username}/profile` reference the same never-defined module-global
`db_service` behind the leaderboards/`/ai` 500s, so both always raised
`NameError` -> 500 in production (profile 404s first for a missing user). The
ports reproduce this via `gapi_gui.db_service` (AttributeError -> caught -> 500)
while preserving the query/shaping for when a real `db_service` is wired; tests
assert the 500 and the 404-precedence. Chunk 5 tests: `tests/test_backend_users_crud.py`.

**✅ Recommendations fully migrated** (base + ml + smart + variant + ai). The ML/
smart/variant test classes authenticated via `@patch('gapi_gui.current_user',...)`
— which only satisfies the Flask resolver; the ports swap that for a signed
session cookie (FastAPI's `require_login` reads the cookie). `/ai` references the
undefined `db_service` (same latent bug as leaderboards) so it returns the
hardcoded default set in production — preserved.

**Latent bug preserved (leaderboards):** the plural `/api/leaderboards` and
`/seasonal` handlers reference a module-global `db_service` that is **never
defined** in `gapi_gui` (used in ~10 places but `hasattr` is False) — so they
always raised `NameError` -> 500 in production. No test ever hit them. The port
reproduces this faithfully (referencing `gapi_gui.db_service`, caught -> 500);
the SQL/shaping is preserved so the routes work the moment a real `db_service`
is wired. Tests validate that logic via `create=True`. The singular
`/api/leaderboard` (service-backed) is fully functional.

**Two admin checks:** the legacy app had two — `app_settings_service.is_admin`
(used inline by analytics) and `user_manager.is_admin` (the `@require_admin`
decorator). The backend has both as dependencies: `require_admin` (settings) and
`require_admin_um` (user_manager). Each migrated route uses whichever its legacy
form used.

**Picks status:** `/api/pick` and `/api/multiuser/pick` migrated. The single
biggest handler in the app (filters, rarity, collection resolution, Discord RPC,
background ProtonDB thread, webhook + WebhookNotifier fan-out, detail caching,
pick audit) ported faithfully — error bodies preserved as `{"error": ...}` via
JSONResponse. Three source-code-assertion tests (VR filter, collection_id) were
repointed from `gapi_gui.py` to `backend/routers/pick.py`.

**✅ Picks feature fully migrated** — `/api/pick`, `/api/multiuser/pick`, and
`/api/random-game` (anonymous demo path, no login) are all on FastAPI.
`/random-game` uses the optional `get_current_user` dependency so it serves both
demo and authenticated picks.

**Mixed-client test file:** `test_permissions_notifprefs.py` tests many
endpoints, only 3 of which migrated. The session helper now detects the client
type (Flask `session_transaction` vs FastAPI signed cookie), so the migrated
classes use the FastAPI `TestClient` while the still-Flask classes (permissions,
broadcast, error-rate) keep the Flask client — one file, two backends.

**Partial:** the 3 export GETs (CSV/JSON) are migrated; `POST
/api/import/user-data` stays in Flask (dual JSON/multipart upload — needs
`python-multipart` + `UploadFile`, deferred).

**✅ Achievements domain fully migrated.** Hunt, multiplayer challenges,
`GET /stats`, `GET /achievements/{app_id}` (live Steam), and the two Steam *sync*
POSTs are all on FastAPI. No `/api/achievements*` routes remain in Flask. (The
`_PLATFORM_SYNC_HANDLERS` stub functions are retained in gapi_gui and reused.)

**Latent bug fixed during migration:** the legacy `/sync` and `/sync/platform`
handlers called `database.get_user(...)`, which does not exist (the function is
`get_user_by_username`) — the endpoint would have 500'd when reached. The FastAPI
port uses the correct function. (gapi_gui.py still has one unrelated
`database.get_user` call at ~line 1646, outside this migration's scope.)

**Routing note:** `GET /api/achievements/{app_id:int}` uses the Starlette `:int`
path convertor so non-integer siblings (`/stats`, `/sync`) don't collide with it
and fall through correctly — the FastAPI equivalent of Flask's `<int:app_id>`.

**Partial-domain migration:** schedule is large (17 routes), migrated in chunks.
Chunk 2 took the event list/update/RSVP routes (no Discord) and ported their
existing Flask HTTP tests to the FastAPI TestClient. The live-`requests` Discord integration ports
cleanly: the test patches the **global** `requests.post`, so it intercepts the
FastAPI handler's call unchanged. The Discord-API-error path returns a
`JSONResponse` to preserve the legacy `{'error', 'status_code', 'details'}`
body shape and upstream status code.

**Flask-context hazard (resolved in 4a):** `_build_schedule_ical_sync_urls`
read Flask's `request.url_root`. Migrating its route to FastAPI raised "working
outside an active HTTP request". Fix: the helper now takes an optional
`base_url`, which the FastAPI handler supplies from `request.base_url`. Watch
for other helpers that touch Flask globals (`request`, `session`, `url_for`).

**Patterns proven so far:** admin-gated + service singleton (analytics);
per-user picker-backed, 500-on-uninit (reviews, tags); picker-backed,
400-on-uninit (wishlist, playlists, budget); **DB-backed via `SessionLocal` +
service singletons** (ignored-games).

**Test porting:** when a domain has existing Flask HTTP tests (e.g. backlog's
`test_backlog_collections.py`), they are repointed at the FastAPI `TestClient`
in the same PR — the WSGI fallback means such tests can still reach any
unmigrated routes they touch (e.g. `/api/library`).

**Known messy domains (need untangling before a clean slice):**
- **leaderboards** — fragmented across 3 locations; one route uses raw SQL
  instead of `leaderboard_service`.
- **friends** — heterogeneous: `GET /api/friends` is a live Steam-API call,
  while `add`/remove/follow are unpersisted stubs.

**Next candidates:** core multi-route domains (auth/setup, picks, schedule,
achievements, chat).

> Larger slices carry caveats: **backlog** has existing Flask HTTP tests
> (`test_backlog_collections.py`, `test_dashboard_filters.py`) to port; the
> **leaderboards** routes are fragmented across 3 locations and one uses raw SQL
> (not `leaderboard_service`), so it needs untangling before a clean migration.

> Reusable seam: per-user picker-backed domains (reviews, tags) share the
> `get_picker` dependency in `backend/dependencies.py`.

---

## 7. Parallel batch — auth/setup + chat + live-session

Migrated as a parallel batch (two worktree-isolated agents for chat and
live-session, auth/setup done directly), then integrated together.

**✅ auth + setup fully migrated** → `backend/routers/auth.py` (`router` +
`setup_router`). The **session seam**: `login` signs the *same* Flask session
cookie via `gapi_gui.app.session_interface` and sets it on the FastAPI response
(Flask-configured cookie attributes), so a login on the new route authenticates
every FastAPI router and the still-mounted Flask fallback; `logout` clears it and
resets the picker globals + Discord RPC. Faithful quirks preserved: `update-ids`
runs the discord-numeric check *after* the update; `register`/`initial-admin`
don't log the user in; background Steam library-sync threads retained. Tests:
`tests/test_backend_auth.py` (incl. a cookie round-trip through `require_login`).
Repointed legacy tests that asserted Flask internals (audit wiring → FastAPI
client; rate-limit → route-registration; api-stats → still-Flask `/api/changelog`).
**Gap logged:** legacy `@limiter.limit` on login/register was commented out, so
rate limiting was never active — to be re-added on the FastAPI routes.

**✅ chat fully migrated** → `backend/routers/chat.py` (12 routes, all
`require_login`). Preserved `Cache-Control: no-store` (legacy `_add_cache_control`
default for non-cacheable `/api/*`). Tests: `tests/test_backend_chat.py`.

**✅ live-session fully migrated** → `backend/routers/live_session.py` (11 routes).
Literal paths (`/active`, `/discord-locations`) registered before the catch-all
`/{session_id}` so they aren't shadowed. SSE `/events` ported to a
`StreamingResponse`. Flask-context hazard handled: the legacy username resolution
(`get_current_user_record` → demo-user fallback under FastAPI) replaced with an
explicit by-username DB lookup. Tests: `tests/test_backend_live_session.py`.

Full suite after integration: **1989 passed**.

## 8. Parallel batch — search + batch + notifications

Three more self-contained domains, migrated by parallel worktree agents and
integrated together (zero merge conflicts — disjoint router files + disjoint
`gapi_gui.py` deletions; git auto-merged the `main.py` additions).

**✅ search fully migrated** → `backend/routers/search.py` (7 routes, all
`require_login`). Preserved a latent 500: `GET /trending` with non-numeric
`days`/`limit` raises inside the try → 500 (legacy parsed inside the try).

**✅ batch operations fully migrated** → `backend/routers/batch.py` (5 routes).
**Gaps logged:** `add-to-playlist` and `delete` are count-only stubs (report
success without mutating); `change-status` uses deprecated `datetime.utcnow()`.
Preserved faithfully; flagged for the gap-closure pass.

**✅ notifications remainder fully migrated** → added 8 routes to the existing
`backend/routers/notifications.py` (`/mock`, bare list, `/read`, `/send`, and
the slack/teams/ifttt/homeassistant webhook tests). `/send`'s admin gate is an
inline 403-with-JSON-body (notification-service admin check), preserved as-is
rather than swapped to the `require_admin_um` dependency. The notifications
domain is now fully on FastAPI.

Repointed legacy Flask-client tests that hit moved routes: search-history
(`test_audit_search_history.py`) and webhook-test (`test_smart_recommendations_webhooks.py`).

Full suite after integration: **2064 passed**. Flask routes remaining: ~160.

## 9. Parallel batch — tournaments + trades + platform integrations

Three more domains via parallel worktree agents, integrated together.

**✅ tournaments** → `backend/routers/tournaments.py` (3 routes). Mock handlers
(hardcoded data, no DB). The agent found a **duplicate dead GET handler** bound to
the same path (Werkzeug served only the first); dropped the unreachable one.

**✅ trades** → `backend/routers/trades.py` (4 routes). All reference the undefined
`db_service` → caught → success-faking mock bodies (never persist); preserved.

**✅ platform integrations** → `backend/routers/platforms.py` — one router per
platform: psn/xbox/epic/gog/nintendo (15 routes). The **OAuth seam** is the notable
part: the legacy routes wrote `session['<plat>_oauth_state']` and 302'd; the FastAPI
versions merge the state into the Flask session payload and re-sign the same cookie
onto a `RedirectResponse` (reusing `auth._set_session_cookie`), with the redirect
URI derived from `request.base_url`. `/api/platform/status` + the shared
`_get_platform_client` helper intentionally stay in Flask (referenced at call time).

**Gaps logged:** trades + tournaments are mock stubs needing real backends.

Full suite after integration: **2133 passed**. Flask routes remaining: **137**.

## 10. Parallel batch — extensibility + social/stats + community

Six more domains across three agents, integrated together.

**✅ push + plugins** → `backend/routers/extensibility.py` (`push_router` +
`plugins_router`, 8 routes). Plugins keep their two-DB-session admin-check quirk.
`/api/admin/push/broadcast` stays in Flask (different prefix).

**✅ app-friends + stats** → `backend/routers/social_stats.py` (7 routes).
`/api/stats/compare/candidates` returns 200-with-empty on DB-unavailable/error
(not an error code) — preserved.

**✅ guilds + teams + market + system** → `backend/routers/community.py` (4 routers,
12 routes). teams/guilds/market are `db_service`/dead-`try` mock stubs (preserved);
`/api/system/cache/clear` keeps its inline `username == 'admin'` literal check.

Full suite after integration: **2239 passed**. Flask routes remaining: **110**.

## 11. Long-tail batch — engagement + misc + catalog (grab-bags)

Three grab-bag agents cleared ~30 small/single-route domains.

**✅ engagement** → `backend/routers/engagement.py` — creator, battlepass, referral,
streaming, progression, ranked (12 routes; mostly stubs, several `db_service`-500
mock fallbacks preserved).

**✅ misc** → `backend/routers/misc.py` — i18n (kept **unauthenticated**), shop,
events, twitch, cosmetics, anticheat (10 routes).

**✅ catalog** → `backend/routers/catalog.py` — optimized (perf-cached reads),
collections, favorites, favorite, games/{id}/similar, filters, hltb/{name:path}
(11 routes). Confirmed `/api/optimized/*` were never in the cacheable allowlist
(so `no-store`, faithfully replicated); preserved the `db_service`-500s on
optimized users/leaderboard/chat.

Full suite after integration: **2347 passed**. Flask routes remaining: **79**.

---

## Frontend (Phase 4, started)

The hybrid SPA scaffold landed (`frontend/`, React 18 + Vite + TS) — see
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) and `frontend/README.md`. Dashboard +
Analytics consume `GET /api/analytics/dashboard` with Recharts + TanStack Table;
Admin/Profile are wired/stubbed. The session cookie is shared (same-origin), so no
separate login. Next: serve `dist/` under `/app`, deepen Admin once that domain
migrates.
</content>
