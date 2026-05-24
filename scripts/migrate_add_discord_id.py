#!/usr/bin/env python3
"""
Migration script to add discord_id column to users table
"""
import sys
from dotenv import load_dotenv
from sqlalchemy import text
import database

def migrate():
    """Add discord_id column to users table"""
    load_dotenv()
    
    if not database.engine:
        print("❌ Database engine not available")
        sys.exit(1)
    
    print("🔄 Adding discord_id column to users table...")
    
    try:
        with database.engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='users' AND column_name='discord_id'
            """))
            
            if result.fetchone():
                print("✅ discord_id column already exists")
                return
            
            # Add the column
            conn.execute(text("""
                ALTER TABLE users 
                ADD COLUMN discord_id VARCHAR(50)
            """))
            
            # Add index for faster lookups
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_users_discord_id 
                ON users(discord_id)
            """))
            
            conn.commit()
            print("✅ Successfully added discord_id column and index")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
