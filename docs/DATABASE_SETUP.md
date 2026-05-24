# GAPI Advanced Features - Setup Guide

This guide explains how to set up and use the new achievement hunting and ignore features with PostgreSQL support.

## Features Added

### 1. **Ignored Games** 
Users can mark games they're not interested in anymore. These games will be excluded from game picking suggestions.

### 2. **Achievement Hunting**
Track achievement hunting sessions for specific games with difficulty levels and progress tracking.

### 3. **PostgreSQL Database Support**
Persistent storage for user preferences, ignored games, and achievement data.

### 4. **Shared Ignore Rules (Multi-User)**
In multi-user game picking sessions, if all participants have marked a game as ignored, it will be excluded from recommendations.

## Installation

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Set Up PostgreSQL Database

#### Option A: Local PostgreSQL (Recommended for Development)

1. **Install PostgreSQL** (if not already installed)
   - Windows: https://www.postgresql.org/download/windows/
   - macOS: `brew install postgresql@15`
   - Linux: `sudo apt install postgresql postgresql-contrib`

2. **Start PostgreSQL service**
   ```bash
   # Windows (if installed as a service)
   # Service should start automatically
   
   # macOS
   brew services start postgresql@15
   
   # Linux
   sudo systemctl start postgresql
   ```

3. **Create database and user**
   ```bash
   # Connect to PostgreSQL as default user
   psql -U postgres
   
   # In psql shell, run:
   CREATE USER gapi WITH PASSWORD 'gapi_password';
   CREATE DATABASE gapi_db OWNER gapi;
   GRANT ALL PRIVILEGES ON DATABASE gapi_db TO gapi;
   \q
   ```

4. **Set environment variable** (optional, defaults to localhost)
   ```bash
   # Windows PowerShell
   $env:DATABASE_URL = "postgresql://gapi:gapi_password@localhost:5432/gapi_db"
   
   # Linux/macOS bash
   export DATABASE_URL="postgresql://gapi:gapi_password@localhost:5432/gapi_db"
   ```

#### Option B: Docker PostgreSQL

```bash
docker run -d \
  --name gapi-postgres \
  -e POSTGRES_USER=gapi \
  -e POSTGRES_PASSWORD=gapi_password \
  -e POSTGRES_DB=gapi_db \
  -p 5432:5432 \
  postgres:15
```

### Step 3: Initialize Database

The database tables are created automatically on first run. Verify the connection works by checking the Flask startup logs.

## API Endpoints

### Ignored Games

**GET /api/ignored-games**
- Get list of games the current user has ignored
- Returns: `{ignored_games: [{app_id, game_name, reason, created_at}, ...]}`

**POST /api/ignored-games**
- Toggle game ignore status
- Body: `{app_id, game_name, reason}`
- Returns: Success/error message

### Achievements

**GET /api/achievements**
- Get achievements for current user (grouped by game)
- Returns: `{achievements: [{app_id, game_name, achievements: [...]}, ...]}`

**POST /api/achievement-hunt**
- Start tracking an achievement hunting session
- Body: `{app_id, game_name, difficulty, target_achievements}`
- Difficulty: 'easy', 'medium', 'hard', 'extreme'
- Returns: Created hunt object with hunt_id

**PUT /api/achievement-hunt/<hunt_id>**
- Update achievement hunt progress
- Body: `{unlocked_achievements, status}`
- Status: 'in_progress', 'completed', 'abandoned'
- Returns: Updated hunt object

## Game Picking Logic

When picking a game:

1. **Single-User Mode**: Ignored games are automatically excluded
2. **Multi-User Mode**: Only games ignored by ALL participants are excluded (shared ignore rules)
3. **Database Fallback**: If database is unavailable, all games are considered

## Discord Bot Integration

The Discord bot will respect ignore rules when:
- All users in a voting session have ignored the same game
- The game picker recommends games for group sessions

## Usage Examples

### Mark a Game as Ignored

```javascript
// In browser console
fetch('/api/ignored-games', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    app_id: '620',
    game_name: 'Portal 2',
    reason: 'Already completed'
  })
}).then(r => r.json()).then(console.log);
```

### Start Achievement Hunt

```javascript
fetch('/api/achievement-hunt', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    app_id: '12900',
    game_name: 'Deus Ex',
    difficulty: 'hard',
    target_achievements: 36
  })
}).then(r => r.json()).then(hunt => {
  console.log('Hunt started with ID:', hunt.hunt_id);
});
```

### Update Progress

```javascript
fetch(`/api/achievement-hunt/${hunt_id}`, {
  method: 'PUT',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    unlocked_achievements: 12,
    status: 'in_progress'
  })
}).then(r => r.json()).then(console.log);
```

## Database Schema

See `database.py` for complete schema. Key tables:

- **users**: User accounts with platform IDs
- **ignored_games**: Games marked as ignored per user
- **achievements**: Achievement data
- **achievement_hunts**: Active/completed achievement hunt sessions
- **game_library_cache**: Cached game library data
- **multiuser_sessions**: Multi-user session tracking

## Troubleshooting

### "Database not available" error
- Ensure PostgreSQL is running
- Check DATABASE_URL environment variable
- Verify database credentials
- Check network connectivity

### Games still not loading
- Check Flask logs for database errors
- Verify user exists in database
- Try clearing browser cache and logging in again

### Ignored games still showing up
- Ensure database connection is active
- Check that app_id matches exactly (String type)
- Verify user is logged in and has permission

## Next Steps

1. **UI Implementation**: Add ignore/achievement tabs to web interface
2. **Steam API Integration**: Fetch real achievement data from Steam
3. **Discord Bot Commands**: Add commands like `/hunt start`, `/ignore add`
4. **Statistics Dashboard**: Show achievement/completion stats per user
5. **Backup & Export**: Allow users to export their game data

## Support

For issues:
1. Check Flask server logs
2. Verify PostgreSQL connection
3. Ensure all dependencies installed: `pip install -r requirements.txt`
4. Check database schema created: `database.init_db()`
