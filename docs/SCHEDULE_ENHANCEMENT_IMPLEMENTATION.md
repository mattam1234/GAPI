# Schedule Enhancement Implementation Summary

## What Was Added

This implementation extends the GAPI Game Night Scheduler with comprehensive fuzzy search capabilities and Discord event integration.

## Files Modified

### 1. Backend Services

**File: `app/services/schedule_service.py`**
- Extended editable fields to include: `game_appid`, `attendee_ids`, `discord_event_id`, `game_image_url`
- Updated `add_event()` to accept new fields
- Added `set_discord_event_id()` method to store Discord event IDs

### 2. API Endpoints

**File: `gapi_gui.py`**
- Added `POST /api/schedule/search-games` - Fuzzy search for games by title/App ID
- Added `POST /api/schedule/search-attendees` - Fuzzy search for attendees
- Added `POST /api/schedule/<event_id>/create-discord-event` - Create Discord event from schedule
- Updated `POST /api/schedule` to accept and handle new schedule fields
- Added helper functions:
  - `_fuzzy_search_games()` - Game search with difflib
  - `_fuzzy_search_users()` - Attendee search with difflib

### 3. Discord Bot Integration

**File: `discord_bot.py`**
- Added `async create_game_night_event()` method - Creates Discord scheduled events with game images
- Added `/scheduledevent` slash command - Interactive Discord command to create events
- Automatic image handling with fallback to bot banner

### 4. Frontend UI

**File: `templates/index.html`**
- Enhanced schedule form HTML with:
  - Autocomplete inputs for games and attendees
  - Dropdown menus for search results
  - Tag-based attendee display
  - Discord event creation checkbox
  - Hidden fields for game_appid and game_image_url
- Updated JavaScript functions:
  - `searchGames()` - Real-time game search with debouncing
  - `searchAttendees()` - Real-time attendee search
  - `selectGame()` - Game selection with image capture
  - `addAttendee()` / `removeAttendee()` - Tag management
  - `renderEventCard()` - Enhanced display with game images and Discord badges
  - `submitScheduleForm()` - Updated to handle new fields
  - `createDiscordEventForSchedule()` - Manual Discord event trigger
- Added click-outside handler to close dropdowns

### 5. Documentation

**File: `SCHEDULE_ENHANCEMENT.md`**
- Complete user guide for new features
- API reference with examples
- Configuration instructions
- Troubleshooting guide

## Key Features Implemented

### 1. Fuzzy Game Search
- Uses Python's `difflib.SequenceMatcher` for smart matching
- Minimum similarity threshold: 60%
- Priority matching for exact and prefix matches
- Displays game images in dropdown
- Captures game App ID and image URL on selection

### 2. Fuzzy Attendee Search
- Searches friend list by name
- Case-insensitive matching
- Tag-based UI for easy management
- Simple × button to remove attendees

### 3. Game Image Integration
- Automatically fetches game images from Steam/Epic/GOG
- Displays in schedule event cards
- Passes to Discord as event cover image
- Fallback to bot banner if no game image available

### 4. Discord Event Creation
- Endpoint-based creation from schedule
- Automatic title, description, and image
- Includes attendee list in Discord description
- Discord slash command support
- Event duration defaulted to 2 hours

### 5. Enhanced UX
- Real-time search with debouncing (300ms)
- Autocomplete dropdowns
- Tag-based attendee selection
- Visual feedback (Discord event badge on cards)
- Smooth scrolling to form on edit

## Technical Architecture

### Fuzzy Matching Algorithm

```
1. Exact match check (score: 1.0)
2. App ID match check (score: 0.95)
3. Prefix match check (score: 0.9+)
4. Sequence similarity (score: ratio)
5. Filter by minimum threshold (0.6)
6. Sort by score DESC, then name ASC
```

### Data Flow for Discord Event Creation

```
Frontend Schedule Form
    ↓
POST /api/schedule
    ↓
ScheduleService.add_event() → Stores event with game data
    ↓
[Optional] POST /api/schedule/{id}/create-discord-event
    ↓
GAPIBot.create_game_night_event()
    ↓
Fetches game image URL
    ↓
guild.create_scheduled_event()
    ↓
Discord Event Created with Image & Attendee List
```

## API Contract

### Schedule Event Object (Enhanced)

```json
{
  "id": "a1b2c3d4",
  "title": "String (required)",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "attendees": ["Name1", "Name2"],
  "game_name": "String (optional)",
  "game_appid": "String (optional, e.g., '620')",
  "attendee_ids": ["id1", "id2"],
  "game_image_url": "https://...",
  "notes": "String (optional)",
  "discord_event_id": "12345 or null",
  "created_at": "ISO8601 timestamp",
  "updated_at": "ISO8601 timestamp"
}
```

### Search Game Response

```json
{
  "results": [
    {
      "name": "Game Name",
      "appid": "620",
      "image_url": "https://...",
      "platform": "steam"
    }
  ],
  "count": 1
}
```

