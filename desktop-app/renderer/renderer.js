'use strict';

/**
 * renderer.js — GAPI Desktop App renderer process.
 *
 * Communicates with the main process exclusively through window.gapiAPI
 * (exposed via the contextBridge preload script).
 */

/* ─── Platform badge colours ─────────────────────────────────────────────── */
const PLATFORM_COLORS = {
  steam:    {bg: '#1b2838', text: '#c7d5e0'},
  epic:     {bg: '#2d2d2d', text: '#ffffff'},
  gog:      {bg: '#8b008b', text: '#ffffff'},
  xbox:     {bg: '#107c10', text: '#ffffff'},
  psn:      {bg: '#003087', text: '#ffffff'},
  nintendo: {bg: '#e4000f', text: '#ffffff'},
};

function platformBadgeHTML(platform) {
  const key    = (platform ?? '').toLowerCase();
  const colors = PLATFORM_COLORS[key] ?? {bg: '#21262d', text: '#8b949e'};
  const label  = platform?.toUpperCase() ?? '?';
  return `<span class="platform-badge"
               style="background:${colors.bg};color:${colors.text}">${label}</span>`;
}

/* ─── Formatters ─────────────────────────────────────────────────────────── */
function formatPlaytime(minutes) {
  if (!minutes) { return '0h played'; }
  if (minutes < 60) { return `${minutes}m played`; }
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m played` : `${h}h played`;
}

function formatRelativeTime(isoString) {
  if (!isoString) { return ''; }
  const diff = Date.now() - new Date(isoString).getTime();
  const sec  = Math.floor(diff / 1000);
  if (sec < 60)          { return 'just now'; }
  const min = Math.floor(sec / 60);
  if (min < 60)          { return `${min}m ago`; }
  const h = Math.floor(min / 60);
  if (h < 24)            { return `${h}h ago`; }
  const d = Math.floor(h / 24);
  if (d < 7)             { return `${d}d ago`; }
  const w = Math.floor(d / 7);
  if (w < 5)             { return `${w}w ago`; }
  return new Date(isoString).toLocaleDateString();
}

/* ─── State ──────────────────────────────────────────────────────────────── */
let currentGame = null;
let pickMode    = 'random';
let libPlatform = 'all';

/* ─── DOM refs ───────────────────────────────────────────────────────────── */
const statusDot      = document.getElementById('nav-status-dot');
const statusText     = document.getElementById('nav-status-text');
const errorBar       = document.getElementById('error-bar');
const gamePlaceholder = document.getElementById('placeholder');
const gameDisplay    = document.getElementById('game-display');
const gameNameEl     = document.getElementById('game-name');
const gameMetaEl     = document.getElementById('game-meta');
const reasonBox      = document.getElementById('reason-box');
const genreRow       = document.getElementById('genre-row');
const btnPick        = document.getElementById('btn-pick');
const btnReroll      = document.getElementById('btn-reroll');
const btnOpenStore   = document.getElementById('btn-open-store');
const secondaryRow   = document.getElementById('secondary-row');
const gameList       = document.getElementById('game-list');
const gameCount      = document.getElementById('game-count');
const historyList    = document.getElementById('history-list');
const librarySearch  = document.getElementById('library-search');
const filterRow      = document.getElementById('filter-row');
const serverUrlInput = document.getElementById('server-url-input');
const btnSaveSettings = document.getElementById('btn-save-settings');
const saveStatus     = document.getElementById('save-status');
const btnOpenGapi    = document.getElementById('btn-open-gapi');

/* ─── Navigation ─────────────────────────────────────────────────────────── */
document.querySelectorAll('.nav-btn[data-panel]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-current', 'page');
    document.getElementById(`panel-${btn.dataset.panel}`).classList.add('active');

    // Lazy-load data when switching panels
    if (btn.dataset.panel === 'library') { loadLibrary(); }
    if (btn.dataset.panel === 'history') { loadHistory(); }
  });
});

/* ─── Connection status ──────────────────────────────────────────────────── */
function setConnected(online) {
  statusDot.className = `status-dot ${online ? 'online' : 'offline'}`;
  statusText.textContent = online ? 'Connected' : 'Disconnected';
}

window.gapiAPI.onConnectionStatus(online => setConnected(online));
window.gapiAPI.getConnectionStatus().then(setConnected);

/* ─── Pick mode buttons ──────────────────────────────────────────────────── */
document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    pickMode = btn.dataset.mode;
  });
});

/* ─── Game display ───────────────────────────────────────────────────────── */
function showGame(game, reason) {
  currentGame = game;
  gamePlaceholder.style.display = 'none';
  gameDisplay.style.display     = 'block';
  secondaryRow.style.display    = 'flex';
  errorBar.style.display        = 'none';

  gameNameEl.textContent = game.name ?? 'Unknown Game';
  gameMetaEl.innerHTML   = `${formatPlaytime(game.playtime_forever)}&ensp;
    ${platformBadgeHTML(game.platform)}`;

  if (reason) {
    reasonBox.textContent  = `💡 ${reason}`;
    reasonBox.style.display = 'block';
  } else {
    reasonBox.style.display = 'none';
  }

  // Genre chips
  genreRow.innerHTML = '';
  (game.genres ?? []).slice(0, 5).forEach(g => {
    const chip  = document.createElement('span');
    chip.className = 'genre-chip';
    chip.textContent = g.description ?? g;
    genreRow.appendChild(chip);
  });
}

function showError(msg) {
  errorBar.textContent  = msg;
  errorBar.style.display = 'block';
}

/* ─── Pick action ────────────────────────────────────────────────────────── */
async function doPick() {
  btnPick.disabled = true;
  btnPick.textContent = '⌛  Picking…';
  errorBar.style.display = 'none';
  try {
    const result = await window.gapiAPI.quickPick(pickMode);
    if (result.ok && result.game) {
      showGame(result.game, result.game.reason);
    } else {
      showError(result.error ?? 'No game returned.');
    }
  } finally {
    btnPick.disabled = false;
    btnPick.textContent = '🎮  Pick a Game';
  }
}

btnPick.addEventListener('click', doPick);
btnReroll.addEventListener('click', doPick);

/* ─── Open store ─────────────────────────────────────────────────────────── */
btnOpenStore.addEventListener('click', async () => {
  if (!currentGame) { return; }
  const appid    = currentGame.appid ?? currentGame.game_id;
  const platform = (currentGame.platform ?? 'steam').toLowerCase();
  let url;
  if (platform === 'steam' && appid) {
    url = `https://store.steampowered.com/app/${appid}`;
  } else if (platform === 'epic') {
    url = 'https://store.epicgames.com/';
  } else if (platform === 'gog') {
    url = 'https://www.gog.com/';
  } else {
    const serverUrl = await window.gapiAPI.getServerUrl();
    url = serverUrl;
  }
  window.gapiAPI.openExternal(url);
});

