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
