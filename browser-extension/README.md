# GAPI Browser Extension

A **Manifest V3** Chrome/Firefox browser extension that lets you pick a random
game from your GAPI library directly from the browser toolbar — no tab switching
required.

## Features

- **Quick-pick popup** — one click to get a random game suggestion
- **Pick mode filter** — Random, Unplayed only, or Barely played
- **Open in store** — jump straight to the Steam/Epic/GOG store page
- **Reroll** — instantly pick again
- **Connection indicator** — live badge shows whether GAPI server is reachable
- **Desktop notification** — shows picked game name via browser notifications
- **Configurable server URL** — works with any running GAPI instance

## Installation

### Chrome / Edge (Developer Mode)

1. Download or clone this repository.
2. Navigate to `chrome://extensions` (or `edge://extensions`).
3. Enable **Developer mode** (top-right toggle).
4. Click **Load unpacked** and select the `browser-extension/` directory.
5. The GAPI icon appears in the toolbar — click it to open the picker.

### Firefox

1. Navigate to `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…** and select
   `browser-extension/manifest.json`.

> **Permanent Firefox install**: Package as a `.xpi` by zipping the
> `browser-extension/` directory and signing via
> [addons.mozilla.org](https://addons.mozilla.org/developers/).

## Configuration

Click the **⚙ Settings** link inside the popup (or right-click the toolbar
icon → Options) to set:

| Setting | Default | Description |
|---------|---------|-------------|
| **GAPI Server URL** | `http://localhost:5000` | URL of your running GAPI web server |

## How it works

```
[Popup click]
      │
      ▼
GET  <server>/api/random-game?mode=<mode>
      │
      ▼
Display game name + playtime + platform badge
```

The background service worker runs a health-check alarm every minute and
updates the toolbar badge (green = connected, red ● = disconnected).

## Building Icons

The extension ships with bundled icons in `icons/` (`icon16.png`, `icon32.png`,
`icon48.png`, `icon128.png`). To regenerate them — no third-party dependencies
required, pure Python stdlib:

```bash
python generate_icons.py
```

This redraws the green game-controller badge at all four sizes. Edit
`generate_icons.py` to tweak the artwork or palette, or replace the PNGs with
any 16×16 / 32×32 / 48×48 / 128×128 images of your own.

## API Compatibility

The extension calls two GAPI endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Connectivity check |
| `GET /api/random-game?mode=<mode>` | Pick a random game |

Both endpoints are available in all GAPI versions.
