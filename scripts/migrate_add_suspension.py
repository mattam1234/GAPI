#!/usr/bin/env python3
"""
Migration script to add suspension columns to the users table.
Run this script to update your database schema.
"""

import sys
import os

# Add the parent directory to the path so we can import database module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import database
    from sqlalchemy import inspect, text
except ImportError as e:
    print(f"Error: Failed to import required modules: {e}")
    print("Make sure you have SQLAlchemy installed: pip install sqlalchemy")
    sys.exit(1)


def check_column_exists(column_name):
    """Check if a column already exists in the users table."""
    if not database.engine:
        print("Error: Database engine not available")
        return False
        
    inspector = inspect(database.engine)
    columns = [col['name'] for col in inspector.get_columns('users')]
    return column_name in columns


def add_suspension_columns():
    """Add suspension columns to the users table if they don't exist."""
    if not database.engine:
        print("Error: Database engine not available.")
        return False
        
    try:
        # List of columns to add
        suspension_columns = {
            'is_suspended': 'INTEGER DEFAULT 0 NOT NULL',
            'suspended_until': 'TEXT',
            'suspended_reason': 'TEXT',
            'suspended_by': 'TEXT',
            'suspended_at': 'TEXT'
        }
        
        added_columns = []
        skipped_columns = []
        
        with database.engine.connect() as conn:
            for column_name, column_def in suspension_columns.items():
                if check_column_exists(column_name):
                    print(f"  ✓ Column '{column_name}' already exists")
                    skipped_columns.append(column_name)
                else:
                    print(f"  + Adding column '{column_name}'...")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_def}"))
                    added_columns.append(column_name)
            
            if added_columns:
                conn.commit()
                print(f"\n✓ Successfully added {len(added_columns)} column(s)")
            else:
                print(f"\n✓ All suspension columns already exist")
        
        return True
        
    except Exception as e:
        print(f"✗ Error adding suspension columns: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print("GAPI Database Migration: Add Suspension Columns to Users Table")
    print("=" * 70)
    print()
    
    # Check database connection
    if not database.engine:
        print("✗ Error: Cannot connect to database")
        print("  Make sure the database is accessible")
        return 1
    
    db_url = str(database.engine.url)
    # Hide password in output
    if '@' in db_url:
        parts = db_url.split('@')
        if ':' in parts[0]:
            user_part = parts[0].split(':')[0]
            db_url = f"{user_part}:***@{parts[1]}"
    
    print(f"Database URL: {db_url}")
    print()
    print("Adding suspension columns to users table...")
    print()
    
    # Add suspension columns
    if not add_suspension_columns():
        return 1
    
    print()
    print("=" * 70)
    print("Migration Complete!")
    print("=" * 70)
    print()
    print("The following suspension-related columns are now available:")
    print("  - is_suspended: Suspension status (0=False, 1=True)")
    print("  - suspended_until: Suspension end date (NULL=permanent)")
    print("  - suspended_reason: Reason for suspension")
    print("  - suspended_by: Admin who issued suspension")
    print("  - suspended_at: When suspension was issued")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
