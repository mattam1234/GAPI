#!/usr/bin/env python3
"""
Migration script to add password field to existing User table.
Run this script to update your database schema.
"""

import sys
import os

# Add the parent directory to the path so we can import database module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import database
    from sqlalchemy import inspect, Column, String, text
except ImportError as e:
    print(f"Error: Failed to import required modules: {e}")
    print("Make sure you have SQLAlchemy installed: pip install sqlalchemy psycopg2-binary")
    sys.exit(1)


def check_password_column_exists():
    """Check if the password column already exists in the users table."""
    if not database.engine:
        print("Error: Database engine not available")
        return False
        
    inspector = inspect(database.engine)
    columns = [col['name'] for col in inspector.get_columns('users')]
    return 'password' in columns


def add_password_column():
    """Add password column to the users table if it doesn't exist."""
    if not database.engine:
        print("Error: Database engine not available. Check your DATABASE_URL environment variable.")
        return False
        
    try:
        # Check if column already exists
        if check_password_column_exists():
            print("✓ Password column already exists in users table")
            return True
        
        print("Adding password column to users table...")
        
        # Add the password column
        with database.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN password VARCHAR(64)"
            ))
            conn.commit()
        
        print("✓ Successfully added password column to users table")
        return True
        
    except Exception as e:
        print(f"✗ Error adding password column: {e}")
        return False


def main():
    print("=" * 60)
    print("GAPI Database Migration: Add Password Column")
    print("=" * 60)
    print()
    
    # Check database connection
    if not database.engine:
        print("✗ Error: Cannot connect to database")
        print("  Make sure PostgreSQL is running and DATABASE_URL is set correctly")
        print(f"  Current DATABASE_URL: {database.DATABASE_URL}")
        return 1
    
    print(f"Database URL: {database.DATABASE_URL}")
    print()
    
    # Add password column
    if not add_password_column():
        return 1
    
    print()
    print("=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Start the app to create missing tables")
    print("2. Use the admin migration UI if you need to add role tables")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
