/**
 * background.js — GAPI Browser Extension service worker (Manifest V3)
 *
 * Responsibilities:
 *  1. Set up periodic health-check alarms.
 *  2. Handle the `PICK_GAME` message from popup.js (keeps the request alive
 *     even if the popup is closed).
 *  3. Manage the extension badge (green = connected, red = disconnected).
 */

'use strict';

const STORAGE_KEY_SERVER = 'gapiServerUrl';
const DEFAULT_SERVER     = 'http://localhost:5000';
const ALARM_NAME         = 'gapi-health-check';
const CHECK_INTERVAL_MIN = 1;  // minutes

/* ─── Badge helpers ──────────────────────────────────────────────────────── */
function setBadge(online) {
  const text  = online ? '' : '!';
  const color = online ? '#3fb950' : '#f85149';
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

/* ─── Health check ───────────────────────────────────────────────────────── */
async function healthCheck() {
  const stored = await chrome.storage.sync.get([STORAGE_KEY_SERVER]);
  const url    = (stored[STORAGE_KEY_SERVER] || DEFAULT_SERVER) + '/api/health';
  try {
    const r = await fetch(url, { cache: 'no-store' });
    setBadge(r.ok);
  } catch {
    setBadge(false);
  }
}

/* ─── Alarm ──────────────────────────────────────────────────────────────── */
chrome.alarms.create(ALARM_NAME, { periodInMinutes: CHECK_INTERVAL_MIN });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM_NAME) healthCheck();
});

/* ─── Message handler ────────────────────────────────────────────────────── */
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'PICK_GAME') {
    (async () => {
      const stored = await chrome.storage.sync.get([STORAGE_KEY_SERVER]);
      const base   = stored[STORAGE_KEY_SERVER] || DEFAULT_SERVER;
      const mode   = msg.mode || 'random';
      try {
        const r    = await fetch(`${base}/api/random-game?mode=${mode}`, { cache: 'no-store' });
        const data = await r.json();
        sendResponse({ ok: true, game: data.game || data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;  // keep channel open for async response
  }
});

/* ─── Install / startup ──────────────────────────────────────────────────── */
chrome.runtime.onInstalled.addListener(() => {
  healthCheck();
});

self.addEventListener('activate', () => {
  healthCheck();
});
