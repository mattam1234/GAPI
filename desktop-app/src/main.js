'use strict';

/**
 * main.js — GAPI Desktop App main process (Electron)
 *
 * Responsibilities
 * ────────────────
 * 1. Create and manage the main BrowserWindow.
 * 2. Create a system tray icon with a context menu:
 *      • Pick a Game       — asks renderer to run a quick-pick
 *      • Open GAPI          — opens the main window
 *      • Open in Browser    — opens the server URL in the default browser
 *      • ─── separator ───
 *      • Connection status  — shows connected / disconnected (non-clickable)
 *      • Settings           — opens settings modal in renderer
 *      • ─── separator ───
 *      • Quit               — quits the app
 * 3. Periodic health-check against the configured GAPI server URL.
 * 4. Desktop notifications when a game is picked.
 * 5. Persist settings (server URL, window size/position) using electron-store.
 */

const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  nativeImage,
  ipcMain,
  shell,
  Notification,
} = require('electron');
const path = require('path');
const Store = require('electron-store');

// ─── Persistent settings ─────────────────────────────────────────────────────
const store = new Store({
  defaults: {
    serverUrl:   'http://localhost:5000',
    windowBounds: {width: 1000, height: 700},
  },
});

// ─── Globals ──────────────────────────────────────────────────────────────────
let mainWindow  = null;
let tray        = null;
let isConnected = false;
let healthTimer = null;
const CHECK_INTERVAL_MS = 30_000; // 30 s

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow();
  createTray();
  startHealthCheck();
});

app.on('window-all-closed', () => {
  // On macOS keep the app running in the tray even when all windows are closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else {
    mainWindow?.show();
  }
});

app.on('before-quit', () => {
  if (healthTimer) {
    clearInterval(healthTimer);
  }
});

// ─── BrowserWindow ────────────────────────────────────────────────────────────

function createWindow() {
  const {width, height} = store.get('windowBounds');

  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth:  600,
    minHeight: 400,
    show: false,           // shown after ready-to-show
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#0d1117',
    icon: _trayIcon(),
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => mainWindow.show());

  // Persist window size on resize
  mainWindow.on('resize', () => {
    if (!mainWindow.isMaximized()) {
      store.set('windowBounds', mainWindow.getBounds());
    }
  });

  // Hide to tray on close (macOS) / minimize on Windows+Linux
  mainWindow.on('close', event => {
    if (process.platform === 'darwin' && !app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ─── Tray ─────────────────────────────────────────────────────────────────────

function _trayIcon() {
  // Use a bundled asset if present; fall back to a plain nativeImage
  const iconPath = path.join(__dirname, '..', 'assets', 'tray-icon.png');
  try {
    const img = nativeImage.createFromPath(iconPath);
    if (!img.isEmpty()) {
      return img.resize({width: 16, height: 16});
    }
  } catch {}
  return nativeImage.createEmpty();
}

function createTray() {
  tray = new Tray(_trayIcon());
  tray.setToolTip('GAPI Game Picker');
  updateTrayMenu();

  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.focus() : mainWindow.show();
    } else {
      createWindow();
    }
  });
}

function updateTrayMenu() {
  if (!tray) {
    return;
  }
  const serverUrl  = store.get('serverUrl');
  const statusIcon = isConnected ? '🟢' : '🔴';

  const menu = Menu.buildFromTemplate([
    {
      label: '🎮  Pick a Game',
      click: () => quickPickFromTray(),
    },
    {
      label: '🪟  Open GAPI Window',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        } else {
          createWindow();
        }
      },
    },
    {
      label: '↗  Open in Browser',
      click: () => shell.openExternal(serverUrl),
    },
    {type: 'separator'},
    {
      label: `${statusIcon}  ${isConnected ? 'Connected' : 'Disconnected'}`,
      enabled: false,
    },
    {
      label: '⚙  Settings',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.webContents.send('open-settings');
        } else {
          createWindow();
        }
      },
    },
    {type: 'separator'},
    {
      label: 'Quit GAPI',
      role: 'quit',
    },
  ]);

  tray.setContextMenu(menu);
}

