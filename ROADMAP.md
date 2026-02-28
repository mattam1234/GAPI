# 🗺️ GAPI Roadmap

This document outlines the planned features and improvements for GAPI (Game Picker with Multi-Platform Integration).

## ✅ Recently Completed (Current Release - v2.1.0)

### Configuration & Code Quality
- ✅ Configurable playtime thresholds (barely played, well played hours)
- ✅ Configurable history size
- ✅ Configurable API timeout
- ✅ Helper function for playtime conversion (DRY principle)
- ✅ Helper function for Steam ID validation
- ✅ Improved code maintainability
- ✅ Environment variable support for sensitive credentials (STEAM_API_KEY, STEAM_ID, etc.)
- ✅ Steam ID format validation (17-digit, starts with 7656119)
- ✅ Configuration validation with helpful error messages

### User Experience
- ✅ Batch game picking - Pick multiple games at once with `--count N` (up to 10)
- ✅ Genre exclusion filter - Exclude specific genres with `--exclude-genre`
- ✅ Better error messages with actionable suggestions

### Documentation
- ✅ Comprehensive ROADMAP.md file
- ✅ Updated CHANGELOG.md
- ✅ .env.example for environment variables

## 🚀 Upcoming Features

### 📅 Next Release (v2.2.0)

#### High Priority - User Experience
- [x] **Advanced Filtering Options**
  - [x] Filter by Metacritic score (e.g., score > 80) – `--min-score` CLI flag + Web GUI
  - [x] Filter by release date (e.g., games from 2020-2023) – `--min-year`/`--max-year` + Web GUI
  - [x] Exclude specific games by name or ID from picker – `--exclude-game` CLI flag + Web GUI
- [x] **Loading Indicators** - Spinner overlay in Web GUI for long operations

#### High Priority - Performance
- [x] **Enhanced Caching System** - Persist game details cache between sessions
- [x] **Parallel Library Fetching** - Concurrent user-library fetching with ThreadPoolExecutor
- [x] **Optimized Genre Filtering** - Parallel `ThreadPoolExecutor` detail-fetching inside `filter_games()`

#### Medium Priority - Data & Configuration
- [x] **Atomic File Writes** - Prevent data corruption on crashes
- [x] **Logging Framework** - Replace print statements with proper logging (configurable levels)

#### Social Features
- [x] **Voting System** – Multi-user emoji-reaction voting via Discord + Web UI
- [x] **Game Reviews** – Personal rating (1-10) + notes per game, stored in `.gapi_reviews.json`
- [x] **Custom Game Tags** – Tag games with labels, filter/pick by tag, REST API + Web UI
- [x] **Dark Mode** – CSS custom properties + toggle button, theme persisted to localStorage
- [x] **Statistics Charts** – Chart.js doughnut (played/unplayed) + horizontal bar (top 10) in Stats tab

### 📅 Future Release (v2.3.0)

#### Platform Integration
- [ ] **Epic Games OAuth** - Full library access with OAuth authentication
- [ ] **GOG Galaxy Integration** - Complete GOG library support
- [ ] **Xbox Game Pass** - Integration with Xbox Game Pass library
- [ ] **PlayStation Network** - PSN library integration (if API available)
- [ ] **Nintendo eShop** - Nintendo Switch library support (if API available)

#### Smart Features
- [ ] **Smart Recommendations** - AI-powered game suggestions based on playtime patterns
- [x] **Smart Recommendations** - Genre-affinity based recommendations from user's own library
- [x] **Duplicate Detection** - Identify same games across platforms
- [x] **ProtonDB Integration** - Linux compatibility ratings for Windows games
- [x] **Achievement Tracking** - Display completion percentage
- [x] **Friend Activity** - See what friends are playing (Steam API)

#### Social Features
- [ ] **Discord Rich Presence** - Show currently picked game in Discord status
- [x] **Game Night Scheduler** - Schedule game sessions with friends
- [x] **Voting System Improvements** - Multiple voting rounds, ranked choice (Instant Runoff Voting)
- [x] **Game Reviews** - Add personal notes/reviews to games
- [x] **Export game recommendations** - Export library / favorites as CSV

