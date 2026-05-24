# Schedule Enhancement Guide

This document describes the new enhanced schedule functionality for GAPI Game Night Scheduler.

## Overview

The Game Night Scheduler has been significantly extended with:

1. **Fuzzy Search for Games** - Intelligently search for games by title, partial title, or app ID
2. **Fuzzy Search for Attendees** - Find friends in your friend list with fuzzy matching
3. **Game Images** - Display game cover art in schedule events
4. **Discord Event Integration** - Automatically create Discord scheduled events with game images
5. **Better UX** - Tag-based attendee selection with autocomplete

## Features

### 1. Fuzzy Game Search

When adding/editing a schedule event, you can search for games by:
- **Full game title**: "Portal 2"
- **Partial title**: "Port" -> matches "Portal", "Portal 2", etc.
- **App ID**: "620" (Steam app ID)
- **Prefix matching**: Games starting with your query get priority

**How to use:**
1. Click the Game field in the schedule form
2. Start typing (minimum 2 characters)
3. Dropdown will show matching games with images and app IDs
4. Click to select a game
5. The game image URL is automatically captured

### 2. Fuzzy Attendee Search

Find attendees from your friend list with:
- **Full name**: "Alice"
- **Partial name**: "Ali" -> matches "Alice", "Alison", etc.
- **Case-insensitive**: Works regardless of capitalization

**How to use:**
1. Click the Attendees field
2. Start typing a friend's name (minimum 1 character)
3. Dropdown shows matching friends
4. Click to add them
5. Added attendees appear as tags below the field
6. Click the × on a tag to remove

### 3. Game Images

- Game images are automatically fetched when you select a game via fuzzy search
- Images appear in:
  - Schedule event cards (small preview on left)
  - Discord scheduled events (as cover image)
- If no game image is available, Discord events use your bot's banner

### 4. Discord Event Integration

Create Discord scheduled events directly from your schedule:

**Automatic Creation:**
- Check "Create Discord event" when creating/editing a schedule
- When you save, the Discord event will be created with:
  - Event title and game name
  - Game image (or bot banner fallback)
  - Start/end times from schedule
  - Attendee list in description

**Manual Creation (Alternative):**
- Create schedule event normally
- On the event card, click "Create Discord Event" button
- Requires appropriate Discord permissions

**Discord Slash Command:**
Use `/scheduledevent` in Discord to create events:
```
/scheduledevent event_id: <schedule-event-id> game_name: Portal 2 image_url: <optional-url>
```

## API Reference

### Search Games

**Endpoint:** `POST /api/schedule/search-games`

**Request:**
```json
{
  "query": "portal",
  "limit": 10
}
```

**Response:**
```json
{
  "results": [
    {
      "name": "Portal 2",
      "appid": "620",
      "image_url": "https://steamcdn.com/...",
      "platform": "steam"
    }
  ],
  "count": 1
}
```

### Search Attendees

**Endpoint:** `POST /api/schedule/search-attendees`

**Request:**
```json
{
  "query": "alice",
  "limit": 10
}
```

**Response:**
```json
{
  "results": [
    {
      "name": "Alice",
      "id": "alice",
      "discord_id": "123456789"
    }
  ],
  "count": 1
}
```

### Create Schedule Event (Enhanced)

**Endpoint:** `POST /api/schedule`

**Request:**
```json
{
  "title": "Gaming Night",
  "date": "2026-03-15",
  "time": "20:00",
  "game_name": "Portal 2",
  "game_appid": "620",
  "game_image_url": "https://...",
  "attendees": ["Alice", "Bob"],
  "attendee_ids": ["alice", "bob"],
  "notes": "Bring your A-game!",
  "create_discord_event": true,
  "discord_guild_id": 123456789
}
```

**Response:**
```json
{
  "id": "a1b2c3d4",
  "title": "Gaming Night",
  "date": "2026-03-15",
  "time": "20:00",
  "game_name": "Portal 2",
  "game_appid": "620",
  "game_image_url": "https://...",
  "attendees": ["Alice", "Bob"],
  "attendee_ids": ["alice", "bob"],
  "notes": "Bring your A-game!",
  "discord_event_id": null,
  "created_at": "2026-03-02T15:30:00+00:00"
}
```

### Create Discord Event for Schedule

**Endpoint:** `POST /api/schedule/{event_id}/create-discord-event`

**Request:**
```json
{
  "guild_id": 123456789
}
```

