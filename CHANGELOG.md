# Changelog

All notable changes to GAPI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.1.0] - 2026-02-18

### Added
- **Batch Game Picking**: New `--count N` CLI option to pick multiple games at once
  - Pick up to 10 games in a single command
  - Ensures no duplicate picks in the same batch
  - Works with all filter combinations
  - Example: `python3 gapi.py --genre "RPG" --count 5`
- **Genre Exclusion Filter**: New `--exclude-genre` CLI option to exclude games with specific genres
  - Combine with `--genre` for precise filtering (e.g., "Action games but not Horror")
  - Works with all filter combinations (playtime, favorites, etc.)
- **Environment Variable Support**: Securely configure credentials via environment variables
  - `STEAM_API_KEY`, `STEAM_ID`, `DISCORD_BOT_TOKEN`, `EPIC_ID`, `GOG_ID`
  - Environment variables override config.json values
  - `.env.example` file provided as a template
- **Configurable Settings**: New configuration options in config.json
  - `barely_played_hours` - Customize threshold for barely played games (default: 2 hours)
  - `well_played_hours` - Customize threshold for well-played games (default: 10 hours)
  - `max_history_size` - Configure how many recent picks to remember (default: 20)
  - `api_timeout_seconds` - Set API request timeout (default: 10 seconds)
- **Steam ID Validation**: Automatic validation of Steam ID format (17-digit, starting with 7656119)
  - Helpful error messages with link to steamid.io
- **ROADMAP.md** - Comprehensive roadmap for future features and improvements
- Helper function `minutes_to_hours()` for consistent playtime conversion
- Helper function `is_valid_steam_id()` for Steam ID validation

### Changed
- Improved code maintainability by extracting hardcoded values to configuration
- Refactored playtime conversion to use centralized helper function (DRY principle)
- Steam API client now respects configurable timeout value
- Enhanced error messages with actionable suggestions

### Security
- Environment variable support for sensitive credentials (recommended over config.json)
- Steam ID format validation prevents invalid API calls
- `.env` added to `.gitignore` to prevent credential leaks

### Developer Experience
- Reduced code duplication with reusable helper functions
- More flexible configuration system for easier customization
- Better separation of concerns (configuration vs. constants)
- Improved input validation and error messages

## [Unreleased]

### Added
- Initial implementation of GAPI (Game Picker with SteamDB Integration)
- Steam Web API integration for fetching user's game library
- Steam Store API integration for detailed game information
- Interactive CLI menu with multiple game selection options
- Command-line arguments for non-interactive use
- Smart filtering options:
  - Unplayed games
  - Barely played games (< 2 hours)
  - Well-played games (> 10 hours)
  - Custom hour-based filters (--min-hours, --max-hours)
  - **Genre/tag filtering** - Filter games by genre (Action, RPG, Strategy, etc.)
  - **Favorites filtering** - Pick from favorite games only
- **Favorites Management System**:
  - Mark games as favorites
  - View all favorites
  - Remove games from favorites
  - Interactive prompts to add/remove favorites after picking a game
  - CLI argument --favorites to pick from favorites
  - CLI argument --list-favorites to view all favorites
- **History Export/Import**:
  - Export game picking history to JSON files
  - Import game history from files
  - CLI arguments --export-history and --import-history
  - Interactive menu for export/import operations
- **Performance Improvements**:
  - Game details caching to reduce API calls
  - Faster genre filtering with cached data
- Game history tracking to avoid repeating recent picks
- Library statistics display (now includes favorites count)
- Colorful terminal output using colorama
- Direct links to Steam Store and SteamDB pages
- Configuration file support (config.json)
- Setup script with virtual environment recommendations
- Demo mode for testing without Steam credentials
- Comprehensive documentation (README, CONTRIBUTING)
- MIT License

### Security
- Input validation for Steam credentials
- Input validation for hour arguments (non-negative values)
- No known vulnerabilities in dependencies
- Passed CodeQL security analysis

### Developer Experience
- PEP 8 compliant code
- Type hints for better code clarity
- Named constants for magic numbers
- Modular class structure
- Extensive docstrings
