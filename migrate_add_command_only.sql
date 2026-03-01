-- Migration script to add command_only column to chat_messages table
-- Run this on your SQL Server database if you have existing chat messages

-- SQL Server
IF COL_LENGTH('dbo.chat_messages', 'command_only') IS NULL
	ALTER TABLE dbo.chat_messages ADD command_only BIT DEFAULT 0;

-- PostgreSQL (uncomment if you are using Postgres)
-- ALTER TABLE chat_messages
-- ADD COLUMN IF NOT EXISTS command_only BOOLEAN DEFAULT false;

-- Note: This column marks messages that are only visible to the sender and admins
-- (e.g., /help, /room status, /picker status responses)
