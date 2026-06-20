-- Migration script to add password column to users table
-- Run this on your PostgreSQL database if you have existing users

-- Add password column (nullable initially to allow migration)
-- PostgreSQL (uncomment if you are using Postgres)
-- ALTER TABLE users
-- ADD COLUMN IF NOT EXISTS password VARCHAR(64);

-- SQL Server
IF COL_LENGTH('dbo.users', 'password') IS NULL
	ALTER TABLE dbo.users ADD password VARCHAR(64);

-- Note: After running this migration, the application will automatically
-- migrate user passwords from users_auth.json to the database on first run.
-- Once migration is complete, you can optionally make the column NOT NULL:
-- ALTER TABLE users ALTER COLUMN password SET NOT NULL;
