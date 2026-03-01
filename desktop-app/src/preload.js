'use strict';

/**
 * preload.js — Electron contextBridge preload script.
 *
 * Exposes a safe `window.gapiAPI` object to the renderer process with
 * typed wrappers around ipcRenderer.invoke calls.  The renderer never
 * gets direct access to Node.js or Electron internals.
 */

const {contextBridge, ipcRenderer} = require('electron');

contextBridge.exposeInMainWorld('gapiAPI', {
  /** Get the currently configured server URL */
  getServerUrl: () => ipcRenderer.invoke('get-server-url'),

  /** Save a new server URL (triggers health-check) */
  setServerUrl: (url) => ipcRenderer.invoke('set-server-url', url),

  /** Get the last-known connection status */
  getConnectionStatus: () => ipcRenderer.invoke('get-connection-status'),

  /** Pick a random game.  Returns {ok, game} or {ok: false, error} */
  quickPick: (mode = 'random') => ipcRenderer.invoke('quick-pick', mode),

  /** Fetch the game library */
  getLibrary: (opts) => ipcRenderer.invoke('get-library', opts),

  /** Fetch pick history */
  getHistory: () => ipcRenderer.invoke('get-history'),

  /** Open a URL in the system default browser */
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  /** Listen for connection status changes pushed from the main process */
  onConnectionStatus: (cb) =>
    ipcRenderer.on('connection-status', (_e, status) => cb(status)),

  /** Listen for a game picked via the tray quick-pick */
  onGamePicked: (cb) =>
    ipcRenderer.on('game-picked', (_e, game) => cb(game)),

  /** Listen for the "open-settings" signal from the tray */
  onOpenSettings: (cb) =>
    ipcRenderer.on('open-settings', () => cb()),

  /** Remove all listeners (call on component unmount / cleanup) */
  removeAllListeners: (channel) =>
    ipcRenderer.removeAllListeners(channel),
});
