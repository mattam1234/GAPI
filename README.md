# 🎮 GAPI - Game Picker with SteamDB Integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)

**Can't decide what to play?** GAPI is a command-line tool that helps you discover games in your Steam library. It randomly picks games based on smart filters and displays detailed information from Steam Store and SteamDB.

## 📋 Table of Contents

- [About](#about)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Interactive Mode](#interactive-menu)
  - [Command-Line Options](#command-line-options)
  - [Example Output](#example-output)
- [Configuration](#configuration)
- [Getting Your Steam Credentials](#getting-your-steam-credentials)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

## 🎯 About

GAPI solves a common problem: having too many games and not knowing what to play! With hundreds of games in your Steam library, decision paralysis is real. GAPI helps by intelligently selecting games based on your preferences and providing all the information you need to make a decision.

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

**5. Run GAPI:**
```bash
python3 gapi.py
```

### Virtual Environment (Recommended)

For a cleaner setup, use a virtual environment:

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

```bash
python3 gapi.py
```

You'll see a menu with these options:

```
GAPI - Game Picker
========================================
1. Pick a random game
2. Pick from unplayed games
3. Pick from barely played games (< 2 hours)
4. Pick from well-played games (> 10 hours)
5. Pick by genre/tag
6. Pick from favorites
7. Show library stats
8. Manage favorites
9. Export/Import history
q. Quit
========================================
```

After picking a game, you'll be able to add it to (or remove it from) your favorites!

### Command-Line Options

GAPI supports non-interactive mode for scripting and automation:

**Basic Usage:**
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
