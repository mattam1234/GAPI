# PostgreSQL Setup Guide for GAPI

This guide walks you through setting up a PostgreSQL database for GAPI instead of using Docker or SQLite.

## Prerequisites

- Windows 10/11 with admin access
- PostgreSQL 15+ installed
- Python 3.8+ (already have this for GAPI)

## Step 1: Install PostgreSQL on Windows

### Option A: Using PostgreSQL Installer (Recommended)

1. **Download PostgreSQL**
   - Go to: https://www.postgresql.org/download/windows/
   - Download PostgreSQL 15+ installer

2. **Run the Installer**
   - Execute the downloaded `.exe` file
   - Follow the installation wizard:
     - **Installation Directory**: Keep default (`C:\Program Files\PostgreSQL\15`)
     - **Select Components**: Keep all selected
     - **Data Directory**: Keep default
     - **Superuser Password**: Set a strong password (e.g., `postgres_admin_2026`)
     - **Port**: Keep default (`5432`)
     - **Locale**: Select your language

3. **Finish Installation**
   - PostgreSQL service will start automatically
   - pgAdmin 4 (GUI tool) will open

### Option B: Using PostgreSQL Windows Installer (Easier)

1. Use the "One Click Installer":
   ```
   https://www.postgresql.org/download/windows/
   → Interactive installer by EDB
   ```

2. Follow the setup wizard (same steps as Option A)

## Step 2: Create GAPI Database and User

Open **PowerShell** as Administrator and run:

```powershell
# Connect to PostgreSQL (replace 'password' with your superuser password)
$env:PGPASSWORD = "postgres_admin_2026"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -h localhost

# You should see: postgres=#
```

Then run these SQL commands in psql:

```sql
-- Create GAPI user
CREATE USER gapi WITH PASSWORD 'gapi_password_secure';

-- Create GAPI database
CREATE DATABASE gapi_db OWNER gapi;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE gapi_db TO gapi;

-- Exit
\q
```

**Or use the automated script** (see Step 3).

## Step 3: Automated Setup (Recommended)

Run the automated setup script to create the database and user:

```powershell
# In your GAPI directory
python setup_postgres.py
```

The script will:
- Check PostgreSQL installation
- Create the `gapi` user
- Create the `gapi_db` database
- Set up proper permissions
- Initialize the schema

## Step 4: Configure GAPI to Use PostgreSQL

Edit your `.env` file:

```dotenv
# Change from SQLite to PostgreSQL
DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db

# Keep your other settings...
STEAM_API_KEY=...
STEAM_ID=...
SECRET_KEY=...
```

Or edit `config.json`:

```json
{
  "database_url": "postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db",
  "steam_api_key": "...",
  ...
}
```

## Step 5: Initialize Database Schema

The database tables are created automatically when you start GAPI for the first time with PostgreSQL configured.

To manually initialize the schema:

```powershell
# Activate your virtual environment
& .\.venv\Scripts\Activate.ps1

# Run the initialization script
python initialize_db.py
```

## Step 6: Verify PostgreSQL Connection

Test the connection:

```powershell
# From PowerShell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -h localhost -d gapi_db -c "SELECT version();"
```

You should see the PostgreSQL version output if the connection works.

## Step 7: Start GAPI with PostgreSQL

```powershell
# Activate virtual environment
& .\.venv\Scripts\Activate.ps1

# Start GAPI
python gapi.py
```

Check the logs for successful database connection:
```
[INFO] Database connected to: postgresql://gapi:***@localhost:5432/gapi_db
[INFO] Tables created: users, roles, favorite_games, ignored_games, achievements, ...
```

## Migrating from SQLite to PostgreSQL

If you have existing data in SQLite (`gapi.db`), run:

```powershell
python migrate_to_postgres.py
```

This will:
1. Read all data from SQLite
2. Import it into PostgreSQL
3. Verify the migration
4. Create a backup of your SQLite database

## Troubleshooting

### Error: "psql: command not found"

Add PostgreSQL to PATH:
```powershell
$env:Path += ";C:\Program Files\PostgreSQL\15\bin"
```

Or use full path:
```powershell
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" ...
```

### Error: "FATAL: Ident authentication failed"

Update PostgreSQL authentication. Edit `C:\Program Files\PostgreSQL\15\data\pg_hba.conf`:
- Change `ident` to `md5` or `scram-sha-256`
- Restart PostgreSQL service

### Connection refused on port 5432

PostgreSQL service is not running:
```powershell
# Check service status
Get-Service postgresql-x64-15

# Start service if stopped
Start-Service postgresql-x64-15
```

### Error: database "gapi_db" does not exist

Run the setup script again or manually create the database:
```bash
createdb -U postgres -O gapi gapi_db
```

## PostgreSQL Management

### View PostgreSQL Logs

```powershell
Get-Content "C:\Program Files\PostgreSQL\15\data\log\postgresql-*.log" -Tail 50
```

### Backup Database

```powershell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe" -U gapi -h localhost gapi_db > gapi_backup.sql
```

### Restore Database

```powershell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -h localhost gapi_db < gapi_backup.sql
```

### Connect with GUI (pgAdmin)

1. Open pgAdmin 4 (installed with PostgreSQL)
2. Right-click "Servers" → "Register" → "Server"
3. **General tab**:
   - Name: `GAPI DB`
4. **Connection tab**:
   - Host: `localhost`
   - Port: `5432`
   - Username: `gapi`
   - Password: `gapi_password_secure`
5. Click "Save"

## Database Schema

GAPI uses these tables:
- `users` - User accounts and authentication
- `roles` - User roles/permissions
- `user_roles` - User to role mapping
- `favorite_games` - User favorite games
- `ignored_games` - Games user wants to skip
- `achievements` - Achievement tracking
- `achievement_hunts` - Achievement hunting sessions
- `achievement_challenges` - Multiplayer challenges
- `challenge_participants` - Challenge participation tracking
- `game_library_cache` - Cached game library data

All tables are created automatically by SQLAlchemy on first run.

## Next Steps

1. ✅ Install PostgreSQL
2. ✅ Create database and user
3. ✅ Configure GAPI
4. ✅ Start GAPI and verify connection
5. 📊 (Optional) Migrate existing data from SQLite
6. 🔄 Set up regular backups

## Security Notes

- Change the default password: `gapi_password_secure`
- Use strong passwords in production
- Enable PostgreSQL SSL for remote connections
- Regularly backup your database
- Restrict network access to port 5432

## Getting Help

If you encounter issues:
1. Check PostgreSQL logs: `C:\Program Files\PostgreSQL\15\data\log\`
2. Test connection: `psql -U gapi -h localhost -d gapi_db`
3. Check `.env` and `config.json` settings
4. Verify PostgreSQL service is running
