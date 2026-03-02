#!/usr/bin/env python3
"""Check user's password hash and verify login."""
import sys
import hashlib
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
        print(f"  Stored password hash: {user.password[:20]}... (truncated)")
        
        # Hash the provided password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        print(f"  Provided password hash: {password_hash[:20]}... (truncated)")
        
        # Compare
        if user.password == password_hash:
            print(f"\n✓ Password MATCHES")
            return True
        else:
            print(f"\n❌ Password DOES NOT MATCH")
            print(f"\nFull stored hash: {user.password}")
            print(f"Full provided hash: {password_hash}")
            return False
        
        db.close()
        
    except Exception as e:
        print(f"❌ Error checking password: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python check_password.py <username> <password>")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    check_password(username, password)
