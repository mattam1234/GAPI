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

/* ─── Controller / Gamepad support ──────────────────────────────────────────
 *
 * Uses the standard Gamepad API to let a connected gamepad control the app:
 *
 *   A / Cross         → Pick a Game (same as clicking the Pick button)
 *   B / Circle        → Reroll
 *   X / Square        → Navigate to Library panel
 *   Y / Triangle      → Navigate to History panel
 *   Start / Options   → Navigate to Settings panel
 *   D-Pad Left/Right  → Cycle between panels (Pick → Library → History → Settings)
 *   D-Pad Up/Down     → Scroll the active panel
 *   LB / L1           → Previous pick mode
 *   RB / R1           → Next pick mode
 *   LT / L2 (> 0.5)  → Toggle VR filter (cycles No-filter → vr_supported → vr_only → no_vr)
 *
 * A small controller HUD overlay shows the last detected input.
 * ──────────────────────────────────────────────────────────────────────── */

(function initControllerSupport() {
  'use strict';

  // Panel navigation order
  const PANELS = ['pick', 'library', 'history', 'settings'];
  // Pick modes (in order)
  const PICK_MODES   = ['random', 'unplayed', 'barely_played'];
  let   _panelIdx    = 0;   // current panel index
  let   _pickModeIdx = 0;   // current pick mode index
  let   _vrFilterIdx = 0;   // 0=any, 1=vr_supported, 2=vr_only, 3=no_vr

  // Debounce: track which buttons were pressed last frame
  const _prevPressed = {};
  let   _prevAxes    = {};
  let   _rafId       = null;

  // HUD element
  const _hud = document.createElement('div');
  _hud.id = 'gamepad-hud';
  Object.assign(_hud.style, {
    position:   'fixed',
    bottom:     '16px',
    right:      '16px',
    padding:    '6px 12px',
    background: 'rgba(0,0,0,0.7)',
    color:      '#58a6ff',
    borderRadius: '6px',
    fontSize:   '12px',
    fontWeight: '700',
    display:    'none',
    zIndex:     '9999',
    pointerEvents: 'none',
  });
  document.body.appendChild(_hud);

  let _hudTimer = null;
  function _showHud(msg) {
    _hud.textContent = `🎮 ${msg}`;
    _hud.style.display = 'block';
    clearTimeout(_hudTimer);
    _hudTimer = setTimeout(() => { _hud.style.display = 'none'; }, 2000);
  }

  /** Switch to a panel by name */
  function _gotoPanel(name) {
    const idx = PANELS.indexOf(name);
    if (idx < 0) { return; }
    _panelIdx = idx;
    document.querySelectorAll('.nav-btn').forEach(b => {
      const active = b.dataset.panel === name;
      b.classList.toggle('active', active);
      if (active) { b.setAttribute('aria-current', 'page'); }
      else { b.removeAttribute('aria-current'); }
    });
    document.querySelectorAll('.panel').forEach(p => {
      p.classList.toggle('active', p.id === `panel-${name}`);
    });
    // loadLibrary / loadHistory are module-level functions in the outer renderer script
    if (name === 'library' && typeof loadLibrary === 'function') { loadLibrary(); } // eslint-disable-line no-undef
    if (name === 'history' && typeof loadHistory === 'function') { loadHistory(); } // eslint-disable-line no-undef
  }

  /** Cycle pick mode buttons */
  function _setPickMode(idx) {
    _pickModeIdx = ((idx % PICK_MODES.length) + PICK_MODES.length) % PICK_MODES.length;
    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === PICK_MODES[_pickModeIdx]);
    });
    // pickMode is the module-level variable declared in the outer renderer script
    if (typeof pickMode !== 'undefined') { // eslint-disable-line no-undef
      pickMode = PICK_MODES[_pickModeIdx]; // eslint-disable-line no-undef
    }
    _showHud(`Mode: ${PICK_MODES[_pickModeIdx].replace('_', ' ')}`);
  }

  /** Cycle VR filter (only applicable when on pick panel) */
  const VR_LABELS = ['All', 'VR Supported', 'VR Only', 'No VR'];
  function _cycleVrFilter() {
    _vrFilterIdx = (_vrFilterIdx + 1) % 4;
    _showHud(`VR: ${VR_LABELS[_vrFilterIdx]}`);
  }

  /** Scroll active panel content */
  function _scroll(delta) {
    const active = document.querySelector('.panel.active');
    if (active) { active.scrollBy({top: delta, behavior: 'smooth'}); }
  }

  /** Main gamepad poll loop */
  function _pollGamepads() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (const gp of gamepads) {
      if (!gp || !gp.connected) { continue; }

      const b = gp.buttons;
      const a = gp.axes;

      // Helper: button just pressed this frame
      const pressed = (idx) => b[idx] && b[idx].pressed;
      const justPressed = (idx) => pressed(idx) && !_prevPressed[`${gp.index}_${idx}`];

      // A / Cross (button 0) — Pick
      // doPick is the module-level async function in the outer renderer script
      if (justPressed(0)) { if (typeof doPick === 'function') { doPick(); } _showHud('Pick!'); } // eslint-disable-line no-undef

      // B / Circle (button 1) — Reroll
      if (justPressed(1)) { if (typeof doPick === 'function') { doPick(); } _showHud('Reroll!'); } // eslint-disable-line no-undef

      // X / Square (button 2) — Library panel
      if (justPressed(2)) { _gotoPanel('library'); _showHud('Library'); }

      // Y / Triangle (button 3) — History panel
      if (justPressed(3)) { _gotoPanel('history'); _showHud('History'); }

      // LB / L1 (button 4) — Previous pick mode
      if (justPressed(4)) { _setPickMode(_pickModeIdx - 1); }

      // RB / R1 (button 5) — Next pick mode
      if (justPressed(5)) { _setPickMode(_pickModeIdx + 1); }

      // LT / L2 (button 6) — Cycle VR filter
      if (b[6] && b[6].value > 0.5 && !((_prevAxes[`${gp.index}_lt`] ?? 0) > 0.5)) {
        _cycleVrFilter();
      }
      _prevAxes[`${gp.index}_lt`] = b[6] ? b[6].value : 0;

      // Start / Options (button 9) — Settings panel
      if (justPressed(9)) { _gotoPanel('settings'); _showHud('Settings'); }

      // D-Pad left (button 14) / right (button 15) — cycle panels
      if (justPressed(14)) {
        _gotoPanel(PANELS[Math.max(0, _panelIdx - 1)]);
        _showHud(PANELS[Math.max(0, _panelIdx - 1)]);
      }
      if (justPressed(15)) {
        _gotoPanel(PANELS[Math.min(PANELS.length - 1, _panelIdx + 1)]);
        _showHud(PANELS[Math.min(PANELS.length - 1, _panelIdx + 1)]);
      }

      // D-Pad up (button 12) / down (button 13) — scroll
      if (pressed(12)) { _scroll(-60); }
      if (pressed(13)) { _scroll(60);  }

      // Left stick vertical (axis 1) — scroll
      const axisY = a[1] ?? 0;
      if (Math.abs(axisY) > 0.3) { _scroll(axisY * 80); }

      // Update previous-state map
      b.forEach((btn, idx) => {
        _prevPressed[`${gp.index}_${idx}`] = btn && btn.pressed;
      });
    }
    _rafId = requestAnimationFrame(_pollGamepads);
  }

  // Start polling when a gamepad is connected
  window.addEventListener('gamepadconnected', (ev) => {
    _showHud(`Controller connected: ${ev.gamepad.id.slice(0, 40)}`);
    if (!_rafId) { _rafId = requestAnimationFrame(_pollGamepads); }
  });

  window.addEventListener('gamepaddisconnected', (ev) => {
    _showHud('Controller disconnected');
    // Stop polling if no more gamepads
    const any = [...(navigator.getGamepads ? navigator.getGamepads() : [])].some(g => g && g.connected);
    if (!any && _rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
  });
}());
