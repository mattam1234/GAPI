# PostgreSQL Troubleshooting Guide for GAPI

Quick solutions to common PostgreSQL setup issues.

## ❌ Common Issues & Solutions

### Issue 1: "PostgreSQL not found" or "psql: command not found"

**Symptoms:**
```
Error: PostgreSQL not found. Please install PostgreSQL first.
```

**Causes:**
- PostgreSQL not installed
- Installation path not found
- PATH not updated

**Solutions:**

1. **Check if PostgreSQL is installed:**
   ```powershell
   Test-Path "C:\Program Files\PostgreSQL\15"
   ```

2. **If not installed, download it:**
   - Go to: https://www.postgresql.org/download/windows/
   - Download the latest installer
   - Run and follow the installation wizard
   - Remember the superuser password!

3. **If installed but `psql` command fails:**
   ```powershell
   # Add PostgreSQL to PATH
   $env:Path += ";C:\Program Files\PostgreSQL\15\bin"
   
   # Verify it works
   psql --version
   ```

4. **Add to PATH permanently (Windows):**
   - Windows Key + X → System
   - Advanced system settings
   - Environment Variables
   - Add `C:\Program Files\PostgreSQL\15\bin` to PATH
   - Restart PowerShell

---

### Issue 2: "FATAL: password authentication failed"

**Symptoms:**
```
FATAL:  password authentication failed for user "gapi"
FATAL:  Ident authentication failed for user "gapi"
```

**Causes:**
- Wrong password in `.env`
- Wrong password in `config.json`
- Database user doesn't exist
- PostgreSQL ident authentication enabled

**Solutions:**

1. **Verify the password in .env:**
   ```powershell
   Get-Content .env | Select-String "DATABASE_URL"
   ```
   
   Should look like:
   ```
   DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db
   ```

2. **Re-run setup to confirm user and password:**
   ```powershell
   python setup_postgres.py
   ```

3. **Manually reset the password:**
   ```powershell
   $env:PGPASSWORD = "postgres_admin_password"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -h localhost
   ```
   
   In psql shell:
   ```sql
   ALTER USER gapi WITH PASSWORD 'gapi_password_secure';
   \q
   ```
   
   Then update `.env`:
   ```dotenv
   DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db
   ```

4. **Check PostgreSQL authentication method:**
   Edit: `C:\Program Files\PostgreSQL\15\data\pg_hba.conf`
   
   Change this line:
   ```
   local   all             all                                     ident
   ```
   To:
   ```
   local   all             all                                     md5
   ```
   
   Then restart PostgreSQL service.

---

### Issue 3: "Connection refused on port 5432"

**Symptoms:**
```
Error: Connection refused
FATAL: could not connect to server: No such file or directory
```

**Causes:**
- PostgreSQL service not running
- PostgreSQL crashed
- Wrong server address/port
- Windows Firewall blocking connection

**Solutions:**

1. **Check if service is running:**
   ```powershell
   Get-Service postgresql-x64-15 | Select Status
   ```

2. **Start the service:**
   ```powershell
   Start-Service postgresql-x64-15
   ```

3. **Check if listening on port 5432:**
   ```powershell
   netstat -ano | Select-String ":5432"
   ```

4. **Check Windows Firewall:**
   - Windows Defender Firewall → Allow an app
   - Make sure PostgreSQL is allowed
   - Or: `netsh advfirewall firewall add rule name="PostgreSQL" dir=in action=allow program="C:\Program Files\PostgreSQL\15\bin\postgres.exe"`

5. **Check PostgreSQL logs:**
   ```powershell
   Get-Content "C:\Program Files\PostgreSQL\15\data\log\*.log" -Tail 20
   ```

6. **Verify connection string:**
   Should be: `localhost:5432` or `127.0.0.1:5432`
   
   Not: `192.168.x.x` or domain names (unless configured)

---

### Issue 4: "Database 'gapi_db' does not exist"

**Symptoms:**
```
FATAL:  database "gapi_db" does not exist
```

**Causes:**
- Database not created
- Wrong database name in CONNECTION string
- Created in different user's cluster

**Solutions:**

1. **Check if database exists:**
   ```powershell
   $env:PGPASSWORD = "postgres_admin_password"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -c "\l"
   ```
   
   Look for `gapi_db` in the list.

2. **If not in list, create it:**
   ```powershell
   python setup_postgres.py
   ```
   
   Or manually:
   ```sql
   CREATE DATABASE gapi_db OWNER gapi;
   ```

3. **Verify database name in .env:**
   Should be: `postgresql://gapi:password@localhost:5432/gapi_db`
   
   Not: `gapi_database`, `gapi`, or other names.

---

### Issue 5: "Role 'gapi' does not exist"

**Symptoms:**
```
FATAL:  role "gapi" does not exist
```

**Causes:**
- User not created
- User created in different cluster
- User deleted accidentally

**Solutions:**

1. **Check if user exists:**
   ```powershell
   $env:PGPASSWORD = "postgres_admin_password"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -c "\du"
   ```

2. **Create user if missing:**
   ```powershell
   python setup_postgres.py
   ```
   
   Or manually:
   ```sql
   CREATE USER gapi WITH PASSWORD 'gapi_password_secure';
   GRANT ALL PRIVILEGES ON DATABASE gapi_db TO gapi;
   ```

3. **Verify user name in .env:**
   Should be: `postgresql://gapi:...`
   
   Not: `postgres`, `gapi_user`, or other names.

---

### Issue 6: "GAPI still using SQLite"

