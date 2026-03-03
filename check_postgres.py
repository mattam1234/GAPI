#!/usr/bin/env python3
"""
Check PostgreSQL database health and connection status.
Useful for troubleshooting database issues.
"""

import os
import sys
from pathlib import Path

def check_postgres_health():
    """Check PostgreSQL health and connection."""
    print("=" * 70)
    print("GAPI PostgreSQL Health Check")
    print("=" * 70)
    
    try:
        print("\n1️⃣  Checking configuration...")
        
        # Check .env
        env_file = Path(".env")
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("DATABASE_URL"):
                        db_url = line.split("=", 1)[1].strip()
                        if "postgresql" in db_url:
                            print("   ✅ .env configured for PostgreSQL")
                        else:
                            print(f"   ⚠️  .env using: {db_url.split('://')[0]}")
        else:
            print("   ⚠️  .env file not found")
        
        # Check config.json
        import json
        config_file = Path("config.json")
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
                if config.get("database_url", "").startswith("postgresql"):
                    print("   ✅ config.json configured for PostgreSQL")
        
        print("\n2️⃣  Checking PostgreSQL connection...")
        
        from database import engine, SessionLocal
        
        if not engine:
            print("   ❌ Database engine not initialized!")
            sys.exit(1)
        
        print(f"   Engine: {engine.url}")
        print(f"   Driver: {engine.url.drivername}")
        
        print("\n3️⃣  Testing connection...")
        
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                print("   ✅ Connection successful!")
                
                # Try a simple query
                result = conn.execute(text("SELECT version()"))
                version = result.scalar() if result else "Unknown"
                print(f"   Version: {version}")
        
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
            print("\n   Troubleshooting:")
            print("   • Is PostgreSQL service running?")
            print("   • Check DATABASE_URL in .env")
            print("   • Verify password is correct")
            print("   • Make sure database 'gapi_db' exists")
            sys.exit(1)
        
        print("\n4️⃣  Checking database schema...")
        
        if SessionLocal:
            session = SessionLocal()
            try:
                from database import Base
                from sqlalchemy import inspect, text
                
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                
                if tables:
                    print(f"   ✅ Found {len(tables)} tables:")
                    expected_tables = [
                        'users', 'roles', 'favorite_games', 'ignored_games',
                        'achievements', 'achievement_hunts'
                    ]
                    
                    for table in sorted(tables):
                        status = "✅" if table in expected_tables else "ℹ️"
                        print(f"      {status} {table}")
                    
                    missing = [t for t in expected_tables if t not in tables]
                    if missing:
                        print(f"\n   ⚠️  Missing tables: {', '.join(missing)}")
                        print("      Run: python initialize_db.py")
                else:
                    print("   ⚠️  No tables found!")
                    print("      Run: python initialize_db.py")
                
            except Exception as e:
                print(f"   ℹ️  Could not inspect schema: {e}")
            finally:
                session.close()
        
        print("\n5️⃣  Checking user configuration...")
        
        session = SessionLocal()
        try:
            from database import User
            user_count = session.query(User).count()
            print(f"   Users in database: {user_count}")
            
            if user_count == 0:
                print("   💡 No users created yet. Create one through the web interface.")
            else:
                print(f"   ✅ Database has {user_count} user(s)")
        except Exception as e:
            print(f"   ℹ️  Could not query users: {e}")
        finally:
            session.close()
        
        print("\n" + "=" * 70)
        print("✅ Health Check Complete!")
        print("=" * 70)
        print("\nYour PostgreSQL database is configured and ready to use.")
        print("Start GAPI with: python gapi.py")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    check_postgres_health()
