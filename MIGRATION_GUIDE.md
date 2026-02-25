# Database Migration Guide

## Summary

The application has been successfully migrated from using JSON files (`users_auth.json`, `users_template.json`) to using the PostgreSQL database as the primary storage for user authentication and platform IDs.

## Changes Made

### 1. Database Schema Updates

- Added `password` column to the `users` table to store password hashes (SHA256)
- Updated the `User` model in [database.py](database.py)

### 2. New Database Functions

Added the following authentication functions in [database.py](database.py):
- `get_all_users()` - Retrieve all users
- `delete_user()` - Delete a user
- `update_user_role()` - Update user role
- `verify_user_password()` - Verify password hash
- Updated `create_or_update_user()` to handle passwords

### 3. UserManager Refactored

The `UserManager` class in [gapi_gui.py](gapi_gui.py) has been completely refactored to:
- Use the database as the primary storage (no more in-memory dictionary)
- Automatically migrate users from `users_auth.json` to the database on first run
- Perform all operations (register, login, get/update IDs) directly against the database

## Migration Process

### Automatic Migration

When you start the application after this update, it will automatically:

1. Check if `users_auth.json` exists
2. Migrate all users from the JSON file to the database
3. Create a backup file `users_auth.json.migrated`
4. Log all migration activities

### Manual Migration Steps

If you have an existing database, run the migration script first:

```powershell
python migrate_database.py
```

This will add the `password` column to your existing `users` table.

## Testing Results

All tests passed successfully:

✅ Database schema migration complete
✅ User migration from JSON to database (11 users migrated)
✅ User registration works
✅ User login authentication works
✅ Platform ID retrieval works
✅ Platform ID updates work

## What Changed for Users

### Before (JSON-based)
- User data stored in `users_auth.json`
- Platform IDs synced between JSON and database
- JSON file was the source of truth

### After (Database-based)
- All user data stored in PostgreSQL database
- No runtime dependency on JSON files
- Database is the single source of truth
- JSON files only used for one-time migration

## Files Modified

1. [database.py](database.py) - Added password field and auth functions
2. [gapi_gui.py](gapi_gui.py) - Refactored UserManager to use database
3. [migrate_database.py](migrate_database.py) - New migration script (created)
4. [migrate_add_password.sql](migrate_add_password.sql) - SQL migration (created)

## Backward Compatibility

- Existing users in `users_auth.json` are automatically migrated
- The JSON file is backed up to `users_auth.json.migrated`
- You can safely delete the JSON backup after confirming migration

## Important Notes

1. **Database Required**: The application now requires a working PostgreSQL database connection
2. **No Fallback**: Unlike before, there's no fallback to JSON files - the database must be available
3. **Password Security**: Passwords are stored as SHA256 hashes (same as before)
4. **First User**: The first registered user automatically becomes an admin

## Troubleshooting

### Database Connection Issues

If you see "Database not available" errors:
1. Check that PostgreSQL is running
2. Verify your `DATABASE_URL` environment variable
3. Default: `postgresql://gapi:gapi_password@localhost:5432/gapi_db`

### Migration Issues

If migration fails:
1. Run `python migrate_database.py` manually
2. Check the logs in `logs/gapi_gui.log`
3. Verify your `users_auth.json` file is valid JSON

### User Not Found Errors

If you get "User not found in database" errors:
1. Users must be registered before using the app
2. Check that migration completed successfully
3. Verify users exist: `python -c "import database; db = database.SessionLocal(); print([u.username for u in database.get_all_users(db)])"`

## Next Steps

1. ✅ Migration is complete!
2. Start the application: `python gapi_gui.py`
3. Verify all users can log in
4. Optionally delete `users_auth.json` and `users_auth.json.migrated` after confirming everything works

## Support

If you encounter any issues, check:
- Application logs in `logs/gapi_gui.log`
- Database connection via `psql -U gapi -d gapi_db`
- Run migration script for detailed output: `python migrate_database.py`