### Search Attendee Response

```json
{
  "results": [
    {
      "name": "Friend Name",
      "id": "identifier",
      "discord_id": "123456789"
    }
  ],
  "count": 1
}
```

## Integration Points

### With Existing GAPI Components

- **MultiUserPicker**: Used to fetch game list and user list
- **ScheduleService**: Core schedule management with new fields
- **GAPIBot**: Discord bot integration for event creation
- **Request validation**: Uses existing picker_lock for thread safety

### Configuration Required

```json
{
  "discord_bot_token": "YOUR_TOKEN",
  "steam_api_key": "YOUR_API_KEY"
}
```

## Performance Considerations

1. **Debouncing**: Search requests debounced at 300ms to reduce API load
2. **Result Limiting**: Dropdown limited to 10 results per search
3. **Image Caching**: Game images cached by browser (standard HTTP caching)
4. **Async Discord Creation**: Discord event creation runs asynchronously

## Security Features

1. **XSS Prevention**: All user input HTML-escaped in UI
2. **Input Validation**: Required fields validated on both frontend and backend
3. **CSRF Protection**: Uses existing safeFetch() wrapper
4. **Rate Limiting**: Uses existing Flask-Limiter integration

## Browser Compatibility

- Modern browsers (Chrome, Firefox, Safari, Edge)
- ES6+ features used (async/await, fetch, template literals)
- Requires JavaScript enabled
- Responsive design for mobile

## Testing Scenarios

### Test 1: Game Search
1. Open Schedule tab
2. Click Game field
3. Type "port" → should show Portal games
4. Click Portal 2 → should populate game name and image URL
5. Type "620" (Steam ID) → should show Portal 2 directly

### Test 2: Attendee Search
1. Open Schedule tab
2. Click Attendees field
3. Type "ali" → should show matching friends
4. Click to add → should appear as tag
5. Click × on tag → should remove
6. Should show list in final event

### Test 3: Discord Event Creation
1. Create schedule event with game
2. Check "Create Discord event"
3. Save event
4. Discord event should appear in your server
5. Event should have game image
6. Event description should list attendees

### Test 4: Edit Schedule
1. Create event with game and attendees
2. Click Edit
3. All fields should populate (including game image)
4. Add another attendee
5. Save
6. Event should update with new attendee

## Known Limitations

1. **Discord Event Updates**: Modifying schedule doesn't update existing Discord event (by design)
2. **Image Availability**: Not all games have images available
3. **Friend List**: Only shows friends configured in multiuser setup
4. **Timezone**: Stores times as-is, no timezone conversion
5. **Attendee Format**: Expects user names as configured in multiuser setup

## Future Enhancement Ideas

- 🔄 **Sync Discord Changes**: Update Discord event when schedule changes
- 📱 **Mobile Optimizations**: Touch-friendly attendee selection
- 🎮 **Game Details**: Show game description, playtime, achievements
- 📊 **Analytics**: Track most popular games/times
- 🔔 **Notifications**: Send Discord reminders before event
- 🗳️ **Voting**: Let attendees vote on which game to play
- 📅 **Calendar Export**: Export schedule to iCal/Google Calendar
- 🌍 **Timezone Support**: Convert times across timezones
- 💬 **Comments**: Allow attendees to add notes to events

## Debugging Tips

### Enable Logging
- Check browser console (F12) for frontend errors
- Check Flask logs for backend errors
- Discord-py logs available if DISCORD_LOG_LEVEL set

### Common Issues

**Dropdowns not showing:**
- Check browser console for JS errors
- Ensure search queries are long enough (games: 2+, attendees: 1+)
- Verify API endpoints are responding

**Game images not showing:**
- Check if appid is correct
- Verify image URL is accessible
- Check bot banner is accessible as fallback

**Discord event creation failing:**
- Ensure bot has MANAGE_EVENTS permission
- Check bot is online and responsive
- Verify guild_id is correct

## Code Statistics

- **Lines Added**: ~500 (split across files)
- **New Endpoints**: 3 API endpoints
- **New Methods**: 5 (3 backend, 2 frontend handlers)
- **New UI Components**: 4 (dropdowns, tags, buttons, badges)
- **Test Coverage**: Recommended to add unit tests for fuzzy search

## Deployment Checklist

- [ ] Update database schema (optional - uses existing fields as JSON)
- [ ] Test fuzzy search with sample games/friends
- [ ] Verify Discord bot permissions
- [ ] Test Discord event creation
- [ ] Update user documentation
- [ ] Set up logging for monitoring
- [ ] Test on mobile devices
- [ ] Validate image loading from all platforms
- [ ] Test error handling scenarios
- [ ] Monitor performance with real data

## Conclusion

The Schedule Enhancement provides a modern, user-friendly experience for planning game nights with your friends. The fuzzy search makes it easy to find games and attendees, while Discord integration keeps everyone on the same page with automatically created events featuring game artwork.

Users can now create rich, interactive game night events with just a few clicks!