**Symptoms:**
- Logs show: "Using SQLite..."
- Changes not reflected in GAPI
- Getting `gapi.db` file instead of PostgreSQL

**Causes:**
- `DATABASE_URL` is still pointing to SQLite
- `.env` not read correctly
- `config.json` still has SQLite setting

**Solutions:**

1. **Check .env:**
   ```powershell
   Get-Content .env | Select-String DATABASE_URL
   ```
   
   Should show: `postgresql://...` not `sqlite://...`

2. **Update .env:**
   ```dotenv
   # Wrong:
   DATABASE_URL=sqlite:///gapi.db
   
   # Correct:
   DATABASE_URL=postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db
   ```

3. **Also update config.json:**
   ```json
   {
     "database_url": "postgresql://gapi:gapi_password_secure@localhost:5432/gapi_db"
   }
   ```

4. **Restart GAPI:**
   ```powershell
   # Stop current GAPI (Ctrl+C)
   # Restart:
   python gapi.py
   ```
   
   Check logs for: `Database connected to: postgresql://...`

---

### Issue 7: "TimeoutError: Could not connect to PostgreSQL"

**Symptoms:**
```
TimeoutError: Could not connect to server after 10 seconds
```

**Causes:**
- Network timeout
- Server is slow/hung
- Firewall blocking connection
- PostgreSQL crashed

**Solutions:**

1. **Check if PostgreSQL is responsive:**
   ```powershell
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -c "SELECT 1;" -t 10
   ```

2. **Check server load:**
   ```powershell
   Get-Process postgres | Measure-Object
   ```

3. **Restart PostgreSQL service:**
   ```powershell
   Restart-Service postgresql-x64-15
   ```

4. **Check PostgreSQL logs for errors:**
   ```powershell
   tail -f "C:\Program Files\PostgreSQL\15\data\log\postgresql-*.log"
   ```

5. **Increase timeout value:**
   
   In `database.py`, modify:
   ```python
   engine = create_engine(DATABASE_URL, connect_args={"timeout": 30})
   ```

---

### Issue 8: "permission denied" or "Access denied"

**Symptoms:**
```
ERROR: permission denied for database "gapi_db"
ERROR: permission denied for schema public
```

**Causes:**
- User doesn't have required privileges
- Database owner is different user
- Privileges revoked accidentally

**Solutions:**

1. **Grant all privileges:**
   ```powershell
   $env:PGPASSWORD = "postgres_admin_password"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -d gapi_db
   ```
   
   In psql:
   ```sql
   GRANT ALL PRIVILEGES ON DATABASE gapi_db TO gapi;
   GRANT ALL PRIVILEGES ON SCHEMA public TO gapi;
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO gapi;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gapi;
   \q
   ```

2. **Check current privileges:**
   ```sql
   \dp
   \l
   ```

---

### Issue 9: "Tables not found" or "No tables created"

**Symptoms:**
```
❌ No tables found!
Run: python initialize_db.py
```

**Causes:**
- Schema not initialized
- `initialize_db.py` failed
- Wrong database

**Solutions:**

1. **Initialize schema:**
   ```powershell
   python initialize_db.py
   ```

2. **Check for errors:**
   ```powershell
   python initialize_db.py 2>&1 | Tee-Object output.log
   ```

3. **Verify database is correct:**
   ```powershell
   $env:PGPASSWORD = "gapi_password_secure"
   & "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -d gapi_db -c "\dt"
   ```

4. **If still failing:**
   ```powershell
   python setup_postgres.py  # Recreate everything
   python initialize_db.py    # Initialize schema
   python check_postgres.py   # Verify
   ```

---

### Issue 10: "Virtual environment not activated"

**Symptoms:**
```
'python' is not recognized as an internal or external command
```

**Causes:**
- Python virtual environment not activated
- Wrong directory

**Solutions:**

1. **Navigate to GAPI directory:**
   ```powershell
   cd c:\Users\matta\source\repos\GAPI
   ```

2. **Activate virtual environment:**
   ```powershell
   & .\.venv\Scripts\Activate.ps1
   ```

3. **Verify it's activated:**
   ```powershell
   # Prompt should show:
   (.venv) PS C:\Users\matta\source\repos\GAPI>
   ```

4. **If activation fails:**
   ```powershell
   # Try:
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   & .\.venv\Scripts\Activate.ps1
   ```

---

## 🔍 Diagnostic Commands

Run these to diagnose issues:

### Check Configuration
```powershell
Get-Content .env | Select-String DATABASE_URL
Get-Content config.json | Select-String database_url
```

### Check PostgreSQL Status
```powershell
Get-Service postgresql-x64-15 | Select Status
Get-NetTCPConnection | Select-String 5432
```

### Test Connectivity
```powershell
$env:PGPASSWORD = "gapi_password_secure"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U gapi -h localhost -d gapi_db -c "SELECT version();"
```

### Run Health Check
```powershell
python check_postgres.py
```

### View Recent Logs
```powershell
Get-Content "C:\Program Files\PostgreSQL\15\data\log\postgresql-*.log" -Tail 50
```

---

## 📞 Getting More Help

1. **Run diagnostic:** `python check_postgres.py`
2. **Check logs:** `C:\Program Files\PostgreSQL\15\data\log\`
3. **Read docs:** `POSTGRES_SETUP_GUIDE.md`
4. **Verify config:** `.env` and `config.json`
5. **Test manually:** Use `psql` directly
6. **Restart service:** `Restart-Service postgresql-x64-15`

---

**Last Updated:** March 2026  
**PostgreSQL Version:** 14+ supported  
**Status:** ✅ Complete Guide
