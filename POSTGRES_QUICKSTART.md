# GAPI PostgreSQL Quick Start Guide

Follow these steps to get your GAPI application running with PostgreSQL instead of Docker or SQLite.

## ⏱️ Estimated Time: 15-30 minutes

## Prerequisites

- Windows 10/11
- Admin access to install PostgreSQL
- Python 3.8+ (you already have this)
- GAPI repository cloned

---

## 🚀 Quick Start (5 Easy Steps)

### Step 1: Install PostgreSQL (5 minutes)

1. Go to: https://www.postgresql.org/download/windows/
2. Click **"Download" → "Windows"**
3. Download the latest installer (PostgreSQL 15 or newer)
4. Run the installer:
   - Accept defaults
   - **Remember your superuser password!** (e.g., `postgres_admin_2026`)
   - Port: 5432
   - Locale: Leave default
5. PostgreSQL service starts automatically

✅ Done! PostgreSQL is installed.

---

### Step 2: Run Automated Setup (3 minutes)

Open **PowerShell** in your GAPI directory and run:

```powershell
# Activate your virtual environment
& .\.venv\Scripts\Activate.ps1

# Run the automated setup
python setup_postgres.py
```

The script will:
- Find PostgreSQL installation
- Ask for your PostgreSQL superuser password
- Create GAPI user and database
- Update `.env` and `config.json`
- Test the connection

**Total time: ~1-2 minutes**

✅ Done! Database created and configured.

---

### Step 3: Initialize Database Schema (1 minute)

```powershell
# Should already be activated from previous step
python initialize_db.py
```

This creates all the tables GAPI needs:
- users, roles, favorite_games, ignored_games, achievements, etc.

✅ Done! Schema is ready.

---

### Step 4: Verify Everything Works (2 minutes)

```powershell
python check_postgres.py
```

You should see:
- ✅ Connection successful
- ✅ Found X tables
- ✅ PostgreSQL version info

If anything fails, this script will tell you exactly what's wrong.

✅ Done! Everything is verified.

---

### Step 5: Start GAPI (Ongoing)

```powershell
python gapi.py
```

Watch the logs for:
```
[INFO] Database connected to: postgresql://...
[INFO] Starting GAPI server...
[INFO] Listening on http://localhost:5000
```

✅ Done! GAPI is running with PostgreSQL!

---

## 📋 Configuration Reference

### Environment Variables (.env)

```dotenv
# PostgreSQL database connection
DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db

# Other settings...
STEAM_API_KEY=...
DISCORD_BOT_TOKEN=...
SECRET_KEY=...
```

### Config File (config.json)

```json
{
  "database_url": "postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db",
  "steam_api_key": "...",
  ...
}
```

---

## 🔧 Management Commands

### Check Health
```powershell
python check_postgres.py
```

### View Database
Open pgAdmin (included with PostgreSQL):
- Search for "pgAdmin" in Windows Start Menu
- Server: localhost
- User: gapi
- Password: gapi_password_secure
- Database: gapi_db

### Backup Database
```powershell
# In PowerShell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe" -U gapi -h localhost gapi_db > backup_$(Get-Date -f 'yyyyMMdd').sql
```

### Restore Backup
```powershell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -h localhost gapi_db < backup_20260303.sql
```

---

## ❌ Troubleshooting

### "PostgreSQL not found"
- Download from: https://www.postgresql.org/download/windows/
- Run installer
- Restart this script

### "FATAL: password authentication failed"
- Check the password you entered in `setup_postgres.py`
- Update DATABASE_URL in `.env` with correct password
- Password is case-sensitive!

### "Database already exists" warning
- This is normal! You can safely ignore it
- Database was already created on previous run

### "Connection refused on port 5432"
- PostgreSQL service might not be running
- Open Services app (Windows Key + R, type `services.msc`)
- Find "postgresql-x64-15" and click "Start"

### "Cannot find psql.exe"
- PostgreSQL might not be fully installed
- Reinstall from: https://www.postgresql.org/download/windows/

### GAPI still using SQLite
- Check your `.env` file: `DATABASE_URL=sqlite:...` ?
- Should be: `DATABASE_URL=postgresql://...`
- Restart GAPI after changing

---

## 📊 Database Schema

These tables are automatically created:

| Table | Purpose |
|-------|---------|
| **users** | User accounts & auth |
| **roles** | User roles/permissions |
| **favorite_games** | Bookmarked games |
| **ignored_games** | Games to exclude |
| **achievements** | Achievement tracking |
| **achievement_hunts** | Hunt sessions |
| **achievement_challenges** | Multiplayer challenges |
| **game_library_cache** | Cached game data |

---

## 🔐 Security Notes

### Change Default Password

If you used the default password during setup, change it:

```powershell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -h localhost gapi_db
```

In psql shell:
```sql
ALTER USER gapi WITH PASSWORD 'your_strong_new_password';
\q
```

Then update `.env` and `config.json` with the new password.

### Regular Backups

Set Windows Task Scheduler to backup daily:
```powershell
# Example: Daily backup at 2 AM
$action = New-ScheduledTaskAction -Execute "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe" `
  -Argument '-U gapi -d gapi_db > C:\GAPI\backups\db_$(Get-Date -f yyyyMMdd).sql'
```

---

## ✨ Next Steps

Now that PostgreSQL is set up:

1. ✅ Create user accounts through GAPI web interface
2. 📱 Link Discord accounts (bot will ask for Steam ID)
3. 🎮 Link Steam accounts for game library access
4. 🗳️ Start using voting/game picking features
5. 💾 Set up regular database backups

---

## 📖 Full Documentation

For more details:
- See [POSTGRES_SETUP_GUIDE.md](POSTGRES_SETUP_GUIDE.md) for comprehensive guide
- See [DATABASE_SETUP.md](DATABASE_SETUP.md) for feature details
- PostgreSQL docs: https://www.postgresql.org/docs/

---

## 💬 Need Help?

1. Run the health check: `python check_postgres.py`
2. Check PostgreSQL logs:
   ```
   C:\Program Files\PostgreSQL\15\data\log\
   ```
3. Verify `.env` and `config.json` settings
4. Test connection manually:
   ```
   C:\Program Files\PostgreSQL\15\bin\psql -U gapi -d gapi_db
   ```

---

**Version:** March 2026  
**Compatible with:** PostgreSQL 14+, GAPI v9+  
**Status:** ✅ Production Ready
