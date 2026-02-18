# 🎮 GAPI - Game Picker with SteamDB Integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)

GAPI is a game picker tool that helps you decide what to play from your Steam library. It randomly picks games based on various filters and displays detailed information from Steam Store and SteamDB. Available in both **Web GUI** and **CLI** modes!

## 📋 Table of Contents

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

## 🎯 About

- Python 3.6 or higher
- Steam API Key (get one at https://steamcommunity.com/dev/apikey)
- Your Steam ID (find it at https://steamid.io/)
- (Optional) Discord Bot Token for Discord integration (get one at https://discord.com/developers/applications)

## ✨ Features

### Core Features
- 🎮 **Random Game Selection** - Pick from your entire Steam library
- 🎯 **Smart Filters** - Filter by playtime, genre, and more
- 💾 **Smart History** - Avoids suggesting recently picked games
- 🔍 **Rich Game Information** - Descriptions, genres, release dates, Metacritic scores

### Filtering Options
- ⏱️ **Playtime Filters** - Unplayed, barely played (< 2 hours), well-played (> 10 hours), or custom ranges
- 🎨 **Genre/Tag Filtering** - Filter by Action, RPG, Strategy, and more
- ⭐ **Favorites System** - Mark games as favorites and pick from them

### User Experience
- 🖥️ **Interactive Menu** - Easy-to-use text-based interface
- ⚡ **CLI Mode** - Command-line arguments for scripting and quick picks
- 🎨 **Colorful Output** - Easy-to-read colored terminal display
- 📊 **Library Statistics** - View detailed stats about your game collection

### Data Management
- 📤 **Export/Import** - Save and restore your game picking history
- 🔗 **Direct Links** - Quick access to Steam Store and SteamDB pages
- 🔧 **Configurable** - Customize settings via config file

## 🚀 Quick Start

### Try the Demo (No Setup Required!)

Want to see GAPI in action without any configuration? Run the demo with mock data:

```bash
git clone https://github.com/mattam1234/GAPI.git
cd GAPI
pip install -r requirements.txt
python3 demo.py
```

This lets you explore all features without needing Steam credentials!

### Full Setup (5 minutes)

1. **Get your Steam credentials:**
   - [Steam API Key](https://steamcommunity.com/dev/apikey) (free, takes 1 minute)
   - [Steam ID](https://steamid.io/) (find your 64-bit Steam ID)

2. **Install GAPI:**
   ```bash
   git clone https://github.com/mattam1234/GAPI.git
   cd GAPI
   bash setup.sh  # Automated setup
   ```

3. **Configure:**
   ```bash
   cp config_template.json config.json
   # Edit config.json with your Steam API key and Steam ID
   ```

4. **Run:**
   ```bash
   python3 gapi.py
   ```

## 📦 Installation

### Prerequisites

- **Python 3.6+** - [Download Python](https://www.python.org/downloads/)
- **Steam API Key** - [Get one here](https://steamcommunity.com/dev/apikey) (free, requires Steam account)
- **Steam ID** - [Find yours here](https://steamid.io/) (64-bit format)
- **Public Steam Profile** - Your profile must be public for the API to work

### Step-by-Step Installation

**1. Clone the repository:**
```bash
git clone https://github.com/mattam1234/GAPI.git
cd GAPI
```

**2. Install dependencies:**

Option A - Automated setup (recommended):
```bash
bash setup.sh
```

Option B - Manual installation:
```bash
pip install -r requirements.txt
```

**3. Configure your Steam credentials:**
```bash
cp config_template.json config.json
```

**4. Edit `config.json`** with your actual credentials:
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
python3 gapi.py
```

Both demos run GAPI with mock game data so you can see how it works.

For a cleaner setup, use a virtual environment:

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
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Linux/Mac
# OR
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt

# Run GAPI
python3 gapi.py
```

## 🎮 Usage

### Interactive Menu

Run GAPI in interactive mode for the full experience:

**Interactive CLI Mode** (default):
```bash
python3 gapi.py
```

**Non-Interactive CLI Mode** - Pick a game and exit:
```bash
# Pick any random game and exit
python3 gapi.py --random

# Pick from unplayed games
python3 gapi.py --unplayed

# Pick from barely played games (< 2 hours)
python3 gapi.py --barely-played

# Pick from well-played games (> 10 hours)
python3 gapi.py --well-played

# Pick from your favorites
python3 gapi.py --favorites
```

**Advanced Filtering:**
```bash
# Custom playtime range (5-50 hours)
python3 gapi.py --min-hours 5 --max-hours 50

# Filter by genre
python3 gapi.py --genre "Action,RPG"

# Combine filters (unplayed Action games)
python3 gapi.py --unplayed --genre "Action"

# Skip detailed info for faster results
python3 gapi.py --random --no-details
```

**Library Management:**
```bash
# Show library statistics
python3 gapi.py --stats

# List all favorite games
python3 gapi.py --list-favorites

# Export/Import history
python3 gapi.py --export-history my_backup.json
python3 gapi.py --import-history my_backup.json

# Use custom config file
python3 gapi.py --config /path/to/config.json
```

**Get Help:**
```bash
python3 gapi.py --help
```

### Example Output

When you pick a game, you'll see rich information like this:

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

## ⚙️ Configuration

The `config.json` file contains your Steam credentials:

```json
{
  "steam_api_key": "YOUR_ACTUAL_API_KEY",
  "steam_id": "YOUR_STEAM_ID"
}
```

**Configuration Options:**
- `steam_api_key` - Your Steam Web API key *(required)*
- `steam_id` - Your Steam ID in 64-bit format *(required)*

## 🔑 Getting Your Steam Credentials

### Steam API Key

1. Go to https://steamcommunity.com/dev/apikey
2. Log in with your Steam account
3. Enter a domain name (can be anything, e.g., "localhost")
4. Copy the generated API key

### Steam ID

**Option 1 - Using SteamID.io (Easiest):**
1. Go to https://steamid.io/
2. Enter your Steam profile URL or username
3. Copy your **steamID64** (17-digit number)

**Option 2 - From Steam Profile:**
1. Open Steam and go to your profile
2. Right-click anywhere on your profile page
3. Click "Copy Page URL"
4. Use the URL at https://steamid.io/ to get your steamID64

**Important:** Your Steam profile must be set to **Public** for GAPI to access your game library.

## ❓ FAQ

<details>
<summary><strong>Do I need to pay for a Steam API key?</strong></summary>

No! Steam API keys are completely free. You just need a Steam account to generate one.
</details>

<details>
<summary><strong>Can I use GAPI without Steam credentials?</strong></summary>

Yes! Run `python3 demo.py` to try GAPI with mock data and explore all features without setting up credentials.
</details>

<details>
<summary><strong>Why isn't GAPI finding my games?</strong></summary>

Make sure:
1. Your Steam profile is set to **Public** (not Private or Friends Only)
2. Your Steam API key is valid and correctly entered in `config.json`
3. Your Steam ID is in the correct 64-bit format (17-digit number)
</details>

<details>
<summary><strong>How does the history feature work?</strong></summary>

GAPI keeps track of recently picked games to avoid suggesting them again. The history is stored locally and persists between sessions. You can export/import it using the menu or CLI options.
</details>

<details>
<summary><strong>Can I use GAPI with multiple Steam accounts?</strong></summary>

Yes! Create multiple config files (e.g., `config1.json`, `config2.json`) and use the `--config` flag to switch between them:
```bash
python3 gapi.py --config config1.json
python3 gapi.py --config config2.json
```
</details>

<details>
<summary><strong>Does GAPI work on Windows/Mac/Linux?</strong></summary>

Yes! GAPI is written in Python and works on all major platforms. On Windows, use `python` instead of `python3` in commands.
</details>

## 🔧 Troubleshooting

### Common Issues

**"No games found or error fetching games"**
- ✅ Verify your Steam API key is correct in `config.json`
- ✅ Ensure your Steam ID is in the correct 64-bit format (17-digit number)
- ✅ Check that your Steam profile is set to **Public** (not Private or Friends Only)
- ✅ Make sure you have games in your Steam library

**"Config file not found"**
- ✅ Ensure you've created `config.json` from `config_template.json`
- ✅ Verify the file is in the same directory as `gapi.py`
- ✅ Check file permissions (must be readable)

**API rate limiting errors**
- ✅ Steam API has rate limits; wait a few minutes if you see errors
- ✅ The application caches game data during the session to minimize API calls
- ✅ Use `--no-details` flag for faster, less API-intensive picks

**"Module not found" errors**
- ✅ Make sure you've installed dependencies: `pip install -r requirements.txt`
- ✅ Consider using a virtual environment
- ✅ Try running with `python3` instead of `python` (or vice versa)

**Games not being filtered correctly**
- ✅ Check your filter settings match your expectations
- ✅ Some games may not have genre information available
- ✅ Playtime is measured in minutes from Steam API (converted to hours for display)

### Still Having Issues?

1. Check the [GitHub Issues](https://github.com/mattam1234/GAPI/issues) for similar problems
2. Run the demo to verify basic functionality: `python3 demo.py`
3. Create a new issue with:
   - Python version (`python3 --version`)
   - Operating system
   - Error message (if any)
   - Steps to reproduce

## 🤝 Contributing

Contributions are welcome! We'd love your help to make GAPI even better.

### Ways to Contribute

- 🐛 **Report bugs** - Found an issue? Let us know!
- 💡 **Suggest features** - Have an idea? We'd love to hear it!
- 📝 **Improve documentation** - Help make the docs clearer
- 💻 **Submit pull requests** - Code contributions are appreciated!

### Quick Start for Contributors

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/GAPI.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test with the demo: `python3 demo.py`
6. Submit a pull request

For detailed guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md)

## 📚 Additional Resources

- **[Contributing Guide](CONTRIBUTING.md)** - Detailed contribution guidelines
- **[Changelog](CHANGELOG.md)** - Version history and changes
- **[License](LICENSE)** - MIT License details

## 📜 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

## 🙏 Credits & Acknowledgments

**APIs & Services:**
- [Steam Web API](https://steamcommunity.com/dev) - Game library and player data
- [SteamDB](https://steamdb.info/) - Enhanced game information

**Libraries:**
- [Colorama](https://github.com/tartley/colorama) - Cross-platform colored terminal output
- [Requests](https://requests.readthedocs.io/) - HTTP library for Python

## ⚠️ Disclaimer

This is an **unofficial tool** and is not affiliated with, endorsed by, or connected to Valve Corporation or Steam. All Steam-related trademarks and logos are property of their respective owners.

GAPI is a community project designed to enhance your gaming experience by helping you discover games in your library.

---

<div align="center">

**Made with ❤️ for the Steam community**

If you find GAPI useful, give it a ⭐ on GitHub!

[Report a Bug](https://github.com/mattam1234/GAPI/issues) · [Request a Feature](https://github.com/mattam1234/GAPI/issues) · [Contribute](CONTRIBUTING.md)

</div>
