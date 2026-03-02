#!/usr/bin/env python3
"""Check if a user has admin role in the database."""
import sys
import database

def check_admin_role(username: str):
    """Check if user has admin role."""
    try:
        db = database.SessionLocal()
        
        # Get user
        user = db.query(database.User).filter(database.User.username == username).first()
        if not user:
            print(f"❌ User '{username}' not found in database")
            db.close()
            return False
        
        print(f"✓ Found user: {username}")
        print(f"  ID: {user.id}")
        print(f"  Created: {user.created_at}")
        
        # Get roles
        roles = database.get_user_roles(db, username)
        print(f"  Roles: {roles if roles else '(none)'}")
        
        # Check if admin
        has_admin = 'admin' in roles
        if has_admin:
            print(f"\n✓ User '{username}' HAS admin role")
        else:
            print(f"\n❌ User '{username}' DOES NOT have admin role")
            print(f"\nTo grant admin role, run:")
            print(f"  python -c \"import database; db=database.SessionLocal(); database.set_user_roles(db, '{username}', ['admin']); print('Admin role granted')\"")
        
        db.close()
        return has_admin
        
    except Exception as e:
        print(f"❌ Error checking admin role: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python check_admin_role.py <username>")
        sys.exit(1)
    
    username = sys.argv[1]
    check_admin_role(username)
