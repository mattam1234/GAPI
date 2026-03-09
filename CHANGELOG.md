# Changelog

All notable changes to GAPI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.9.0] - 2026-03-09

### Added
- **Email Notification Service** (`app/services/email_service.py`)
  - New `EmailService` class sends transactional email via SMTP (standard
    library `smtplib`; no extra dependencies required)
  - Configuration via environment variables: `SMTP_HOST`, `SMTP_PORT`,
    `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `SMTP_USE_SSL`
  - Graceful degradation: all sends return `False` and log a debug message
    when `SMTP_HOST` is not set, so the app continues to work without email
  - `EmailService.from_env()` — class-level factory reads config from env
  - `send_email(to, subject, body, html_body=None)` — single email with
    optional HTML alternative part (`multipart/alternative`)
  - `send_notification_email(to, username, notification)` — sends a single
    in-app notification as a formatted email
  - `send_digest_email(to, username, notifications, period)` — bundles
    multiple unread notifications into one daily/weekly digest email
  - `send_test_email(to)` — smoke-test for SMTP configuration
  - `is_configured()` — returns `True` when `SMTP_HOST` is set
  - 55 new unit tests in `tests/test_email_service.py`

- **Email management API endpoints**
  - `GET  /api/admin/email/status` — show SMTP configuration status (admin)
  - `POST /api/admin/email/test` — send a test email to verify SMTP (admin)
  - `POST /api/admin/notifications/send-digests` — manually trigger digest
    delivery for all opted-in users; supports `dry_run=true` and
    `period=daily|weekly` (admin)
  - `GET  /api/users/<username>/email` — retrieve stored email address
    (own account or admin)
  - `PUT  /api/users/<username>/email` — store/update email address
    (own account or admin)

- **User `email` column** (`database.py`)
  - New nullable `email` column on the `users` table
  - `database.get_user_email(db, username)` — returns address or `''`
  - `database.set_user_email(db, username, email)` — stores/clears address
  - `POST /api/auth/register` now accepts an optional `email` field
    (validated for `@` presence; stored immediately if provided)

- **SMTP configuration documentation** (`.env.example`)
  - New `SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM /
    SMTP_USE_TLS / SMTP_USE_SSL` section with inline usage notes

## [2.8.0] - 2026-02-28

### Added
- **Discord Rich Presence** (`discord_presence.py`)
  - New `DiscordPresence` class wraps `pypresence` with a thread-safe, non-blocking
    design; all IPC work happens in daemon threads so Flask request handlers are never
    blocked
  - Opt-in: set `DISCORD_CLIENT_ID` in `.env` to your Discord application's numeric
    Client ID (create one free at https://discord.com/developers/applications)
  - Graceful degradation: if `pypresence` is not installed, or if Discord is not
    running on the host, GAPI logs a debug message and continues normally without
    raising an exception
  - The game name, playtime, and a "GAPI picked this game" state line are shown in the
    Rich Presence panel; details and state lines are fully customisable
  - `DiscordPresence.update(game_name, playtime_hours, details)` — called automatically
    inside `POST /api/pick` when a game is successfully picked
  - `DiscordPresence.clear()` — called automatically on `POST /api/auth/logout`
  - `DiscordPresence.close()` — for clean shutdown
  - 16 new unit tests covering disabled mode, missing-pypresence, connect/update/clear,
    connection failures, thread safety, environment-variable configuration
  - `pypresence>=4.3.0` added to `requirements.txt` as an optional dependency
  - `DISCORD_CLIENT_ID` documented in `.env.example`

- **Localization / i18n** (`locales/` directory + two REST endpoints)
  - `locales/en.json` — full English translation strings for all UI sections:
    `nav`, `pick`, `library`, `reviews`, `tags`, `backlog`, `playlists`,
    `schedule`, `budget`, `wishlist`, `voting`, `stats`, `auth`, `common`
  - `locales/es.json` — complete Spanish (Español) translation with the same
    structure; all section keys and sub-keys are present
  - `GET /api/i18n` — lists all available locales (returns `lang` + `lang_name`)
  - `GET /api/i18n/<lang>` — returns the full translation object for a language;
    `404` when the requested language is not available; path-traversal is sanitised
    (directory separators and `..` components are stripped before file lookup)
  - 13 new tests covering the list/get endpoints, structural parity between locales,
    404 handling, and path-traversal safety

- **CI: expanded coverage scope**
  - `--cov` flags now include `discord_presence`, `openapi_spec`, and `app/`
  - `discord_presence.py` and `openapi_spec.py` added to the syntax-check step

## [2.7.0] - 2026-02-28

### Changed
- **Complete service migration** — all remaining Flask route handlers now use services
  directly instead of calling `GamePicker` domain methods:
  - Reviews (`GET/POST/PUT/DELETE /api/reviews`, `/api/reviews/<game_id>`) →
    `picker.review_service`
  - Tags (`GET/POST/DELETE /api/tags`, `/api/library/by-tag/<tag>`) →
    `picker.tag_service`
  - Schedule (`GET/POST/PUT/DELETE /api/schedule`) → `picker.schedule_service`
  - Playlists (`GET/POST/DELETE /api/playlists`, `/api/playlists/<name>/games`) →
    `picker.playlist_service`
  - Backlog (`GET/POST/PUT/DELETE /api/backlog`) → `picker.backlog_service`
  - Pick route tag-filter and game-details enrichment → `picker.tag_service`,
    `picker.review_service`, `picker.backlog_service`
  - Export routes (`/api/export/library`, `/api/export/favorites`) →
    `picker.review_service`, `picker.tag_service`, `picker.backlog_service`,
    `picker.favorites_service`

### Added
- **`GET /api/openapi.json`** — serves the full OpenAPI 3.0 specification (JSON)
  generated by `openapi_spec.build_spec()`; server URL is set dynamically from the
  request's base URL
- **`GET /api/docs`** — Swagger UI (via CDN) for interactive API exploration

## [2.6.0] - 2026-02-28

### Added
- **Service/Repository architecture** — separates business logic from the Flask UI layer
  - `app/repositories/` package: `BaseRepository` (atomic JSON write/read) + nine concrete
    repository classes: `ReviewRepository`, `TagRepository`, `ScheduleRepository`,
    `PlaylistRepository`, `BacklogRepository`, `BudgetRepository`, `WishlistRepository`,
    `FavoritesRepository`, `HistoryRepository`
  - `app/services/` package: eight service classes containing all domain/business logic:
    `ReviewService`, `TagService`, `ScheduleService`, `PlaylistService`, `BacklogService`,
    `BudgetService`, `WishlistService`, `FavoritesService`
  - `GamePicker.__init__` wires repositories and services; exposes them as
    `picker.review_service`, `picker.budget_service`, `picker.wishlist_service`, etc.
  - Legacy `picker.xxx` dict/list attributes now point at the same in-memory object as
    the corresponding repository — full backward compatibility, zero test regressions
  - Budget API endpoints (`GET/POST/DELETE /api/budget`) refactored to use
    `picker.budget_service` directly, demonstrating the pattern
  - Wishlist API endpoints (`GET/POST/DELETE /api/wishlist`, `GET /api/wishlist/sales`)
    refactored to use `picker.wishlist_service` directly
  - 104 new unit/integration tests in `tests/test_services.py` covering all repos and
    services (total test count: 265, up from 161)
- **Dependabot** — `.github/dependabot.yml` for automated dependency updates (pip + actions)
- **Code coverage configuration** — `setup.cfg` with `[coverage:run]` / `[coverage:report]`
  sections; CI now produces `coverage.xml` and uploads it as a build artefact
- **Type checking (mypy)** — `mypy.ini` settings in `setup.cfg`; new `typecheck` job in CI
- **OpenAPI 3.0 documentation** — `openapi_spec.py` builds a full spec dict for all 83
  API endpoints; serves at `GET /api/openapi.json` and `GET /api/docs` (Swagger UI via CDN)

## [2.5.0] - 2026-02-27

### Added
- **Wishlist with Sale Alerts** — track unowned games and get notified of discounts
  - New `GamePicker` methods: `load_wishlist()`, `save_wishlist()`, `add_to_wishlist()`,
    `remove_from_wishlist()`, `check_wishlist_sales()`
  - Per-game entries: `game_id`, `name`, `platform`, `added_date`, `target_price`, `notes`
  - `check_wishlist_sales()` calls the Steam Store API for live prices; returns games
    that are discounted **or** at/below the user's target price
  - New `SteamAPIClient.get_price_overview(app_id)` — lightweight price-only Steam call
    (does not pollute the full details cache)
  - Persisted to `.gapi_wishlist.json` via atomic write
  - `GET /api/wishlist` — list all wishlist entries (login required)
  - `POST /api/wishlist` — add/update a wishlist entry (login required)
  - `DELETE /api/wishlist/<game_id>` — remove a wishlist entry (login required)
  - `GET /api/wishlist/sales` — live sale check for all Steam wishlist items (login required)
  - 21 new unit tests covering all wishlist and price-overview code paths
- **CI/CD Pipeline** — new `.github/workflows/tests.yml` GitHub Actions workflow
  - Runs on every push to `main` / `copilot/**` branches and on all pull requests
  - Python 3.11, installs all dependencies from `requirements.txt`
  - Executes full pytest suite with coverage report (`--cov=gapi --cov=multiuser`)
  - Verifies syntax of all main Python modules

## [2.4.0] - 2026-02-27

### Added
- **Ranked-Choice (Instant Runoff) Voting** — extended `VotingSession` in `multiuser.py`
  - New `voting_method` parameter: `'plurality'` (default, fully backward-compatible)
    or `'ranked_choice'` (Instant Runoff Voting)
  - `cast_vote()` now accepts an ordered preference list for ranked-choice sessions
  - `run_irv()` method implements the full IRV algorithm with round-by-round elimination
  - `get_winner()` dispatches to IRV automatically when `voting_method='ranked_choice'`
  - `to_dict()` includes `voting_method` and, for ranked-choice sessions, `irv_rounds`
    (list of per-round counts and eliminated candidates)
  - `POST /api/voting/create` accepts `voting_method` in request body
  - `POST /api/voting/<id>/vote` accepts `ranking` (list) for ranked-choice sessions
  - `POST /api/voting/<id>/close` response includes `voting_method` and `irv_rounds`
  - 18 new unit tests covering all ranked-choice code paths
- **Budget Tracking** — track what you paid for your games
  - New `GamePicker` methods: `load_budget()`, `save_budget()`, `set_game_budget()`,
    `remove_game_budget()`, `get_budget_summary()`
  - Per-game entries: `price`, `currency`, `purchase_date`, `notes`
  - Aggregated summary: `total_spent`, `primary_currency`, `currency_breakdown`,
    `game_count`, `entries` (sorted by purchase date, enriched with game names)
  - Persisted to `.gapi_budget.json` via atomic write
  - `GET /api/budget` — retrieve all entries + summary (login required)
  - `POST/PUT /api/budget/<game_id>` — set / update budget entry (login required)
  - `DELETE /api/budget/<game_id>` — remove budget entry (login required)
  - 16 new unit tests covering all budget code paths

## [2.3.0] - 2026-02-25

### Added
- **Comprehensive Unit Test Suite** (`tests/test_gapi.py`)
  - 106 tests covering all core `GamePicker` functionality
  - Helper function tests: `minutes_to_hours`, `is_valid_steam_id`, `is_placeholder_value`,
    `_parse_release_year`, `extract_game_id`, `_atomic_write_json`
  - `GamePicker` state tests: favorites, tags, reviews, backlog, playlists
  - `filter_games()` tests including genre/metacritic/release-year filters via cached details
  - `pick_random_game()` tests including history-avoidance behaviour
  - `VotingSession` tests: vote casting, eligibility, results tallying, expiry
  - `get_recommendations()` tests with mock library and genre affinity
  - Runnable with `python -m pytest tests/` or `python -m unittest discover tests/`
- **Smart Recommendations** (`/api/recommendations` endpoint + 💡 For You tab)
  - Scores every unplayed / barely-played game in the user's library
  - Genre affinity built from the user's most-played games using cached Steam details
  - Applies a recency penalty for games picked recently (history list)
  - New `GamePicker.get_recommendations(count)` method in `gapi.py`
  - `GET /api/recommendations?count=N` Flask endpoint (login required)
  - **💡 For You** tab in the Web GUI with configurable result count (5 / 10 / 20)
  - Each recommendation shows name, playtime, explanation, Steam link, favourite ☆, and quick-ignore 🚫
- **HowLongToBeat Integration** (`/api/hltb/<game_name>` endpoint + game-details modal)
  - Shows Main Story, Main + Extra, and Completionist completion times
  - Optional dependency (`howlongtobeatpy>=1.0.0`); feature degrades gracefully if not installed
  - New `gapi.get_hltb_data(game_name)` helper with in-process caching
  - HLTB pills rendered in the game-details modal alongside Metacritic / ProtonDB
- **Cross-Platform Duplicate Detection** (`/api/duplicates` endpoint + Library tab section)
  - Detects games you own on more than one platform (Steam, Epic, GOG) by normalised name
  - New `GamePicker.find_duplicates()` method in `gapi.py`
  - Duplicate groups appear at the bottom of the Library tab, each showing platform badges and per-platform playtime
- **Export Library / Favorites as CSV** (`/api/export/library` and `/api/export/favorites`)
  - One-click "⬇️ Export CSV" buttons in the Library and Favorites tabs
  - Exports: app_id, name, platform, playtime_hours, is_favorite, backlog_status, tags, review_rating, review_notes
  - Favorites export: app_id, name, platform, playtime_hours, tags, review_rating, review_notes

## [2.2.0] - 2026-02-25

### Added
- **Steam Friend Activity** (`/api/friends` endpoint + 👥 Friends tab in Web GUI)
  - View all Steam friends with their online status (Online, Offline, Busy, Away…)
  - See which friends are currently in-game, including the game name
  - Per-friend recently-played list (last 2 weeks) with links to Steam store pages
  - Sorted by activity: in-game friends first, then online, then offline
  - New `SteamAPIClient.get_friend_list()`, `get_player_summaries()`, and
    `get_recently_played()` methods in `gapi.py`
- **Quick-Ignore button in Library view** (🚫 button on each game row)
  - One-click to add any library game to the No-Play List without leaving the Library tab
  - Available in both the full library view and the search results

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
