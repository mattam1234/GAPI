'use strict';

const STORAGE_KEY_SERVER = 'gapiServerUrl';
const DEFAULT_SERVER     = 'http://localhost:5000';

const serverInput  = document.getElementById('server-url');
const btnSave      = document.getElementById('btn-save');
const saveStatus   = document.getElementById('save-status');

// Load current settings
chrome.storage.sync.get([STORAGE_KEY_SERVER], result => {
  serverInput.value = result[STORAGE_KEY_SERVER] || DEFAULT_SERVER;
});

// Save settings
btnSave.addEventListener('click', () => {
  const url = serverInput.value.trim().replace(/\/$/, '') || DEFAULT_SERVER;
  chrome.storage.sync.set({ [STORAGE_KEY_SERVER]: url }, () => {
    saveStatus.style.display = 'inline';
    setTimeout(() => { saveStatus.style.display = 'none'; }, 2000);
  });
});
