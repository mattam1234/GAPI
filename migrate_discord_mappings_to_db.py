#!/usr/bin/env python3
"""
Migration script to import existing Discord user mappings from JSON to database
"""
import json
import os
import sys
from dotenv import load_dotenv
import database

def migrate():
    """Import Discord user mappings from discord_config.json to database"""
    load_dotenv()
    
    if not database.SessionLocal:
        print("❌ Database not available")
        sys.exit(1)
    
    json_file = 'discord_config.json'
    if not os.path.exists(json_file):
        print(f"ℹ️  No {json_file} found, nothing to migrate")
        return
    
    print(f"🔄 Migrating Discord user mappings from {json_file} to database...")
    
    try:
        # Load JSON mappings
        with open(json_file, 'r') as f:
            data = json.load(f)
            mappings = data.get('user_mappings', {})
        
        if not mappings:
            print("ℹ️  No user mappings found in JSON file")
            return
        
        print(f"📋 Found {len(mappings)} mappings to import")
        
        # Import to database
        db = database.SessionLocal()
        try:
            imported = 0
            skipped = 0
            
            for discord_id, steam_id in mappings.items():
                # Check if user exists with this steam_id
                user = db.query(database.User).filter(
                    database.User.steam_id == steam_id
                ).first()
                
                if user:
                    if user.discord_id == discord_id:
                        print(f"  ⏭️  User {user.username} already has Discord ID {discord_id}")
                        skipped += 1
                    else:
                        user.discord_id = discord_id
                        print(f"  ✅ Updated user {user.username} with Discord ID {discord_id}")
                        imported += 1
                else:
                    # User doesn't exist, create a placeholder warning
                    print(f"  ⚠️  No user found with Steam ID {steam_id} (Discord ID: {discord_id})")
                    print(f"      User needs to register on web interface first")
                    skipped += 1
            
            db.commit()
            print(f"\n✅ Migration complete:")
            print(f"   • Imported: {imported}")
            print(f"   • Skipped: {skipped}")
            
        except Exception as e:
            db.rollback()
            print(f"❌ Migration failed: {e}")
            sys.exit(1)
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Error reading JSON file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
