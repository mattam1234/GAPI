# GAPI Console — frontend (React + Vite)

The modern hybrid SPA. It serves the **dashboard / analytics / admin / profile**
views; the legacy `templates/` + `static/` UI continues to serve everything else
during the migration (see [../docs/MODERNIZATION_BRIEF.md](../docs/MODERNIZATION_BRIEF.md)).

## Stack
- **React 18 + Vite + TypeScript**
- **Recharts** — trend areas, ranked bars, donut breakdowns
- **TanStack Table** — sortable/filterable data tables
- Design system in `src/styles/tokens.css` (dark + light themes via `[data-theme]`)
- Typed `fetch` client (`src/api/client.ts`) with `credentials: 'include'` so the
  Flask session cookie (decoded by `backend/dependencies.py`) authenticates the SPA
  with no separate login.

## Develop
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173/app  (proxies /api -> :8000)
```
Run the backend separately (`uvicorn backend.main:app --port 8000`). Without a
backend/admin session the dashboard falls back to bundled **sample data** (shown
with a "Sample data" badge) so views are always demoable in dev.

## Build
```bash
npm run build      # tsc --noEmit && vite build -> dist/  (base path /app)
npm run gen:api    # regenerate typed API client from a running backend's /openapi.json
```

## Layout
```
src/
  api/        client.ts (typed fetch), types.ts (mirrors backend schemas)
  components/ Layout, Card, StatCard, charts (Recharts), DataTable (TanStack)
  lib/        theme (dark/light), useFetch, format, sampleData
  pages/      Dashboard, Analytics, Admin, Profile
  styles/     tokens.css (design system), global.css
```

## Serving in production (next step)
`vite build` emits to `dist/` with base `/app/`. A follow-up wires the backend to
serve `dist/` under `/app` (mount static + SPA fallback), so the console ships in
the same origin as the API.
