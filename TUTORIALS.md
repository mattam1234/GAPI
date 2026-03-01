# GAPI Video Tutorials

Step-by-step written walkthroughs of the most common GAPI workflows.
Each section maps to a planned video tutorial.

---

## Table of Contents

1. [Getting Started — Steam Setup](#1-getting-started--steam-setup)
2. [Using the Web GUI](#2-using-the-web-gui)
3. [Connecting Platform Accounts](#3-connecting-platform-accounts)
4. [Smart & ML Recommendations](#4-smart--ml-recommendations)
5. [Live Picking Sessions](#5-live-picking-sessions)
6. [Playlists, Tags & Backlog Management](#6-playlists-tags--backlog-management)
7. [Review System & Ratings](#7-review-system--ratings)
8. [Discord Bot Setup](#8-discord-bot-setup)
9. [Notifications — Slack, Teams, IFTTT, Home Assistant](#9-notifications--slack-teams-ifttt-home-assistant)
10. [Browser Extension](#10-browser-extension)
11. [Docker Deployment](#11-docker-deployment)
12. [Admin Panel & User Management](#12-admin-panel--user-management)

---

## 1. Getting Started — Steam Setup

**Duration: ~5 min**

### Prerequisites
- Python 3.8+
- A Steam account

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/mattam1234/GAPI.git
   cd GAPI
   pip install -r requirements.txt
   ```

2. **Get your Steam API key**
   - Visit <https://steamcommunity.com/dev/apikey>
   - Enter any domain (e.g. `localhost`) and click **Register**.
   - Copy the generated key.

3. **Get your Steam 64-bit ID**
   - Visit <https://www.steamidfinder.com/> and look up your username.
   - Copy the number that looks like `76561198XXXXXXXXX`.

4. **Configure GAPI**
   ```bash
   cp config_template.json config.json
   ```
   Edit `config.json`:
   ```json
   {
     "steam_api_key": "PASTE_YOUR_KEY_HERE",
     "steam_id":      "PASTE_YOUR_STEAM_ID_HERE"
   }
   ```

5. **Start the web server**
   ```bash
   python gapi_gui.py
   ```
   Open <http://localhost:5000> in your browser.

---

## 2. Using the Web GUI

**Duration: ~8 min**

### Picking a random game

1. Log in with your Steam credentials (or the demo account).
2. Click **🎲 Pick Random Game** on the dashboard.
3. The picked game appears with playtime, platform badges, and store links.
4. Use **Reroll** to try again, or **Mark as played today** to log it.

### Filters

The filter bar on the dashboard lets you narrow picks by:

| Filter | Description |
|--------|-------------|
| Unplayed only | Games with 0 minutes played |
| Barely played | Under 2 hours (configurable) |
| Genre | Action, RPG, Puzzle… |
| Platform | Steam, Epic, GOG, Xbox, PSN |
| Tags | Your custom tags |

### History

The **History** tab shows your last 20 picks.  Click any entry to re-pick
or view store details.

---

## 3. Connecting Platform Accounts

**Duration: ~10 min**

### Epic Games

1. Register an OAuth application at
   <https://dev.epicgames.com/portal/applications>. Set the redirect URI to
   `http://localhost:5000/api/epic/oauth/callback`.
2. Add to `config.json`:
   ```json
   "epic_enabled":       true,
   "epic_client_id":     "YOUR_CLIENT_ID",
   "epic_client_secret": "YOUR_CLIENT_SECRET"
   ```
3. Restart GAPI and visit `http://localhost:5000/api/epic/oauth/authorize`.
4. After authorising, your Epic library appears in the game list.

### GOG Galaxy

1. Register at <https://devportal.gog.com/> and note your client ID/secret.
2. Add to `config.json`:
   ```json
   "gog_enabled":       true,
   "gog_client_id":     "YOUR_GOG_CLIENT_ID",
   "gog_client_secret": "YOUR_GOG_CLIENT_SECRET"
   ```
3. Visit `http://localhost:5000/api/gog/oauth/authorize` to connect.

### Xbox Game Pass

1. Create an Azure AD app registration at
   <https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps>
   with platform **Web** and redirect URI
   `http://localhost:5000/api/xbox/oauth/callback`.
2. Add to `config.json`:
   ```json
   "xbox_enabled":       true,
   "xbox_client_id":     "YOUR_AZURE_APP_ID",
   "xbox_client_secret": "YOUR_AZURE_CLIENT_SECRET"
   ```
3. Visit `http://localhost:5000/api/xbox/oauth/authorize` to connect.

### PlayStation Network

1. Log in at <https://my.playstation.com>.
2. Open DevTools (F12) → Application → Cookies → `my.playstation.com`.
3. Copy the value of the **npsso** cookie.
4. Send a POST request (**use HTTPS in production** to protect your NPSSO token):
   ```bash
   # Development (HTTP OK for localhost only)
   curl -X POST http://localhost:5000/api/psn/connect \
        -H 'Content-Type: application/json' \
        -d '{"npsso": "PASTE_YOUR_NPSSO_HERE"}'
   # Production — always use HTTPS
   curl -X POST https://your-gapi-server/api/psn/connect \
        -H 'Content-Type: application/json' \
        -d '{"npsso": "PASTE_YOUR_NPSSO_HERE"}'
   ```
5. Your PSN library is now available at `GET /api/psn/library`.

### Nintendo eShop

Nintendo does not provide a user-library API.  The Nintendo integration gives
you access to the **public catalog search**:

```bash
# Search for Zelda games
GET /api/nintendo/search?q=zelda

# Get price info
GET /api/nintendo/prices?nsuids=70010000000025,70010000012345
```

---

## 4. Smart & ML Recommendations

**Duration: ~6 min**

### Smart Recommendations (heuristic)

```
GET /api/recommendations/smart?count=10
```

Returns up to 10 games scored by:
- Genre / tag affinity with your well-played games
- Developer / publisher affinity
- Metacritic score boost
- Diversity pass (avoids recommending the same developer twice)

### ML Recommendations (numpy-powered)

```
GET /api/recommendations/ml?count=10&method=cf
```

Three `method` options:

| Method | Algorithm |
|--------|-----------|
| `cf`     | Item-based collaborative filtering (cosine similarity in genre space) |
| `mf`     | ALS implicit-feedback matrix factorization |
| `hybrid` | Weighted blend — 60% CF + 40% MF |

---

## 5. Live Picking Sessions

**Duration: ~7 min**

Live sessions let a group of players collectively vote on what to play.

1. **Create a session** (POST `/api/live-session`)
2. **Share the invite link** — participants click it to join
3. Each participant **casts their vote** — the game with the most votes wins
4. The organiser can **force-pick** at any time
5. Results update in real-time via Server-Sent Events (`GET /api/live-session/<id>/events`)

---

## 6. Playlists, Tags & Backlog Management

**Duration: ~8 min**

### Playlists

Organise games into named playlists (e.g. "Weekend Games", "Co-op Queue"):

```
POST /api/playlists          # create
GET  /api/playlists          # list all
GET  /api/playlists/<id>     # games in playlist
POST /api/playlists/<id>/games  # add game
```

### Tags

Apply custom tags to games for fine-grained filtering:

```
POST /api/games/<id>/tags    # {"tags": ["co-op", "short"]}
GET  /api/tags               # all your tags
```

### Backlog

The backlog is your "want to play" list:

```
POST /api/backlog/<game_id>  # add to backlog
GET  /api/backlog            # view backlog
DELETE /api/backlog/<id>     # remove
```

---

## 7. Review System & Ratings

**Duration: ~5 min**

Rate and review games you've played:

```
POST /api/reviews            # {"game_id": "steam:620", "rating": 9, "review": "..."}
GET  /api/reviews            # all your reviews
GET  /api/reviews/<game_id>  # review for a specific game
PUT  /api/reviews/<id>       # update review
```

Ratings appear in recommendation scoring — games you've rated highly get a
lower "recommendation urgency" (you've already played them well).

---

## 8. Discord Bot Setup

**Duration: ~6 min**

1. Create a bot at <https://discord.com/developers/applications>.
2. Enable **Message Content Intent** under Bot → Privileged Gateway Intents.
3. Copy the bot token and add to `config.json`:
   ```json
   "discord_bot_token": "YOUR_BOT_TOKEN_HERE"
   ```
4. Run the bot:
   ```bash
   python discord_bot.py
   ```
5. In your Discord server, type `!pick` to have the bot pick a random game and
   announce it in the channel.

---

## 9. Notifications — Slack, Teams, IFTTT, Home Assistant

**Duration: ~8 min**

Every game pick can automatically notify your team.

### Slack

1. Create an Incoming Webhook at <https://api.slack.com/apps>.
2. Add the webhook URL to `config.json`:
   ```json
   "slack_webhook_url": "https://hooks.slack.com/services/..."
   ```
3. Test: `POST /api/notifications/slack/test`

### Microsoft Teams

1. In Teams, add an **Incoming Webhook** connector to a channel.
2. Add the URL:
   ```json
   "teams_webhook_url": "https://outlook.office.com/webhook/..."
   ```
3. Test: `POST /api/notifications/teams/test`

### IFTTT

1. Connect the **Webhooks** service at <https://ifttt.com/maker_webhooks>.
2. Copy your key and set the event name:
   ```json
   "ifttt_webhook_key":  "YOUR_KEY",
   "ifttt_event_name":   "gapi_game_picked"
   ```
3. Test: `POST /api/notifications/ifttt/test`

### Home Assistant

1. In Home Assistant, create a **Webhook automation** trigger.
2. Add:
   ```json
   "homeassistant_url":        "http://homeassistant.local:8123",
   "homeassistant_token":      "YOUR_LONG_LIVED_TOKEN",
   "homeassistant_webhook_id": "gapi_game_picked"
   ```
3. Test: `POST /api/notifications/homeassistant/test`

---

## 10. Browser Extension

**Duration: ~4 min**

### Install

1. Download the `browser-extension/` directory from this repository.
2. Open `chrome://extensions` → enable **Developer mode**.
3. Click **Load unpacked** → select the `browser-extension/` folder.

### Use

- Click the GAPI icon in your toolbar.
- Select a **pick mode** (Random / Unplayed / Barely played).
- Click **🎮 Pick a Game**.
- Use **Open** to jump to the store page, or **↺ Reroll** to try again.

### Configure

Click **⚙ Settings** in the popup footer to set your GAPI server URL
(default: `http://localhost:5000`).

---

## 11. Docker Deployment

**Duration: ~10 min**

### Quick start

```bash
cp .env.example .env
# Edit .env with your credentials

docker compose up -d
docker compose logs -f gapi-web
```

Open <http://localhost> (or your domain via HTTPS).

### Services started

| Service | Purpose |
|---------|---------|
| `gapi-web`   | Main Flask application |
| `gapi-db`    | PostgreSQL 15 database |
| `gapi-redis` | Redis 7 cache + session store |
| `gapi-nginx` | Nginx reverse proxy (HTTP→HTTPS, WebSocket) |

### Development mode

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up
```

Source code is volume-mounted; Flask runs with hot-reload.

---

## 12. Admin Panel & User Management

**Duration: ~5 min**

The admin panel (`/admin` in the web GUI, or `GET /api/admin/settings`) lets
you:

- **Change Steam credentials** without restarting the server
- **Toggle platform integrations** (Epic, GOG, Xbox, PSN, Nintendo)
- **Adjust recommendation thresholds** (well-played hours, barely-played hours)
- **Manage users** — add, remove, change passwords
- **View server statistics** — pick count, cache hits, API response times

Only users with the `admin` role can access the admin panel.
