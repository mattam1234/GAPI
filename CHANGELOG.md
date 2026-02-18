# Changelog

All notable changes to GAPI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
