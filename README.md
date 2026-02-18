# GAPI - Game Picker with SteamDB Integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)

GAPI is a game picker tool that helps you decide what to play from your Steam library. It randomly picks games based on various filters and displays detailed information from Steam Store and SteamDB. Available in both **Web GUI** and **CLI** modes!

## Features

- 🌐 **Modern Web GUI**: Beautiful browser-based interface with tabs for game picking, library browsing, favorites, statistics, and multi-user management
- 👥 **Multi-User Support**: Link multiple Steam accounts and find common games among friends
- 🎮 **Co-op Game Finder**: Automatically filter and pick co-op/multiplayer games for your group
- 🤖 **Discord Bot Integration**: Pick games with friends directly from Discord with voting and auto-selection
- 🎲 **Random Game Selection**: Pick a random game from your entire Steam library
- 🎯 **Smart Filters**: Filter by playtime (unplayed, barely played, well-played games)
- 🎨 **Genre Filtering**: Filter games by genre/tags (Action, RPG, Strategy, etc.)
- ⭐ **Favorites System**: Mark games as favorites and pick from your favorite games
- 📊 **Library Statistics**: View stats about your game collection including top played games
- 🔍 **Detailed Game Info**: Fetch descriptions, genres, release dates, and Metacritic scores
- 🔗 **Direct Links**: Quick access to Steam Store and SteamDB pages
- 🎨 **Colorful Interface**: Easy-to-read colored terminal output (CLI mode)
- 💾 **Smart History**: Avoids suggesting recently picked games
- 📤 **Export/Import**: Export and import your game picking history
- ⚡ **CLI Mode**: Command-line arguments for scripting and quick picks
- 🔧 **Configurable**: Custom playtime filters and settings

## Prerequisites