**Response:**
```json
{
  "success": true,
  "message": "Discord event creation queued",
  "event_id": "a1b2c3d4",
  "discord_event_data": {
    "name": "Gaming Night",
    "start_time": "2026-03-15T20:00:00+00:00",
    "end_time": "2026-03-15T22:00:00+00:00"
  }
}
```

## Discord Event Details

### What Gets Sent to Discord

When a Discord event is created from a schedule:

- **Event Name**: Schedule title
- **Time**: Date and time from schedule
- **Duration**: 2 hours (default)
- **Description**:
  ```
  🎮 **Game Name**
  
  [Optional notes]
  
  👥 Attendees: Alice, Bob, Charlie
  
  📅 Created by GAPI Game Night Scheduler
  ```
- **Image**: Game image URL (with bot banner as fallback)

### Discord Permissions Required

The bot needs these permissions:
- `MANAGE_EVENTS` - To create scheduled events in server
- `CONNECT` - To access voice channels (if applicable)
- `EMBED_LINKS` - To display rich event information

## Frontend UI Components

### Game Search Dropdown

- Shows up to 10 matching games
- Displays game image (40px × 24px)
- Shows game name and App ID
- Hover effect for better UX
- Click to select

### Attendee Tags

- Once added, attendees appear as colored tags
- Tags show attendee name
- Each tag has an × to remove
- Can still edit the text field directly

### Event Cards

- Displays game image (if available)
- Shows Discord event badge if created
- "Create Discord Event" button appears if game_appid exists but no discord_event_id

## Configuration

### Enable Discord Integration

1. Ensure your Discord bot is set up with proper permissions
2. The bot needs MANAGE_EVENTS permission on your server
3. Set `discord_bot_token` in `config.json`

### Game Images

Images are sourced from:
1. Steam: Game header images (automatically via Steam API)
2. Epic Games: Game image URLs
3. GOG: Product images
4. Fallback: Discord bot banner

## Troubleshooting

### Fuzzy Search Not Working

- Ensure you're typing at least 2 characters for games, 1 for attendees
- Check that games/friends are loaded in your GAPI instance
- Verify no browser console errors

### Discord Event Not Creating

- Check bot has MANAGE_EVENTS permission
- Ensure guild_id is specified (required for event creation)
- Check Discord bot is online and responsive
- Bot needs appropriate intents enabled in Discord Developer Portal

### Game Image Not Showing

- Some games may not have images in Steam API
- Bot will attempt to use its banner as fallback
- You can manually specify image_url in API calls
- Check image URL is accessible (not behind auth)

### Attendee Search Empty

- Ensure friends are added to your multiuser setup (users.json)
- Friend list must have 'name' field populated
- Check Discord user linking is configured (if using Discord IDs)

## Future Enhancements

Potential improvements for future versions:
- Video game trailer preview in Discord events
- Auto-update Discord event if schedule changes
- Friend availability checking before event
- Calendar integration (iCal, Google Calendar)
- Event reminders (Discord notifications)
- Voting/polling for game selection during event
- Cross-guild event creation

## Example Workflow

1. **Create Event**:
   - Title: "Friday Coop Night"
   - Click Game field, search "Portal"
   - Select "Portal 2" from dropdown
   - Click Attendees field, search "alice"
   - Click "Alice" to add
   - Add more attendees the same way
   - Check "Create Discord event"
   - Save

2. **Event Created**:
   - Schedule event appears with Portal 2 image
   - Discord event created automatically
   - Discord server shows scheduled event with game image
   - Friends can join the Discord event

3. **Edit Event**:
   - Click "Edit" on event card
   - Make changes
   - Save (Discord event updates if needed)

## Technical Details

### Fuzzy Matching Algorithm

Uses Python's `difflib.SequenceMatcher` for matching:
- Exact matches get priority (1.0 score)
- Prefix matches get boost (0.9+)
- Other matches use sequence similarity ratio
- Minimum threshold: 0.6 (60% similarity)
- Results sorted by score, then alphabetically

### Game Image Selection

Priority order:
1. User-provided image_url from fuzzy search
2. Game's native image from platform API
3. Discord bot banner (fallback)

### Event Data Storage

Schedule events stored with:
- `game_appid`: Platform-specific game ID
- `game_image_url`: URL of game image
- `attendee_ids`: List of attendee identifiers
- `discord_event_id`: Discord event ID (if created)

## Notes

- All fields are case-insensitive for searching
- Special characters are ignored in fuzzy matching
- Game App IDs can be Steam, Epic, or GOG format
- Discord events are standalone (deleting schedule event doesn't delete Discord event)
- Times are stored in user's local timezone, displayed as-is