// ─── Quick pick from tray ─────────────────────────────────────────────────────

async function quickPickFromTray() {
  const serverUrl = store.get('serverUrl');
  try {
    const resp = await fetch(`${serverUrl}/api/pick`, {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({mode: 'random'}),
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = await resp.json();
    const game = data.game ?? data;
    const name = game?.name ?? 'Unknown Game';

    // Show desktop notification
    if (Notification.isSupported()) {
      const n = new Notification({
        title: '🎮 Time to play!',
        body:  name,
        icon:  _trayIcon(),
      });
      n.show();
    }

    // Send picked game to renderer if window is open
    mainWindow?.webContents.send('game-picked', game);

    // Open window to show result
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  } catch (err) {
    // Show error notification
    if (Notification.isSupported()) {
      new Notification({
        title: 'GAPI — Pick failed',
        body:  err.message ?? 'Could not reach the GAPI server.',
      }).show();
    }
  }
}

// ─── Health check ─────────────────────────────────────────────────────────────

async function checkHealth() {
  const serverUrl = store.get('serverUrl');
  try {
    const resp = await fetch(`${serverUrl}/api/health`, {cache: 'no-store'});
    const wasConnected = isConnected;
    isConnected = resp.ok;
    if (wasConnected !== isConnected) {
      updateTrayMenu();
      mainWindow?.webContents.send('connection-status', isConnected);
    }
  } catch {
    if (isConnected) {
      isConnected = false;
      updateTrayMenu();
      mainWindow?.webContents.send('connection-status', false);
    }
  }
}

function startHealthCheck() {
  checkHealth(); // immediate first check
  healthTimer = setInterval(checkHealth, CHECK_INTERVAL_MS);
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────

/** Renderer → main: save a new server URL */
ipcMain.handle('set-server-url', (_event, url) => {
  const trimmed = String(url).trim().replace(/\/$/, '') || 'http://localhost:5000';
  store.set('serverUrl', trimmed);
  checkHealth();
  return trimmed;
});

/** Renderer → main: get current server URL */
ipcMain.handle('get-server-url', () => {
  return store.get('serverUrl');
});

/** Renderer → main: get current connection status */
ipcMain.handle('get-connection-status', () => {
  return isConnected;
});

/** Renderer → main: trigger a quick pick */
ipcMain.handle('quick-pick', async (_event, mode = 'random') => {
  const serverUrl = store.get('serverUrl');
  try {
    const resp = await fetch(`${serverUrl}/api/pick`, {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({mode}),
    });
    const data = await resp.json();
    if (!resp.ok) {
      return {ok: false, error: data.error ?? `HTTP ${resp.status}`};
    }
    const game = data.game ?? data;
    if (Notification.isSupported()) {
      new Notification({
        title: '🎮 Time to play!',
        body:  game?.name ?? 'Game picked!',
      }).show();
    }
    return {ok: true, game};
  } catch (err) {
    return {ok: false, error: err.message};
  }
});

/** Renderer → main: fetch library */
ipcMain.handle('get-library', async (_event, {search, platform} = {}) => {
  const serverUrl = store.get('serverUrl');
  const params = new URLSearchParams();
  if (search)   { params.set('search',   search); }
  if (platform && platform !== 'all') { params.set('platform', platform); }
  const qs = params.toString() ? `?${params}` : '';
  try {
    const resp = await fetch(`${serverUrl}/api/library${qs}`);
    const data = await resp.json();
    return {ok: resp.ok, data};
  } catch (err) {
    return {ok: false, error: err.message};
  }
});

/** Renderer → main: fetch history */
ipcMain.handle('get-history', async () => {
  const serverUrl = store.get('serverUrl');
  try {
    const resp = await fetch(`${serverUrl}/api/history`);
    const data = await resp.json();
    return {ok: resp.ok, data};
  } catch (err) {
    return {ok: false, error: err.message};
  }
});

/** Renderer → main: open external URL */
ipcMain.handle('open-external', (_event, url) => {
  shell.openExternal(url);
});
