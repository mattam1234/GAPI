# Current Architecture Map

## 1) Runtime Surfaces

- **Web app/API:** `gapi_gui.py` (Flask app, HTML rendering, REST endpoints, auth/session flow)
- **CLI app:** `gapi.py` (command-driven picker and utility operations)
- **Discord bot:** `discord_bot.py` (chat-driven commands and account linking)
- **Shared data/model layer:** `database.py`

## 2) Layer Boundaries

### Presentation and API Layer
- Flask routes and request/response handling are centered in `gapi_gui.py`.
- Frontend is a single-page template in `templates/index.html` backed by `static/main.js` + `static/style.css`.

### Domain Services
- Domain logic lives in `app/services/` (examples: backlog, schedule, wishlist, notifications, recommendations).
- Route handlers should delegate business operations to services instead of embedding logic.

### Repository/Data Access
- Data-access abstractions live in `app/repositories/`.
- ORM models and DB helper functions live in `database.py`.

## 3) Core Request Flow

1. Request enters Flask route in `gapi_gui.py`.
2. Route validates auth/ownership/inputs.
3. Route delegates domain operation to service(s).
4. Service interacts with repository/database helpers.
5. Route returns normalized JSON/HTTP response.

## 4) Background and Async Workloads

Current background patterns are thread-based and include:
- periodic/background library sync scheduling
- queued achievement sync after library sync
- non-blocking external-data refreshes
- SSE subscriber queue fanout for live updates
- Discord bot process output capture

These run outside the critical request path to keep API/UI interactions responsive.

## 5) API Contracts and Client Consumers

- Primary REST surface is under `/api/*`.
- OpenAPI contract is generated in `openapi_spec.py` and served via `/api/openapi.json`.
- `/api/docs` hosts the interactive Swagger UI.
- Multiple clients consume this API: web UI, extension, mobile/desktop integrations, and Discord workflows.

## 6) Architectural Guardrails

- Keep business logic in services, not in route handlers.
- Preserve backward compatibility for existing API fields/routes unless a documented breaking change is approved.
- When adding background jobs, ensure idempotency and safe error handling.
- Update this map whenever component ownership or boundaries shift.
