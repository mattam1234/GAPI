#!/usr/bin/env python3
"""
Automated PostgreSQL setup for GAPI
Creates database, user, and initializes schema.
Run this as Administrator on Windows.
"""

import subprocess
import sys
import os
import json
import getpass
from pathlib import Path

# PostgreSQL installation paths (Windows)
POSTGRES_DEFAULT_PATHS = [
    r"C:\Program Files\PostgreSQL\15\bin",
    r"C:\Program Files\PostgreSQL\14\bin",
    r"C:\Program Files\PostgreSQL\16\bin",
    r"C:\Program Files (x86)\PostgreSQL\15\bin",
]

def find_psql():
    """Find psql executable."""
    for path in POSTGRES_DEFAULT_PATHS:
        psql_path = os.path.join(path, "psql.exe")
        if os.path.exists(psql_path):
            return psql_path
    
    # Try PATH
    try:
        result = subprocess.run(["where", "psql"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    
    return None

def run_psql_command(command: str, password: str = None) -> bool:
    """Run a psql command."""
    psql_path = find_psql()
    if not psql_path:
        print("❌ PostgreSQL not found. Please install PostgreSQL first.")
        print("   Download: https://www.postgresql.org/download/windows/")
        return False
    
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    
    try:
        result = subprocess.run(
            [psql_path, "-U", "postgres", "-h", "localhost", "-c", command],
            capture_output=True,
            text=True,
            env=env
        )
        
        if result.returncode != 0:
            print(f"❌ Error: {result.stderr}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Error executing command: {e}")
        return False

def main():
    print("=" * 70)
    print("GAPI PostgreSQL Setup")
    print("=" * 70)
    
    # Check if running as admin (Windows)
    if sys.platform == "win32":
        import ctypes
        is_admin = ctypes.windll.shell.IsUserAnAdmin()
        if not is_admin:
            print("⚠️  Warning: This script should be run as Administrator for best results.")
            proceed = input("Continue anyway? (y/n): ").lower()
            if proceed != 'y':
                sys.exit(1)
    
    # Find PostgreSQL
    psql_path = find_psql()
    if not psql_path:
        print("❌ PostgreSQL not found!")
        print("\nInstallation instructions:")
        print("1. Download: https://www.postgresql.org/download/windows/")
        print("2. Run the installer")
        print("3. Note the SuperUser (postgres) password you set")
        print("4. Run this script again")
        sys.exit(1)
    
    print(f"✅ Found PostgreSQL: {psql_path}")
    print()
    
    # Get passwords
    print("PostgreSQL Configuration:")
    pg_password = getpass.getpass("Enter PostgreSQL 'postgres' superuser password: ")
    
    gapi_password = getpass.getpass("Enter new GAPI database user password (or press Enter for 'gapi_password_secure'): ")
    if not gapi_password:
        gapi_password = "gapi_password_secure"
    
    print("\n" + "=" * 70)
    print("Setting up PostgreSQL...")
    print("=" * 70)
    
    # Create GAPI user
    print("\n1️⃣  Creating GAPI user...")
    create_user_sql = f"CREATE USER gapi WITH PASSWORD '{gapi_password}';"
    if run_psql_command(create_user_sql, pg_password):
        print("   ✅ User 'gapi' created")
    else:
        print("   ⚠️  User might already exist (this is OK)")
    
    # Create database
    print("\n2️⃣  Creating GAPI database...")
    create_db_sql = "CREATE DATABASE gapi_db OWNER gapi;"
    if run_psql_command(create_db_sql, pg_password):
        print("   ✅ Database 'gapi_db' created")
    else:
        print("   ⚠️  Database might already exist (this is OK)")
    
    # Grant privileges
    print("\n3️⃣  Setting up privileges...")
    grant_sql = "GRANT ALL PRIVILEGES ON DATABASE gapi_db TO gapi;"
    if run_psql_command(grant_sql, pg_password):
        print("   ✅ Privileges granted")
    else:
        print("   ⚠️  Could not grant privileges")
    
    # Update .env file
    print("\n4️⃣  Updating .env file...")
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "r") as f:
            content = f.read()
        
        # Replace SQLite with PostgreSQL
        old_db_url = "DATABASE_URL=sqlite:///gapi.db"
        new_db_url = f"DATABASE_URL=postgresql://gapi:{gapi_password}@localhost:5432/gapi_db"
        
        if old_db_url in content:
            content = content.replace(old_db_url, f"# {old_db_url} (switched to PostgreSQL)\n{new_db_url}")
        elif "DATABASE_URL=postgresql://" not in content:
            # Add after SECRET_KEY
            content = content.replace(
                "# Database connection",
                f"{new_db_url}\n\n# Database connection"
            )
        
        with open(env_file, "w") as f:
            f.write(content)
        print("   ✅ Updated .env file")
    else:
        print("   ⚠️  .env file not found")
    
    # Update config.json
    print("\n5️⃣  Updating config.json...")
    config_file = Path("config.json")
    if config_file.exists():
        with open(config_file, "r") as f:
            config = json.load(f)
        
        config["database_url"] = f"postgresql://gapi:{gapi_password}@localhost:5432/gapi_db"
        
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        print("   ✅ Updated config.json")
    else:
        print("   ⚠️  config.json file not found")
    
    # Test connection
    print("\n6️⃣  Testing database connection...")
    env = os.environ.copy()
    env["PGPASSWORD"] = gapi_password
    
    try:
        result = subprocess.run(
            [psql_path, "-U", "gapi", "-h", "localhost", "-d", "gapi_db", "-c", "SELECT version();"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5
        )
        
        if result.returncode == 0:
            print("   ✅ Connection successful!")
            print(f"   PostgreSQL version: {result.stdout.strip()}")
        else:
            print(f"   ❌ Connection failed: {result.stderr}")
            sys.exit(1)
    except Exception as e:
        print(f"   ❌ Error testing connection: {e}")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("✅ PostgreSQL Setup Complete!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Activate your virtual environment:")
    print("   & .\.venv\Scripts\Activate.ps1")
    print("\n2. Initialize the database schema:")
    print("   python initialize_db.py")
    print("\n3. Start GAPI:")
    print("   python gapi.py")
    print("\nConfiguration saved:")
    print(f"  Database URL: postgresql://gapi:***@localhost:5432/gapi_db")
    print(f"  Files updated: .env, config.json")
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
