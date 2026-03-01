# Achievement Hunting & Ignore Features - Summary

## What's New

### 🎮 Core Features Added

1. **Ignored Games**
   - Mark games you're not interested in anymore
   - Automatically excluded from game picker recommendations
   - Optional reason/notes for each ignored game
   - Per-user settings stored in PostgreSQL

2. **Achievement Hunting**
   - Track achievement hunting sessions per game
   - Set difficulty levels (easy, medium, hard, extreme)
   - Monitor progress with percentage tracking
   - Mark hunts as in-progress, completed, or abandoned

3. **PostgreSQL Database**
   - Persistent storage for all user features
   - Automatic schema creation on startup
   - Fallback support (works without database)
   - Fully SQLAlchemy-based ORM

4. **Shared Ignore Rules (Multi-User)**
   - Games ignored by ALL users in a session are excluded
   - Smart filtering that respects everyone's preferences
   - Database support for tracking multi-user sessions

### 📁 New Files

1. **database.py** (167 lines)
   - SQLAlchemy models for all data types
   - Database initialization and helpers
   - Functions for managing ignored games and achievements

2. **DATABASE_SETUP.md** (280 lines)
   - Complete PostgreSQL setup guide
   - API endpoint documentation
   - Usage examples and troubleshooting

### 🔧 Updated Files

1. **gapi_gui.py** - Added:
   - 6 new API endpoints for ignored games and achievements
   - Database initialization on startup
   - Game picker logic to respect ignored games
   - Fallback support when database unavailable

2. **requirements.txt** - Added:
   - `sqlalchemy>=2.0.0` - ORM framework
   - `psycopg2-binary>=2.9.0` - PostgreSQL driver

### 📡 New API Endpoints

**Ignored Games:**
- `GET /api/ignored-games` - List ignored games
- `POST /api/ignored-games` - Toggle ignore status

**Achievements:**
- `GET /api/achievements` - Get all achievements
- `POST /api/achievement-hunt` - Start tracking hunt
- `PUT /api/achievement-hunt/<hunt_id>` - Update progress

### 🗄️ Database Schema

**Users Table**
- ID, username, platform IDs (Steam/Epic/GOG), role, timestamps

**Ignored Games**
- User ID, app ID, game name, reason, created date

**Achievements**
- User ID, app ID, achievement details, unlock status, rarity

**Achievement Hunts**
- User ID, game, difficulty, progress %, status, timestamps

**Game Library Cache**
- User ID, app ID, platform, playtime, last played

**Multi-User Sessions**
- Session ID, participants list, shared ignore flag

## How It Works

### Game Picking with Ignores
1. User picks a game via `/api/pick`
2. System fetches user's ignored games from database
3. Ignored games added to exclude list
4. Random game picked from remaining games
5. If no games available, error returned

### Multi-User Game Picking
1. Get list of all participants
2. Fetch ignored games for each user
3. Find games ignored by ALL participants
4. Use as shared exclude list
5. Pick from remaining common games

### Achievement Hunt Workflow
1. User starts hunt for a game via `/api/achievement-hunt`
2. Hunt created with difficulty and target count
3. User updates progress via `/api/achievement-hunt/<hunt_id>`
4. Can mark as completed or abandoned
5. Historical data persisted in database

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up PostgreSQL** (see DATABASE_SETUP.md)
   ```bash
   # Create database and user
   psql -U postgres
   CREATE USER gapi WITH PASSWORD 'gapi_password';
   CREATE DATABASE gapi_db OWNER gapi;
   ```

3. **Set environment (optional):**
   ```bash
   export DATABASE_URL="postgresql://gapi:gapi_password@localhost:5432/gapi_db"
   ```

4. **Run app:**
   ```bash
   python gapi_gui.py
   ```
   
Database tables auto-created on startup.

## Fallback Support

If PostgreSQL is not available:
- App runs normally without persistence
- Ignored games/achievements not saved
- Game picker still works with manual excludes
- Perfect for development without database

## Next Steps

### Immediate (Recommended)
- [x] Add UI tabs for "Ignore List" and "Achievements"
- [x] Create quick-ignore buttons in game library
- [x] Show ignored games in separate section

### Short-term
- [x] Sync with actual Steam achievement data via `POST /api/achievements/sync`
- [x] Add Discord bot commands (`/hunt`, `/ignore`)
- [x] Statistics dashboard (completion %, rarity)

## Next Steps

### Immediate (Recommended)
- [x] Add UI tabs for "Ignore List" and "Achievements"
- [x] Create quick-ignore buttons in game library
- [x] Show ignored games in separate section

