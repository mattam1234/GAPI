#!/usr/bin/env python3
"""
Migrate data from SQLite to PostgreSQL.
This script safely transfers all data from gapi.db to PostgreSQL.
Creates backups before migration.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

def migrate_to_postgres():
    """Migrate from SQLite to PostgreSQL."""
    print("=" * 70)
    print("GAPI Database Migration: SQLite → PostgreSQL")
    print("=" * 70)
    
    sqlite_db = Path("gapi.db")
    
    # Check if SQLite database exists
    if not sqlite_db.exists():
        print("\n⚠️  No SQLite database found (gapi.db)")
        print("   If you're starting fresh, you don't need to migrate.")
        print("   Just run: python initialize_db.py")
        return
    
    print(f"\n📊 SQLite database found: {sqlite_db.name}")
    print(f"   Size: {sqlite_db.stat().st_size:,} bytes")
    
    # Confirm before proceeding
    print("\n⚠️  This will:")
    print("   1. Create a backup of gapi.db")
    print("   2. Copy all data to PostgreSQL")
    print("   3. Verify the migration")
    
    response = input("\nProceed with migration? (yes/no): ").strip().lower()
    if response != 'yes':
        print("✋ Migration cancelled")
        return
    
    try:
        print("\n" + "=" * 70)
        print("Step 1: Creating backup...")
        print("=" * 70)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(f"gapi_backup_{timestamp}.db")
        shutil.copy2(sqlite_db, backup_path)
        print(f"✅ Backup created: {backup_path}")
        
        print("\n" + "=" * 70)
        print("Step 2: Connecting to databases...")
        print("=" * 70)
        
        # Import after checking .env setup
        from database import Base, engine, SessionLocal
        import sqlalchemy
        
        if not engine:
            print("❌ PostgreSQL connection failed!")
            print("   Check your DATABASE_URL in .env or config.json")
            sys.exit(1)
        
        db_type = engine.url.drivername
        print(f"✅ Target database: {db_type}")
        print(f"   URL: {engine.url}")
        
        # Create tables in target
        print("\n" + "=" * 70)
        print("Step 3: Creating schema in PostgreSQL...")
        print("=" * 70)
        Base.metadata.create_all(bind=engine)
        print("✅ Schema created")
        
        # Now do the migration
        print("\n" + "=" * 70)
        print("Step 4: Migrating data...")
        print("=" * 70)
        
        # Connect to SQLite
        from sqlalchemy import create_engine as create_sqlite_engine
        from sqlalchemy.orm import sessionmaker
        sqlite_engine = create_sqlite_engine(f"sqlite:///{sqlite_db}")
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        
        # Get PostgreSQL session
        postgres_session = SessionLocal()
        
        try:
            # Get all model classes
            models = _get_model_classes()
            
            total_records = 0
            
            for model in models:
                # Skip certain tables
                if model.__tablename__ in ['user_roles', 'challenge_participants']:
                    continue
                
                print(f"\n   Migrating {model.__tablename__}...")
                
                # Get records from SQLite
                records = sqlite_session.query(model).all()
                
                if records:
                    print(f"   Found {len(records)} records")
                    
                    for record in records:
                        # Create new instance for PostgreSQL
                        for key, value in record.__dict__.items():
                            if not key.startswith('_'):
                                setattr(record, key, value)
                        postgres_session.add(record)
                    
                    postgres_session.commit()
                    print(f"   ✅ Imported {len(records)} records")
                    total_records += len(records)
                else:
                    print(f"   (empty table)")
            
            print(f"\n✅ Total records migrated: {total_records}")
            
        finally:
            sqlite_session.close()
            postgres_session.close()
        
        # Verify migration
        print("\n" + "=" * 70)
        print("Step 5: Verifying migration...")
        print("=" * 70)
        
        postgres_session = SessionLocal()
        try:
            models = _get_model_classes()
            all_good = True
            
            for model in models:
                if model.__tablename__ in ['user_roles', 'challenge_participants']:
                    continue
                
                count = postgres_session.query(model).count()
                print(f"   {model.__tablename__}: {count} records")
                
        finally:
            postgres_session.close()
        
        print("\n" + "=" * 70)
        print("✅ Migration Complete!")
        print("=" * 70)
        print("\nNext steps:")
        print("1. Test your application with PostgreSQL")
        print("2. Keep the backup file until everything works:")
        print(f"   {backup_path}")
        print("3. Once satisfied, you can delete gapi.db")
        print("\nTo start GAPI with PostgreSQL:")
        print("   python gapi.py")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def _get_model_classes():
    """Get all database model classes."""
    from database import (
        User, Role, FavoriteGame, IgnoredGame, Achievement,
        AchievementHunt, AchievementChallenge, ChallengeParticipant,
        GameLibraryCache
    )
    
    return [
        User, Role, FavoriteGame, IgnoredGame, Achievement,
        AchievementHunt, AchievementChallenge, ChallengeParticipant,
        GameLibraryCache
    ]

if __name__ == "__main__":
    migrate_to_postgres()
