-- Migration script to add suspension columns to users table
-- Run this on your SQLite database if you have existing users

-- SQLite
-- Add suspension-related columns
ALTER TABLE users ADD COLUMN is_suspended INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE users ADD COLUMN suspended_until TEXT;
ALTER TABLE users ADD COLUMN suspended_reason TEXT;
ALTER TABLE users ADD COLUMN suspended_by TEXT;
ALTER TABLE users ADD COLUMN suspended_at TEXT;

-- Note: SQLite uses INTEGER for BOOLEAN (0=False, 1=True)
-- TEXT is used for DateTime columns (stored as ISO8601 strings)
