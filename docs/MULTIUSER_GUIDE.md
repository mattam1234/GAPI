# GAPI Multi-User and Discord Integration Guide

## Overview

GAPI now supports multiple users and Discord integration, making it perfect for finding co-op games to play with friends!

## Components

1. **multiuser.py** - Core multi-user functionality
2. **discord_bot.py** - Discord bot integration
3. **gapi_gui.py** - Web GUI with user management
4. **users.json** - User data storage (auto-created)
5. **discord_config.json** - Discord bot configuration (auto-created)

## User Data Structure

Each user has the following information:
- **name**: Display name
- **email**: Email address (optional, for future features)
- **steam_id**: Steam 64-bit ID (required)
- **discord_id**: Discord user ID (optional, for bot integration)

## Web GUI Usage

### Managing Users

1. **Add a User:**
   - Go to the "Users" tab
   - Fill in the form with user details
   - Name and Steam ID are required
   - Email and Discord ID are optional
   - Click "Add User"

2. **View Users:**
   - All users are displayed in a list
   - Shows name, email, Steam ID, and Discord ID
   - Remove button available for each user

3. **Multi-User Game Picking:**
   - Go to the "Multi-User" tab
   - Select users by checking their boxes
   - Optionally enable "Co-op/Multiplayer Games Only"
   - Click "Pick Common Game" for a random selection
   - Click "Show Common Games" to see the full list

## Discord Bot Usage

### Setup

1. **Create a Discord Bot:**
   - Go to https://discord.com/developers/applications
   - Click "New Application"
   - Go to "Bot" section and click "Add Bot"
   - Copy the bot token
   - Enable "Message Content Intent" in bot settings

2. **Configure GAPI:**
   ```json
   {
     "steam_api_key": "YOUR_STEAM_API_KEY",
     "steam_id": "YOUR_STEAM_ID",
     "discord_bot_token": "YOUR_DISCORD_BOT_TOKEN"
   }
   ```

3. **Invite Bot to Server:**
   - Go to OAuth2 > URL Generator
   - Select "bot" scope
   - Select permissions: Send Messages, Embed Links, Add Reactions, Read Message History
   - Copy and use the generated URL

4. **Run the Bot:**
   ```bash
   python3 discord_bot.py
   ```

### Commands

#### User Management

**Link Steam Account:**
```
!gapi link <steam_id> [username]
```
Links your Discord account to a Steam account.
- `steam_id`: Your Steam 64-bit ID (required)
- `username`: Display name (optional, defaults to Discord username)

Example: `!gapi link 76561198000000001 JohnDoe`

**Unlink Account:**
```
!gapi unlink
```
Removes the link between your Discord and Steam accounts.

**List Users:**
```
!gapi users
```
Shows all users who have linked their Steam accounts.

#### Game Picking

**Pick a Game:**
```
!gapi pick [@user1 @user2 ...]
```
Picks a random co-op game that all mentioned users own.
- If no users mentioned, picks from all linked users
- Automatically filters to co-op/multiplayer games

Example: `!gapi pick @Alice @Bob`

**Start Vote:**
```
/vote [duration] [candidates]
```
Starts a game-choice voting session for all linked users.
- `duration`: Voting time in seconds (default: 60)
- `candidates`: Number of game options to vote on (default: 5, max: 10)
- The bot picks N random games from the common library and posts them with number emoji reactions
- Users react with the number emoji (1️⃣–🔟) of their preferred game
- After the timer ends, the bot tallies reactions and announces the winning game with a full breakdown

Example: `/vote duration:120 candidates:4` (2-minute vote, 4 game options)

**Show Common Games:**
```
!gapi common [limit]
```
Lists games owned by all linked users.
- `limit`: Number of games to show (default: 10)

Example: `!gapi common 20`

**Show Statistics:**
```
!gapi stats
```
Displays library statistics for all linked users.
- Total games per user
- Common games count
- Total unique games

## Python API Usage

You can also use the multi-user functionality directly in Python:

```python
from multiuser import MultiUserPicker

# Initialize
picker = MultiUserPicker(steam_api_key="YOUR_API_KEY")

# Add users
picker.add_user(
    name="Alice",
    steam_id="76561198000000001",
    email="alice@example.com",
    discord_id="123456789012345678"
)

picker.add_user(
    name="Bob",
    steam_id="76561198000000002",
    email="bob@example.com",
    discord_id="987654321098765432"
)

# Find common games
common_games = picker.find_common_games()
print(f"Found {len(common_games)} common games")

# Filter for co-op games
coop_games = picker.filter_coop_games(common_games)
print(f"Found {len(coop_games)} co-op games")

# Pick a random common game
game = picker.pick_common_game(coop_only=True)
if game:
    print(f"Play: {game['name']}")
    print(f"Owned by: {', '.join(game['owners'])}")

# Get statistics
stats = picker.get_library_stats()
print(f"Total users: {len(stats['users'])}")
print(f"Common games: {stats['common_games_count']}")
```

