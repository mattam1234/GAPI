#!/usr/bin/env python3
"""
Migration script to widen the password column in the users table from
VARCHAR(64) to VARCHAR(255).

Modern password hashing algorithms (e.g. scrypt via werkzeug) produce
hashes that are ~160 characters long, which exceeds the original 64-
character limit and causes a StringDataRightTruncation error on commit.

Run this script once against your database to apply the fix:

    python scripts/migrate_password_column.py

"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import database
    from sqlalchemy import inspect, text
except ImportError as e:
    print(f"Error: Failed to import required modules: {e}")
    print("Make sure you have SQLAlchemy installed: pip install sqlalchemy")
    sys.exit(1)


def get_password_column_length():
    """Return the current character-varying length of the password column, or None."""
    if not database.engine:
        return None
    inspector = inspect(database.engine)
    for col in inspector.get_columns("users"):
        if col["name"] == "password":
            # col["type"] is a SQLAlchemy type object; access its length attribute.
            return getattr(col.get("type"), "length", None)
    return None


def widen_password_column():
    """Alter the password column to VARCHAR(255) if it is narrower."""
    if not database.engine:
        print("Error: Database engine not available. Check your DATABASE_URL.")
        return False

    current_length = get_password_column_length()

    if current_length is None:
        print("✗ Could not determine password column length (column may not exist).")
        return False

    target_length = 255

    if current_length >= target_length:
        print(
            f"✓ Password column is already VARCHAR({current_length}) — no changes needed."
        )
        return True

    print(
        f"  Widening password column: VARCHAR({current_length}) → VARCHAR({target_length}) …"
    )

    try:
        with database.engine.connect() as conn:
            conn.execute(
                text(
                    f"ALTER TABLE users ALTER COLUMN password TYPE VARCHAR({target_length})"
                )
            )
            conn.commit()
        print(f"✓ Successfully widened password column to VARCHAR({target_length}).")
        return True
    except Exception as e:
        print(f"✗ Error widening password column: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("GAPI Database Migration: Widen Password Column")
    print("=" * 60)
    print()

    if not database.engine:
        print("✗ Error: Cannot connect to database.")
        print("  Make sure the database is accessible and DATABASE_URL is set.")
        return 1

    db_url = str(database.engine.url)
    if "@" in db_url:
        parts = db_url.split("@")
        if ":" in parts[0]:
            user_part = parts[0].split(":")[0]
            db_url = f"{user_part}:***@{parts[1]}"
    print(f"Database URL: {db_url}")
    print()

    if not widen_password_column():
        return 1

    print()
    print("=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print()
    print("The password column now accepts hashes up to 255 characters.")
    print("You can now use reset_password.py without error.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
