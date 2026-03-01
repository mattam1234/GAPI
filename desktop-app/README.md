# GAPI Desktop App

An **Electron** desktop application for macOS, Windows, and Linux that puts
GAPI in your system tray.  Pick a random game, browse your library, and get
a desktop notification — all without opening a browser tab.

## Features

- **🎮 Quick Pick** — three pick modes: Random / Unplayed / Barely Played
- **📚 Library Browser** — full game list with search and platform filter
- **🕒 Pick History** — recent picks with relative timestamps
- **⚙ Settings** — configurable GAPI server URL (persisted across restarts)
- **System Tray**
  - Tray icon with connection indicator badge
  - Context menu: Pick a Game / Open Window / Open in Browser / Settings / Quit
  - Desktop `Notification` when a game is picked (from tray or in-app)
- **Periodic health check** — tray badge turns red when server is unreachable
- **🎮 Gamepad / Controller support** — full Gamepad API integration (see below)
- **macOS** — native hidden inset title bar, stays in tray when window is closed
- **Windows / Linux** — standard windowed app, minimise to tray on close

## Requirements

| Tool | Version |
|------|---------|
| Node.js | 18+ |
| npm | 9+ |
| Electron | 28+ (installed via `npm install`) |

## Quick Start

```bash
cd desktop-app
npm install
npm start
```

## Project Structure

```
desktop-app/
├── src/
│   ├── main.js       # Main process (tray, IPC, health check, windows)
│   └── preload.js    # contextBridge preload — exposes gapiAPI to renderer
├── renderer/
│   ├── index.html    # App UI
│   └── renderer.js   # UI logic (navigation, pick, library, history, settings)
├── assets/
│   ├── tray-icon.png # 16×16 tray icon (replace with your icon)
│   └── icon.png      # App icon for packaging
├── __tests__/
│   └── formatters.test.js  # Unit tests for shared formatters
└── package.json
```

## Configuration

Set your GAPI server URL in the **Settings** panel.  The app persists it via
`electron-store` (stored in the OS user data directory).

Default: `http://localhost:5000`

## Building Distributables

```bash
# macOS (DMG)
npm run dist:mac

# Windows (NSIS installer)
npm run dist:win

# Linux (AppImage + .deb)
npm run dist:linux

# All platforms (requires appropriate build tools)
npm run dist
```

Built files appear in `desktop-app/dist/`.

## System Tray

The tray icon appears in the system tray / menu bar as soon as the app starts.

| Tray menu item | Action |
|----------------|--------|
| 🎮 Pick a Game | Picks a random game and shows a desktop notification |
| 🪟 Open GAPI Window | Brings the main window to the front |
| ↗ Open in Browser | Opens the GAPI server URL in your default browser |
| 🟢/🔴 Connected/Disconnected | Status indicator (not clickable) |
| ⚙ Settings | Opens the Settings panel |
| Quit GAPI | Quits the application |

## Testing

```bash
npm test
```

## IPC API Reference

The renderer communicates with the main process through `window.gapiAPI`:

| Method | Description |
|--------|-------------|
| `getServerUrl()` | Get current server URL |
| `setServerUrl(url)` | Save new server URL |
| `getConnectionStatus()` | Current connection status |
| `quickPick(mode)` | Pick a random game |
| `getLibrary({search, platform})` | Fetch library |
| `getHistory()` | Fetch pick history |
| `openExternal(url)` | Open URL in browser |
| `onConnectionStatus(cb)` | Listen for status changes |
| `onGamePicked(cb)` | Listen for tray picks |
| `onOpenSettings(cb)` | Listen for settings open request |


## Gamepad / Controller Support

GAPI Desktop supports **any standard gamepad** via the [Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API).
Just connect a controller (Xbox, PlayStation, Switch Pro, etc.) and a HUD overlay
will confirm it is detected.

| Button | Action |
|--------|--------|
| **A / Cross** | Pick a Game |
| **B / Circle** | Reroll |
| **X / Square** | Navigate to Library panel |
| **Y / Triangle** | Navigate to History panel |
| **Start / Options** | Navigate to Settings panel |
| **D-Pad Left / Right** | Cycle between panels |
| **D-Pad Up / Down** | Scroll the active panel |
| **LB / L1** | Previous pick mode |
| **RB / R1** | Next pick mode |
| **LT / L2** (held) | Cycle VR filter (All → VR Supported → VR Only → No VR) |
| **Left stick (vertical)** | Scroll the active panel |