### Voting System API

```python
import random
from multiuser import MultiUserPicker

picker = MultiUserPicker(config)

# Pick candidate games from common library
common_games = picker.find_common_games()
candidates = random.sample(common_games, min(5, len(common_games)))

# Create a timed voting session (60-second window)
session = picker.create_voting_session(
    candidates=candidates,
    voters=["Alice", "Bob", "Charlie"],
    duration=60
)
print(f"Session ID: {session.session_id}")

# Users cast votes
ok, msg = session.cast_vote("Alice", "730")   # vote for CS2 (appid 730)
ok, msg = session.cast_vote("Bob", "570")     # vote for Dota 2
ok, msg = session.cast_vote("Charlie", "730")

# Check vote tallies
results = session.get_results()
for app_id, data in results.items():
    print(f"{data['game']['name']}: {data['count']} vote(s)")

# Close the session and get the winner
winner = picker.close_voting_session(session.session_id)
if winner:
    print(f"🏆 Winner: {winner['name']}")

# Retrieve an existing session by ID
existing = picker.get_voting_session(session.session_id)
```

### Web GUI Voting API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `POST` | `/api/voting/create` | Create a voting session |
| `POST` | `/api/voting/<id>/vote` | Cast a vote |
| `GET`  | `/api/voting/<id>/status` | Get tallies and session state |
| `POST` | `/api/voting/<id>/close` | Close session and reveal winner |

**Create session** body:
```json
{
  "users": ["Alice", "Bob"],
  "num_candidates": 5,
  "duration": 60,
  "coop_only": false
}
```

**Cast vote** body:
```json
{
  "user_name": "Alice",
  "app_id": "730"
}
```

## File Locations

- **users.json**: Stores user profiles (created in the same directory as scripts)
- **discord_config.json**: Stores Discord user mappings (created when bot runs)
- **config.json**: Main configuration file (you need to create this)

## Tips

1. **Finding Steam ID:**
   - Go to https://steamid.io/
   - Enter your Steam profile URL or username
   - Copy the steamID64 value

2. **Finding Discord ID:**
   - Enable Developer Mode in Discord (User Settings > Advanced)
   - Right-click on your username
   - Click "Copy ID"

3. **Multi-User Game Selection:**
   - More users = fewer common games
   - Use genre filters to narrow down choices
   - Co-op filter helps find games for playing together

4. **Discord Bot Permissions:**
   - Bot needs "Read Messages" and "Send Messages"
   - "Add Reactions" for voting feature
   - "Embed Links" for rich game displays

## Troubleshooting

**"No common games found":**
- Check that all users have public Steam profiles
- Verify Steam IDs are correct
- Try with fewer users
- Check if co-op filter is too restrictive

**Discord bot not responding:**
- Verify bot token is correct in config.json
- Check that Message Content Intent is enabled
- Ensure bot has proper permissions in the server
- Check that users have linked their Steam accounts

**User already exists error:**
- Each Steam ID and Discord ID must be unique
- Remove the existing user first if you need to update
- Or use the update_user method in Python

## Advanced Features

### Custom Player Count
```python
# Find games for exactly 4 players
game = picker.pick_common_game(
    user_names=["Alice", "Bob", "Charlie", "Dave"],
    coop_only=True,
    max_players=4
)
```

### Update User Information
```python
# Update by name, steam_id, or discord_id
picker.update_user(
    identifier="Alice",
    email="newemail@example.com",
    discord_id="111111111111111111"
)
```

### Get Specific Users' Games
```python
# Only get games for specific users
libraries = picker.get_user_libraries(["Alice", "Bob"])
for user, games in libraries.items():
    print(f"{user} has {len(games)} games")
```

## Future Enhancements

Planned features that will use the email field:
- Email notifications when games are picked
- Weekly game recommendations
- Friend invitations via email
- Game sharing notifications

## Security Notes

- Keep your Steam API key private
- Keep your Discord bot token private
- Don't commit config.json to version control
- Use .gitignore to exclude sensitive files
- User data is stored locally and not transmitted anywhere except Steam API calls