### Short-term
- [x] Sync with actual Steam achievement data via `POST /api/achievements/sync`
- [x] Add Discord bot commands (`/hunt`, `/ignore`)
- [x] Statistics dashboard (completion %, rarity)

### Medium-term
- [x] Achievement rarity filters in game picker
- [x] Multiplayer achievement challenges
- [x] Backup/export user data
- [x] Achievement statistics by platform

### Recently Completed
- [x] **Mobile App** — React Native application (`mobile-app/`) for iOS and Android.
  Four bottom-tab screens: **Pick** (three modes: Random/Unplayed/Barely Played, game
  card with platform badge + genre chips), **Library** (real-time debounced search,
  platform filter chips, pull-to-refresh FlatList), **History** (recent picks with
  relative timestamps, pull-to-refresh), **Settings** (server URL persisted in
  AsyncStorage, connectivity indicator, open-in-browser link).  Shared
  `ServerConfigContext` provides the GAPI URL + health-check status to every screen.
  `useGapiApi` hook wraps `POST /api/pick`, `GET /api/library`, `GET /api/history`.
  Dark GitHub-dark theme throughout.  Includes Jest formatter tests.

- [x] **Desktop Application** — Electron desktop app (`desktop-app/`) for macOS,
  Windows, and Linux with a **system tray** icon.  Main process (`src/main.js`):
  BrowserWindow, system tray with context menu (Pick a Game / Open Window / Open in
  Browser / Settings / Quit), periodic 30-second health-check with tray badge update,
  desktop notifications via `Notification` API, settings persisted via `electron-store`.
  All IPC through a `contextBridge` preload (`src/preload.js`) that exposes `window.gapiAPI`
  without leaking Node.js.  Renderer (`renderer/index.html` + `renderer.js`): sidebar
  navigation, pick panel (three modes), library panel (search + platform filter), history
  panel, settings panel.  macOS hidden-inset title bar; stays alive in tray when window
  is closed.  Packaged for all platforms via `electron-builder`.  Includes Jest formatter
  tests and full README.
- [x] **PlayStation Network** — `PSNClient` in `platform_clients.py` uses the two-step
  NPSSO→auth-code→token exchange flow.  `POST /api/psn/connect` accepts the user's NPSSO
  token (extracted from the `npsso` browser cookie at `my.playstation.com`), exchanges it
  for an access + refresh token pair, and enables library access via
  `GET /api/psn/library` (paginated `gamelist/v2` API) and
  `GET /api/psn/trophies`.  Automatic token refresh on expiry.
  Config: `psn_enabled`, `psn_npsso`.

- [x] **Nintendo eShop** — `NintendoEShopClient` in `platform_clients.py` wraps Nintendo's
  public Algolia-powered catalog search API (the same backend used by `nintendo.com`).
  Supports multi-region (US/EU/JP), free-text search, filter strings, and paginated results.
  Price data is fetched from the public `api.ec.nintendo.com/v1/price` endpoint.
  Routes: `GET /api/nintendo/search`, `GET /api/nintendo/game/{nsuid}`,
  `GET /api/nintendo/prices`.  Note: no user library API exists for Nintendo — the
  integration is catalog-only.

- [x] **Browser Extension** — Manifest V3 Chrome/Firefox extension in `browser-extension/`.
  Features: toolbar popup with quick-pick UI, three pick modes (Random/Unplayed/Barely
  played), store link opener, badge-based connection status, desktop notifications,
  configurable GAPI server URL via options page, background service worker with periodic
  health-check alarm.

- [x] **Docker / Microservices** — `Dockerfile` (multi-stage, non-root user, HEALTHCHECK),
  `docker-compose.yml` with four services (`gapi-web`, `gapi-db` PostgreSQL 15,
  `gapi-redis` Redis 7, `gapi-nginx` reverse proxy with WebSocket + TLS support),
  `docker-compose.override.yml` for hot-reload development, `nginx/nginx.conf`,
  and updated `.env.example` with all credential placeholders.

- [x] **Video Tutorials** — `TUTORIALS.md` with 12 step-by-step tutorial sections covering
  Steam setup, Web GUI, all platform integrations (Epic/GOG/Xbox/PSN/Nintendo), Smart/ML
  recommendations, Live sessions, playlists/tags/backlog, reviews, Discord bot,
  notifications (Slack/Teams/IFTTT/Home Assistant), browser extension, Docker deployment,
  and admin panel.