### 📅 Long-term Vision (v3.0.0+)

#### Mobile & Cross-Platform
- [ ] **Mobile App** - Native iOS/Android applications
- [ ] **Progressive Web App** - Offline-capable PWA version
- [ ] **Desktop Application** - Electron-based desktop app with system tray integration
- [ ] **Browser Extension** - Quick game picker from browser toolbar

#### Advanced Features
- [ ] **Machine Learning Recommendations** - ML model trained on your playing habits
- [ ] **Calendar Integration** - Sync game sessions with calendar apps
- [ ] **Twitch Integration** - Pick games based on what's trending on Twitch
- [x] **Custom Playlists** - Create themed game lists (e.g., "Cozy Games", "Quick Sessions")
- [x] **Game Backlog Manager** - Prioritize and track game completion
- [x] **Budget Tracking** - Track game purchases and library value
- [x] **Sale Alerts** - Notify when wishlist games go on sale

#### API & Integrations
- [x] **Public API** - RESTful API for third-party integrations (Flask REST API fully implemented)
- [x] **Webhook Support** - Trigger external services on game picks
- [ ] **IFTTT Integration** - Connect with IFTTT for automation
- [ ] **Slack/Teams Bots** - Enterprise communication platform integrations
- [ ] **Home Assistant** - Smart home integration for game lighting/setup

#### Long-term Backlog Features
- [x] **Custom Playlists** - Create themed game lists (e.g., "Cozy Games", "Quick Sessions")
- [x] **Game Backlog Manager** - Track want_to_play / playing / completed / dropped per game
- [x] **Budget Tracking** - Track game purchases and library value
- [x] **Sale Alerts** - Notify when wishlist games go on sale

## 🔧 Technical Improvements

### Code Quality
- [x] Comprehensive test suite (unit, integration, e2e)
- [x] CI/CD pipeline with automated testing (GitHub Actions)
- [ ] Code coverage reports (target: 80%+)
- [x] Type checking with mypy
- [x] Automated dependency updates (Dependabot)
- [ ] Security scanning (CodeQL, Snyk)

### Architecture
- [ ] Plugin system for custom platforms
- [x] Database support (SQLite/PostgreSQL) for better data management
- [x] Service/Repository layer — business logic fully separated from Flask UI layer
- [ ] Microservices architecture for scalability
- [ ] GraphQL API alongside REST
- [ ] WebSocket support for real-time updates

### Documentation
- [x] API documentation (Swagger/OpenAPI) — `GET /api/openapi.json` + `GET /api/docs`
- [ ] Video tutorials
- [ ] Interactive demo environment
- [ ] Localization (i18n) - Support for multiple languages
- [ ] Developer guide for contributors

## 💡 Community Requested Features

Features requested by the community will be tracked here. Please open an issue with the `feature-request` label to suggest new features!

### Under Consideration
- Custom themes for Web GUI
- Dark mode support
- Game statistics visualization (charts, graphs)
- Import game lists from other services
- ~~Export game recommendations~~ ✅ (see v2.3.0)
- ~~Integration with HowLongToBeat API~~ ✅ (see v2.3.0)
- VR game filtering
- Controller support for desktop app
- Voice commands for game picking

## 🤝 How to Contribute

We welcome contributions to help achieve these goals! Here's how you can help:

1. **Pick a Feature** - Choose an item from the roadmap that interests you
2. **Open an Issue** - Discuss the implementation approach
3. **Submit a PR** - Implement the feature following our [Contributing Guide](CONTRIBUTING.md)
4. **Review & Test** - Help review PRs from other contributors

## 📊 Release Schedule

- **Minor Releases (v2.x)** - Every 2-3 months
- **Patch Releases (v2.x.y)** - As needed for bug fixes
- **Major Releases (v3.0+)** - When significant architectural changes are ready

## 📝 Notes

- This roadmap is subject to change based on community feedback and priorities
- Features are listed in approximate order of priority within each release
- Timelines are estimates and may shift based on contributor availability
- Security and critical bug fixes will be prioritized over new features

---

**Last Updated:** February 2026

For questions about the roadmap, please open a [GitHub Discussion](https://github.com/mattam1234/GAPI/discussions).
