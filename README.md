# GAPI - Game Picker with SteamDB Integration

GAPI is a command-line tool that helps you decide what to play from your Steam library. It randomly picks games based on various filters and displays detailed information from Steam Store and SteamDB.

## Features

- 🎮 **Random Game Selection**: Pick a random game from your entire Steam library
- 🎯 **Smart Filters**: Filter by playtime (unplayed, barely played, well-played games)
- 📊 **Library Statistics**: View stats about your game collection
- 🔍 **Detailed Game Info**: Fetch descriptions, genres, release dates, and Metacritic scores
- 🔗 **Direct Links**: Quick access to Steam Store and SteamDB pages
- 🎨 **Colorful Interface**: Easy-to-read colored terminal output
- 💾 **Smart History**: Avoids suggesting recently picked games
- ⚡ **CLI Mode**: Command-line arguments for scripting and quick picks
- 🔧 **Configurable**: Custom playtime filters and settings

## Prerequisites

- Python 3.6 or higher
- Steam API Key (get one at https://steamcommunity.com/dev/apikey)
- Your Steam ID (find it at https://steamid.io/)

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

## Usage

Run the application:
```bash
python gapi.py
```

### Command-Line Options

GAPI supports both interactive and non-interactive modes:

**Interactive Mode** (default):
```bash
python gapi.py
```

**Non-Interactive Mode** - Pick a game and exit:
```bash
# Pick any random game
python gapi.py --random

# Pick from unplayed games
python gapi.py --unplayed

# Pick from barely played games (< 2 hours)
python gapi.py --barely-played

# Pick from well-played games (> 10 hours)
python gapi.py --well-played

# Custom playtime filter
python gapi.py --min-hours 5 --max-hours 50

# Show statistics only
python gapi.py --stats

# Skip detailed information (faster)
python gapi.py --random --no-details

# Use custom config file
python gapi.py --config /path/to/config.json
```

**Available Arguments:**
- `--random, -r`: Pick a random game and exit
- `--unplayed, -u`: Pick from unplayed games only
- `--barely-played, -b`: Pick from barely played games (< 2 hours)
- `--well-played, -w`: Pick from well-played games (> 10 hours)
- `--min-hours HOURS`: Minimum playtime in hours
- `--max-hours HOURS`: Maximum playtime in hours
- `--stats, -s`: Show library statistics and exit
- `--no-details`: Skip fetching detailed game information
- `--config, -c PATH`: Path to config file (default: config.json)
- `--help, -h`: Show help message

### Interactive Menu

Once started, you'll see an interactive menu with the following options:

1. **Pick a random game** - Selects any game from your library
2. **Pick from unplayed games** - Only games you haven't played yet
3. **Pick from barely played games** - Games with less than 2 hours playtime
4. **Pick from well-played games** - Games with more than 10 hours playtime
5. **Show library stats** - Display statistics about your game collection
q. **Quit** - Exit the application

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

## License

This project is open source and available under the MIT License.

## Credits

- Steam Web API: https://steamcommunity.com/dev
- SteamDB: https://steamdb.info/
- Colorama: https://github.com/tartley/colorama

## Disclaimer

This is an unofficial tool and is not affiliated with Valve Corporation or Steam. All Steam-related trademarks are property of their respective owners.
