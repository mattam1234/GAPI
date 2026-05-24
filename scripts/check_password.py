#!/usr/bin/env python3
"""Check user's password hash and verify login."""
import sys
import database

def check_password(username: str, password: str):
    """Check if password matches user's stored hash."""
    try:
        db = database.SessionLocal()
        
        # Get user
        user = db.query(database.User).filter(database.User.username == username).first()
        if not user:
            print(f"❌ User '{username}' not found in database")
            db.close()
            return False
        
        print(f"✓ Found user: {username}")
        if database.verify_user_password(db, username, password):
            print(f"\n✓ Password MATCHES")
            return True
        else:
            print(f"\n❌ Password DOES NOT MATCH")
            return False
        
        db.close()
        
    except Exception as e:
        print(f"❌ Error checking password: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python scripts/check_password.py <username> <password>")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    check_password(username, password)
