# 🚀 Quick Setup Guide

This is a quick reference for setting up GAPI. For detailed documentation, see [README.md](README.md).

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- PostgreSQL 12+ (optional, for production multi-user setup)
- Steam API Key (free from [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey))

## Setup Steps

### 1. Install Dependencies

```bash
# Using the virtual environment that's already set up
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Edit the `.env` file (already created) and add your credentials:

```env
# Required - Get from https://steamcommunity.com/dev/apikey
STEAM_API_KEY=your_steam_api_key_here

# Required - Find yours at https://steamid.io/
STEAM_ID=your_steam_id_here

# Required for production - Generate a random secret string
SECRET_KEY=generate-a-random-secret-key-here

# Database connection (PostgreSQL recommended for production)
DATABASE_URL=postgresql://gapi:change-password@localhost:5432/gapi_db

# Or use SQLite for simple/local setup
# DATABASE_URL=sqlite:///gapi.db
```

### 3. Configure Additional Settings (Optional)

Edit `config.json` for advanced configuration:
- Discord bot token
- Epic Games OAuth credentials
- GOG OAuth credentials
- Webhook URLs for notifications
- And more...

### 4. Set Up Database

**Option A: PostgreSQL (Recommended for Production)**
```bash
# Create database
createdb gapi

# Update DATABASE_URL in .env file
DATABASE_URL=postgresql://your_user:your_password@localhost:5432/gapi
```

**Option B: SQLite (Simple/Local Setup)**
```bash
# Just set this in .env (no server needed)
DATABASE_URL=sqlite:///gapi.db
```

The database schema will be created automatically on first run.

### 5. Run GAPI

**Web GUI (Recommended):**
```bash
python gapi_gui.py
```
Then open http://127.0.0.1:5000

**CLI Mode:**
```bash
python gapi.py
```

**Discord Bot:**
```bash
python discord_bot.py
```

### 6. First Time Setup (Web GUI)

1. Navigate to http://127.0.0.1:5000
2. Click **Register** and create an account
3. Log in with your credentials
4. Go to **Settings** tab
5. Add your Steam ID (and optionally Epic/GOG IDs)
6. Click **Sync Library**
7. Start picking games!

## Docker Setup (Alternative)

```bash
# Set your Steam API key
export STEAM_API_KEY=your_api_key

# Start services
docker-compose up -d

# Access at http://localhost:5000
```

## Troubleshooting

### "No games found"
- ✅ Verify your Steam API key is correct in `.env`
- ✅ Check your Steam ID format (17-digit number)
- ✅ Ensure your Steam profile is set to **Public**

### "Module not found"
- ✅ Make sure you're in the virtual environment: `.venv\Scripts\Activate.ps1`
- ✅ Reinstall dependencies: `pip install -r requirements.txt`

### Database connection errors
- ✅ Check DATABASE_URL is correctly set in `.env`
- ✅ For PostgreSQL, ensure the database exists
- ✅ Try SQLite for simpler setup: `DATABASE_URL=sqlite:///gapi.db`

## Next Steps

- 📖 Read the full [README.md](README.md) for detailed feature documentation
- 🔧 Check [TROUBLESHOOTING.md](README.md#-troubleshooting) for common issues
- 🤝 See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
- 📚 Read [TUTORIALS.md](TUTORIALS.md) for advanced usage guides

## Quick Commands Reference

```bash
# Web GUI
python gapi_gui.py

# CLI - Interactive
python gapi.py

# CLI - Quick pick
python gapi.py --random

# CLI - Pick unplayed game
python gapi.py --unplayed

# CLI - Filter by genre
python gapi.py --genre "Action,RPG"

# CLI - Show library stats
python gapi.py --stats

# Discord Bot
python discord_bot.py
```

## Support

- 🐛 [Report Issues](https://github.com/mattam1234/GAPI/issues)
- 💡 [Request Features](https://github.com/mattam1234/GAPI/issues)
- 📖 [Full Documentation](README.md)