- [x] **Epic Games OAuth** — `EpicOAuthClient` in `platform_clients.py` implements the full
  OAuth2 PKCE authorization code flow.  After completing `/api/epic/oauth/authorize` →
  `/api/epic/oauth/callback` the user's Epic library is available at `GET /api/epic/library`.
  Tokens are refreshed automatically.  Configure via `epic_enabled`, `epic_client_id`,
  `epic_client_secret`, `epic_redirect_uri` in `config.json`.
- [x] **GOG Galaxy Integration** — `GOGOAuthClient` implements standard OAuth2 (no PKCE) against
  `auth.gog.com`.  Library fetched from `embed.gog.com/user/data/games`; game details from
  GOG API v2.  Endpoints: `/api/gog/oauth/authorize`, `/api/gog/oauth/callback`,
  `GET /api/gog/library`.  Config: `gog_enabled`, `gog_client_id`, `gog_client_secret`.
- [x] **Xbox Game Pass** — `XboxAPIClient` performs Microsoft Identity MSA token exchange,
  then Xbox Live (XBL) and XSTS authentication, and paginates the `titlehub` API to list
  owned + Game Pass titles.  Endpoints: `/api/xbox/oauth/authorize`,
  `/api/xbox/oauth/callback`, `GET /api/xbox/library`.  Config: `xbox_enabled`,
  `xbox_client_id`, `xbox_client_secret`.  `GET /api/platform/status` reports auth state
  for all four platforms simultaneously.
- [x] **Machine Learning Recommendations** — `MLRecommendationEngine` in
  `app/services/ml_recommendation_service.py` provides three scoring modes:
  * **CF** — item-based collaborative filtering: cosine similarity in genre feature space
  * **MF** — ALS implicit-feedback matrix factorization (pure numpy, no external ML library)
  * **Hybrid** — weighted blend (60% CF + 40% MF)
  Endpoint: `GET /api/recommendations/ml?count=10&method=cf|mf|hybrid`.
  Graceful fallback to heuristic ranker when numpy is unavailable.
- [x] **Smart Recommendations** — `GET /api/recommendations/smart` uses the new
  `SmartRecommendationEngine` which scores games by genre **and** Steam category/tag
  affinity, developer/publisher affinity, Metacritic score, diversity boosting, and
  history penalty.  Richer results than the basic `/api/recommendations` endpoint.
- [x] **Slack/Teams Bots** — `WebhookNotifier` dispatches Block Kit (Slack) and
  Adaptive Card (Microsoft Teams) messages on game pick.  Test endpoints:
  `POST /api/notifications/slack/test` and `POST /api/notifications/teams/test`.
  Configure via `slack_webhook_url` / `teams_webhook_url` in `config.json`.
- [x] **IFTTT Integration** — Maker Webhooks channel support. Fires `value1` (game
  name), `value2` (playtime hours), `value3` (Steam URL) to any IFTTT applet.
  Test via `POST /api/notifications/ifttt/test`.  Configure via `ifttt_webhook_key`
  and `ifttt_event_name` in `config.json`.
- [x] **Home Assistant** — REST API webhook trigger on game pick, including optional
  long-lived access token for authentication.  Test via
  `POST /api/notifications/homeassistant/test`.  Configure via
  `homeassistant_url`, `homeassistant_webhook_id`, `homeassistant_token`.
- [x] **Twitch Integration** — `GET /api/twitch/trending` and `GET /api/twitch/library-overlap`
  cross-reference the user's library against live Twitch trending games.
  Configure via `twitch_client_id` / `twitch_client_secret` in `config.json`
  or the `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` environment variables.
- [x] **Progressive Web App (PWA)** — `manifest.json` + service worker at `/sw.js`
  enable "Add to Home Screen" on mobile/desktop and offline shell caching.
  PWA meta tags added to `index.html`.
- [x] **Interactive Demo** — `python3 demo.py [--quiet]` showcases all major
  features without requiring credentials or a database.
- [x] **CodeQL Security Scanning** — automated weekly security analysis via
  `.github/workflows/codeql.yml` using the `security-extended` query suite.

## Database Operations

### Manual Setup (if auto-init fails)
```python
# In Python shell
from database import init_db
init_db()  # Creates all tables
```

### Verify Connection
```bash
psql -U gapi -W -d gapi_db
\dt  # List all tables
\q  # Exit
```

## Notes

- SQLAlchemy provides database abstraction (could switch to MySQL, PostgreSQL, SQLite later)
- All timestamps in UTC (datetime.utcnow())
- Foreign keys maintain data integrity
- Cascading deletes ensure cleanup
- Connection pooling for better performance

---

See DATABASE_SETUP.md for detailed documentation and troubleshooting!