/* ─── Game picked from tray ──────────────────────────────────────────────── */
window.gapiAPI.onGamePicked(game => showGame(game, null));

/* ─── Library ────────────────────────────────────────────────────────────── */
const PLATFORMS = ['all', 'steam', 'epic', 'gog', 'xbox', 'psn', 'nintendo'];

// Build filter chips once
PLATFORMS.forEach(p => {
  const chip = document.createElement('button');
  chip.className = `filter-chip${p === 'all' ? ' active' : ''}`;
  chip.textContent = p === 'all' ? 'All' : p.toUpperCase();
  chip.dataset.platform = p;
  chip.addEventListener('click', () => {
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    libPlatform = p;
    loadLibrary();
  });
  filterRow.appendChild(chip);
});

let searchDebounce = null;
librarySearch.addEventListener('input', () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(loadLibrary, 300);
});

async function loadLibrary() {
  gameCount.textContent = 'Loading…';
  gameList.innerHTML    = '';
  const result = await window.gapiAPI.getLibrary({
    search:   librarySearch.value.trim(),
    platform: libPlatform,
  });
  if (!result.ok) {
    gameCount.textContent = result.error ?? 'Error loading library.';
    return;
  }
  const games = result.data?.games ?? [];
  const total = result.data?.total ?? games.length;
  gameCount.textContent = `${total.toLocaleString()} game${total !== 1 ? 's' : ''}`;
  games.forEach(game => {
    const li   = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = game.name;
    const play = document.createElement('span');
    play.className = 'play';
    play.textContent = formatPlaytime(game.playtime_forever);
    li.appendChild(name);
    li.appendChild(play);
    li.innerHTML += platformBadgeHTML(game.platform);
    gameList.appendChild(li);
  });
  if (games.length === 0) {
    const li = document.createElement('li');
    li.style.color = '#8b949e';
    li.style.padding = '20px 0';
    li.textContent = 'No games found.';
    gameList.appendChild(li);
  }
}

/* ─── History ────────────────────────────────────────────────────────────── */
async function loadHistory() {
  historyList.innerHTML = '';
  const result = await window.gapiAPI.getHistory();
  const entries = result.data?.history ?? [];
  entries.forEach((entry, idx) => {
    const li      = document.createElement('li');
    const idxBadge = document.createElement('span');
    idxBadge.className = 'history-idx';
    idxBadge.textContent = String(idx + 1);
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = entry.game_name;
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = formatRelativeTime(entry.picked_at);
    li.appendChild(idxBadge);
    li.appendChild(name);
    li.appendChild(meta);
    li.innerHTML += platformBadgeHTML(entry.platform);
    historyList.appendChild(li);
  });
  if (entries.length === 0) {
    const li = document.createElement('li');
    li.style.color = '#8b949e';
    li.style.padding = '20px 0';
    li.textContent = 'No picks yet.';
    historyList.appendChild(li);
  }
}

/* ─── Settings ───────────────────────────────────────────────────────────── */
window.gapiAPI.getServerUrl().then(url => {
  serverUrlInput.value = url;
});

btnSaveSettings.addEventListener('click', async () => {
  const url = await window.gapiAPI.setServerUrl(serverUrlInput.value);
  serverUrlInput.value = url;
  saveStatus.style.display = 'inline';
  setTimeout(() => { saveStatus.style.display = 'none'; }, 2500);
});

btnOpenGapi.addEventListener('click', async () => {
  const url = await window.gapiAPI.getServerUrl();
  window.gapiAPI.openExternal(url);
});

window.gapiAPI.onOpenSettings(() => {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector('[data-panel="settings"]').classList.add('active');
  document.getElementById('panel-settings').classList.add('active');
});
