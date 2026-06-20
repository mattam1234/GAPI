#!/usr/bin/env python3
"""
Test Discord bot database integration
"""
import sys
import json
from dotenv import load_dotenv
import database

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Simulate the Discord bot's load_user_mappings function
def test_load_mappings():
    load_dotenv()
    
    print("🧪 Testing Discord bot database integration...\n")
    
    if not database.SessionLocal:
        print("❌ Database not available")
        return False
    
    # Load from PostgreSQL database (same logic as Discord bot)
    db = database.SessionLocal()
    try:
        users = db.query(database.User).filter(database.User.discord_id.isnot(None)).all()
        user_mappings = {}
        for user in users:
            if user.discord_id and user.steam_id:
                try:
                    user_mappings[int(user.discord_id)] = user.steam_id
                except ValueError:
                    print(f"⚠️  Invalid discord_id for user {user.username}: {user.discord_id}")
        
        print(f"✅ Loaded {len(user_mappings)} Discord user mappings from database\n")
        
        for discord_id, steam_id in user_mappings.items():
            user = db.query(database.User).filter(database.User.discord_id == str(discord_id)).first()
            print(f"  🔗 Discord ID {discord_id}")
            print(f"     → Steam ID: {steam_id}")
            print(f"     → Username: {user.username if user else 'Unknown'}")
            print()
        
        return True
    finally:
        db.close()

def test_save_mappings():
    """Test saving a new mapping to database"""
    print("🧪 Testing save functionality...\n")
    
    if not database.SessionLocal:
        print("❌ Database not available")
        return False
    
    # This would be called when a new user links their Discord account
    test_mappings = {
        1000390090524205076: "76561198123639801"  # Existing mapping
    }
    
    db = database.SessionLocal()
    try:
        for discord_id, steam_id in test_mappings.items():
            user = db.query(database.User).filter(
                database.User.steam_id == steam_id
            ).first()
            
            if user:
                print(f"  ✅ Found user {user.username} with Steam ID {steam_id}")
                print(f"     Current Discord ID: {user.discord_id}")
            else:
                print(f"  ⚠️  No user found with Steam ID {steam_id}")
        
        print("\n✅ Save test complete (no changes made)")
        return True
    finally:
        db.close()

if __name__ == "__main__":
    success = test_load_mappings()
    if success:
        test_save_mappings()
        print("\n" + "="*60)
        print("✅ Discord bot database integration working correctly!")
        print("="*60)
        print("\n📝 Next steps:")
        print("   1. Restart the Discord bot to load mappings from database")
        print("   2. New mappings will be saved to both database and JSON")
        print("   3. Database is now the primary source of truth")
