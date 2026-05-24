#!/usr/bin/env python3
"""
Verify Discord ID integration in database
"""
from dotenv import load_dotenv
import database

load_dotenv()

print("🔍 Checking Discord ID integration...\n")

if not database.SessionLocal:
    print("❌ Database not available")
    exit(1)

db = database.SessionLocal()
try:
    # Check if discord_id column exists
    from sqlalchemy import text, inspect
    inspector = inspect(database.engine)
    columns = [col['name'] for col in inspector.get_columns('users')]
    
    if 'discord_id' in columns:
        print("✅ discord_id column exists in users table")
    else:
        print("❌ discord_id column NOT found")
        exit(1)
    
    # Get users with Discord IDs
    users = db.query(database.User).filter(database.User.discord_id.isnot(None)).all()
    
    print(f"\n📊 Users with Discord IDs linked: {len(users)}\n")
    
    for user in users:
        print(f"  👤 {user.username}")
        print(f"     • Discord ID: {user.discord_id}")
        print(f"     • Steam ID: {user.steam_id}")
        print(f"     • Created: {user.created_at}")
        print()
    
    # Check indexes
    indexes = inspector.get_indexes('users')
    discord_indexes = [idx for idx in indexes if 'discord_id' in str(idx)]
    if discord_indexes:
        print(f"✅ Discord ID is indexed for fast lookups")
    else:
        print("⚠️  No index found on discord_id column")
    
    print("\n✅ Discord database integration verified!")
    
finally:
    db.close()
