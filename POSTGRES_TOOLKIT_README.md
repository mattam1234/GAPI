# PostgreSQL Setup for GAPI - Complete Toolkit

I've created a complete toolkit to help you set up and manage PostgreSQL for your GAPI application. Here's what you have:

## 📚 Documentation Files

### 1. **POSTGRES_QUICKSTART.md** ⭐ START HERE
   - **5-step quick start guide**
   - Estimated time: 15-30 minutes
   - Perfect for getting up and running fast
   - Includes troubleshooting section

### 2. **POSTGRES_SETUP_GUIDE.md**
   - Comprehensive setup guide
   - Detailed PostgreSQL installation on Windows
   - Advanced configuration options
   - Database management commands
   - Backup and restore procedures
   - pgAdmin GUI tool guide

## 🛠️ Automation Scripts

### Setup Scripts (Run these in order)

#### **setup_postgres.py** (Automated Setup)
```powershell
python setup_postgres.py
```
- Automatically finds PostgreSQL installation
- Creates database user: `gapi`
- Creates database: `gapi_db`
- Updates `.env` and `config.json` automatically
- Tests the connection
- **Time: ~1-2 minutes**

#### **initialize_db.py** (Create Schema)
```powershell
python initialize_db.py
```
- Creates all database tables
- Sets up schema relationships
- Verifies table creation
- Safe to run multiple times
- **Time: ~30 seconds**

#### **test_postgres.py** (Verify Operations)
```powershell
python test_postgres.py
```
- Tests CREATE, READ, UPDATE, DELETE operations
- Creates and deletes test user
- Verifies relationships work
- Shows database statistics
- **Time: ~30 seconds**

### Management Scripts (Use anytime)

#### **check_postgres.py** (Health Check)
```powershell
python check_postgres.py
```
- Checks PostgreSQL configuration
- Verifies connection
- Lists all tables
- Shows user count
- Diagnoses problems
- **Run this when troubleshooting**

#### **migrate_to_postgres.py** (Data Migration)
```powershell
python migrate_to_postgres.py
```
- Migrates data from SQLite to PostgreSQL
- Creates automatic backup before migration
- Verifies migration success
- **Only needed if you have existing SQLite data**

## 🚀 Quick Start Workflow

Follow these 5 steps in order:

### Step 1: Install PostgreSQL
- Download from: https://www.postgresql.org/download/windows/
- Run installer
- Keep your superuser password safe

### Step 2: Run Setup Script
```powershell
& .\.venv\Scripts\Activate.ps1
python setup_postgres.py
```
- Provide PostgreSQL superuser password
- Script creates user, database, and updates config

### Step 3: Initialize Schema
```powershell
python initialize_db.py
```
- Creates all tables
- Verifies tables exist

### Step 4: Test Database
```powershell
python test_postgres.py
```
- Tests all CRUD operations
- Confirms everything works

### Step 5: Start GAPI
```powershell
python gapi.py
```
- Watch logs for: "Database connected to: postgresql://..."
- Access GAPI at: http://localhost:5000

## 🔍 Troubleshooting Workflow

If something doesn't work:

1. **First check:** Run health check
   ```powershell
   python check_postgres.py
   ```

2. **Common issues:**
   - PostgreSQL not installed? Download and install
   - Wrong password? Re-run `setup_postgres.py`
   - Connection refused? Check PostgreSQL service is running
   - Still using SQLite? Check `.env` DATABASE_URL setting

3. **Get detailed logs:**
   ```
   C:\Program Files\PostgreSQL\15\data\log\postgresql-*.log
   ```

4. **Test manually:**
   ```powershell
   $env:PGPASSWORD = "gapi_password_secure"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -d gapi_db
   ```

## 📋 File Reference

```
GAPI/
├── POSTGRES_QUICKSTART.md          ← Start here (5-step guide)
├── POSTGRES_SETUP_GUIDE.md         ← Detailed guide
├── setup_postgres.py               ← Create database (automated)
├── initialize_db.py                ← Create schema
├── test_postgres.py                ← Verify everything works
├── check_postgres.py               ← Health check (troubleshooting)
├── migrate_to_postgres.py          ← Migrate data from SQLite
├── .env                            ← Configuration (DATABASE_URL)
├── config.json                     ← Alternative config
└── database.py                     ← ORM models (don't edit)
```

## ⚙️ Configuration

### .env Format
```dotenv
DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db
```

### config.json Format
```json
{
  "database_url": "postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db"
}
```

Both are checked, `.env` takes precedence.

## 🛡️ Security Considerations

1. **Change default password after setup:**
   ```sql
   ALTER USER gapi WITH PASSWORD 'your_strong_new_password';
   ```

2. **Set secure SECRET_KEY in .env:**
   ```dotenv
   SECRET_KEY=some-random-secure-string-here
   ```

3. **PostgreSQL only listens on localhost by default** (secure)

4. **Regular backups:**
   ```powershell
   python backup_postgres.py  # (if available)
   ```

5. **Restrict database access in production**

## 📊 Database Tables

Automatically created:
- `users` - User accounts
- `roles` - Authorization roles  
- `favorite_games` - Bookmarks
- `ignored_games` - Exclusions
- `achievements` - Progress tracking
- `achievement_hunts` - Hunt sessions
- `achievement_challenges` - Group challenges
- `game_library_cache` - Game data cache

## 💡 Pro Tips

1. **Use pgAdmin for visual database management:**
   - Search Windows Start Menu for "pgAdmin 4"
   - Easy table browser and query tool

2. **Backup before major changes:**
   ```powershell
   pg_dump -U gapi gapi_db > backup.sql
   ```

3. **Monitor PostgreSQL logs:**
   ```powershell
   tail -f "C:\Program Files\PostgreSQL\15\data\log\*"
   ```

4. **Check current connections:**
   ```sql
   SELECT pid, usename, application_name, state 
   FROM pg_stat_activity;
   ```

## 🆘 Support

1. **If scripts fail:**
   - Check PostgreSQL is installed: https://www.postgresql.org/download/windows/
   - Run `check_postgres.py` for diagnostics
   - Check PostgreSQL logs in `C:\Program Files\PostgreSQL\15\data\log\`

2. **Common error messages:**
   - "psql: command not found" → Add PostgreSQL to PATH
   - "password authentication failed" → Wrong password in `.env`
   - "FATAL: database doesn't exist" → Run `setup_postgres.py`
   - "Connection refused" → PostgreSQL service not running

3. **Test connection manually:**
   ```powershell
   PSQLPath = "C:\Program Files\PostgreSQL\15\bin\psql.exe"
   & $PSQLPath -U gapi -h localhost -d gapi_db -c "SELECT 1;"
   ```

## 📈 Performance

PostgreSQL offers better performance than SQLite for GAPI because:
- ✅ Multi-user concurrent access
- ✅ Better query optimization
- ✅ Connection pooling
- ✅ Built-in backups
- ✅ Advanced indexing
- ✅ Production-ready

## 🎯 Next Steps After Setup

1. Create user accounts through GAPI web interface
2. Link Discord accounts (ask for Steam ID)
3. Add game libraries from Steam, Epic, GOG, etc.
4. Use voting features
5. Set up backups
6. Monitor performance with `check_postgres.py`

## 📞 Questions?

Check files in this order:
1. POSTGRES_QUICKSTART.md - Quick answers
2. POSTGRES_SETUP_GUIDE.md - Detailed info
3. Run `check_postgres.py` - Diagnose issues
4. PostgreSQL logs - Technical details

---

**Version:** March 2026  
**Status:** ✅ Ready to Use  
**PostgreSQL:** 14+ supported  
**Python:** 3.8+
