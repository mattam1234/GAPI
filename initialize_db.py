#!/usr/bin/env python3
"""
Initialize GAPI database schema.
Creates all required tables for PostgreSQL.
Safe to run multiple times - will not drop existing tables.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def initialize_database():
    """Initialize the database schema."""
    print("=" * 70)
    print("GAPI Database Initialization")
    print("=" * 70)
    
    try:
        print("\n📦 Importing database module...")
        from database import Base, engine, SessionLocal
        
        if not engine:
            print("❌ Error: Database engine not initialized!")
            print("   Check your DATABASE_URL in .env or config.json")
            sys.exit(1)
        
        print(f"✅ Connected to database: {engine.url}")
        
        print("\n📋 Creating tables...")
        # This creates all tables defined in the database module
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tables created successfully!")
        
        # Verify connection
        print("\n🔍 Verifying tables...")
        if SessionLocal:
            session = SessionLocal()
            try:
                result = session.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                tables = [row[0] for row in result]
                
                if tables:
                    print(f"✅ Found {len(tables)} tables:")
                    for table in sorted(tables):
                        print(f"   • {table}")
                else:
                    print("⚠️  No tables found (this might be normal if using SQLite)")
            except Exception as e:
                # SQLite doesn't have information_schema
                print(f"   (Cannot verify with this backend: {type(e).__name__})")
            finally:
                session.close()
        
        print("\n" + "=" * 70)
        print("✅ Database Initialization Complete!")
        print("=" * 70)
        print("\nYou can now:")
        print("1. Start GAPI: python gapi.py")
        print("2. Create user accounts through the web interface")
        print("3. Link Discord accounts and Steam IDs through the bot")
        print("\nDatabase location:")
        print(f"  {engine.url}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("\nPlease ensure:")
        print("1. You're in the GAPI directory")
        print("2. Virtual environment is activated")
        print("3. Requirements are installed: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    initialize_database()
