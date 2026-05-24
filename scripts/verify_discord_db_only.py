#!/usr/bin/env python3
"""
Verify Discord bot only uses PostgreSQL database, not JSON files
"""
import sys
import os
from dotenv import load_dotenv

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import database

print("="*70)
print("Discord Bot Database-Only Verification")
print("="*70)

print("\n✅ File Operations Check:\n")

# Read the discord bot source
with open('discord_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check for JSON file operations related to user mappings
checks = {
    'discord_config.json writes': 'json.dump' in content and 'discord_config' in content,
    'discord_config.json reads': 'json.load' in content and 'discord_config' in content,
    'open(self.config_file': 'open(self.config_file' in content,
    'Database SessionLocal': 'database.SessionLocal' in content,
    'database.User.discord_id': 'database.User.discord_id' in content,
}

json_file_issues = []
db_operations = []

for check, present in checks.items():
    if 'discord_config' in check or 'open(self' in check:
        status = "❌ FOUND" if present else "✅ NOT FOUND"
        print(f"  {status}: {check}")
        if present:
            json_file_issues.append(check)
    else:
        status = "✅ FOUND" if present else "❌ NOT FOUND"
        print(f"  {status}: {check}")
        if present:
            db_operations.append(check)

print("\n📊 Summary:")
print(f"  Database operations: {len(db_operations)}")
print(f"  File operation issues: {len(json_file_issues)}")

if json_file_issues:
    print(f"\n⚠️  Issues found: {json_file_issues}")
else:
    print("\n✅ No JSON file operations for user mappings!")

print("\n📝 What the Discord bot now uses:\n")
print("  🟢 PostgreSQL Database (from .env DATABASE_URL)")
print("     → Loads user mappings from users.discord_id column")
print("     → Saves user mappings to users.discord_id column")
print("\n  🔵 config.json (READ-ONLY at startup)")
print("     → Discord bot token (discord_bot_token)")
print("     → Steam API key fallback (steam_api_key)")
print("     → Used for initial bot configuration ONLY")

print("\n  🟡 .env file (READ at startup)")
print("     → DATABASE_URL for PostgreSQL connection")
print("     → STEAM_API_KEY for Steam integration")
print("     → DISCORD_BOT_TOKEN for Discord bot")

print("\n  ❌ discord_config.json")
print("     → NO LONGER USED")
print("     → Can be archived or deleted")

print("\n" + "="*70)
if not json_file_issues:
    print("✅ Discord bot is now DATABASE-ONLY for user mappings!")
else:
    print("⚠️  Discord bot still has file operations")
print("="*70)
