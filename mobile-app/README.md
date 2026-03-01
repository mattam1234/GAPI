# GAPI Mobile App

A **React Native** application for iOS and Android that connects to your running
GAPI server and lets you pick a random game, browse your library, and review
your pick history — all from your phone.

## Features

- **🎮 Quick Pick** — one tap to pick a random game with three modes:
  Random / Unplayed / Barely Played
- **📚 Library Browser** — full game list with real-time search and platform
  filter (Steam / Epic / GOG / Xbox / PSN / Nintendo Switch)
- **🕒 History** — your last 20+ picks with relative timestamps
- **⚙ Settings** — configure your GAPI server URL (persisted across restarts)
- **Platform badges** — coloured labels for each gaming platform
- **Dark theme** — GitHub-dark colour palette throughout
- **Pull-to-refresh** everywhere

## Requirements

| Tool | Minimum version |
|------|----------------|
| Node.js | 18+ |
| npm / Yarn | 8+ / 1.22+ |
| React Native CLI | 0.73+ |
| Xcode (iOS) | 14+ |
| Android Studio | Giraffe+ |
| JDK | 17+ |

## Quick Start

```bash
cd mobile-app

# Install JavaScript dependencies
npm install

# iOS — install CocoaPods
cd ios && pod install && cd ..

# Start Metro bundler
npm start

# Run on iOS simulator
npm run ios

# Run on Android emulator / device
npm run android
```

## Project Structure

```
mobile-app/
├── App.tsx                         # Root component
├── src/
│   ├── AppNavigator.tsx            # Bottom-tab navigation
│   ├── context/
│   │   └── ServerConfigContext.tsx # GAPI server URL + connection state
│   ├── hooks/
│   │   └── useGapiApi.ts           # REST API wrapper hook
│   ├── screens/
│   │   ├── PickScreen.tsx          # Home — pick a game
│   │   ├── LibraryScreen.tsx       # Browse library
│   │   ├── HistoryScreen.tsx       # Recent picks
│   │   └── SettingsScreen.tsx      # Server config
│   ├── components/
│   │   ├── GameCard.tsx            # Game detail card
│   │   └── PlatformBadge.tsx       # Platform label badge
│   └── utils/
│       └── formatters.ts           # Playtime / date formatters
└── __tests__/
    ├── formatters.test.ts          # Unit tests for formatters
    └── PlatformBadge.test.tsx      # Component snapshot tests
```

## Configuration

Set your GAPI server URL in the **Settings** tab.  The app persists it in
AsyncStorage so it survives app restarts.

Default: `http://localhost:5000`

> For a device connected to the same Wi-Fi network as your GAPI server, use
> the server's local IP address (e.g. `http://192.168.1.100:5000`).

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Connectivity check |
| `POST /api/pick` | Pick a random game |
| `GET /api/library` | Browse / search library |
| `GET /api/history` | Recent pick history |

## Testing

```bash
npm test
```

## Building for Release

### Android APK

```bash
cd android
./gradlew assembleRelease
# APK: android/app/build/outputs/apk/release/app-release.apk
```

### iOS Archive

Open `ios/GAPIApp.xcworkspace` in Xcode, select **Product → Archive**, then
distribute via TestFlight or App Store Connect.
