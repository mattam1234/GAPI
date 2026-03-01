/**
 * popup.js — GAPI Browser Extension popup script
 *
 * Communicates with a running GAPI server instance.  The server URL is stored
 * in chrome.storage.sync so it persists across browser sessions.
 *
 * API calls made:
 *   GET  <serverUrl>/api/random-game?mode=<mode>   → pick a game
 *   GET  <serverUrl>/api/health                    → connectivity check
 */

'use strict';

/* ─── Constants ──────────────────────────────────────────────────────────── */
const DEFAULT_SERVER = 'http://localhost:5000';
const STORAGE_KEY_SERVER = 'gapiServerUrl';
const STORAGE_KEY_LAST   = 'gapiLastGame';

/* ─── State ──────────────────────────────────────────────────────────────── */
let serverUrl   = DEFAULT_SERVER;
let currentGame = null;

/* ─── DOM refs ───────────────────────────────────────────────────────────── */
const statusDot       = document.getElementById('status-dot');
const placeholderText = document.getElementById('placeholder-text');
const gameNameEl      = document.getElementById('game-name');
const gameMetaEl      = document.getElementById('game-meta');
const metaPlaytime    = document.getElementById('meta-playtime');
const metaPlatform    = document.getElementById('meta-platform');
const errorMsg        = document.getElementById('error-msg');
const btnPick         = document.getElementById('btn-pick');
const btnOpen         = document.getElementById('btn-open');
const btnReroll       = document.getElementById('btn-reroll');
const filterMode      = document.getElementById('filter-mode');
const linkOpenGapi    = document.getElementById('link-open-gapi');

/* ─── Utilities ──────────────────────────────────────────────────────────── */
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = 'block';
}
function clearError() {
  errorMsg.style.display = 'none';
}

function setOnline(online) {
  statusDot.classList.toggle('offline', !online);
  statusDot.title = online ? 'Connected to GAPI' : 'Cannot reach GAPI server';
  btnPick.disabled = !online;
}

function formatPlaytime(minutes) {
  if (!minutes) return '0h played';
  if (minutes < 60) return `${minutes}m played`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h}h ${m}m played` : `${h}h played`;
}

function showGame(game) {
  currentGame = game;
  placeholderText.style.display  = 'none';
  gameNameEl.style.display       = 'block';
  gameMetaEl.style.display       = 'block';
  gameNameEl.textContent         = game.name || 'Unknown Game';
  metaPlaytime.textContent       = formatPlaytime(game.playtime_forever);
  metaPlatform.textContent       = `[${(game.platform || 'steam').toUpperCase()}]`;
  btnOpen.style.display    = 'inline-block';
  btnReroll.style.display  = 'inline-block';
  clearError();

  // Persist last pick
  chrome.storage.local.set({ [STORAGE_KEY_LAST]: game });

  // Show notification
  const notifTitle = '🎮 Time to play!';
  const notifMsg   = game.name || 'A game has been picked for you.';
  chrome.notifications?.create('gapi-pick', {
    type:    'basic',
    iconUrl: 'icons/icon48.png',
    title:   notifTitle,
    message: notifMsg,
  });
}

/* ─── API helpers ────────────────────────────────────────────────────────── */
async function checkHealth() {
  try {
    const r = await fetch(`${serverUrl}/api/health`, { cache: 'no-store' });
    setOnline(r.ok);
  } catch {
    setOnline(false);
  }
}

async function pickGame() {
  clearError();
  btnPick.disabled = true;
  btnPick.textContent = '⌛ Picking…';
  try {
    const mode = filterMode.value;
    const url  = `${serverUrl}/api/random-game?mode=${encodeURIComponent(mode)}`;
    const r    = await fetch(url, { cache: 'no-store' });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      showError(body.error || `Server error ${r.status}`);
      return;
    }
    const data = await r.json();
    const game = data.game || data;
    if (!game || !game.name) {
      showError('No game returned. Check your library is loaded in GAPI.');
      return;
    }
    showGame(game);
  } catch (err) {
    showError(`Cannot reach GAPI (${err.message}). Is the server running?`);
    setOnline(false);
  } finally {
    btnPick.disabled = false;
    btnPick.textContent = '🎮 Pick a Game';
  }
}

/* ─── Open game URL ──────────────────────────────────────────────────────── */
btnOpen.addEventListener('click', () => {
  if (!currentGame) return;
  const appid    = currentGame.appid || currentGame.game_id;
  const platform = (currentGame.platform || 'steam').toLowerCase();
  let url;
  if (platform === 'steam' && appid) {
    url = `https://store.steampowered.com/app/${appid}`;
  } else if (platform === 'epic') {
    url = `https://store.epicgames.com/`;
  } else if (platform === 'gog') {
    url = `https://www.gog.com/`;
  } else {
    url = `${serverUrl}`;
  }
  chrome.tabs.create({ url });
});

/* ─── Button wiring ──────────────────────────────────────────────────────── */
btnPick.addEventListener('click', pickGame);
btnReroll.addEventListener('click', pickGame);

/* ─── Init ───────────────────────────────────────────────────────────────── */
(async () => {
  // Load stored server URL
  const stored = await new Promise(resolve =>
    chrome.storage.sync.get([STORAGE_KEY_SERVER], r => resolve(r))
  );
  serverUrl      = stored[STORAGE_KEY_SERVER] || DEFAULT_SERVER;
  linkOpenGapi.href = serverUrl;

  // Restore last picked game (if any)
  const local = await new Promise(resolve =>
    chrome.storage.local.get([STORAGE_KEY_LAST], r => resolve(r))
  );
  if (local[STORAGE_KEY_LAST]) {
    showGame(local[STORAGE_KEY_LAST]);
  }

  await checkHealth();
})();
