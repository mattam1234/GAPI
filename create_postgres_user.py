#!/usr/bin/env python3
"""
Create PostgreSQL user and database for GAPI.
Connects to the PostgreSQL server specified in .env and creates the necessary user and database.
"""

import subprocess
import os
import sys
from pathlib import Path

def run_psql_command(host: str, port: int, username: str, password: str, command: str) -> tuple[bool, str]:
    """Run a psql command on remote PostgreSQL server."""
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    
    try:
        result = subprocess.run(
            ["psql", "-h", host, "-p", str(port), "-U", username, "-c", command],
            capture_output=True,
            text=True,
            env=env,
            timeout=10
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except FileNotFoundError:
        return False, "psql not found. Make sure PostgreSQL is installed."
    except Exception as e:
        return False, str(e)

def main():
    print("=" * 70)
    print("PostgreSQL User & Database Setup for GAPI")
    print("=" * 70)
    
    # Load configuration from .env
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found!")
        sys.exit(1)
    
    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    
    # Parse connection details
    db_url = config.get("DATABASE_URL", "")
    pg_user = config.get("POSTGRES_USER", "postgres")
    pg_password = config.get("POSTGRES_PASSWORD", "")
    gapi_user = config.get("POSTGRES_USER", "gapi")
    gapi_password = config.get("POSTGRES_PASSWORD", "gapi_password")
    gapi_db = config.get("POSTGRES_DB", "gapi_db")
    
    # Extract host and port from DATABASE_URL
    # Format: postgresql://gapi:password@host:port/db
    try:
        # postgresql://gapi:gapi_password@192.168.5.126:5432/gapi_db
        parts = db_url.replace("postgresql://", "").split("@")
        if len(parts) != 2:
            print("❌ Invalid DATABASE_URL format in .env")
            sys.exit(1)
        
        host_port = parts[1].split("/")[0]
        host, port = host_port.rsplit(":", 1)
        port = int(port)
    except Exception as e:
        print(f"❌ Error parsing DATABASE_URL: {e}")
        sys.exit(1)
    
    print(f"\n📋 Configuration from .env:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Admin User: {pg_user}")
    print(f"   GAPI User: {gapi_user}")
    print(f"   GAPI Database: {gapi_db}")
    
    # Get admin password
    print("\n" + "=" * 70)
    print("PostgreSQL Admin Credentials")
    print("=" * 70)
    print(f"\nYou need the PostgreSQL superuser ('{pg_user}') password to create the GAPI user.")
    print(f"This is the password you set during PostgreSQL installation.")
    
    import getpass
    admin_password = getpass.getpass(f"\nEnter PostgreSQL '{pg_user}' password: ")
    
    print("\n" + "=" * 70)
    print("Creating PostgreSQL User and Database...")
    print("=" * 70)
    
    # Step 1: Create GAPI user
    print(f"\n1️⃣  Creating user '{gapi_user}'...")
    create_user_cmd = f"CREATE USER {gapi_user} WITH PASSWORD '{gapi_password}';"
    
    success, output = run_psql_command(host, port, pg_user, admin_password, create_user_cmd)
    if success or "already exists" in output:
        print(f"   ✅ User '{gapi_user}' created/exists")
    else:
        print(f"   ❌ Failed to create user: {output}")
        sys.exit(1)
    
    # Step 2: Create GAPI database
    print(f"\n2️⃣  Creating database '{gapi_db}'...")
    create_db_cmd = f"CREATE DATABASE {gapi_db} OWNER {gapi_user};"
    
    success, output = run_psql_command(host, port, pg_user, admin_password, create_db_cmd)
    if success or "already exists" in output:
        print(f"   ✅ Database '{gapi_db}' created/exists")
    else:
        print(f"   ❌ Failed to create database: {output}")
        sys.exit(1)
    
    # Step 3: Grant privileges
    print(f"\n3️⃣  Granting privileges to '{gapi_user}'...")
    grant_cmd = f"GRANT ALL PRIVILEGES ON DATABASE {gapi_db} TO {gapi_user};"
    
    success, output = run_psql_command(host, port, pg_user, admin_password, grant_cmd)
    if success:
        print(f"   ✅ Privileges granted")
    else:
        print(f"   ⚠️  Could not grant privileges: {output}")
    
    # Step 4: Test connection
    print(f"\n4️⃣  Testing connection with GAPI user...")
    test_cmd = "SELECT 1;"
    
    success, output = run_psql_command(host, port, gapi_user, gapi_password, test_cmd)
    if success:
        print(f"   ✅ Connection successful with '{gapi_user}' user")
    else:
        print(f"   ❌ Connection failed: {output}")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("✅ PostgreSQL Setup Complete!")
    print("=" * 70)
    print(f"\nUser and database created:")
    print(f"  User: {gapi_user}")
    print(f"  Password: {gapi_password}")
    print(f"  Database: {gapi_db}")
    print(f"  Host: {host}:{port}")
    print(f"\nNext steps:")
    print(f"1. Run: python initialize_db.py")
    print(f"2. Run: python test_postgres.py")
    print(f"3. Run: python gapi.py")

if __name__ == "__main__":
    main()
