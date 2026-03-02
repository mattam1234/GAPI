#!/usr/bin/env python3
"""Reset user password."""
import sys
import hashlib
import database

def reset_password(username: str, new_password: str):
    """Reset user's password."""
    try:
        db = database.SessionLocal()
        
        # Get user
        user = db.query(database.User).filter(database.User.username == username).first()
        if not user:
            print(f"❌ User '{username}' not found in database")
            db.close()
            return False
        
        print(f"✓ Found user: {username}")
        
        # Hash the new password
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
        
        # Update password
        user.password = password_hash
        db.commit()
        
        print(f"✓ Password updated successfully")
        print(f"  New password hash: {password_hash}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Error resetting password: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python reset_password.py <username> <new_password>")
        sys.exit(1)
    
    username = sys.argv[1]
    new_password = sys.argv[2]
    
    print(f"⚠️  About to reset password for user: {username}")
    confirm = input("Type 'yes' to confirm: ")
    
    if confirm.lower() == 'yes':
        reset_password(username, new_password)
    else:
        print("Cancelled.")