- Python 3.6 or higher
- Steam API Key (get one at https://steamcommunity.com/dev/apikey)
- Your Steam ID (find it at https://steamid.io/)
- (Optional) Discord Bot Token for Discord integration (get one at https://discord.com/developers/applications)

## Installation

1. Clone this repository:
```bash
git clone https://github.com/mattam1234/GAPI.git
cd GAPI
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

Or use the automated setup script:
```bash
bash setup.sh
```

3. Configure your Steam credentials:
```bash
cp config_template.json config.json
```

4. Edit `config.json` and add your Steam API key and Steam ID:
```json
{
  "steam_api_key": "YOUR_ACTUAL_API_KEY",
  "steam_id": "YOUR_STEAM_ID"
}
```

### Try the Demo

Want to try GAPI without setting up Steam credentials?

**Web GUI Demo:**
```bash
python3 gapi_gui.py --demo
```
Then open your browser to http://127.0.0.1:5000

**CLI Demo:**
```bash
python3 demo.py
```

Both demos run GAPI with mock game data so you can see how it works.

## Usage

GAPI can be used in two modes: **Web GUI** or **Command-Line Interface**.

### Web GUI Mode (Recommended)

Run the web-based graphical interface:
```bash
python3 gapi_gui.py
```

Then open your browser to: **http://127.0.0.1:5000**

The Web GUI provides:
- **Pick a Game Tab**: Select filters and pick random games with a beautiful interface
- **Library Tab**: Browse your entire game library with search functionality
- **Favorites Tab**: Manage your favorite games
- **Statistics Tab**: View detailed statistics and top played games
- **Users Tab**: Add and manage multiple user accounts (Steam ID, Discord ID, email, name)
- **Multi-User Tab**: Pick common games among multiple users, perfect for finding co-op games

![GAPI Web GUI](https://github.com/user-attachments/assets/ef5ae18a-da33-4332-91b0-9b2b3d67a481)
![User Management](https://github.com/user-attachments/assets/4edf7a65-c401-4206-8384-55d0f01740e1)
![Multi-User Picker](https://github.com/user-attachments/assets/59e3977f-2c7f-4112-b1bf-f3f76d7e8df9)

### Multi-User Features

**Adding Users via Web GUI:**
1. Navigate to the **Users** tab
2. Fill in the user information:
   - Name (required)
   - Email (optional, for future features)
   - Steam ID (required)
   - Discord ID (optional, for Discord bot integration)
3. Click "Add User"

**Finding Common Games:**
1. Go to the **Multi-User** tab
2. Select the players you want to include
3. Optionally check "Co-op/Multiplayer Games Only"
4. Click "Pick Common Game" to get a random game everyone owns
5. Or click "Show Common Games" to see the full list

### Discord Bot Integration

GAPI includes a Discord bot that lets you and your friends pick games together!

**Setup:**
1. Create a Discord bot at https://discord.com/developers/applications
2. Add your bot token to `config.json`:
```json
{
  "steam_api_key": "YOUR_STEAM_API_KEY",
  "steam_id": "YOUR_STEAM_ID",
  "discord_bot_token": "YOUR_DISCORD_BOT_TOKEN"
}
```

3. Run the bot:
```bash
python3 discord_bot.py
```

**Discord Commands:**
- `!gapi link <steam_id> [username]` - Link your Discord account to your Steam account
- `!gapi unlink` - Unlink your Steam account
- `!gapi users` - List all users with linked Steam accounts
- `!gapi vote [duration]` - Start a voting session (react with ✅ to join)
- `!gapi pick [@user1 @user2]` - Pick a random common game for mentioned users
- `!gapi common [limit]` - Show common games owned by all linked users
- `!gapi stats` - Display library statistics for all users

**Example Discord Workflow:**
```
User1: !gapi link 76561198000000001 User1
Bot: ✅ Linked @User1 to Steam ID: 76561198000000001

User2: !gapi link 76561198000000002 User2
Bot: ✅ Linked @User2 to Steam ID: 76561198000000002

User1: !gapi vote 60
Bot: 🗳️ Vote to Play! React with ✅ to join...
[Users react with ✅]
[After 60 seconds]
Bot: 🎮 Let's play: Portal 2!
     Players: User1, User2
     Steam Store: [link]
```

### Command-Line Interface (CLI) Mode

Run the application in terminal mode:
```bash
python3 gapi.py
```

### Command-Line Options

GAPI supports both interactive and non-interactive modes:

**Interactive CLI Mode** (default):
```bash
python3 gapi.py
```

**Non-Interactive CLI Mode** - Pick a game and exit:
```bash
# Pick any random game
python3 gapi.py --random

# Pick from unplayed games
python3 gapi.py --unplayed

# Pick from barely played games (< 2 hours)
python3 gapi.py --barely-played

# Pick from well-played games (> 10 hours)
python3 gapi.py --well-played

# Custom playtime filter
python3 gapi.py --min-hours 5 --max-hours 50

# Filter by genre
python3 gapi.py --genre "Action,RPG"

# Pick from favorites
python3 gapi.py --favorites

# Combine filters (e.g., unplayed Action games)
python3 gapi.py --unplayed --genre "Action"

# Show statistics only
python3 gapi.py --stats

# Skip detailed information (faster)
python3 gapi.py --random --no-details

# Export/Import history
python3 gapi.py --export-history my_history.json
python3 gapi.py --import-history my_history.json

# List favorites
python3 gapi.py --list-favorites

# Use custom config file
python3 gapi.py --config /path/to/config.json
```

**Available Arguments:**
- `--random, -r`: Pick a random game and exit
- `--unplayed, -u`: Pick from unplayed games only
- `--barely-played, -b`: Pick from barely played games (< 2 hours)
- `--well-played, -w`: Pick from well-played games (> 10 hours)
- `--min-hours HOURS`: Minimum playtime in hours (must be non-negative)
- `--max-hours HOURS`: Maximum playtime in hours (must be non-negative)
- `--genre GENRES`: Filter by genre(s), comma-separated (e.g., "Action,RPG")
- `--favorites`: Pick from favorite games only
- `--stats, -s`: Show library statistics and exit
- `--list-favorites`: List all favorite games and exit
- `--export-history FILE`: Export game history to a file
- `--import-history FILE`: Import game history from a file
- `--no-details`: Skip fetching detailed game information
- `--config, -c PATH`: Path to config file (default: config.json)
- `--help, -h`: Show help message

### Interactive Menu

Once started, you'll see an interactive menu with the following options:

1. **Pick a random game** - Selects any game from your library
2. **Pick from unplayed games** - Only games you haven't played yet
3. **Pick from barely played games** - Games with less than 2 hours playtime
4. **Pick from well-played games** - Games with more than 10 hours playtime
5. **Pick by genre/tag** - Filter games by genre (Action, RPG, Strategy, etc.)
6. **Pick from favorites** - Select from your favorite games
7. **Show library stats** - Display statistics about your game collection
8. **Manage favorites** - Add, remove, or list your favorite games
9. **Export/Import history** - Export or import your game picking history
q. **Quit** - Exit the application

After picking a game, you'll be prompted to add it to (or remove it from) your favorites!

### Example Output

```
🎮 Portal 2
============================================================
App ID: 620
Playtime: 45.3 hours

Description:
The "Perpetual Testing Initiative" has been expanded to allow you to design co-op puzzles...

Genres: Action, Adventure
Release Date: Apr 18, 2011
Metacritic Score: 95

Steam Store: https://store.steampowered.com/app/620/
SteamDB: https://steamdb.info/app/620/
============================================================
```

## Getting Your Steam Credentials

### Steam API Key

1. Go to https://steamcommunity.com/dev/apikey
2. Log in with your Steam account
3. Enter a domain name (can be anything, e.g., "localhost")
4. Copy the generated API key

### Steam ID

1. Go to https://steamid.io/
2. Enter your Steam profile URL or username
3. Copy your Steam ID (steamID64)

## Configuration

The `config.json` file supports the following options:

- `steam_api_key`: Your Steam Web API key (required)
- `steam_id`: Your Steam ID in 64-bit format (required)

## Troubleshooting

**Problem**: "No games found or error fetching games"
- Verify your Steam API key is correct
- Ensure your Steam ID is in the correct 64-bit format
- Check that your Steam profile is set to public

**Problem**: "Config file not found"
- Make sure you've created `config.json` from the template
- Verify the file is in the same directory as `gapi.py`

**Problem**: API rate limiting
- Steam API has rate limits; wait a few minutes if you see errors
- The application caches game data during the session

## Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest new features
- Submit pull requests

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a list of changes and version history.

## License

This project is open source and available under the MIT License.

## Credits

- Steam Web API: https://steamcommunity.com/dev
- SteamDB: https://steamdb.info/
- Colorama: https://github.com/tartley/colorama

## Disclaimer

This is an unofficial tool and is not affiliated with Valve Corporation or Steam. All Steam-related trademarks are property of their respective owners.
