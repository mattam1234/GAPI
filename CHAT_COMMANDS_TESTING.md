# Chat Autocomplete & Command Visibility - Fixes & Testing Guide

## What Was Fixed

### 1. Autocomplete Positioning
- Restructured HTML so autocomplete dropdown appears below the input field
- Changed from `bottom:46px` (relative to flex container) to `top:100%` (directly below input)
- Increased z-index from 15 to 1000 for better visibility

### 2. Autocomplete Event Handling
- Replaced `onclick` attributes with `addEventListener` for more reliable click handling
- Added console logging to help diagnose any remaining issues

### 3. Command-Only Messages
- Added `command_only` column to ChatMessage database model
- Command responses like `/help`, `/room status`, `/picker status` are now only visible to:
  - The user who sent the command
  - Admins (all message visibility)
- Regular chat messages are visible to all room members

### 4. Database Migration
- Created `migrate_add_command_only.sql` for SQL Server
- SQLAlchemy will auto-create the column on startup with default value

## Testing Instructions

### Test 1: Verify Functions Are Loaded
1. Open browser Developer Tools (F12)
2. Go to Console tab
3. You should see a log message: `Chat functions loaded: { ... }`
4. All functions should show `true`

### Test 2: Test Autocomplete
1. Click the Chat tab
2. Click in the input field below (where it says "Type a message…")
3. Type forward slash: `/`
4. A dropdown should appear with command suggestions
5. You should see suggestions like `/help`, `/room create`, `/room create-private`, etc.
6. Use ↑ (arrow up) and ↓ (arrow down) to navigate
7. Press Enter or Tab to apply suggestion
8. Check console (F12) for logs: `Chat input changed`, `Suggestions:`, `Rendering autocomplete`

### Test 3: Test `/help` Command
1. In chat input, type: `/help`
2. Click Send button
3. You should see the help text appear in your chat (only visible to you)
4. The message will show only in your view, not to other room members

### Test 4: Create a Private Room
1. In chat input, type one of:
   - `/room create-private myroom`
   - `/room create myroom private`
2. Click Send
3. You should see confirmation message in chat
4. The new room should automatically appear in the "Room:" dropdown
5. The room will be private -- only invited members can access it

### Test 5: View Room Status (Command-Only)
1. Type: `/room status`
2. Send
3. You'll see the room info, but only in your chat (not visible to others)

## If Autocomplete Still Doesn't Show

Check browser console (F12) for these errors:
1. `chat-input not found` - input element missing
2. `chat-autocomplete box not found` - autocomplete div missing
3. `Chat input changed:` log doesn't appear - oninput event not firing

Check the HTML structure - make sure the input has:
- `id="chat-input"`
- `oninput="handleChatInputChange()"`
- `onkeydown="handleChatInputKeydown(event)"`

## If Private Room Creation Fails

Run this SQL command to ensure the column exists:

SQL Server:
```sql
IF COL_LENGTH('dbo.chat_messages', 'command_only') IS NULL
    ALTER TABLE dbo.chat_messages ADD command_only BIT DEFAULT 0;
```

PostgreSQL:
```sql
ALTER TABLE chat_messages
ADD COLUMN IF NOT EXISTS command_only BOOLEAN DEFAULT false;
```

Then restart the application.

## Files Modified

- `templates/index.html`: Autocomplete UI, positioning, and event handlers
- `database.py`: Added `command_only` column to ChatMessage model
- `gapi_gui.py`: Updated command handlers and responses
- `app/services/chat_service.py`: Added `command_only` parameter support
- `migrate_add_command_only.sql`: Migration file for existing databases
