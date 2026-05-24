# GAPI Discord Bot Setup Guide

Complete guide to set up and use the GAPI Discord Bot with achievement tracking and ignore list features.

## Quick Start

### 1. Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name (e.g., "GAPI Bot")
3. Go to "Bot" section and click "Add Bot"
4. Under TOKEN, click "Reset Token" and copy it
5. Enable these Intents:
   - Message Content Intent
   - Server Members Intent
   - Guilds
   - Guild Messages
   - Reactions / Read Message History so users can join linked sessions with ✅

### 2. Create App Config

Create or update `config.json` in your GAPI directory:

```json
{
    "discord_bot_token": "YOUR_DISCORD_BOT_TOKEN_HERE",
    "steam_api_key": "YOUR_STEAM_API_KEY_HERE",
    "app_url": "http://localhost:5000"
}
```

Get your Steam API key from: https://steamcommunity.com/dev/apikey

### 3. Invite Bot to Server

1. In Developer Portal, go to OAuth2 → URL Generator
2. Select scopes: `bot`
3. Select permissions:
   - Send Messages
   - Embed Links
   - Read Message History
   - Read Messages/View Channels
4. Copy the generated URL and open it in browser
5. Select your server and authorize

### 4. Run the Bot

```bash
cd c:\Users\matta\source\repos\GAPI
python discord_bot.py
```

Or with the main Flask server:

```bash
python gapi_gui.py
# In another terminal:
python discord_bot.py
```

## Commands

### Account Linking

**`/link <steam_id> [username]`**
- Link your Discord account to a Steam ID
- Example: `/link 76561198000000000`
- Optional custom username if different from Discord name

**`/unlink`**
- Unlink your Discord account from Steam

**`/users`**
- List all Discord users and their linked Steam accounts

### Game Picking

**`/pick [max_players]`**
- Pick a random game for all linked users
- Respects ignore lists and shared rules

**`/common [limit]`**
- Show games common to all linked users
- Default limit: 10 games

**`/vote [duration] [candidates]`**
- Start a voting session to pick a game
- Duration in seconds (default: 60)
- Number of game candidates (default: 5, max: 10)
- Users react or run subfunctions to vote

### Ignore List Management

**`/ignore list`**
- View your no-play list
- Shows game names, app IDs, and reasons for ignoring

**`/ignore add <app_id> <game_name>`**
- Add a game to your ignore list
- Example: `/ignore add 534380 "Loop Hero"`

**`/ignore remove <app_id>`**
- Remove a game from your ignore list
- Example: `/ignore remove 534380`

**Feature:** When picking games for multi-user sessions, games ignored by ALL participants are excluded from the pool.

### Achievement Hunting

**`/hunt start <app_id> <game_name> [difficulty]`**
- Start a new achievement hunting session
- Difficulty options: `easy`, `medium` (default), `hard`, `extreme`
- Example: `/hunt start 570 "Dota 2" hard`

**`/hunt progress`**
- View your active achievement hunts
- Shows game name and progress (unlocked/total achievements)

### Statistics

**`/stats`**
- View combined library statistics for all linked users
- Shows total games per user and common games count

## Linked Web Sessions

You can create a session in the web UI and mirror it into a Discord server/channel:

1. Start both `gapi_gui.py` and `discord_bot.py`
2. Save your Discord ID in the web UI **Settings**
3. Let the bot join your server so it can cache the guild, available channels, and your membership
4. In the web UI **🎯 Sessions** tab, choose the Discord server/channel and create the session
5. The bot posts one session status message in that channel and keeps editing it as users join, picks are made, and results finalize

### Join flow for Discord friends

- Linked users join or leave by reacting with ✅ on the session message
- Unlinked users receive a DM with onboarding instructions and a 5-minute join window
- When they finish linking their GAPI account and game-service IDs, the pending join is completed automatically

### Result presentation

- **Web UI:** lootbox-style final reveal animation
- **Discord:** plain embed/message updates only, to avoid spam

## Multi-User Shared Rules

When multiple users are linked to the bot:

1. **Shared Ignore Rules**: If all linked users have the same game in their ignore list, that game is excluded from picks
2. **Common Games Only**: Game picking can be filtered to only common games across users
3. **Voting Sessions**: Great for groups to democratically choose the next game

## Usage Examples

### Example 1: Group Game Night

```
User A: /link 76561198000000001 Alice
User B: /link 76561198000000002 Bob
User C: /link 76561198000000003 Charlie

@Admin: /vote 120 8
# Voting session starts with 8 game candidates for 2 minutes
# Users react to vote on their favorite
# Winner is announced after voting ends
```

### Example 2: Respect Ignore Lists

```
Alice: /ignore add 620 "Portal 2"  # Alice doesn't want Portal 2
Bob: /ignore add 220 "Half-Life 2"  # Bob doesn't want HL2
Charlie: (doesn't ignore anything)

Admin: /pick
# Bot suggests a game that:
# - Alice has but is ignoring (excluded for Alice if picking solo)
# - Is common to all three if /common is used
# - Respects Bob's ignore list
```

### Example 3: Achievement Hunt Tracking

```
Alice: /hunt start 730 "CS:GO" hard
# Alice starts hunting hard achievements in CS:GO

Alice: /hunt progress
# Shows CS:GO with progress counter

Later...
Alice: /hunt start 620 "Portal 2" medium
# Now tracking two hunts

Alice: /hunt progress
# Shows both active hunts with progress
```

## Configuration Options

Edit `config.json` for:

- `discord_bot_token`: Your Discord bot token (required)
- `steam_api_key`: Your Steam API key (optional, for Steam data)
- `app_url`: Base web URL used in Discord DMs and `/url`

## Troubleshooting

### Bot doesn't respond to commands
- Check bot has "Applications.commands" scope
- Verify bot is online in server member list
- Ensure MESSAGE CONTENT INTENT is enabled
- Verify your `config.json` has a valid `discord_bot_token`

### "Failed to add game" error
- Ensure your account is created/logged in on the web dashboard
- Check app_id is a valid Steam game (check on SteamDB)
- Verify PostgreSQL is running (for database persistence)

### Games not being picked
- Ensure users have their Steam IDs linked via `/link`
- Check users have games in their Steam library
- Verify database is initialized with `python -c "from database import init_db; init_db()"`

### Can't find game in ignore list
- Check app_id is correct (use SteamDB to find it)
- Ensure game was added to YOUR account (not another user's)
- Use `/ignore list` to verify it was added

## API Integration

The Discord bot connects to the Flask API:

- Base URL: `http://localhost:5000`
- Endpoints used:
  - `POST /api/ignored-games` - Add/remove ignored games
  - `GET /api/ignored-games` - Fetch user's ignore list
  - `POST /api/achievement-hunt` - Start hunt
  - `GET /api/achievements` - View hunts
  - `POST /api/pick` - Pick random game
  - `GET /api/multiuser/common` - Get common games

## Advanced: User Mapping Storage

The bot stores Discord account links in the main database on each user row:

```json
{
    "username": "alice",
    "steam_id": "76561198000000000",
    "discord_id": "123456789"
}
```

This keeps mappings user-separated and shared safely between the web UI and the Discord bot.

## Support

For issues or feature requests, check:
- `FEATURES_SUMMARY.md` - Overview of all features
- `DATABASE_SETUP.md` - Database configuration
- `README.md` - Main documentation

---

**Last Updated**: February 2026
**GAPI Version**: 2.0
