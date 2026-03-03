#!/usr/bin/env python3
"""
Test GAPI PostgreSQL database connection and operations.
Creates a test user and verifies all basic operations work.
"""

import os
import sys
from pathlib import Path

def test_database():
    """Test database connection and operations."""
    print("=" * 70)
    print("GAPI Database Operation Test")
    print("=" * 70)
    
    try:
        print("\n1️⃣  Importing database module...")
        from database import SessionLocal, User, Role, FavoriteGame, IgnoredGame
        
        if not SessionLocal:
            print("❌ Database not properly configured!")
            sys.exit(1)
        
        print("   ✅ Database module imported")
        
        print("\n2️⃣  Creating database session...")
        session = SessionLocal()
        print("   ✅ Session created")
        
        print("\n3️⃣  Testing CREATE operation...")
        
        # Check if test user exists
        test_user = session.query(User).filter_by(username="test_user_gapi").first()
        if test_user:
            session.delete(test_user)
            session.commit()
            print("   Cleaned up existing test user")
        
        # Create test user
        new_user = User(
            username="test_user_gapi",
            password="testhash123",
            steam_id="12345",
            display_name="Test User",
            bio="This is a test user"
        )
        session.add(new_user)
        session.commit()
        print("   ✅ Created test user")
        
        print("\n4️⃣  Testing READ operation...")
        
        read_user = session.query(User).filter_by(username="test_user_gapi").first()
        if read_user:
            print(f"   ✅ Retrieved user: {read_user.username}")
            print(f"      Display Name: {read_user.display_name}")
            print(f"      Steam ID: {read_user.steam_id}")
        else:
            print("   ❌ Could not retrieve user!")
            sys.exit(1)
        
        print("\n5️⃣  Testing UPDATE operation...")
        
        read_user.bio = "Updated bio for testing"
        session.commit()
        
        updated_user = session.query(User).filter_by(username="test_user_gapi").first()
        if updated_user and updated_user.bio == "Updated bio for testing":
            print(f"   ✅ Updated user bio")
        else:
            print("   ❌ Update failed!")
            sys.exit(1)
        
        print("\n6️⃣  Testing relationship operations...")
        
        # Create favorite game
        fav_game = FavoriteGame(
            user_id=read_user.id,
            app_id="570",  # Dota 2
            platform="steam"
        )
        session.add(fav_game)
        session.commit()
        print(f"   ✅ Added favorite game")
        
        # Create ignored game
        ignored_game = IgnoredGame(
            user_id=read_user.id,
            app_id="570",  # Dota 2
            game_name="Dota 2",
            reason="Not interested"
        )
        session.add(ignored_game)
        session.commit()
        print(f"   ✅ Added ignored game")
        
        # Verify relationships
        user_with_relations = session.query(User).filter_by(username="test_user_gapi").first()
        print(f"   ✅ User has {len(user_with_relations.favorites)} favorite(s)")
        print(f"   ✅ User has {len(user_with_relations.ignored_games)} ignored game(s)")
        
        print("\n7️⃣  Testing DELETE operation...")
        
        session.delete(read_user)
        session.commit()
        
        deleted_user = session.query(User).filter_by(username="test_user_gapi").first()
        if not deleted_user:
            print("   ✅ User deleted successfully")
        else:
            print("   ❌ User still exists after deletion!")
            sys.exit(1)
        
        print("\n8️⃣  Checking database statistics...")
        
        user_count = session.query(User).count()
        print(f"   Total users: {user_count}")
        
        role_count = session.query(Role).count()
        print(f"   Total roles: {role_count}")
        
        fav_count = session.query(FavoriteGame).count()
        print(f"   Total favorite games: {fav_count}")
        
        ignored_count = session.query(IgnoredGame).count()
        print(f"   Total ignored games: {ignored_count}")
        
        session.close()
        
        print("\n" + "=" * 70)
        print("✅ All Database Tests Passed!")
        print("=" * 70)
        print("\nYour PostgreSQL database is working correctly!")
        print("\nYou can now:")
        print("1. Start GAPI: python gapi.py")
        print("2. Create user accounts")
        print("3. Link Discord and Steam accounts")
        print("4. Use all GAPI features")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
        print("\nTroubleshooting:")
        print("1. Is PostgreSQL running?")
        print("2. Check .env and config.json")
        print("3. Run: python setup_postgres.py")
        print("4. Run: python initialize_db.py")
        
        try:
            session.close()
        except:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    test_database()
