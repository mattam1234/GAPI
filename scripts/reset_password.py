#!/usr/bin/env python3
"""Reset user password.

Usage:
    python scripts/reset_password.py <username> <new_password>          # interactive confirmation
    python scripts/reset_password.py <username> <new_password> --yes    # non-interactive (for server use)
    python scripts/reset_password.py <username> <new_password> -y       # non-interactive shorthand
"""
import sys
import os
import argparse

# Ensure the repo root is on sys.path so `database` can be imported when
# running this script from the scripts/ subdirectory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


def reset_password(username: str, new_password: str) -> bool:
    """Reset user's password. Returns True on success."""
    try:
        db = database.SessionLocal()

        user = db.query(database.User).filter(database.User.username == username).first()
        if not user:
            print(f"❌ User '{username}' not found in database")
            db.close()
            return False

        print(f"✓ Found user: {username}")

        user.password = database.hash_password(new_password)
        db.commit()

        print("✓ Password updated successfully")

        db.close()
        return True

    except Exception as e:
        print(f"❌ Error resetting password: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Reset a GAPI user password from the command line.'
    )
    parser.add_argument('username', help='Username of the account to reset')
    parser.add_argument('new_password', help='New password to set')
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='Skip interactive confirmation (useful for scripted/server use)',
    )
    args = parser.parse_args()

    if not args.yes:
        print(f"⚠️  About to reset password for user: {args.username}")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            sys.exit(0)

    success = reset_password(args.username, args.new_password)
    sys.exit(0 if success else 1)
