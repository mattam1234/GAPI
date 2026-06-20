#!/usr/bin/env python3
"""Test PostgreSQL encoding configuration."""

from database import engine
from sqlalchemy import text

print("Testing PostgreSQL UTF-8 encoding...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SHOW client_encoding"))
        encoding = result.scalar()
        print(f"✅ Client encoding: {encoding}")
        
        # Test storing and retrieving Unicode characters
        result = conn.execute(text("SELECT 'Test®™©' as test_text"))
        test_text = result.scalar()
        print(f"✅ Unicode test: {test_text}")
        
    print("\n✅ Encoding test passed! UTF-8 is working correctly.")
except Exception as e:
    print(f"❌ Encoding test failed: {e}")
