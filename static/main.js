// Surface runtime errors to the console for easier diagnosis
        window.addEventListener('error', function (ev) {
            try { console.error('Runtime error caught:', ev && ev.error ? ev.error : ev.message); } catch(e){}
        });
        window.addEventListener('unhandledrejection', function (ev) {
            try { console.error('Unhandled promise rejection:', ev.reason); } catch(e){}
        });

        // CSRF disabled - safeFetch is now just an alias for fetch with credentials
        window.safeFetch = function(url, options = {}) {
            options.credentials = options.credentials || 'same-origin';
            return fetch(url, options);
        };

        let currentGame = null;
        let activeVoteSession = null;
        let voteTimerInterval = null;
        let libraryLoadPromise = Promise.resolve();
        const PRESENCE_CACHE_TTL_MS = 5 * 60 * 1000;
        let presenceCache = { friends: [], fetchedAt: 0, error: null };

        // ---- Spinner helpers ----
        function showSpinner(label) {
            document.getElementById('spinner-label').textContent = label || 'Loading…';
            document.getElementById('loading-overlay').classList.add('active');
        }
        function hideSpinner() {
            document.getElementById('loading-overlay').classList.remove('active');
        }

        function handleTopbarSearch(query) {
            switchTab('library', null);
            const input = document.getElementById('library-search');
            if (input) { input.value = query; }

            const trimmed = query.trim();
            if (!trimmed) {
                return;
            }

            libraryLoadPromise
                .catch(() => {})
                .then(() => searchLibraryDebounced());
        }

        // ---- Dark Mode ----
        function applyTheme(theme) {
            const normalized = theme === 'dark' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', normalized);
            localStorage.setItem('gapi_theme', normalized);
            const btn = document.getElementById('dark-mode-btn');
            if (btn) btn.textContent = normalized === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';
            const themeBtn = document.getElementById('theme-toggle-btn');
            if (themeBtn) themeBtn.textContent = normalized === 'dark' ? '☀️' : '🌙';
        }
        function toggleDarkMode() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        }
        // ── Sidebar ──────────────────────────────────────────────────────────────
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const btn = sidebar ? sidebar.querySelector('.sidebar-toggle-btn') : null;
            if (!sidebar) return;
            const collapsed = sidebar.classList.toggle('collapsed');
            localStorage.setItem('gapi_sidebar_collapsed', collapsed ? '1' : '0');
            if (btn) btn.textContent = collapsed ? '›' : '‹';
        }

        (function initSidebar() {
            document.addEventListener('DOMContentLoaded', function() {
                const sidebar = document.getElementById('sidebar');
                if (!sidebar) return;
                const btn = sidebar.querySelector('.sidebar-toggle-btn');
                if (localStorage.getItem('gapi_sidebar_collapsed') === '1') {
                    sidebar.classList.add('collapsed');
                    if (btn) btn.textContent = '›';
                }
            });
        })();

        // ── Discord Rich Presence ─────────────────────────────────────────────────
        let _presenceEnabled = false;

        function initPresenceToggle() {
            const saved = localStorage.getItem('gapi_presence_enabled');
            _presenceEnabled = saved === '1';
            const toggle = document.getElementById('presence-enabled-toggle');
            if (toggle) toggle.checked = _presenceEnabled;
        }

        function setPresenceEnabled(enabled) {
            _presenceEnabled = !!enabled;
            localStorage.setItem('gapi_presence_enabled', enabled ? '1' : '0');
            const banner = document.getElementById('presence-status-banner');
            if (banner) {
                banner.style.display = '';
                banner.style.background = enabled ? 'rgba(35,165,89,0.15)' : 'rgba(255,255,255,0.05)';
                banner.style.color = enabled ? '#23A559' : 'var(--text-muted)';
                banner.style.border = '1px solid ' + (enabled ? 'rgba(35,165,89,0.3)' : 'var(--border)');
                banner.textContent = enabled ? '✅ Rich Presence is ON — your Discord status will update when you pick a game.' : 'Rich Presence is OFF.';
                setTimeout(() => { if (banner) banner.style.display = 'none'; }, 3500);
            }
        }

        async function updatePresence(gameName, playtimeHours) {
            if (!_presenceEnabled) return;
            try {
                await safeFetch('/api/presence/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({game: gameName, playtime_hours: playtimeHours})
                });
            } catch(e) { /* silent */ }
        }

        async function clearPresence() {
            try {
                await safeFetch('/api/presence/clear', { method: 'POST' });
                const banner = document.getElementById('presence-status-banner');
                if (banner) {
                    banner.style.display = '';
                    banner.style.background = 'rgba(255,255,255,0.05)';
                    banner.style.color = 'var(--text-muted)';
                    banner.style.border = '1px solid var(--border)';
                    banner.textContent = 'Discord status cleared.';
                    setTimeout(() => { banner.style.display = 'none'; }, 2500);
                }
            } catch(e) { console.debug('clearPresence error', e); }
        }

        async function testPresence() {
            try {
                const r = await safeFetch('/api/presence/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({game: 'GameNight (test)', playtime_hours: 0})
                });
                const data = await r.json();
                const banner = document.getElementById('presence-status-banner');
                if (banner) {
                    banner.style.display = '';
                    if (data.ok || data.updated) {
                        banner.style.background = 'rgba(35,165,89,0.15)';
                        banner.style.color = '#23A559';
                        banner.style.border = '1px solid rgba(35,165,89,0.3)';
                        banner.textContent = '✅ Discord status updated! Check your Discord profile.';
                    } else {
                        banner.style.background = 'rgba(242,63,66,0.1)';
                        banner.style.color = '#F23F42';
                        banner.style.border = '1px solid rgba(242,63,66,0.3)';
                        banner.textContent = '⚠️ ' + (data.error || 'Could not update presence. Is Discord running and DISCORD_CLIENT_ID set?');
                    }
                    setTimeout(() => { banner.style.display = 'none'; }, 4000);
                }
            } catch(e) { console.debug('testPresence error', e); }
        }

        function normalizePresenceFriends(friends) {
            return Array.isArray(friends) ? friends : [];
        }

        function updatePresenceCache(friends, error = null) {
            presenceCache = {
                friends: normalizePresenceFriends(friends),
                fetchedAt: Date.now(),
                error: error || null,
            };
        }

        function resetPresenceCache() {
            presenceCache = { friends: [], fetchedAt: 0, error: null };
        }

        function getPresenceStatusLabel(friend) {
            const state = Number(friend && friend.personastate || 0);
            if (friend && friend.current_game) return 'Playing';
            return PERSONA_STATE[state] || 'Offline';
        }

        function getPresenceStatusClass(friend) {
            const state = Number(friend && friend.personastate || 0);
            if (friend && friend.current_game) return 'presence-status-online';
            if (state === 2) return 'presence-status-dnd';
            if (state === 3 || state === 4) return 'presence-status-idle';
            if (state > 0) return 'presence-status-online';
            return 'presence-status-offline';
        }

        function getPresenceInitials(name) {
            return String(name || 'G')
                .trim()
                .split(/\s+/)
                .slice(0, 2)
                .map(part => part ? part[0] : '')
                .join('')
                .toUpperCase() || 'G';
        }

        function getPresenceActivitySummary(friend) {
            if (friend && friend.current_game) {
                return `Playing ${friend.current_game}`;
            }
            if (friend && friend.recently_played && friend.recently_played.length > 0) {
                const recent = friend.recently_played[0];
                const hours = recent.playtime_2weeks ? ` · ${(recent.playtime_2weeks / 60).toFixed(1)}h this week` : '';
                return `Recently active: ${recent.name || 'Game'}${hours}`;
            }
            const state = Number(friend && friend.personastate || 0);
            return PERSONA_STATE[state] || 'Online now';
        }

        function renderPresenceEmpty(containerClass, message, detail = '') {
            return `<div class="${containerClass}">
                <span>${escapeHtml(message || 'No friends online right now.')}</span>
                ${detail ? `<span style="font-size:0.85em;">${escapeHtml(detail)}</span>` : ''}
            </div>`;
        }

        function renderPresenceAvatarItem(friend) {
            const name = friend.personaname || 'Friend';
            const statusClass = getPresenceStatusClass(friend);
            const avatarMarkup = friend.avatarfull
                ? `<img src="${escAttr(friend.avatarfull)}" alt="${escapeHtml(name)}" loading="lazy">`
                : `<span>${escapeHtml(getPresenceInitials(name))}</span>`;
            return `<div class="presence-avatar-item" title="${escapeHtml(name)} — ${escapeHtml(getPresenceActivitySummary(friend))}">
                <div class="presence-avatar">
                    ${avatarMarkup}
                    <span class="presence-avatar-status ${statusClass}"></span>
                </div>
                <div class="presence-avatar-name">${escapeHtml(name)}</div>
            </div>`;
        }

        function renderPresenceFriendRow(friend) {
            const name = friend.personaname || 'Friend';
            const statusClass = getPresenceStatusClass(friend);
            const avatarMarkup = friend.avatarfull
                ? `<img src="${escAttr(friend.avatarfull)}" alt="${escapeHtml(name)}" loading="lazy">`
                : `<span>${escapeHtml(getPresenceInitials(name))}</span>`;
            return `<div class="online-friend-row">
                <div class="online-friend-avatar">
                    ${avatarMarkup}
                    <span class="presence-avatar-status ${statusClass}"></span>
                </div>
                <div class="online-friend-info">
                    <div class="online-friend-name-row">
                        <div class="online-friend-name">${escapeHtml(name)}</div>
                        <div class="online-friend-status">${escapeHtml(getPresenceStatusLabel(friend))}</div>
                    </div>
                    <div class="online-friend-game">${escapeHtml(getPresenceActivitySummary(friend))}</div>
                </div>
            </div>`;
        }

        function renderPresenceContainers(friends, options = {}) {
            const activeFriends = normalizePresenceFriends(friends)
                .filter(friend => Number(friend && friend.personastate || 0) > 0 || !!(friend && friend.current_game))
                .sort((a, b) => {
                    const aPlaying = !!(a && a.current_game);
                    const bPlaying = !!(b && b.current_game);
                    if (aPlaying !== bPlaying) return aPlaying ? -1 : 1;
                    return Number(b && b.personastate || 0) - Number(a && a.personastate || 0);
                });

            const stripEl = document.getElementById('presence-avatars');
            const panelEl = document.getElementById('dash-online-list');
            const countEl = document.getElementById('presence-count');
            const emptyTitle = options.emptyTitle || 'No friends online right now.';
            const emptyDetail = options.emptyDetail || '';

            if (countEl) {
                countEl.textContent = activeFriends.length ? `${activeFriends.length} online` : '';
            }
            if (stripEl) {
                stripEl.innerHTML = activeFriends.length
                    ? activeFriends.map(renderPresenceAvatarItem).join('')
                    : renderPresenceEmpty('presence-empty', emptyTitle, emptyDetail);
            }
            if (panelEl) {
                panelEl.innerHTML = activeFriends.length
                    ? activeFriends.map(renderPresenceFriendRow).join('')
                    : renderPresenceEmpty('dash-empty', emptyTitle, emptyDetail);
            }

            return activeFriends;
        }

        async function updatePresenceStrip(force = false) {
            const stripEl = document.getElementById('presence-avatars');
            const panelEl = document.getElementById('dash-online-list');
            if (!stripEl && !panelEl) return [];

            const cacheAge = Date.now() - (presenceCache.fetchedAt || 0);
            const hasFreshCache = Array.isArray(presenceCache.friends)
                && presenceCache.fetchedAt
                && cacheAge < PRESENCE_CACHE_TTL_MS;

            let friends = hasFreshCache ? presenceCache.friends : [];
            let emptyTitle = 'No friends online right now.';
            let emptyDetail = presenceCache.error || '';

            if (force || !hasFreshCache) {
                try {
                    const response = await safeFetch('/api/friends');
                    if (response.status === 503) {
                        const data = await response.json();
                        emptyTitle = 'Friend activity is unavailable.';
                        emptyDetail = data.error || 'Steam is not configured, or the profile is private.';
                        updatePresenceCache([], emptyDetail);
                        friends = [];
                    } else if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    } else {
                        const data = await response.json();
                        friends = normalizePresenceFriends(data.friends);
                        updatePresenceCache(friends, null);
                        emptyDetail = '';
                    }
                } catch (error) {
                    if (!friends.length) {
                        emptyTitle = 'Friend activity could not be loaded.';
                        emptyDetail = error.message || 'Please try again later.';
                        presenceCache.error = emptyDetail;
                    }
                }
            }

            renderPresenceContainers(friends, { emptyTitle, emptyDetail });
            return friends;
        }

        async function markDashboardNotification(id) {
            if (!id) return;
            try {
                await safeFetch('/api/notifications/read', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ids: [id] })
                });
                await loadDashboard();
            } catch (error) {
                console.debug('markDashboardNotification error', error);
            }
        }

        async function markAllDashboardNotificationsRead() {
            try {
                await safeFetch('/api/notifications/read', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                await loadDashboard();
            } catch (error) {
                console.debug('markAllDashboardNotificationsRead error', error);
            }
        }
        // Restore saved theme on load
        (function() {
            const saved = localStorage.getItem('gapi_theme') || 'dark';
            document.addEventListener('DOMContentLoaded', () => applyTheme(saved));
        })();

        // Initialize
        /**
         * Generates skeleton loading HTML for list-type containers.
         * @param {number} count - Number of skeleton rows to render.
         * @returns {string} HTML string.
         */
        function renderSkeletonList(count = 6) {
            let html = '';
            for (let i = 0; i < count; i++) {
                html += `
                <div class="skeleton-item">
                    <div class="skeleton skeleton-thumb"></div>
                    <div class="skeleton-text-block">
                        <div class="skeleton skeleton-text-line wide"></div>
                        <div class="skeleton skeleton-text-line mid"></div>
                    </div>
                    <div class="skeleton skeleton-text-line short" style="flex-shrink:0;"></div>
                </div>`;
            }
            return html;
        }

        /**
         * Generates skeleton loading HTML for the stats grid.
         * @returns {string} HTML string.
         */
        function renderStatSkeleton() {
            return `<div class="stats-grid">
                ${[1,2,3,4].map(() => `<div class="skeleton skeleton-stat-card"></div>`).join('')}
            </div>`;
        }

        /**
         * Clears all user-specific DOM data. Called on logout to ensure
         * no stale data from the previous user is visible.
         */
        function clearUserData() {
            const listIds = [
                'library-list', 'favorites-list', 'ignored-games-list',
                'backlog-list', 'playlists-list', 'playlists-container',
                'achievements-list', 'friends-list', 'recommendations-list',
                'schedule-list', 'schedule-pending-list', 'notifications-list', 'leaderboard-list', 'dash-leaderboard-list',
                'users-list', 'common-games-list', 'presence-avatars', 'dash-online-list'
            ];
            listIds.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = '';
            });
            // Clear stats panel
            const statsContent = document.getElementById('stats-content');
            if (statsContent) statsContent.innerHTML = '';
            // Clear game details cache so no cross-user data leaks
            clearGameDetailsCache();
            resetPresenceCache();
            const presenceCount = document.getElementById('presence-count');
            if (presenceCount) presenceCount.textContent = '';
            const topbarSearch = document.getElementById('topbar-search');
            if (topbarSearch) topbarSearch.value = '';
            const librarySearch = document.getElementById('library-search');
            if (librarySearch) librarySearch.value = '';
            // Reset status bar
            const statusEl = document.getElementById('status');
            if (statusEl) statusEl.textContent = 'Please sign in';
        }

        async function init() {
            showSpinner('Loading your game library…');
            try {
                renderChatRoomList();
                await updateStatus();
                await Promise.all([loadLibrary(), loadFavorites(), loadStats(), loadUsers(), refreshTagFilter(), refreshPlatformFilters()]);
                checkInitialSetup();
                
                // Real-time updates are now managed by setAuthenticatedUI()
            } finally {
                hideSpinner();
            }
        }
        
        async function updateStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                if (data.ready) {
                    document.getElementById('status').textContent = 
                        `✅ Loaded ${data.total_games} games | ${data.favorites} favorites`;
                } else {
                    document.getElementById('status').textContent = data.message;
                }
            } catch (error) {
                document.getElementById('status').textContent = '❌ Error loading data';
            }
        }

        // ============ GAME DETAILS CACHING SYSTEM ============
        const gameDetailsCache = new Map();
        const detailsLoadingQueue = new Map();

        /**
         * Fetch and cache game details from API
         * Returns immediately if cached, loads async otherwise
         */
        async function loadGameDetailsAsync(appId) {
            // Return if already cached
            if (gameDetailsCache.has(appId)) {
                return gameDetailsCache.get(appId);
            }
            
            // Return cached promise if already loading
            if (detailsLoadingQueue.has(appId)) {
                return detailsLoadingQueue.get(appId);
            }
            
            // Start async fetch
            const fetchPromise = fetch(`/api/game/${appId}/details`)
                .then(r => r.json())
                .then(data => {
                    if (data && !data.error) {
                        gameDetailsCache.set(appId, data);
                        detailsLoadingQueue.delete(appId);
                        return data;
                    } else {
                        detailsLoadingQueue.delete(appId);
                        return null;
                    }
                })
                .catch(err => {
                    console.error(`Failed to load details for ${appId}:`, err);
                    detailsLoadingQueue.delete(appId);
                    return null;
                });
            
            detailsLoadingQueue.set(appId, fetchPromise);
            return fetchPromise;
        }

        /**
         * Get cached game details (synchronous, returns null if not cached)
         */
        function getGameDetailsFromCache(appId) {
            return gameDetailsCache.get(appId) || null;
        }

        /**
         * Clear game cache (useful for manual refresh)
         */
        function clearGameDetailsCache() {
            gameDetailsCache.clear();
            detailsLoadingQueue.clear();
            console.log('Game details cache cleared');
        }

        /**
         * Pre-load details for multiple games (batch async loading with concurrency limit)
         * Games are loaded on-demand when user clicks on them - this just primes the cache
         */
        async function preloadGameDetails(appIds) {
            // With lazy loading, we don't need to preload all details anymore
            // Details are loaded on-demand from cache (database) or API
            // This function is kept for compatibility but doesn't preload anymore
            return [];
        }
        
        function switchTab(tabName, event) {
            if (tabName === 'playlists') tabName = 'backlog';
            // Sync sidebar active state
            document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
            const navItem = document.getElementById('nav-' + tabName);
            if (navItem) navItem.classList.add('active');

            // Update topbar title
            const titleMap = {
                dashboard: 'Dashboard',
                picker: 'Game Picker', library: 'Library',
                stats: 'Statistics', users: 'Users', multiuser: 'Multi-User',
                schedule: 'Schedule', playlists: 'Playlists', backlog: 'Lists',
                ignored: 'No-Play List', achievements: 'Achievements', friends: 'Friends',
                recommendations: 'For You', chat: 'Chat',
                sessions: 'Sessions', notifications: 'Notifications',
                plugins: 'Plugins', settings: 'Settings', admin: 'Admin'
            };
            const titleEl = document.getElementById('topbar-page-title');
            if (titleEl) titleEl.textContent = titleMap[tabName] || 'GameNight';

            // Ensure we're working with a navigation trigger even when called programmatically
            let button = null;
            if (event && event.target) {
                button = event.target.closest('.sidebar-item, .tab') || event.target;
            }
            if (!button) {
                button = document.querySelector(`.sidebar-item[onclick*="switchTab('${tabName}'"]`)
                    || document.querySelector(`.tab[onclick*="switchTab('${tabName}'"]`);
            }

            if (tabName !== 'chat' && typeof stopChatPolling === 'function') stopChatPolling();
            if (tabName !== 'sessions' && typeof stopSessionsPolling === 'function') stopSessionsPolling();
            if (tabName !== 'backlog') closeBacklogEntryPreviewModal();

            document.querySelectorAll('.tab, .sidebar-item').forEach(tab => {
                tab.classList.remove('active');
                if (typeof tab.setAttribute === 'function') tab.setAttribute('aria-selected', 'false');
            });
            if (button && button.classList) {
                button.classList.add('active');
                if (typeof button.setAttribute === 'function') button.setAttribute('aria-selected', 'true');
            }

            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            const tabContent = document.getElementById(tabName + '-tab');
            if (tabContent) {
                tabContent.classList.add('active');
            } else {
                console.error('Tab content not found: ' + tabName + '-tab');
                return;
            }

            if (tabName === 'library') libraryLoadPromise = Promise.resolve(loadLibrary());
            if (tabName === 'stats') {
                loadStats();
                loadStatsUsers();
            }
            if (tabName === 'users') { loadUsers(); loadPasswordResetRequests(); }
            if (tabName === 'multiuser') {
                loadUsersForMultiUser();
                const commonGamesList = document.getElementById('common-games-list');
                if (commonGamesList) {
                    commonGamesList.innerHTML = '<div class="loading">Select users and click "Show Common Games"</div>';
                }
            }
            if (tabName === 'schedule') loadSchedule();
            if (tabName === 'backlog') {
                loadBacklog();
            }
            if (tabName === 'ignored') loadIgnoredGames();
            if (tabName === 'achievements') loadUserAchievements();
            if (tabName === 'friends') loadFriends();
            if (tabName === 'recommendations') loadRecommendations();
            if (tabName === 'chat') {
                loadChatMessages(false);
                loadOnlineUsers();
                loadRoomInfo();
                startChatPolling();
            }
            if (tabName === 'sessions') {
                loadLiveSessionDiscordLocations();
                loadLiveSessions();
                if (activeLiveSessionId) {
                    openLiveSession(activeLiveSessionId);
                }
                startSessionsPolling();
            }
            if (tabName === 'settings') {
                loadSettings();
            }
            if (tabName === 'dashboard') {
                loadDashboard();
            }
        }

        // ── Dashboard ─────────────────────────────────────────────────────────
        async function loadDashboard() {
            // Fetch data in parallel; fail gracefully
            const [libRes, sessRes, schedRes, recRes, notifRes] = await Promise.allSettled([
                safeFetch('/api/library').then(r => r.json()),
                safeFetch('/api/live-session/active').then(r => r.json()),
                safeFetch('/api/schedule').then(r => r.json()),
                safeFetch(`/api/recommendations?count=4&refresh_seed=${Date.now()}`).then(r => r.json()),
                safeFetch('/api/notifications?unread_only=false').then(r => r.json()),
            ]);

            const games    = libRes.status   === 'fulfilled' ? (libRes.value.games    || []) : [];
            const sessions = sessRes.status  === 'fulfilled' ? (sessRes.value.sessions || []) : [];
            const allEvs   = schedRes.status === 'fulfilled' ? (schedRes.value.events  || []) : [];
            const recommendations = recRes.status === 'fulfilled' ? (recRes.value.recommendations || []) : [];
            const notifications = notifRes.status === 'fulfilled' ? (notifRes.value.notifications || []) : [];
            const unreadCount = notifRes.status === 'fulfilled'
                ? (notifRes.value.unread_count || 0)
                : notifications.filter(n => !n.is_read).length;

            await loadLeaderboard({ listId: 'dash-leaderboard-list', metricId: 'dash-leaderboard-metric', limit: 5 });

            // Filter upcoming events
            const now = Date.now();
            const upcoming = allEvs.filter(e => {
                if (!e.date) return false;
                try { return new Date(e.date + (e.time ? 'T' + e.time : 'T00:00')).getTime() >= now - 3600000; }
                catch (_) { return false; }
            }).sort((a, b) => new Date(a.date) - new Date(b.date));

            // ── Welcome banner ──────────────────────────────────────────────
            const rawName = (document.getElementById('sidebar-username') || {}).textContent
                         || (document.getElementById('current-username') || {}).textContent || '';
            const firstName = rawName.trim().split(/\s+/)[0] || 'Gamer';
            const greetEl = document.getElementById('dash-greeting');
            const hintEl  = document.getElementById('dash-events-teaser');
            if (greetEl) greetEl.textContent = firstName + ' 👋';
            if (hintEl)  hintEl.textContent  = upcoming.length
                ? `Ready for game night? You have ${upcoming.length} upcoming event${upcoming.length !== 1 ? 's' : ''}.`
                : recommendations.length
                    ? `${recommendations.length} personalised pick${recommendations.length !== 1 ? 's are' : ' is'} waiting for you.`
                    : 'Ready for game night?';

            // ── Stat cards ──────────────────────────────────────────────────
            const _stat = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
            _stat('dash-stat-library',  games.length);
            _stat('dash-stat-sessions', sessions.length);
            _stat('dash-stat-events',   upcoming.length);
            _stat('dash-stat-catalog',  unreadCount);
            updateNotifBadge(unreadCount);

            // ── Top games grid ──────────────────────────────────────────────
            const topGames = [...games]
                .sort((a, b) => (b.playtime_hours || 0) - (a.playtime_hours || 0))
                .slice(0, 6);
            const gridEl = document.getElementById('dash-games-grid');
            if (gridEl) {
                if (topGames.length === 0) {
                    gridEl.innerHTML = '<div class="dash-empty" style="grid-column:1/-1; padding:24px;">No games yet — add some to your library.</div>';
                } else {
                    gridEl.innerHTML = topGames.map(g => {
                        const appId = g.app_id || g.appid;
                        const coverUrl = appId
                            ? `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/library_600x900.jpg`
                            : '';
                        const fallback = appId
                            ? `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`
                            : '';
                        const safeName = escapeHtml(g.name || 'Game');
                        const hrs = g.playtime_hours != null ? `${g.playtime_hours}h` : '';
                        return `<div class="dash-game-tile" onclick="showGameDetails(${appId || 0}, '${escAttr(g.name || '')}', ${g.playtime_hours || 0}, '')">
                            <div class="dash-game-tile-cover">
                                <img src="${coverUrl}" alt="${safeName}"
                                     onerror="this.src='${fallback}'" loading="lazy">
                            </div>
                            <div class="dash-game-tile-name" title="${safeName}">${safeName}</div>
                            ${hrs ? `<div class="dash-game-tile-hours">${hrs}</div>` : ''}
                        </div>`;
                    }).join('');
                }
            }

            // ── Recommended games ───────────────────────────────────────────
            const recEl = document.getElementById('dash-recommendations-list');
            if (recEl) {
                if (recommendations.length === 0) {
                    recEl.innerHTML = `<div class="dash-empty" style="padding:18px 0;">
                        <span style="opacity:0.45; font-size:0.85em;">No recommendations yet. Add more games to your library to personalize For You.</span>
                        <button class="dash-card-link" style="margin-top:8px;" onclick="switchTab('recommendations',event)">Open For You →</button>
                    </div>`;
                } else {
                    recEl.innerHTML = recommendations.slice(0, 4).map((game, idx) => {
                        const appId = game.appid || game.app_id || 0;
                        const safeName = escapeHtml(game.name || 'Game');
                        const safeNameJs = escAttr(game.name || 'Game');
                        const reason = escapeHtml(game.recommendation_reason || 'Good fit for your library');
                        const score = Number(game.recommendation_score || 0);
                        const scoreText = score ? score.toFixed(1) : '—';
                        const playtime = game.playtime_hours || 0;
                        const platform = escapeHtml(game.platform || game.store || 'Steam');
                        return `<div class="dash-rec-item" onclick="showGameDetails(${appId}, '${safeNameJs}', ${playtime}, '')">
                            <div class="dash-rec-rank">${idx + 1}</div>
                            <div class="dash-rec-thumb">${renderGameListThumb(appId, game.name)}</div>
                            <div class="dash-rec-info">
                                <div class="dash-rec-topline">
                                    <div class="dash-rec-name">${safeName}</div>
                                    <div class="dash-rec-score">★ ${scoreText}</div>
                                </div>
                                <div class="dash-rec-reason">${reason}</div>
                                <div class="dash-rec-meta">${playtime > 0 ? `${playtime}h played` : 'Never played'} · ${platform}</div>
                            </div>
                            <div class="dash-rec-actions">
                                <button class="dash-rec-btn" onclick="event.stopPropagation(); showGameDetails(${appId}, '${safeNameJs}', ${playtime}, '')">Details</button>
                                <button class="dash-rec-btn primary" onclick="event.stopPropagation(); toggleFavorite(${appId})">★</button>
                            </div>
                        </div>`;
                    }).join('');
                }
            }

            // ── Live sessions list ──────────────────────────────────────────
            const sessListEl = document.getElementById('dash-sessions-list');
            if (sessListEl) {
                if (sessions.length === 0) {
                    sessListEl.innerHTML = `<div class="dash-empty"><span style="opacity:0.4;">No active sessions right now.</span>
                        <button class="dash-card-link" style="margin-top:6px;" onclick="switchTab('sessions',event)">Start one →</button></div>`;
                } else {
                    sessListEl.innerHTML = sessions.slice(0, 5).map(s => {
                        const gameName = escapeHtml(s.game_title || s.game_name || 'Game TBD');
                        const sessName = escapeHtml(s.name || 'Session');
                        const appId    = s.game_appid || s.appid;
                        const thumb    = appId
                            ? `<img src="https://cdn.akamai.steamstatic.com/steam/apps/${appId}/capsule_sm_120.jpg" onerror="this.style.display='none'" loading="lazy">`
                            : '🎮';
                        return `<div class="dash-session-item">
                            <div class="dash-session-thumb">${thumb}</div>
                            <div class="dash-session-info">
                                <div class="dash-session-name">${sessName}</div>
                                <div class="dash-session-game">${gameName}</div>
                            </div>
                            <span class="dash-live-badge">Live</span>
                        </div>`;
                    }).join('');
                }
            }

            // ── Notifications preview ──────────────────────────────────────
            const notifEl = document.getElementById('dash-notifications-list');
            if (notifEl) {
                const latest = notifications.slice(0, 4);
                if (latest.length === 0) {
                    notifEl.innerHTML = `<div class="dash-empty" style="padding:16px 0;">
                        <span style="opacity:0.45; font-size:0.85em;">You're all caught up.</span>
                        <button class="dash-card-link" style="margin-top:8px;" onclick="switchTab('notifications',event)">Open inbox →</button>
                    </div>`;
                } else {
                    const typeIcon = { info:'ℹ️', success:'✅', warning:'⚠️', error:'❌', friend_request:'👥' };
                    notifEl.innerHTML = latest.map(n => {
                        const isRead = !!n.is_read;
                        return `<div class="dash-notif-item${isRead ? ' read' : ''}" onclick="switchTab('notifications',event)">
                            <div class="dash-notif-icon">${typeIcon[n.type] || '🔔'}</div>
                            <div class="dash-notif-body">
                                <div class="dash-notif-title-row">
                                    <div class="dash-notif-title">${escapeHtml(n.title || 'Notification')}</div>
                                    <div class="dash-notif-time">${n.created_at ? new Date(n.created_at).toLocaleString() : ''}</div>
                                </div>
                                <div class="dash-notif-message">${escapeHtml(n.message || '')}</div>
                            </div>
                            ${!isRead ? `<button class="dash-rec-btn" onclick="event.stopPropagation(); markDashboardNotification(${n.id})">Mark read</button>` : ''}
                        </div>`;
                    }).join('');
                    if (unreadCount > 1) {
                        notifEl.innerHTML += `<div style="padding:0 18px 14px;">
                            <button class="dash-card-link" onclick="markAllDashboardNotificationsRead()">Mark all read</button>
                        </div>`;
                    }
                }
            }

            // ── Upcoming events ─────────────────────────────────────────────
            const upcomingEl = document.getElementById('dash-upcoming-list');
            if (upcomingEl) {
                if (upcoming.length === 0) {
                    upcomingEl.innerHTML = `<div class="dash-empty"><span style="opacity:0.4; font-size:0.85em;">No upcoming events.</span>
                        <button class="dash-card-link" style="margin-top:6px;" onclick="switchTab('schedule',event)">Plan one →</button></div>`;
                } else {
                    upcomingEl.innerHTML = upcoming.slice(0, 4).map(ev => {
                        let monthStr = '', dayStr = '';
                        try {
                            const d = new Date(ev.date + 'T00:00');
                            monthStr = d.toLocaleDateString('en', { month: 'short' });
                            dayStr   = d.getDate();
                        } catch(_) {}
                        return `<div class="dash-event-item">
                            <div class="dash-event-date-box">
                                <div class="dash-event-month">${monthStr}</div>
                                <div class="dash-event-day">${dayStr}</div>
                            </div>
                            <div style="flex:1; min-width:0;">
                                <div class="dash-event-title">${escapeHtml(ev.title || 'Event')}</div>
                                <div class="dash-event-time">${escapeHtml(ev.time || 'Time TBD')}</div>
                            </div>
                        </div>`;
                    }).join('');
                }
            }

            // ── Activity feed (most-played games as proxy for recent activity) ─
            const actEl = document.getElementById('dash-activity-feed');
            if (actEl) {
                const recent = [...games]
                    .filter(g => (g.playtime_hours || 0) > 0)
                    .sort((a, b) => (b.playtime_hours || 0) - (a.playtime_hours || 0))
                    .slice(0, 6);
                if (recent.length === 0) {
                    actEl.innerHTML = '<div class="dash-empty"><span style="opacity:0.4; font-size:0.85em;">No activity yet.</span></div>';
                } else {
                    actEl.innerHTML = recent.map(g => {
                        const safeName = escapeHtml(g.name || 'Game');
                        const hrs = g.playtime_hours != null ? `${g.playtime_hours}h played` : '';
                        return `<div class="dash-activity-item">
                            <div class="dash-activity-icon">🎮</div>
                            <div class="dash-activity-text">
                                <div class="dash-activity-msg">${safeName}</div>
                                <div class="dash-activity-time">${hrs}</div>
                            </div>
                        </div>`;
                    }).join('');
                }
            }

            await updatePresenceStrip();
        }

        async function pickGame() {
            const filterValue = document.querySelector('input[name="filter"]:checked').value;
            const genreValue = document.getElementById('genre-filter').value.trim();
            const platformFilter = document.getElementById('platform-filter').value;
            const deviceFilter = document.getElementById('device-filter').value;
            const minScore = document.getElementById('adv-min-score').value;
            const minYear = document.getElementById('adv-min-year').value;
            const maxYear = document.getElementById('adv-max-year').value;
            const maxPrice = document.getElementById('adv-max-price').value;
            const excludeIds = document.getElementById('adv-exclude-ids').value.trim();
            const tagFilter = document.getElementById('tag-filter').value;
            const multiplayerOnly = document.getElementById('adv-multiplayer').checked;
            const singleplayerOnly = document.getElementById('adv-singleplayer').checked;

            showSpinner('Picking a game…');
            try {
                const body = {
                    filter: filterValue,
                    genre: genreValue,
                };
                if (minScore) body.min_metacritic = parseInt(minScore);
                if (minYear) body.min_year = parseInt(minYear);
                if (maxYear) body.max_year = parseInt(maxYear);
                if (maxPrice) body.max_price = parseFloat(maxPrice);
                if (excludeIds) body.exclude_game_ids = excludeIds;
                if (tagFilter) body.tag = tagFilter;
                if (multiplayerOnly) body.multiplayer_only = true;
                if (singleplayerOnly) body.singleplayer_only = true;
                if (platformFilter) body.platform_filter = platformFilter;
                if (deviceFilter) body.device_filter = deviceFilter;

                const response = await fetch('/api/pick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                });

                if (!response.ok) {
                    const error = await response.json();
                    alert(error.error || 'Failed to pick game');
                    return;
                }

                const game = await response.json();
                currentGame = game;
                displayGame(game);
                updatePresence(game.name, game.playtime_hours);

            } catch (error) {
                alert('Error: ' + error.message);
            } finally {
                hideSpinner();
            }
        }

        async function refreshTagFilter() {
            try {
                const resp = await fetch('/api/tags');
                if (!resp.ok) return;
                const data = await resp.json();
                const sel = document.getElementById('tag-filter');
                const current = sel.value;
                // Rebuild options
                sel.innerHTML = '<option value="">Any tag</option>';
                (data.tags || []).forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t;
                    opt.textContent = t;
                    if (t === current) opt.selected = true;
                    sel.appendChild(opt);
                });
            } catch (e) { console.warn('Tag filter refresh failed:', e.message); }
        }

        function rebuildFilterSelect(selectEl, items, anyLabel, selectedValue) {
            if (!selectEl) return;
            const current = selectedValue !== undefined ? selectedValue : (selectEl.value || '');
            selectEl.innerHTML = `<option value="">${anyLabel}</option>`;
            (items || []).forEach(item => {
                const option = document.createElement('option');
                option.value = item.value;
                option.textContent = item.label;
                if (item.value === current) option.selected = true;
                selectEl.appendChild(option);
            });
        }

        async function refreshPlatformFilters() {
            try {
                const response = await fetch('/api/filters/platform-options');
                if (!response.ok) return;
                const data = await response.json();

                rebuildFilterSelect(
                    document.getElementById('platform-filter'),
                    data.platforms || [],
                    'Any platform'
                );
                rebuildFilterSelect(
                    document.getElementById('device-filter'),
                    data.devices || [],
                    'Any device'
                );
            } catch (error) {
                console.warn('Platform filter refresh failed:', error.message);
            }
        }

        async function refreshMultiUserPlatformFilters() {
            const selectedUsers = getSelectedUsers();
            const usersParam = encodeURIComponent(selectedUsers.join(','));
            const url = `/api/filters/platform-options${selectedUsers.length ? `?users=${usersParam}` : ''}`;

            try {
                const response = await fetch(url);
                if (!response.ok) return;
                const data = await response.json();

                rebuildFilterSelect(
                    document.getElementById('multi-platform-filter'),
                    data.platforms || [],
                    'Any platform'
                );
                rebuildFilterSelect(
                    document.getElementById('multi-device-filter'),
                    data.devices || [],
                    'Any device'
                );
            } catch (error) {
                console.warn('Multi-user platform filter refresh failed:', error.message);
            }
        }

        function escapeHtml(value) {
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        // Escape a value for safe embedding inside a JS single-quoted string
        // that itself lives in an HTML attribute (e.g. onclick="f('VALUE')")
        function escAttr(value) {
            return String(value || '')
                .replace(/\\/g, '\\\\')   // backslash first
                .replace(/'/g, "\\'")      // single-quote
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        function getGameThumbUrl(appId) {
            const cached = gameDetailsCache.get(appId);
            return (cached && (cached.header_image || cached.capsule_image))
                || `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`;
        }

        function handleMissingCover(img) {
            img.style.background = 'var(--card-border)';
            img.removeAttribute('src');
        }

        function renderGameListThumb(appId, gameName) {
            const src = getGameThumbUrl(appId);
            const safeName = escapeHtml(gameName || 'Game');
            return `<img class="list-thumb" src="${src}" alt="${safeName} thumbnail" loading="lazy">`;
        }
        
        async function displayGame(game) {
            const resultDiv = document.getElementById('game-result');
            const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
            resultDiv.dataset.gameName = game.name || '';
            const review = game.review;
            // Clamp rating defensively to [1,10] and escape notes for safe attribute/HTML insertion
            const safeRating = review ? Math.min(10, Math.max(1, parseInt(review.rating) || 1)) : null;
            const safeNotes = review && review.notes
                ? review.notes.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')
                : '';
            const reviewHtml = review
                ? `<div id="review-panel" style="margin-top:12px; padding:12px; background:var(--list-hover); border-radius:var(--radius-sm,8px);">
                       <strong>⭐ Your Review:</strong>
                       <span style="font-size:1.1em; margin-left:6px;">${'★'.repeat(safeRating)}${'☆'.repeat(10-safeRating)}</span>
                       <span style="color:var(--text-secondary); margin-left:6px;">(${safeRating}/10)</span>
                       ${safeNotes ? `<p style="margin-top:4px; color:var(--text-secondary);">${safeNotes}</p>` : ''}
                       <button onclick="editReview('${game.game_id}')" style="margin-top:6px; padding:4px 10px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-family:inherit;">✏️ Edit</button>
                       <button onclick="deleteReview('${game.game_id}')" style="margin-top:6px; margin-left:4px; padding:4px 10px; background:#ef4444; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-family:inherit;">🗑️ Delete</button>
                   </div>`
                : `<button onclick="editReview('${game.game_id}')" style="margin-top:8px; padding:6px 14px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.9em;">
                       ✏️ Write a Review
                   </button>`;

            // Tag pills
            const existingTags = game.tags || [];
            const tagPillsHtml = existingTags.length
                ? existingTags.map(t =>
                    `<span class="tag-pill">${t} <span class="remove-tag" onclick="removeTag('${game.game_id}','${t}')">✕</span></span>`
                  ).join('')
                : '<span style="color:var(--text-secondary); font-size:0.85em;">No tags yet</span>';

            // Backlog status selector
            const backlogStatuses = ['want_to_play','playing','completed','dropped'];
            const currentStatus = game.backlog_status || '';
            const backlogOptions = `<option value="">— none —</option>` +
                backlogStatuses.map(s => `<option value="${s}" ${currentStatus===s?'selected':''}>${s.replace(/_/g,' ')}</option>`).join('');
            const safeGameName = escapeHtml(game.name || 'Unknown Game');
            const heroFallback = `https://cdn.akamai.steamstatic.com/steam/apps/${game.app_id}/header.jpg`;

            let html = `
                <div class="game-hero" id="game-hero-card">
                    <img id="game-hero-image" src="${heroFallback}" alt="${safeGameName} hero" loading="lazy">
                    <div class="game-hero-overlay">
                        <div class="game-hero-title">${favoriteIcon}${safeGameName}</div>
                        <div class="game-hero-subtitle">App ID: ${game.app_id}</div>
                    </div>
                </div>
                <div class="game-info">
                    <strong>Playtime:</strong> ${game.playtime_hours} hours
                </div>
                <div id="game-details">Loading details...</div>
                <div id="achievements-section" style="margin-top:6px; color:var(--text-secondary); font-size:0.9em;">
                    <span id="achievement-info">🏆 Loading achievements…</span>
                </div>
                ${reviewHtml}
                <!-- Tags section -->
                <div id="tags-section" style="margin-top:12px;">
                    <strong>🏷️ Tags:</strong>
                    <span id="tag-pills">${tagPillsHtml}</span>
                    <span style="margin-left:8px;">
                        <input type="text" id="new-tag-input" placeholder="Add tag…"
                               style="padding:3px 8px; border:1px solid var(--input-border); border-radius:var(--radius,12px); font-size:0.85em; background:var(--input-bg); color:var(--text-primary); width:110px;"
                               onkeydown="if(event.key==='Enter') addTag('${game.game_id}')">
                        <button onclick="addTag('${game.game_id}')" style="padding:3px 10px; background:#10b981; color:white; border:none; border-radius:var(--radius,12px); font-size:0.8em; cursor:pointer; font-family:inherit; margin-left:3px;">+</button>
                    </span>
                </div>
                <!-- Backlog status -->
                <div style="margin-top:10px; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                    <strong>📚 Backlog:</strong>
                    <select id="backlog-select" onchange="setBacklogStatus('${game.game_id}', this.value)"
                            style="padding:5px 10px; border-radius:var(--radius-sm,8px); border:1px solid var(--input-border); background:var(--input-bg); color:var(--text-primary); font-size:0.9em;">
                        ${backlogOptions}
                    </select>
                </div>
                <div id="game-preview-backlog-notes" style="margin-top:12px; padding:12px; background:var(--list-hover); border-radius:var(--radius-sm,8px);"></div>
                <!-- Inline review editor (hidden by default) -->
                <div id="review-editor" style="display:none; margin-top:12px; padding:14px; background:rgba(245,158,11,0.06); border-radius:var(--radius-sm,8px); border:1px solid rgba(245,158,11,0.3);">
                    <strong>Write a Review</strong>
                    <div style="margin-top:10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                        <label>Rating (1-10):
                            <input type="number" id="review-rating" min="1" max="10" value="${safeRating || 7}"
                                   style="width:55px; margin-left:5px; padding:5px 8px; border-radius:var(--radius-sm,8px); border:1.5px solid var(--input-border); background:var(--input-bg); color:var(--text-primary); font-family:inherit;">
                        </label>
                        <label style="flex:1; min-width:200px;">Notes:
                            <input type="text" id="review-notes" value="${safeNotes}"
                                   placeholder="Optional personal notes…"
                                   style="width:100%; margin-left:5px; padding:5px 8px; border-radius:var(--radius-sm,8px); border:1.5px solid var(--input-border); background:var(--input-bg); color:var(--text-primary); font-family:inherit;">
                        </label>
                    </div>
                    <div style="margin-top:10px; display:flex; gap:8px;">
                        <button onclick="saveReview('${game.game_id}')" style="padding:6px 16px; background:#10b981; color:white; border:none; border-radius:50px; cursor:pointer; font-family:inherit;">💾 Save</button>
                        <button onclick="document.getElementById('review-editor').style.display='none'" style="padding:6px 14px; background:var(--list-hover); color:var(--text-primary); border:1px solid var(--card-border); border-radius:var(--radius-xs,6px); cursor:pointer;">Cancel</button>
                    </div>
                </div>
                <div class="action-buttons" style="margin-top:12px;">
                    <button class="btn btn-favorite" onclick="toggleFavorite(${game.app_id})">
                        ${game.is_favorite ? '⭐ Remove from Favorites' : '⭐ Add to Favorites'}
                    </button>
                    <button class="btn btn-link" onclick="window.open('${game.steam_url}', '_blank')">
                        🔗 Open in Steam
                    </button>
                    <button class="btn btn-link" onclick="window.open('${game.steamdb_url}', '_blank')">
                        📊 Open in SteamDB
                    </button>
                    <button class="btn" onclick="shareGame()" style="background:linear-gradient(135deg,#11998e,#38ef7d); color:white; border:none;">
                        📤 Share
                    </button>
                </div>
            `;

            resultDiv.innerHTML = html;
            resultDiv.style.display = 'block';
            loadPreviewBacklogNotes('game-preview-backlog-notes', game.game_id || `steam:${game.app_id}`, {
                collectionId: getPreviewNotesCollectionId(),
                emptyMessage: 'Choose a backlog status to start saving notes for this game.',
            });

            // Load details and achievements in parallel
            loadGameDetails(game.app_id);
            loadAchievements(game.app_id);
        }

        async function loadAchievements(appId) {
            const el = document.getElementById('achievement-info');
            if (!el) return;
            
            if (!appId) {
                el.textContent = '';
                return;
            }
            try {
                const resp = await fetch(`/api/achievements/${appId}`);
                if (resp.ok) {
                    const d = await resp.json();
                    el.textContent = `🏆 Achievements: ${d.achieved}/${d.total} (${d.percent}%)`;
                } else {
                    el.textContent = '';
                }
            } catch (e) { /* silent */ }
        }

        async function displayMultiUserGame(game, selectedUsers) {
            const resultDiv = document.getElementById('multiuser-result');
            const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
            
            // Multi-user specific info
            const playersInfo = escapeHtml(game.owners ? game.owners.join(', ') : selectedUsers.join(', '));
            const multiplayerBadges = `
                ${game.is_coop ? '<span style="display:inline-block; background:#10b981; color:white; padding:4px 12px; border-radius:15px; font-size:0.85em; margin-right:5px;">✅ Co-op</span>' : ''}
                ${game.is_multiplayer ? '<span style="display:inline-block; background:#3b82f6; color:white; padding:4px 12px; border-radius:15px; font-size:0.85em;">✅ Multiplayer</span>' : ''}
            `;
            
            const safeGameName = escapeHtml(game.name || 'Unknown Game');
            const heroFallback = `https://cdn.akamai.steamstatic.com/steam/apps/${game.app_id}/header.jpg`;

            let html = `
                <div class="game-hero" id="game-hero-card">
                    <img id="game-hero-image" src="${heroFallback}" alt="${safeGameName} hero" loading="lazy">
                    <div class="game-hero-overlay">
                        <div class="game-hero-title">${favoriteIcon}${safeGameName}</div>
                        <div class="game-hero-subtitle">Multi-User Pick • App ID: ${game.app_id}</div>
                    </div>
                </div>
                <div style="background: rgba(79,70,229,0.06); padding: 12px; border-radius: var(--radius-sm, 8px); margin: 12px 0;">
                    <strong>👥 Players:</strong> ${playersInfo}
                    <div style="margin-top: 8px;">${multiplayerBadges}</div>
                </div>
                <div id="game-details">Loading details...</div>
                <div id="multiuser-backlog-notes" style="margin-top:12px; padding:12px; background:var(--list-hover); border-radius:var(--radius-sm,8px);"></div>
                <div class="action-buttons" style="margin-top:12px;">
                    <button class="btn btn-link" onclick="window.open('${game.steam_url}', '_blank')">
                        🔗 Open in Steam
                    </button>
                    <button class="btn btn-link" onclick="window.open('${game.steamdb_url}', '_blank')">
                        📊 Open in SteamDB
                    </button>
                    <button class="btn" onclick="shareMultiUserGame()" style="background:linear-gradient(135deg,#11998e,#38ef7d); color:white; border:none;">
                        📤 Share
                    </button>
                </div>
            `;

            resultDiv.innerHTML = html;
            resultDiv.style.display = 'block';
            loadPreviewBacklogNotes('multiuser-backlog-notes', game.game_id || `steam:${game.app_id}`, {
                emptyMessage: 'Add this game to your backlog to save notes here.',
            });

            // Load game details
            loadGameDetails(game.app_id);
        }

        function shareMultiUserGame() {
            const resultDiv = document.getElementById('multiuser-result');
            const gameName = resultDiv.querySelector('.game-hero-title')?.textContent?.replace('⭐', '').trim() || 'Game';
            const steamUrl = resultDiv.querySelector('[onclick*="steam_url"]')?.getAttribute('onclick')?.match(/https:\/\/[^']+/)?.[0] || '';
            const text = `🎮 Multi-User Pick: **${gameName}**\n${steamUrl}`;
            const modal = document.getElementById('share-modal');
            document.getElementById('share-text').value = text;
            modal.style.display = 'flex';
        }

        async function updateBacklogEntryStatus(gameId, status, collectionId = activeBacklogId, notes = undefined) {
            try {
                const safeCollectionId = String(collectionId || '').trim();
                if (!status) {
                    const query = safeCollectionId ? `?collection_id=${encodeURIComponent(safeCollectionId)}` : '';
                    await safeFetch(`/api/backlog/${gameId}${query}`, {method:'DELETE'});
                    scheduleGameFilterCacheReady = false;
                    return true;
                } else {
                    const payload = {status, collection_id: safeCollectionId || null};
                    if (notes !== undefined) payload.notes = String(notes || '');
                    await safeFetch(`/api/backlog/${gameId}`, {
                        method: 'POST',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify(payload)
                    });
                    scheduleGameFilterCacheReady = false;
                    return true;
                }
            } catch (e) {
                alert('Failed to update backlog: ' + e.message);
                return false;
            }
        }

        async function setBacklogStatus(gameId, status) {
            const updated = await updateBacklogEntryStatus(gameId, status, activeBacklogId);
            if (!updated) return;
            if (currentGame) {
                currentGame.backlog_status = status || null;
                if (!status) currentGame.backlog_notes = '';
            }
            loadPreviewBacklogNotes('game-preview-backlog-notes', gameId, {
                collectionId: getPreviewNotesCollectionId(),
                emptyMessage: 'Choose a backlog status to start saving notes for this game.',
            });
        }

        function shareGame() {
            if (!currentGame) return;
            const r = currentGame.review;
            const ratingStr = r ? ` | ⭐ ${r.rating}/10` : '';
            const tagsStr = (currentGame.tags||[]).length ? ` | 🏷️ ${currentGame.tags.join(', ')}` : '';
            const text = `🎮 **${currentGame.name}** — ${currentGame.playtime_hours}h played${ratingStr}${tagsStr}\n${currentGame.steam_url||''}`;
            const modal = document.getElementById('share-modal');
            document.getElementById('share-text').value = text;
            modal.style.display = 'flex';
        }

        function closeShareModal() {
            document.getElementById('share-modal').style.display = 'none';
        }

        async function copyShareText() {
            const txt = document.getElementById('share-text').value;
            try {
                await navigator.clipboard.writeText(txt);
                document.getElementById('copy-btn').textContent = '✅ Copied!';
                setTimeout(() => { document.getElementById('copy-btn').textContent = '📋 Copy'; }, 2000);
            } catch (e) {
                document.getElementById('share-text').select();
                document.execCommand('copy');
            }
        }

        async function addTag(gameId) {
            const input = document.getElementById('new-tag-input');
            const tag = input.value.trim().toLowerCase();
            if (!tag) return;
            try {
                const resp = await fetch(`/api/tags/${gameId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tag})
                });
                if (resp.ok) {
                    const data = await resp.json();
                    if (currentGame) {
                        currentGame.tags = data.tags;
                        displayGame(currentGame);
                    }
                    input.value = '';
                }
            } catch (e) {
                alert('Error adding tag: ' + e.message);
            }
        }

        async function removeTag(gameId, tag) {
            try {
                const resp = await fetch(`/api/tags/${gameId}/${encodeURIComponent(tag)}`, {method: 'DELETE'});
                if (resp.ok) {
                    const data = await resp.json();
                    if (currentGame) {
                        currentGame.tags = data.tags;
                        displayGame(currentGame);
                    }
                }
            } catch (e) {
                alert('Error removing tag: ' + e.message);
            }
        }

        function editReview(gameId) {
            document.getElementById('review-editor').style.display = 'block';
            document.getElementById('review-editor').scrollIntoView({behavior: 'smooth'});
        }

        async function saveReview(gameId) {
            const rating = parseInt(document.getElementById('review-rating').value);
            const notes = document.getElementById('review-notes').value.trim();
            try {
                const resp = await fetch(`/api/reviews/${gameId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({rating, notes})
                });
                if (resp.ok) {
                    // Refresh the game display with the updated review
                    const updated = await resp.json();
                    if (currentGame) {
                        currentGame.review = {rating, notes, updated_at: new Date().toISOString()};
                        displayGame(currentGame);
                    }
                } else {
                    const err = await resp.json();
                    alert(err.error || 'Failed to save review');
                }
            } catch (e) {
                alert('Error saving review: ' + e.message);
            }
        }

        async function deleteReview(gameId) {
            if (!confirm('Delete this review?')) return;
            try {
                const resp = await safeFetch(`/api/reviews/${gameId}`, {method: 'DELETE'});
                if (resp.ok && currentGame) {
                    currentGame.review = null;
                    displayGame(currentGame);
                }
            } catch (e) {
                alert('Error deleting review: ' + e.message);
            }
        }

        function toggleAdvancedFilters() {
            const panel = document.getElementById('advanced-filters');
            const icon = document.getElementById('adv-toggle-icon');
            const isVisible = panel.style.display === 'flex';
            panel.style.display = isVisible ? 'none' : 'flex';
            icon.textContent = isVisible ? '▾' : '▴';
        }
        
        async function loadGameDetails(appId) {
            try {
                const response = await fetch(`/api/game/${appId}/details`);
                if (response.ok) {
                    const details = await response.json();
                    let detailsHtml = '<div class="game-description">';

                    const previewUrl = details.header_image || details.capsule_image || `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`;
                    const heroImg = document.getElementById('game-hero-image');
                    if (heroImg && previewUrl) {
                        heroImg.src = previewUrl;
                    }

                    const descriptionText = (details.description || '').trim();
                    const safeDescription = escapeHtml(descriptionText);
                    
                    detailsHtml += `<div class="game-description-card"><strong>About this game</strong><p style="margin-top:8px;">${safeDescription || 'No description available for this game yet.'}</p></div>`;
                    
                    if (details.genres && details.genres.length) {
                        detailsHtml += `<p><strong>Genres:</strong> ${details.genres.join(', ')}</p>`;
                    }
                    
                    if (details.release_date) {
                        detailsHtml += `<p><strong>Release Date:</strong> ${details.release_date}</p>`;
                    }
                    
                    if (details.metacritic_score) {
                        detailsHtml += `<p><strong>Metacritic Score:</strong> ${details.metacritic_score}</p>`;
                    }

                    if (details.protondb) {
                        const tier = details.protondb.tier || 'unknown';
                        const tierColors = {
                            platinum: '#ace0fb', gold: '#ffd700', silver: '#c0c0c0',
                            bronze: '#cd7f32', borked: '#ef4444', pending: '#95a5a6'
                        };
                        const bg = tierColors[tier] || '#aaa';
                        const total = details.protondb.total || 0;
                        detailsHtml += `<p><strong>ProtonDB:</strong> <span style="display:inline-block;padding:2px 10px;border-radius:10px;background:${bg};color:#1a1a2e;font-weight:700;font-size:0.9em;">${tier.charAt(0).toUpperCase()+tier.slice(1)}</span> <span style="color:var(--text-secondary);font-size:0.85em;">(${total} report${total!==1?'s':''})</span></p>`;
                    }
                    
                    detailsHtml += '</div>';
                    document.getElementById('game-details').innerHTML = detailsHtml;
                } else {
                    document.getElementById('game-details').innerHTML = 
                        '<p class="game-info">(Detailed information unavailable)</p>';
                }
            } catch (error) {
                document.getElementById('game-details').innerHTML = 
                    '<p class="game-info">(Error loading details)</p>';
            }
        }
        
        function parseFavoriteAppId(appId) {
            const parsed = Number.parseInt(String(appId || '').trim(), 10);
            return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
        }

        function getKnownFavoriteState(appId) {
            if (!appId) return false;
            const finder = (games) => (games || []).find(game => Number(game?.app_id || game?.appid || 0) === appId);
            const fromLibrary = finder(_libraryData?.games);
            if (fromLibrary) return Boolean(fromLibrary.is_favorite);
            const fromBacklog = finder(_backlogData);
            if (fromBacklog) return Boolean(fromBacklog.is_favorite || fromBacklog.backlog_status === 'favorite');
            const fromFavorites = finder(_favoritesData);
            if (fromFavorites) return true;
            const fromRecs = finder(_recommendationsData);
            if (fromRecs) return Boolean(fromRecs.is_favorite);
            if (currentGame && Number(currentGame.app_id || currentGame.appid || 0) === appId) {
                return Boolean(currentGame.is_favorite);
            }
            return false;
        }

        function updateFavoriteFlagInCaches(appId, isFavorite) {
            const apply = (games) => {
                (games || []).forEach(game => {
                    const gameAppId = Number(game?.app_id || game?.appid || 0);
                    if (gameAppId === appId) game.is_favorite = isFavorite;
                });
            };
            apply(_libraryData?.games);
            apply(_recommendationsData);
            apply(_backlogData);
            if (currentGame && Number(currentGame.app_id || currentGame.appid || 0) === appId) {
                currentGame.is_favorite = isFavorite;
            }
        }

        async function toggleFavorite(appId) {
            const safeAppId = parseFavoriteAppId(appId);
            if (!safeAppId) {
                showMessage('This game cannot be favorited because it has no Steam App ID.', 'warning');
                return;
            }
            const isFavorite = getKnownFavoriteState(safeAppId);
            const method = isFavorite ? 'DELETE' : 'POST';
            
            try {
                const response = await fetch(`/api/favorite/${safeAppId}`, {method});
                const data = await response.json();
                
                if (data.success) {
                    const nextFavoriteState = !isFavorite;
                    updateFavoriteFlagInCaches(safeAppId, nextFavoriteState);
                    if (currentGame && Number(currentGame.app_id || currentGame.appid || 0) === safeAppId) {
                        displayGame(currentGame);
                    }
                    await updateStatus();
                    await Promise.all([
                        loadFavorites(),
                        loadLibrary(),
                    ]);
                    if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
                        loadDashboard();
                    }
                }
            } catch (error) {
                alert('Error updating favorite: ' + error.message);
            }
        }
        
        async function loadLibrary() {
            const listDiv = document.getElementById('library-list');
            listDiv.innerHTML = renderSkeletonList(8);
            
            try {
                const response = await fetch('/api/library');
                const data = await response.json();
                
                if (data.games && data.games.length > 0) {
                    let html = '';
                    data.games.forEach(game => {
                        const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
                        const safeName = escAttr(game.name);
                        html += `
                            <div class="list-item" style="cursor:pointer;" onclick="showGameDetails(${game.app_id}, '${safeName}', ${game.playtime_hours || 0}, '${(game.tags || []).join(', ')}')">
                                <div class="list-item-media">
                                    ${renderGameListThumb(game.app_id, game.name)}
                                    <div>${favoriteIcon}<strong class="list-item-title">${game.name}</strong></div>
                                </div>
                                <div style="display:flex; gap:8px; align-items:center;">
                                    <span>${game.playtime_hours}h</span>
                                    <span title="Favorite" style="cursor:pointer; font-size:1.2em;" onclick="event.stopPropagation(); toggleFavorite(${game.app_id})">
                                        ${game.is_favorite ? '⭐' : '☆'}
                                    </span>
                                    <span title="Add to List" style="cursor:pointer; font-size:1.1em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" onclick="event.stopPropagation(); quickAddToBacklog('${game.game_id}', '${safeName}')">📚</span>
                                    <span title="Add to No-Play List" style="cursor:pointer; font-size:1.1em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" onclick="event.stopPropagation(); quickIgnoreGame(${game.app_id}, '${safeName}')">🚫</span>
                                </div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                    
                    // Pre-load details for all games in background
                    const appIds = data.games.map(g => g.app_id);
                    preloadGameDetails(appIds).catch(err => console.log('Pre-load complete or errored'));
                } else {
                    listDiv.innerHTML = '<div class="loading">No games found</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading library</div>';
            }

            // Load cross-platform duplicates section
            loadDuplicates();
        }

        async function loadDuplicates() {
            try {
                const resp = await fetch('/api/duplicates');
                if (!resp.ok) return;
                const data = await resp.json();
                const section = document.getElementById('duplicates-section');
                const listDiv = document.getElementById('duplicates-list');
                if (!data.duplicates || data.duplicates.length === 0) {
                    section.style.display = 'none';
                    return;
                }
                section.style.display = 'block';
                let html = '';
                data.duplicates.forEach(group => {
                    const platformBadges = group.platforms.map(p =>
                        `<span style="padding:2px 8px; border-radius:10px; font-size:0.8em; background:var(--list-hover); margin-right:4px;">${p}</span>`
                    ).join('');
                    const gameRows = group.games.map(g =>
                        `<div style="padding:6px 0; font-size:0.9em; color:var(--text-secondary);">&nbsp;&nbsp;• ${g.platform}: ${g.playtime_hours}h played</div>`
                    ).join('');
                    html += `
                        <div style="padding:12px; background:var(--list-hover); border-radius:var(--radius,12px); margin-bottom:10px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                                <strong>${group.name}</strong>
                                <span>${platformBadges}</span>
                            </div>
                            ${gameRows}
                        </div>`;
                });
                listDiv.innerHTML = html;
            } catch (_) {}
        }
        
        // Helper function for debouncing user input
        function createDebounce(func, delay) {
            let timeoutId = null;
            return function(...args) {
                if (timeoutId) clearTimeout(timeoutId);
                timeoutId = setTimeout(() => func(...args), delay);
            };
        }

        let _favoritesData = [];
        let _backlogData = [];
        let backlogCollectionsCache = [];
        let activeBacklogId = '';
        let activeBacklogEntryGameId = '';
        let activeGameDetailsModalGameId = '';
        let backlogShareCandidatesCache = [];
        let _recommendationsData = [];
        const FAVORITES_BACKLOG_ID = '__favorites__';

        function normalisePlatformKey(value) {
            const key = String(value || '').trim().toLowerCase();
            if (!key) return '';
            if (key === 'psn') return 'playstation';
            if (key.includes('playstation')) return 'playstation';
            if (key.includes('switch') || key.includes('nintendo')) return 'nintendo';
            if (key.includes('xbox')) return 'xbox';
            if (key.includes('good old games') || key.includes('gog')) return 'gog';
            if (key.includes('epic')) return 'epic';
            if (key.includes('steam')) return 'steam';
            return key;
        }

        function getGamePlatformKeys(game) {
            const keys = new Set();
            [
                game.platform,
                game.platform_name,
                game.source,
                game.store,
                game.storefront,
                game.client,
                ...(Array.isArray(game.platforms) ? game.platforms : [game.platforms])
            ].forEach(value => {
                const key = normalisePlatformKey(value);
                if (key) keys.add(key);
            });
            getGamePlatforms(game).forEach(platform => {
                const key = normalisePlatformKey(platform.key);
                if (key) keys.add(key);
            });
            if (!keys.size && (game.app_id || game.appid)) keys.add('steam');
            return Array.from(keys);
        }

        function getFilterValue(id) {
            const element = document.getElementById(id);
            return element ? element.value : '';
        }

        function filterGamesByControls(games, searchInputId, platformSelectId) {
            const searchText = getFilterValue(searchInputId).trim().toLowerCase();
            const platformFilter = normalisePlatformKey(getFilterValue(platformSelectId));
            return (games || []).filter(game => {
                const matchesPlatform = !platformFilter || getGamePlatformKeys(game).includes(platformFilter);
                if (!matchesPlatform) return false;
                if (!searchText) return true;
                const searchValues = [
                    game.name,
                    game.game_id,
                    game.platform,
                    game.platform_name,
                    game.recommendation_reason,
                    game.backlog_status,
                    Array.isArray(game.tags) ? game.tags.join(' ') : game.tags
                ].filter(Boolean).join(' ').toLowerCase();
                return searchValues.includes(searchText);
            });
        }
        
        // Debounced search to prevent excessive API calls
        const debouncedSearch = createDebounce(async () => {
            if (_libraryData) {
                renderLibraryData(_libraryData);
                return;
            }
            if (window.loadLibrary) {
                window.loadLibrary();
            }
        }, 300);

        function applyLibraryFilters() {
            if (_libraryData) {
                renderLibraryData(_libraryData);
                return;
            }
            if (window.loadLibrary) {
                window.loadLibrary();
            }
        }
        
        function searchLibraryDebounced() {
            const searchText = document.getElementById('library-search').value;
            debouncedSearch(searchText);
        }

        function showGameDetails(appId, gameName, playtimeHours, tags, explicitGameId = '') {
            const modal = document.getElementById('game-details-modal');
            activeGameDetailsModalGameId = String(explicitGameId || findKnownGameIdByAppId(appId) || '').trim();
            document.getElementById('game-details-name').textContent = gameName;
            document.getElementById('game-details-playtime').textContent = `${playtimeHours} hours`;
            
            // Set up links
            document.getElementById('game-details-steam').href = `https://store.steampowered.com/app/${appId}/`;
            document.getElementById('game-details-keyshop').href = `https://www.allkeyshop.com/blog/catalogue/search/${encodeURIComponent(gameName)}/?results=50`;
            document.getElementById('game-details-steamdb').href = `https://steamdb.info/app/${appId}/`;
            
            // Tags
            const tagsDiv = document.getElementById('game-details-tags');
            if (tags && tags.trim()) {
                tagsDiv.innerHTML = tags.split(',').map(t => 
                    `<span style="padding:4px 10px; background:var(--list-hover); border-radius:var(--radius-xs,6px); font-size:0.85em;">${t.trim()}</span>`
                ).join('');
            } else {
                tagsDiv.innerHTML = '<span style="color:var(--text-secondary);">No tags</span>';
            }
            
            // Hide additional details sections initially
            document.getElementById('game-details-metacritic-section').style.display = 'none';
            document.getElementById('game-details-protondb-section').style.display = 'none';
            document.getElementById('game-details-hltb-section').style.display = 'none';
            
            // Show loading state
            document.getElementById('game-details-description').innerHTML = `<em>Loading details...</em>`;
            loadPreviewBacklogNotes('game-details-backlog-notes', activeGameDetailsModalGameId, {
                emptyMessage: 'Add this game to your backlog to save notes in the details modal.',
                saveLabel: '💾 Save modal notes',
            });
            
            modal.style.display = 'flex';
            
            // Load details asynchronously and update modal when ready
            loadGameDetailsAsync(appId).then(details => {
                if (details && modal.style.display === 'flex') {
                    let detailsHtml = '';
                    
                    // Add game preview image
                    const previewUrl = details.header_image || details.capsule_image || `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`;
                    const safeName = escapeHtml(gameName);
                    if (previewUrl) {
                        detailsHtml += `
                            <div class="game-hero" style="margin-bottom:15px;">
                                <img src="${previewUrl}" alt="${safeName} hero" loading="lazy">
                                <div class="game-hero-overlay">
                                    <div class="game-hero-title">${safeName}</div>
                                    <div class="game-hero-subtitle">App ID: ${appId}</div>
                                </div>
                            </div>`;
                    }
                    
                    // Add description
                    if (details.description) {
                        detailsHtml += `<div class="game-description-card"><strong>About this game</strong><p style="margin-top:8px;">${escapeHtml(details.description)}</p></div>`;
                    } else {
                        detailsHtml += `<div class="game-description-card"><strong>About this game</strong><p style="margin-top:8px;">No description available for this game yet.</p></div>`;
                    }
                    
                    // Add genres
                    if (details.genres && details.genres.length) {
                        detailsHtml += `<p style="margin:10px 0;"><strong>Genres:</strong> ${details.genres.join(', ')}</p>`;
                    }
                    
                    // Add release date
                    if (details.release_date) {
                        const year = details.release_date.split(', ').pop().trim();
                        document.getElementById('game-details-year').textContent = year || '—';
                        detailsHtml += `<p style="margin:10px 0;"><strong>Release Date:</strong> ${details.release_date}</p>`;
                    }
                    
                    // Add Metacritic score
                    if (details.metacritic_score) {
                        detailsHtml += `<p style="margin:10px 0;"><strong>Metacritic Score:</strong> ${details.metacritic_score}</p>`;
                        document.getElementById('game-details-metacritic-section').style.display = 'block';
                        document.getElementById('game-details-metacritic').textContent = `${details.metacritic_score}/100`;
                    }
                    
                    // Add ProtonDB rating
                    if (details.protondb) {
                        const tier = details.protondb.tier || 'unknown';
                        const tierColors = {
                            platinum: '#ace0fb', gold: '#ffd700', silver: '#c0c0c0',
                            bronze: '#cd7f32', borked: '#ef4444', pending: '#95a5a6'
                        };
                        const bg = tierColors[tier] || '#aaa';
                        const total = details.protondb.total || 0;
                        detailsHtml += `<p style="margin:10px 0;"><strong>ProtonDB:</strong> <span style="display:inline-block;padding:2px 10px;border-radius:10px;background:${bg};color:#1a1a2e;font-weight:700;font-size:0.9em;">${tier.charAt(0).toUpperCase()+tier.slice(1)}</span> <span style="color:var(--text-secondary);font-size:0.85em;">(${total} report${total!==1?'s':''})</span></p>`;
                        document.getElementById('game-details-protondb-section').style.display = 'block';
                    }
                    
                    document.getElementById('game-details-description').innerHTML = detailsHtml;
                }
            });

            // Fetch HLTB data asynchronously (best-effort, non-blocking)
            fetch(`/api/hltb/${encodeURIComponent(gameName)}`)
                .then(r => r.ok ? r.json() : null)
                .then(hltb => {
                    if (!hltb || modal.style.display !== 'flex') return;
                    const pills = [];
                    if (hltb.main != null)          pills.push(`<span style="padding:4px 10px; background:var(--list-hover); border-radius:var(--radius-xs,6px); font-size:0.85em;">🎯 Main: ${hltb.main}h</span>`);
                    if (hltb.main_extra != null)     pills.push(`<span style="padding:4px 10px; background:var(--list-hover); border-radius:var(--radius-xs,6px); font-size:0.85em;">➕ Main+Extra: ${hltb.main_extra}h</span>`);
                    if (hltb.completionist != null)  pills.push(`<span style="padding:4px 10px; background:var(--list-hover); border-radius:var(--radius-xs,6px); font-size:0.85em;">🏆 Completionist: ${hltb.completionist}h</span>`);
                    if (pills.length) {
                        document.getElementById('game-details-hltb-section').style.display = 'block';
                        document.getElementById('game-details-hltb').innerHTML = pills.join('');
                    }
                })
                .catch(() => {});  // silently ignore network errors
        }

        function closeGameDetailsModal() {
            document.getElementById('game-details-modal').style.display = 'none';
            activeGameDetailsModalGameId = '';
        }

        async function toggleFavoriteLibraryLibrary(appId) {
            try {
                const response = await fetch('/api/favorites/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({app_id: appId})
                });
                if (response.ok) {
                    loadLibrary();
                }
            } catch (error) {
                console.error('Error toggling favorite:', error);
            }
        }
        
        function selectGame(appId) {
            // Switch to picker tab and show game details
            // For simplicity, we'll just open Steam page
            window.open(`https://store.steampowered.com/app/${appId}/`, '_blank');
        }
        
        async function loadFavorites() {
            const listDiv = document.getElementById('favorites-list');
            if (listDiv) listDiv.innerHTML = renderSkeletonList(4);
            
            try {
                const response = await fetch('/api/favorites');
                const data = await response.json();
                _favoritesData = data.favorites || [];
                if (listDiv) applyFavoritesFilters();
                if (document.getElementById('backlog-tab')?.classList.contains('active') && isFavoritesBacklog(activeBacklogId)) {
                    _backlogData = _favoritesData.map(game => ({
                        ...game,
                        game_id: String(game.game_id || game.app_id || '').trim(),
                        backlog_status: 'favorite',
                    }));
                    renderBacklogList();
                }
                const appIds = _favoritesData.map(game => game.app_id).filter(Boolean);
                preloadGameDetails(appIds).catch(err => console.log('Pre-load complete or errored'));
            } catch (error) {
                if (listDiv) listDiv.innerHTML = '<div class="error">Error loading favorites</div>';
            }
        }

        function applyFavoritesFilters() {
            const listDiv = document.getElementById('favorites-list');
            if (!listDiv) return;
            const favorites = filterGamesByControls(_favoritesData, 'favorites-search', 'favorites-platform-filter');
            if (!favorites.length) {
                listDiv.innerHTML = _favoritesData.length
                    ? '<div class="loading">No favorites match your current filters.</div>'
                    : '<div class="loading">No favorite games yet!</div>';
                return;
            }

            let html = '';
            favorites.forEach(game => {
                const safeName = escAttr(game.name || '');
                const platformBadges = renderInlinePlatformBadges(game);
                html += `
                    <div class="list-item" style="cursor:pointer;" onclick="showGameDetails(${game.app_id}, '${safeName}', ${game.playtime_hours || 0}, '${(game.tags || []).join(', ')}')">
                        <div class="list-item-media">
                            ${renderGameListThumb(game.app_id, game.name)}
                            <div>
                                <span class="favorite-icon">⭐</span><strong class="list-item-title">${game.name}</strong>
                                ${platformBadges ? `<div class="game-inline-meta" style="margin-top:6px;">${platformBadges}</div>` : ''}
                            </div>
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <span>${game.playtime_hours}h</span>
                            <span title="Add to List" style="cursor:pointer; font-size:1.1em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" onclick="event.stopPropagation(); quickAddToBacklog('${game.game_id || game.app_id}', '${safeName}')">📚</span>
                            <button class="btn btn-favorite" style="padding: 5px 10px; font-size:0.85em;"
                                    onclick="event.stopPropagation(); removeFavorite(${game.app_id})">Remove</button>
                        </div>
                    </div>
                `;
            });
            listDiv.innerHTML = html;
        }
        
        async function removeFavorite(appId) {
            try {
                const response = await safeFetch(`/api/favorite/${appId}`, {method: 'DELETE'});
                const data = await response.json();
                
                if (data.success) {
                    loadFavorites();
                    await updateStatus();
                }
            } catch (error) {
                alert('Error removing favorite: ' + error.message);
            }
        }

        let _compareScope = 'all';

        function setCompareScope(scope) {
            _compareScope = scope;
            // Update active button styles
            document.querySelectorAll('.compare-scope-btn').forEach(btn => {
                const active = btn.dataset.scope === scope;
                btn.style.background = active ? '#4f46e5' : 'transparent';
                btn.style.color = active ? 'white' : 'var(--text-secondary)';
                btn.style.border = active ? '1.5px solid #4f46e5' : '1.5px solid var(--card-border)';
            });
            loadStatsUsers();
        }

        async function loadStatsUsers() {
            const checkboxDiv = document.getElementById('comparison-user-checkboxes');

            try {
                const response = await fetch(`/api/stats/compare/candidates?scope=${_compareScope}`);
                const data = await response.json();
                const currentUser = data.current_user || '';

                if (data.users && data.users.length >= 1) {
                    let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px;">';
                    data.users.forEach(user => {
                        // In me_and_friends mode, pre-check the current user
                        const isMe = user.username === currentUser;
                        const preChecked = (_compareScope === 'me_and_friends' && isMe) ? 'checked' : '';
                        const meLabel = isMe ? ' <em style="color:var(--text-secondary);font-size:0.85em;">(you)</em>' : '';
                        html += `
                            <label style="display: flex; align-items: center; gap: 10px; padding: 10px; background: var(--card-bg); border-radius: var(--radius-sm, 8px); cursor: pointer; border: 2px solid var(--card-border);" title="Select to compare">
                                <input type="checkbox" class="compare-user-checkbox" value="${user.username}" ${preChecked} style="width: 18px; height: 18px;">
                                <span><strong>${escapeHtml(user.username)}</strong>${meLabel}</span>
                            </label>
                        `;
                    });
                    html += '</div>';
                    checkboxDiv.innerHTML = html;

                    const hasEnough = data.users.length > 1 || (_compareScope === 'me_and_friends' && data.users.length >= 1);
                    document.getElementById('compare-btn').style.display = hasEnough ? 'inline-block' : 'none';
                    document.getElementById('clear-compare-btn').style.display = hasEnough ? 'inline-block' : 'none';
                } else {
                    const msg = _compareScope === 'friends'
                        ? 'No friends found. Add friends to compare libraries.'
                        : _compareScope === 'me_and_friends'
                        ? 'No friends found. Add friends to compare, or switch to "All Users".'
                        : 'Need at least 2 users to compare';
                    checkboxDiv.innerHTML = `<p style="color: var(--text-secondary);">${msg}</p>`;
                    document.getElementById('compare-btn').style.display = 'none';
                    document.getElementById('clear-compare-btn').style.display = 'none';
                }
            } catch (error) {
                checkboxDiv.innerHTML = '<div class="error">Error loading users: ' + error.message + '</div>';
            }
        }

        // Debounce helper for search
        
        async function loadStats() {
            const statsDiv = document.getElementById('stats-content');
            if (!statsDiv) return;
            statsDiv.innerHTML = renderStatSkeleton();

            try {
                const response = await fetch('/api/stats');
                const data = await response.json();

                if (!response.ok) {
                    statsDiv.innerHTML = `<div class="error">Error: ${data.error || 'Failed to load statistics'}</div>`;
                    return;
                }

                let html = `
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-label">Total Games</div>
                            <div class="stat-value">${data.total_games}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Unplayed</div>
                            <div class="stat-value">${data.unplayed_games}</div>
                            <div class="stat-label">${data.unplayed_percentage}%</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Total Playtime</div>
                            <div class="stat-value">${data.total_playtime}</div>
                            <div class="stat-label">hours</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Average Playtime</div>
                            <div class="stat-value">${data.average_playtime}</div>
                            <div class="stat-label">hours/game</div>
                        </div>
                    </div>
                    <div class="top-games">
                        <h3>🏆 Top 10 Most Played Games</h3>
                        <div class="list-container">
                `;

                (data.top_games || []).forEach((game, index) => {
                    html += `
                        <div class="list-item">
                            <div><strong>#${index + 1} ${game.name}</strong></div>
                            <div>${game.playtime_hours} hours</div>
                        </div>
                    `;
                });

                html += '</div></div>';
                statsDiv.innerHTML = html;
            } catch (error) {
                statsDiv.innerHTML = '<div class="error">Error loading statistics</div>';
            }
        }

        async function loadStatsComparison() {
            const statsDiv = document.getElementById('stats-content');
            
            const selectedUsers = Array.from(document.querySelectorAll('.compare-user-checkbox:checked'))
                .map(cb => cb.value);
            
            if (selectedUsers.length < 2) {
                alert('Please select at least 2 users to compare');
                return;
            }
            
            statsDiv.innerHTML = renderSkeletonList(3);
            
            try {
                const response = await fetch(`/api/stats/compare?users=${selectedUsers.join(',')}`);
                const data = await response.json();
                
                if (!response.ok) {
                    statsDiv.innerHTML = `<div class="error">Error: ${data.error || 'Failed to load comparison'}</div>`;
                    return;
                }
                
                let html = `
                    <!-- User stats cards -->
                    <div style="margin-bottom: 30px;">
                        <h3 style="margin-bottom: 15px;">📊 User Statistics</h3>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px;">
                `;
                
                const colors = ['#4f46e5', '#7c3aed', '#f59e0b', '#ef4444', '#10b981'];
                
                data.users.forEach((user, idx) => {
                    if (user.error) {
                        html += `
                            <div class="stat-card" style="background: rgba(239,68,68,0.07); border: 1.5px solid rgba(239,68,68,0.3);">
                                <div class="stat-label">${user.username}</div>
                                <div class="error" style="margin-top: 10px;">Error: ${user.error}</div>
                            </div>
                        `;
                    } else {
                        const color = colors[idx % colors.length];
                        html += `
                            <div class="stat-card" style="border-left: 4px solid ${color};">
                                <div style="color: ${color}; font-weight: 700; margin-bottom: 12px; font-size: 1.05em;">${user.username}</div>
                                <div style="display: grid; gap: 10px; font-size: 0.95em;">
                                    <div><strong>Total Games:</strong> ${user.total_games}</div>
                                    <div><strong>Played:</strong> ${user.played_games}</div>
                                    <div><strong>Unplayed:</strong> ${user.unplayed_games} (${user.unplayed_percentage}%)</div>
                                    <div><strong>Total Playtime:</strong> ${user.total_playtime} hrs</div>
                                    <div><strong>Avg per Game:</strong> ${user.average_playtime} hrs</div>
                                </div>
                            </div>
                        `;
                    }
                });
                
                html += `</div></div>`;
                
                // Comparison metrics
                if (data.comparison_metrics) {
                    html += `
                        <div style="margin-bottom: 30px;">
                            <h3 style="margin-bottom: 15px;">📈 Comparison Metrics</h3>
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                                <div style="background: var(--card-bg); padding: 15px; border-radius: var(--radius-sm, 8px); border-left: 4px solid #4f46e5;">
                                    <div style="color: var(--text-secondary); font-size: 0.9em;">Most Games</div>
                                    <div style="font-size: 1.8em; font-weight: 700; color: #4f46e5;">${data.comparison_metrics.most_games}</div>
                                </div>
                                <div style="background: var(--card-bg); padding: 15px; border-radius: var(--radius-sm, 8px); border-left: 4px solid #7c3aed;">
                                    <div style="color: var(--text-secondary); font-size: 0.9em;">Least Games</div>
                                    <div style="font-size: 1.8em; font-weight: 700; color: #7c3aed;">${data.comparison_metrics.least_games}</div>
                                </div>
                                <div style="background: var(--card-bg); padding: 15px; border-radius: var(--radius-sm, 8px); border-left: 4px solid #f59e0b;">
                                    <div style="color: var(--text-secondary); font-size: 0.9em;">Average Games</div>
                                    <div style="font-size: 1.8em; font-weight: 700; color: #f59e0b;">${data.comparison_metrics.avg_games}</div>
                                </div>
                                <div style="background: var(--card-bg); padding: 15px; border-radius: var(--radius-sm, 8px); border-left: 4px solid #10b981;">
                                    <div style="color: var(--text-secondary); font-size: 0.9em;">Total Unique Games</div>
                                    <div style="font-size: 1.8em; font-weight: 700; color: #10b981;">${data.comparison_metrics.total_unique_games}</div>
                                </div>
                                <div style="background: var(--card-bg); padding: 15px; border-radius: var(--radius-sm, 8px); border-left: 4px solid #06b6d4;">
                                    <div style="color: var(--text-secondary); font-size: 0.9em;">Games in Common</div>
                                    <div style="font-size: 1.8em; font-weight: 700; color: #06b6d4;">${data.comparison_metrics.shared_game_count ?? 0}</div>
                                </div>
                            </div>
                        </div>
                    `;
                }
                
                // Comparison charts
                html += `
                    <div class="charts-row">
                        <div class="chart-card">
                            <h3>📊 Games Count Comparison</h3>
                            <canvas id="comparison-bar-chart" height="220"></canvas>
                        </div>
                        <div class="chart-card">
                            <h3>⏱️ Total Playtime Comparison</h3>
                            <canvas id="comparison-playtime-chart" height="220"></canvas>
                        </div>
                    </div>
                `;
                
                statsDiv.innerHTML = html;
                
                // Defer chart rendering to avoid blocking UI
                requestAnimationFrame(() => {
                    // Build comparison bar chart (games count)
                    if (document.getElementById('comparison-bar-chart')) {
                        const userNames = data.users.map(u => u.username);
                        const totalGames = data.users.map(u => u.total_games || 0);
                        const playedGames = data.users.map(u => u.played_games || 0);
                        
                        new Chart(document.getElementById('comparison-bar-chart'), {
                            type: 'bar',
                            data: {
                                labels: userNames,
                                datasets: [
                                    {
                                        label: 'Played',
                                        data: playedGames,
                                        backgroundColor: '#4f46e5',
                                    },
                                    {
                                        label: 'Unplayed',
                                        data: data.users.map(u => u.unplayed_games || 0),
                                        backgroundColor: '#e0e0e0',
                                    }
                                ]
                            },
                            options: {
                                indexAxis: 'y',
                                plugins: { legend: { position: 'bottom' } },
                                scales: { x: { stacked: true, beginAtZero: true } },
                                animation: { duration: 300 },
                            }
                        });
                    }
                    
                    // Build playtime comparison chart (deferred further)
                    requestAnimationFrame(() => {
                        if (document.getElementById('comparison-playtime-chart')) {
                            const playtimes = data.users.map(u => u.total_playtime || 0);
                            
                            new Chart(document.getElementById('comparison-playtime-chart'), {
                                type: 'bar',
                                data: {
                                    labels: data.users.map(u => u.username),
                                    datasets: [{
                                        label: 'Hours',
                                        data: playtimes,
                                        backgroundColor: colors.slice(0, data.users.length),
                                        borderRadius: 5,
                                    }]
                                },
                                options: {
                                    indexAxis: 'y',
                                    plugins: { legend: { display: false } },
                                    scales: { x: { beginAtZero: true } },
                                    animation: { duration: 300 },
                                }
                            });
                        }
                    });
                });
                
            } catch (error) {
                statsDiv.innerHTML = `<div class="error">Error loading comparison: ${error.message}</div>`;
            }
        }

        // Add event listeners for stats controls
        document.addEventListener('DOMContentLoaded', function() {
            // Load stats data and users on page load
            if (document.getElementById('stats-tab')) {
                loadStats();
                loadStatsUsers();
                
                // Compare button
                const compareBtn = document.getElementById('compare-btn');
                if (compareBtn) {
                    compareBtn.addEventListener('click', async function() {
                        const selectedUsers = Array.from(document.querySelectorAll('.compare-user-checkbox:checked'))
                            .map(cb => cb.value);
                        
                        if (selectedUsers.length < 2) {
                            alert('Please select at least 2 users to compare');
                            return;
                        }
                        
                        document.getElementById('view-single-btn').style.background = 'transparent';
                        document.getElementById('view-single-btn').style.color = 'var(--text-secondary)';
                        document.getElementById('view-single-btn').style.border = '2px solid var(--text-secondary)';
                        
                        document.getElementById('view-compare-btn').style.background = '#4f46e5';
                        document.getElementById('view-compare-btn').style.color = 'white';
                        document.getElementById('view-compare-btn').style.border = '2px solid #4f46e5';
                        
                        await loadStatsComparison();
                    });
                }
                
                // Clear comparison button
                const clearBtn = document.getElementById('clear-compare-btn');
                if (clearBtn) {
                    clearBtn.addEventListener('click', function() {
                        document.querySelectorAll('.compare-user-checkbox').forEach(cb => cb.checked = false);
                        
                        document.getElementById('view-single-btn').style.background = '#4f46e5';
                        document.getElementById('view-single-btn').style.color = 'white';
                        document.getElementById('view-single-btn').style.border = '2px solid #4f46e5';
                        
                        document.getElementById('view-compare-btn').style.background = 'transparent';
                        document.getElementById('view-compare-btn').style.color = 'var(--text-secondary)';
                        document.getElementById('view-compare-btn').style.border = '2px solid var(--text-secondary)';
                        
                        loadStats();
                    });
                }
                
                // View mode buttons
                const singleBtn = document.getElementById('view-single-btn');
                const compareBtn2 = document.getElementById('view-compare-btn');
                
                if (singleBtn) {
                    singleBtn.addEventListener('click', function() {
                        singleBtn.style.background = '#4f46e5';
                        singleBtn.style.color = 'white';
                        singleBtn.style.border = '2px solid #4f46e5';
                        
                        compareBtn2.style.background = 'transparent';
                        compareBtn2.style.color = 'var(--text-secondary)';
                        compareBtn2.style.border = '2px solid var(--text-secondary)';
                        
                        loadStats();
                    });
                }
                
                if (compareBtn2) {
                    compareBtn2.addEventListener('click', async function() {
                        const selectedUsers = Array.from(document.querySelectorAll('.compare-user-checkbox:checked'))
                            .map(cb => cb.value);
                        
                        if (selectedUsers.length < 2) {
                            alert('Please select at least 2 users to compare');
                            return;
                        }
                        
                        await loadStatsComparison();
                    });
                }
            }
        });

        
        // User Management Functions
        async function loadUsers() {
            const listDiv = document.getElementById('users-list');
            listDiv.innerHTML = renderSkeletonList(5);
            
            try {
                let availableRoles = [];
                try {
                    const rolesResp = await fetch('/api/roles');
                    if (rolesResp.ok) {
                        const rolesData = await rolesResp.json();
                        availableRoles = rolesData.roles || [];
                    }
                } catch (e) {
                    availableRoles = [];
                }
                window.availableRoles = availableRoles;

                const response = await fetch('/api/users/all');
                const data = await response.json();
                
                if (response.status === 403) {
                    listDiv.innerHTML = '<div class="error">Admin access required to view user management.</div>';
                    return;
                }
                
                if (data.users && data.users.length > 0) {
                    let html = '<div style="display: grid; gap: 10px;">';
                    data.users.forEach(user => {
                        const isAdmin = user.role === 'admin';
                        const roleList = user.roles && user.roles.length ? user.roles : [user.role];
                        const roleBadges = roleList.map(r => `<span style=\"display:inline-block; margin:2px 6px 0 0; padding:2px 8px; background:var(--list-hover); color:var(--text-primary); border-radius:10px; font-size:0.75em; font-weight:600;\">${r}</span>`).join(' ');
                        const roleColor = isAdmin ? '#f59e0b' : '#4f46e5';
                        const roleIcon = isAdmin ? '👑' : '👤';
                        
                        html += `
                            <div class="list-item" style="display: grid; grid-template-columns: 2fr 1fr 1fr 1fr auto; gap: 15px; align-items: center; padding: 15px; background: var(--card-bg); border-radius: var(--radius-sm, 8px);">
                                <div>
                                    <strong style="font-size: 1.1em;">${roleIcon} ${user.username}</strong><br>
                                    <span style="display: inline-block; margin-top: 5px; padding: 3px 10px; background: ${roleColor}; color: white; border-radius: var(--radius, 12px); font-size: 0.85em; font-weight: 600;">
                                        ${user.role.toUpperCase()}
                                    </span>
                                    <div style="margin-top:6px;">${roleBadges}</div>
                                </div>
                                <div>
                                    <small style="color: var(--text-secondary);">Steam ID:</small><br>
                                    <span style="font-family: monospace; font-size: 0.9em;">${user.steam_id || '<span style="color: var(--text-secondary);">Not set</span>'}</span>
                                </div>
                                <div>
                                    <small style="color: var(--text-secondary);">Epic ID:</small><br>
                                    <span style="font-family: monospace; font-size: 0.9em;">${user.epic_id || '<span style="color: var(--text-secondary);">Not set</span>'}</span>
                                </div>
                                <div>
                                    <small style="color: var(--text-secondary);">GOG ID:</small><br>
                                    <span style="font-family: monospace; font-size: 0.9em;">${user.gog_id || '<span style="color: var(--text-secondary);">Not set</span>'}</span>
                                </div>
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <button onclick="editUserRoles('${user.username}')" 
                                            style="padding: 6px 12px; background: #4f46e5; color: white; border: none; border-radius: 50px; cursor: pointer; font-size: 0.85em; font-weight: 600;"
                                            title="Edit Roles">
                                        🧩 Roles
                                    </button>
                                    ${!isAdmin ? `
                                        <button onclick="toggleUserRole('${user.username}', 'admin')" 
                                                style="padding: 6px 12px; background: #f59e0b; color: white; border: none; border-radius: 50px; cursor: pointer; font-size: 0.85em; font-weight: 600; font-family: inherit;"
                                                title="Make Admin">
                                            👑 Admin
                                        </button>
                                    ` : `
                                        <button onclick="toggleUserRole('${user.username}', 'user')" 
                                                style="padding: 6px 12px; background: #4f46e5; color: white; border: none; border-radius: var(--radius-xs, 6px); cursor: pointer; font-size: 0.85em; font-weight: 600;"
                                                title="Make Regular User">
                                            👤 User
                                        </button>
                                    `}
                                    <button onclick="deleteUser('${user.username}')" 
                                            style="padding: 6px 12px; background: #ef4444; color: white; border: none; border-radius: var(--radius-xs, 6px); cursor: pointer; font-size: 0.85em; font-weight: 600;"
                                            title="Delete User">
                                        🗑️
                                    </button>
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No users yet. Register using the login page!</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading users: ' + error.message + '</div>';
            }
        }
        
        async function toggleUserRole(username, newRole) {
            if (!confirm(`Change ${username}'s role to ${newRole.toUpperCase()}?`)) {
                return;
            }
            
            try {
                const response = await fetch('/api/users/role', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: username,
                        role: newRole
                    })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showMessage('Role updated successfully!', 'success');
                    loadUsers();
                } else {
                    showMessage(data.error || 'Failed to update role', 'error');
                }
            } catch (error) {
                showMessage('Error updating role: ' + error.message, 'error');
            }
        }

        async function editUserRoles(username) {
            const roles = (window.availableRoles && window.availableRoles.length) ? window.availableRoles.join(', ') : 'admin, user';
            const input = prompt(`Enter roles for ${username} (comma-separated). Available: ${roles}`);
            if (input === null) return;

            const roleList = input.split(',').map(r => r.trim()).filter(Boolean);
            if (roleList.length === 0) {
                showMessage('At least one role is required', 'error');
                return;
            }

            try {
                const response = await fetch('/api/users/roles', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, roles: roleList })
                });

                const data = await response.json();
                if (response.ok) {
                    showMessage('Roles updated successfully!', 'success');
                    loadUsers();
                } else {
                    showMessage(data.error || 'Failed to update roles', 'error');
                }
            } catch (error) {
                showMessage('Error updating roles: ' + error.message, 'error');
            }
        }
        
        async function deleteUser(username) {
            if (!confirm(`Are you sure you want to delete user "${username}"?\\n\\nThis action cannot be undone!`)) {
                return;
            }
            
            try {
                const response = await fetch(`/api/users/delete/${username}`, {
                    method: 'DELETE'
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showMessage('User deleted successfully!', 'success');
                    loadUsers();
                } else {
                    showMessage(data.error || 'Failed to delete user', 'error');
                }
            } catch (error) {
                showMessage('Error deleting user: ' + error.message, 'error');
            }
        }

        async function loadPasswordResetRequests() {
            const listDiv = document.getElementById('password-reset-requests-list');
            if (!listDiv) return;
            listDiv.innerHTML = renderSkeletonList(3);
            try {
                const resp = await fetch('/api/admin/password-reset-requests');
                if (!resp.ok) {
                    listDiv.innerHTML = '<div class="error">Failed to load password reset requests.</div>';
                    return;
                }
                const data = await resp.json();
                const requests = data.requests || [];
                if (requests.length === 0) {
                    listDiv.innerHTML = '<div style="color: var(--text-secondary); padding: 12px;">No password reset requests.</div>';
                    return;
                }
                let html = '<div style="display: grid; gap: 8px;">';
                requests.forEach(r => {
                    const statusColor = r.status === 'pending' ? '#f59e0b' : '#6b7280';
                    const statusIcon = r.status === 'pending' ? '⏳' : '✅';
                    const date = r.requested_at ? new Date(r.requested_at).toLocaleString() : '—';
                    const dismissedInfo = r.dismissed_by ? ` · dismissed by ${r.dismissed_by}` : '';
                    html += `
                        <div style="display:flex; align-items:center; gap:12px; padding:12px 14px; background:var(--card-bg); border:1px solid var(--card-border); border-radius:var(--radius-sm,8px);">
                            <span style="font-size:1.3em;">${statusIcon}</span>
                            <div style="flex:1; min-width:0;">
                                <strong>${r.username}</strong>
                                <div style="font-size:var(--font-sm); color:var(--text-secondary);">${date}${dismissedInfo}</div>
                            </div>
                            <span style="padding:3px 10px; border-radius:10px; font-size:0.8em; font-weight:600; background:${statusColor}22; color:${statusColor};">${r.status}</span>
                            ${r.status === 'pending' ? `<button onclick="dismissPasswordResetRequest(${r.id})" style="padding:5px 12px; background:#4f46e5; color:white; border:none; border-radius:50px; cursor:pointer; font-size:0.82em; font-weight:600; white-space:nowrap;">✔ Dismiss</button>` : ''}
                        </div>`;
                });
                html += '</div>';
                listDiv.innerHTML = html;
            } catch (e) {
                listDiv.innerHTML = '<div class="error">Error loading requests: ' + e.message + '</div>';
            }
        }
        try { window.loadPasswordResetRequests = loadPasswordResetRequests; } catch(e) {}

        async function dismissPasswordResetRequest(id) {
            try {
                const resp = await fetch(`/api/admin/password-reset-requests/${id}/dismiss`, { method: 'POST' });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage('Request dismissed.', 'success');
                    loadPasswordResetRequests();
                } else {
                    showMessage(data.error || 'Failed to dismiss request.', 'error');
                }
            } catch (e) {
                showMessage('Error: ' + e.message, 'error');
            }
        }
        try { window.dismissPasswordResetRequest = dismissPasswordResetRequest; } catch(e) {}

        function showMessage(message, type = 'info') {
            // Delegate to the richer toast system when available
            if (typeof showToast === 'function') {
                showToast(message, type);
                return;
            }
            // Fallback: styled fixed-position notification
            const normalizedType = ['success', 'error', 'warning', 'info'].includes(type) ? type : 'info';
            const messageDiv = document.createElement('div');
            messageDiv.className = `app-toast app-toast--${normalizedType}`;
            messageDiv.textContent = message;
            document.body.appendChild(messageDiv);
            setTimeout(() => {
                messageDiv.style.animation = 'toastSlideIn 0.24s ease-out reverse';
                setTimeout(() => messageDiv.remove(), 240);
            }, 3000);
        }
        
        
        // Multi-User Functions
        async function loadUsersForMultiUser() {
            const checkboxDiv = document.getElementById('user-checkboxes');
            checkboxDiv.innerHTML = renderSkeletonList(3);
            
            try {
                const response = await fetch('/api/users?scope=me_and_friends');
                const data = await response.json();
                
                if (data.users && data.users.length > 0) {
                    let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px;">';
                    data.users.forEach(user => {
                        const hasAnyId = !!(user.steam_id || user.epic_id || user.gog_id);
                        const badge = hasAnyId ? '🎮' : '⚠️';
                        const tooltipText = hasAnyId ? 'Has platform IDs configured' : 'No platform IDs - add in Settings';
                        
                        html += `
                            <label style="display: flex; align-items: center; gap: 10px; padding: 12px; background: var(--card-bg); border-radius: var(--radius-sm, 8px); cursor: pointer; border: 2px solid ${hasAnyId ? '#4f46e5' : 'var(--card-border)'};" title="${tooltipText}">
                                <input type="checkbox" class="user-checkbox" value="${user.username}" ${!hasAnyId ? 'disabled' : ''} style="width: 18px; height: 18px;" onchange="refreshMultiUserPlatformFilters()">
                                <span><strong>${badge} ${user.username}</strong></span>
                            </label>
                        `;
                    });
                    html += '</div>';
                    html += '<p style="margin-top: 15px; color: var(--text-secondary); font-size: 0.9em;">💡 Tip: Users need at least one platform ID in Settings to appear in multi-user game picker.</p>';
                    checkboxDiv.innerHTML = html;
                    await refreshMultiUserPlatformFilters();
                } else {
                    checkboxDiv.innerHTML = '<div class="loading">No users with platform IDs found. Users can add their IDs in Settings.</div>';
                    rebuildFilterSelect(document.getElementById('multi-platform-filter'), [], 'Any platform');
                    rebuildFilterSelect(document.getElementById('multi-device-filter'), [], 'Any device');
                }
            } catch (error) {
                checkboxDiv.innerHTML = '<div class="error">Error loading users: ' + error.message + '</div>';
            }
        }
        
        function getSelectedUsers() {
            const checkboxes = document.querySelectorAll('.user-checkbox:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }
        
        async function pickMultiUserGame() {
            const selectedUsers = getSelectedUsers();
            
            if (selectedUsers.length === 0) {
                alert('Please select at least one user!');
                return;
            }
            
            // Collect all filter inputs
            const coopOnly = document.getElementById('coop-only').checked;
            const minPlaytime = document.getElementById('min-playtime').value;
            const maxPlaytime = document.getElementById('max-playtime').value;
            const minMetacritic = document.getElementById('min-metacritic').value;
            const minReleaseYear = document.getElementById('min-release-year').value;
            const maxReleaseYear = document.getElementById('max-release-year').value;
            const maxPrice = document.getElementById('max-game-price').value;
            const includeGenres = document.getElementById('include-genres').value;
            const excludeGenres = document.getElementById('exclude-genres').value;
            const includeTags = document.getElementById('include-tags').value;
            const excludeGameIds = document.getElementById('exclude-game-ids').value;
            const minAvgPlaytime = document.getElementById('min-avg-playtime').value;
            const requireMultiplayer = document.getElementById('require-multiplayer').checked;
            const requireSingleplayer = document.getElementById('require-singleplayer').checked;
            const platformFilter = document.getElementById('multi-platform-filter').value;
            const deviceFilter = document.getElementById('multi-device-filter').value;
            
            const resultDiv = document.getElementById('multiuser-result');

            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '<div class="loading">Picking a game...</div>';
            showSpinner('Fetching common games…');
            try {
                const body = {
                    users: selectedUsers,
                    coop_only: coopOnly,
                    max_players: selectedUsers.length
                };
                
                // Add optional filter parameters
                if (minPlaytime) body.min_playtime = parseInt(minPlaytime) * 60; // Convert hours to minutes
                if (maxPlaytime) body.max_playtime = parseInt(maxPlaytime) * 60; // Convert hours to minutes
                if (minMetacritic) body.min_metacritic = parseInt(minMetacritic);
                if (minReleaseYear) body.min_release_year = parseInt(minReleaseYear);
                if (maxReleaseYear) body.max_release_year = parseInt(maxReleaseYear);
                if (maxPrice) body.max_price = parseFloat(maxPrice);
                if (includeGenres) body.genres = includeGenres;
                if (excludeGenres) body.exclude_genres = excludeGenres;
                if (includeTags) body.tags = includeTags;
                if (excludeGameIds) body.exclude_game_ids = excludeGameIds;
                if (minAvgPlaytime) body.min_avg_playtime = parseInt(minAvgPlaytime) * 60; // Convert hours to minutes
                if (requireMultiplayer) body.multiplayer_only = true;
                if (requireSingleplayer) body.singleplayer_only = true;
                if (platformFilter) body.platform_filter = platformFilter;
                if (deviceFilter) body.device_filter = deviceFilter;
                
                const response = await fetch('/api/multiuser/pick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                });

                if (!response.ok) {
                    const error = await response.json();
                    resultDiv.innerHTML = `<div class="error">${error.error || 'No common games found'}</div>`;
                    return;
                }

                const game = await response.json();

                // Display multi-user game with same rich preview as single-player picker
                await displayMultiUserGame(game, selectedUsers);
                
            } catch (error) {
                resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
            } finally {
                hideSpinner();
            }
        }

        function clearMultiUserFilters() {
            document.getElementById('min-playtime').value = '';
            document.getElementById('max-playtime').value = '';
            document.getElementById('min-metacritic').value = '';
            document.getElementById('min-release-year').value = '';
            document.getElementById('max-release-year').value = '';
            document.getElementById('include-genres').value = '';
            document.getElementById('exclude-genres').value = '';
            document.getElementById('include-tags').value = '';
            document.getElementById('exclude-game-ids').value = '';
            document.getElementById('min-avg-playtime').value = '';
            document.getElementById('coop-only').checked = false;
            document.getElementById('multi-platform-filter').value = '';
            document.getElementById('multi-device-filter').value = '';
        }

        async function showCommonGames() {
            const selectedUsers = getSelectedUsers();
            const listDiv = document.getElementById('common-games-list');
            const countSpan = document.getElementById('common-count');

            listDiv.innerHTML = renderSkeletonList(5);
            showSpinner('Loading common games…');
            try {
                const usersParam = selectedUsers.length > 0 ? selectedUsers.join(',') : '';
                const response = await fetch(`/api/multiuser/common?users=${encodeURIComponent(usersParam)}`);
                const data = await response.json();

                countSpan.textContent = `(${data.total_common})`;

                if (data.games && data.games.length > 0) {
                    let html = '';
                    data.games.forEach(game => {
                        html += `
                            <div class="list-item">
                                <div>
                                    <strong>${game.name}</strong><br>
                                    <small style="color: var(--text-secondary);">Owned by: ${game.owners ? game.owners.join(', ') : 'All selected users'}</small>
                                </div>
                                <div>${game.playtime_hours}h</div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No common games found</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading common games</div>';
            } finally {
                hideSpinner();
            }
        }

        // ----------------------------------------------------------------
        // Voting functions
        // ----------------------------------------------------------------

        async function startVote() {
            const selectedUsers = getSelectedUsers();
            if (selectedUsers.length === 0) {
                alert('Please select at least one user first!');
                return;
            }
            // Toggle vote options panel
            const voteOptionsDiv = document.getElementById('vote-options');
            voteOptionsDiv.style.display = voteOptionsDiv.style.display === 'flex' ? 'none' : 'flex';
        }

        function cancelVoteOptions() {
            document.getElementById('vote-options').style.display = 'none';
        }

        async function createVoteSession() {
            const selectedUsers = getSelectedUsers();
            if (selectedUsers.length === 0) {
                alert('Please select at least one user first!');
                return;
            }

            const coopOnly = document.getElementById('coop-only').checked;
            const numCandidates = parseInt(document.getElementById('vote-candidates').value) || 5;
            const duration = parseInt(document.getElementById('vote-duration').value) || 60;
            document.getElementById('vote-options').style.display = 'none';

            const resultDiv = document.getElementById('multiuser-result');
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '<div class="loading">Creating voting session…</div>';
            showSpinner('Finding game candidates…');

            try {
                const response = await fetch('/api/voting/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        users: selectedUsers,
                        num_candidates: numCandidates,
                        duration: duration,
                        coop_only: coopOnly
                    })
                });

                if (!response.ok) {
                    const err = await response.json();
                    resultDiv.innerHTML = `<div class="error">${err.error || 'Failed to create vote'}</div>`;
                    return;
                }

                const session = await response.json();
                activeVoteSession = session;
                resultDiv.style.display = 'none';
                renderVotingSession(session);

                // Start countdown timer
                if (session.duration) {
                    let remaining = session.duration;
                    const timerDiv = document.getElementById('voting-timer');
                    clearInterval(voteTimerInterval);
                    voteTimerInterval = setInterval(() => {
                        remaining -= 1;
                        if (remaining <= 0) {
                            clearInterval(voteTimerInterval);
                            timerDiv.textContent = '⏰ Time is up!';
                        } else {
                            timerDiv.textContent = `⏳ ${remaining}s remaining`;
                        }
                    }, 1000);
                }

            } catch (error) {
                resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
            } finally {
                hideSpinner();
            }
        }

        function renderVotingSession(session) {
            const section = document.getElementById('voting-section');
            const candidatesDiv = document.getElementById('voting-candidates');
            const timerDiv = document.getElementById('voting-timer');

            section.style.display = 'block';
            document.getElementById('vote-winner').style.display = 'none';

            if (session.duration) {
                timerDiv.textContent = `⏳ ${session.duration}s remaining`;
            } else {
                timerDiv.textContent = '';
            }

            let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px;">';
            session.candidates.forEach(candidate => {
                const voteCount = session.vote_counts[candidate.app_id]
                    ? session.vote_counts[candidate.app_id].count : 0;
                const voters = session.vote_counts[candidate.app_id]
                    ? session.vote_counts[candidate.app_id].voters.join(', ') : '';
                html += `
                    <div style="background: var(--card-bg); border-radius: var(--radius, 12px); padding: 15px; text-align: center; box-shadow: var(--shadow-md); border: 1px solid var(--card-border);">
                        <div style="font-weight: bold; margin-bottom: 8px;">${candidate.name}</div>
                        <div style="color: var(--text-secondary); font-size: 0.9em; margin-bottom: 10px;">${candidate.playtime_hours}h played</div>
                        <div id="vote-count-${candidate.app_id}" style="font-size: 1.4em; font-weight: bold; color: #4f46e5; margin-bottom: 6px;">${voteCount} vote${voteCount !== 1 ? 's' : ''}</div>
                        ${voters ? `<div style="font-size: 0.8em; color: var(--text-secondary); margin-bottom: 8px;">${voters}</div>` : ''}
                        <button onclick="castVote('${candidate.app_id}')"
                                style="padding: 8px 18px; background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); color: white; border: none; border-radius: 50px; cursor: pointer; font-size: 0.95em; font-family:inherit;">
                            👍 Vote
                        </button>
                    </div>`;
            });
            html += '</div>';
            candidatesDiv.innerHTML = html;
        }

        async function castVote(appId) {
            if (!activeVoteSession) return;
            const voterName = document.getElementById('voter-name-input').value.trim();
            if (!voterName) {
                alert('Please enter your name before voting!');
                return;
            }

            try {
                const response = await fetch(`/api/voting/${activeVoteSession.session_id}/vote`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_name: voterName, app_id: appId})
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'Failed to cast vote');
                    return;
                }
                // Refresh status
                await refreshVoteStatus();
            } catch (error) {
                alert('Error casting vote: ' + error.message);
            }
        }

        async function refreshVoteStatus() {
            if (!activeVoteSession) return;
            try {
                const response = await fetch(`/api/voting/${activeVoteSession.session_id}/status`);
                if (!response.ok) return;
                const session = await response.json();
                activeVoteSession = session;
                renderVotingSession(session);
            } catch (error) {
                console.error('Error refreshing vote status:', error);
            }
        }

        async function closeVote() {
            if (!activeVoteSession) return;
            clearInterval(voteTimerInterval);

            try {
                const response = await fetch(`/api/voting/${activeVoteSession.session_id}/close`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'Failed to close vote');
                    return;
                }

                // Hide voting section
                document.getElementById('voting-section').style.display = 'none';
                activeVoteSession = null;

                // Show winner
                const winnerDiv = document.getElementById('vote-winner');
                const winner = data.winner;
                let html = `
                    <h3 style="color: #10b981;">🏆 Winner: ${winner.name}</h3>
                    <p style="margin-top: 8px; color: var(--text-secondary);">Total votes: <strong>${data.total_votes}</strong></p>
                    <div style="margin-top: 15px; display: flex; gap: 10px; flex-wrap: wrap;">`;

                // Show per-game tallies
                if (data.vote_counts) {
                    html += '<div style="width:100%; margin-bottom: 10px;">';
                    Object.entries(data.vote_counts).forEach(([appId, info]) => {
                        html += `<div style="margin: 4px 0; color: var(--text-primary);">App ${appId}: <strong>${info.count}</strong> vote(s)`;
                        if (info.voters && info.voters.length) html += ` (${info.voters.join(', ')})`;
                        html += '</div>';
                    });
                    html += '</div>';
                }

                if (winner.steam_url) {
                    html += `<a href="${winner.steam_url}" target="_blank" class="btn btn-link">🔗 Steam Store</a>`;
                }
                if (winner.steamdb_url) {
                    html += `<a href="${winner.steamdb_url}" target="_blank" class="btn btn-link">📊 SteamDB</a>`;
                }
                html += '</div>';
                winnerDiv.innerHTML = html;
                winnerDiv.style.display = 'block';
                winnerDiv.scrollIntoView({behavior: 'smooth'});

            } catch (error) {
                alert('Error closing vote: ' + error.message);
            }
        }

        // Authentication is initialized via DOMContentLoaded below

        // Close search dropdowns when clicking outside
        document.addEventListener('click', function(event) {
            const gameDropdown = document.getElementById('game-search-dropdown');
            const attendeeDropdown = document.getElementById('attendee-search-dropdown');
            const discordDropdown = document.getElementById('discord-guild-search-dropdown');
            const scheduleMembersDropdown = document.getElementById('schedule-collection-members-dropdown');
            const backlogLibraryDropdown = document.getElementById('backlog-library-search-results');
            const gameField = document.getElementById('sch-game');
            const attendeeField = document.getElementById('sch-attendees');
            const discordField = document.getElementById('sch-discord-guild-search');
            const scheduleMembersField = document.getElementById('schedule-collection-members');
            const backlogLibraryField = document.getElementById('backlog-library-search');
            
            if (gameDropdown && gameField && !gameField.contains(event.target) && !gameDropdown.contains(event.target)) {
                gameDropdown.style.display = 'none';
            }
            if (attendeeDropdown && attendeeField && !attendeeField.contains(event.target) && !attendeeDropdown.contains(event.target)) {
                attendeeDropdown.style.display = 'none';
            }
            if (discordDropdown && discordField && !discordField.contains(event.target) && !discordDropdown.contains(event.target)) {
                discordDropdown.style.display = 'none';
            }
            if (scheduleMembersDropdown && scheduleMembersField
                && !scheduleMembersField.contains(event.target)
                && !scheduleMembersDropdown.contains(event.target)) {
                scheduleMembersDropdown.style.display = 'none';
            }
            if (backlogLibraryDropdown && backlogLibraryField
                && !backlogLibraryField.contains(event.target)
                && !backlogLibraryDropdown.contains(event.target)) {
                backlogLibraryDropdown.style.display = 'none';
            }
        });

        // ---- Game Night Scheduler ----

        const DEFAULT_SCHEDULE_DURATION_MINUTES = 60;
        const SCHEDULE_SLOT_MINUTES = 30;
        const SCHEDULE_SLOT_HEIGHT = 28;
        const SCHEDULE_RSVP_OPTIONS = [
            { value: 'pending', label: 'Pending' },
            { value: 'accepted', label: 'Going' },
            { value: 'maybe', label: 'Maybe' },
            { value: 'declined', label: 'Declined' },
        ];
        let scheduleEventsCache = [];
        let scheduleFilteredEventsCache = [];
        let scheduleAgendaWeekStart = null;
        let scheduleAgendaSelection = null;
        let scheduleAgendaSelectionActive = false;
        let scheduleAgendaDraggedEventId = null;
        let scheduleDiscordGuildsCache = [];
        let scheduleCollectionsCache = [];
        let activeScheduleId = '';
        let scheduleCommonGamesCache = [];
        let scheduleIcalSyncInfo = null;
        let scheduleMemberSearchTimeout;
        let scheduleGameSearchCache = [];
        let scheduleGameLibraryCache = [];
        let scheduleGameLibraryById = new Map();
        let scheduleGameFavoriteIds = new Set();
        let scheduleGameBacklogIndex = new Map();
        let scheduleBacklogCollectionChoices = [];
        let scheduleGameFilterCacheReady = false;
        let backlogLibraryQuickAddData = [];
        let backlogLibraryQuickAddSelectedGameId = '';

        function normalizeScheduleDurationMinutes(value, fallback = DEFAULT_SCHEDULE_DURATION_MINUTES) {
            const parsed = parseInt(value, 10);
            if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
            return Math.max(SCHEDULE_SLOT_MINUTES, Math.round(parsed / SCHEDULE_SLOT_MINUTES) * SCHEDULE_SLOT_MINUTES);
        }

        function normalizeScheduleRsvpStatus(value) {
            const safe = String(value || 'pending').trim().toLowerCase();
            return ['pending', 'accepted', 'maybe', 'declined'].includes(safe) ? safe : 'pending';
        }

        function parseScheduleLocalDateTime(dateStr, timeStr = '00:00') {
            const safeDate = String(dateStr || '').trim();
            if (!safeDate) return null;
            const dateParts = safeDate.split('-').map(Number);
            if (dateParts.length !== 3 || dateParts.some(Number.isNaN)) return null;
            const cleanTime = String(timeStr || '00:00').replace('.', ':');
            const [hoursRaw, minutesRaw] = cleanTime.split(':');
            const hours = Number(hoursRaw || 0);
            const minutes = Number(minutesRaw || 0);
            if (Number.isNaN(hours) || Number.isNaN(minutes)) return null;
            return new Date(dateParts[0], dateParts[1] - 1, dateParts[2], hours, minutes, 0, 0);
        }

        function parseScheduleDateTimeInput(value) {
            const safeValue = String(value || '').trim();
            if (!safeValue) return null;
            const parsed = new Date(safeValue);
            return Number.isNaN(parsed.getTime()) ? null : parsed;
        }

        function formatScheduleDateKey(date) {
            return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        }

        function formatScheduleDateTimeLocalValue(date) {
            if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
            return `${formatScheduleDateKey(date)}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
        }

        function scheduleSlotIndexToTime(slotIndex) {
            const totalMinutes = slotIndex * SCHEDULE_SLOT_MINUTES;
            const hours = Math.floor(totalMinutes / 60);
            const minutes = totalMinutes % 60;
            return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
        }

        function scheduleStartOfWeek(baseDate = new Date()) {
            const date = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
            const day = date.getDay();
            const diff = day === 0 ? -6 : 1 - day;
            date.setDate(date.getDate() + diff);
            date.setHours(0, 0, 0, 0);
            return date;
        }

        function ensureScheduleAgendaWeek(events = []) {
            if (scheduleAgendaWeekStart) return;
            const firstEventDate = (events || [])
                .map(ev => parseScheduleLocalDateTime(ev.date, ev.time))
                .filter(Boolean)
                .sort((a, b) => a - b)[0];
            scheduleAgendaWeekStart = scheduleStartOfWeek(firstEventDate || new Date());
        }

        function getScheduleAgendaDays() {
            ensureScheduleAgendaWeek(scheduleFilteredEventsCache.length ? scheduleFilteredEventsCache : scheduleEventsCache);
            return Array.from({ length: 7 }, (_, index) => {
                const day = new Date(scheduleAgendaWeekStart);
                day.setDate(scheduleAgendaWeekStart.getDate() + index);
                return day;
            });
        }

        function formatScheduleAgendaRange(days) {
            if (!days || !days.length) return '';
            const start = days[0].toLocaleDateString([], { month: 'short', day: 'numeric' });
            const end = days[days.length - 1].toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
            return `${start} – ${end}`;
        }

        function getScheduleAgendaWeekBounds(weekStart = scheduleAgendaWeekStart) {
            ensureScheduleAgendaWeek(scheduleFilteredEventsCache.length ? scheduleFilteredEventsCache : scheduleEventsCache);
            const safeWeekStart = weekStart || scheduleAgendaWeekStart || scheduleStartOfWeek(new Date());
            const start = new Date(safeWeekStart);
            start.setHours(0, 0, 0, 0);
            const end = new Date(safeWeekStart);
            end.setDate(end.getDate() + 6);
            end.setHours(23, 30, 0, 0);
            return { start, end };
        }

        function setScheduleFiltersToAgendaWeek() {
            const startField = document.getElementById('schedule-filter-start');
            const endField = document.getElementById('schedule-filter-end');
            const { start, end } = getScheduleAgendaWeekBounds();
            if (startField) startField.value = formatScheduleDateTimeLocalValue(start);
            if (endField) endField.value = formatScheduleDateTimeLocalValue(end);
        }

        function getScheduleEventDurationMinutes(event) {
            return normalizeScheduleDurationMinutes(event?.duration_minutes, DEFAULT_SCHEDULE_DURATION_MINUTES);
        }

        function buildScheduleEventListTimeText(event) {
            const start = parseScheduleLocalDateTime(event?.date, event?.time);
            if (!start) return `${event?.date || ''} ${event?.time || ''}`.trim() || 'Time TBD';
            const end = new Date(start.getTime() + getScheduleEventDurationMinutes(event) * 60000);
            return `${event.date || formatScheduleDateKey(start)} ${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}–${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`;
        }

        function buildScheduleEventAgendaTimeText(event) {
            const start = parseScheduleLocalDateTime(event?.date, event?.time);
            if (!start) return event?.time || 'Time TBD';
            const end = new Date(start.getTime() + getScheduleEventDurationMinutes(event) * 60000);
            return `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}–${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`;
        }

        function getScheduleSelectedAttendees() {
            const names = (document.getElementById('sch-attendee-values')?.value || '')
                .split(',')
                .map(value => value.trim())
                .filter(Boolean);
            const ids = (document.getElementById('sch-attendee-ids')?.value || '')
                .split(',')
                .map(value => value.trim());
            return names.map((name, index) => ({ name, id: ids[index] || name }));
        }

        function getScheduleEventAttendees() {
            return getScheduleSelectedAttendees().map(attendee => attendee.name);
        }

        function getScheduleEventAttendeeIds() {
            return getScheduleSelectedAttendees().map(attendee => attendee.id || attendee.name);
        }

        function getScheduleRsvpValues() {
            const field = document.getElementById('sch-rsvp-values');
            if (!field || !field.value) return {};
            try {
                const parsed = JSON.parse(field.value);
                return parsed && typeof parsed === 'object' ? parsed : {};
            } catch (error) {
                return {};
            }
        }

        function syncScheduleRsvpValues(existing = getScheduleRsvpValues()) {
            const attendees = getScheduleSelectedAttendees();
            const next = {};
            attendees.forEach(({ name, id }) => {
                const key = id || name;
                next[key] = normalizeScheduleRsvpStatus(existing[key] || existing[name] || 'pending');
            });
            const field = document.getElementById('sch-rsvp-values');
            if (field) field.value = JSON.stringify(next);
            renderScheduleRsvpList();
        }

        function setScheduleSelectedAttendees(attendees) {
            const unique = [];
            const seen = new Set();
            (attendees || []).forEach(attendee => {
                const name = String(attendee?.name || attendee || '').trim();
                if (!name) return;
                const id = String(attendee?.id || name).trim() || name;
                const key = id.toLowerCase();
                if (seen.has(key)) return;
                seen.add(key);
                unique.push({ name, id });
            });
            const namesField = document.getElementById('sch-attendee-values');
            const idsField = document.getElementById('sch-attendee-ids');
            if (namesField) namesField.value = unique.map(attendee => attendee.name).join(', ');
            if (idsField) idsField.value = unique.map(attendee => attendee.id).join(', ');
            updateAttendeeTagsDisplay();
            syncScheduleRsvpValues();
        }

        function setScheduleRsvpValues(values) {
            const field = document.getElementById('sch-rsvp-values');
            if (field) field.value = JSON.stringify(values || {});
            syncScheduleRsvpValues(values || {});
        }

        function getScheduleEventRsvpEntries(event) {
            const attendees = Array.isArray(event?.invited_attendees) && event.invited_attendees.length
                ? event.invited_attendees
                : (Array.isArray(event?.attendees) ? event.attendees : []);
            const attendeeIds = Array.isArray(event?.invited_attendee_ids) && event.invited_attendee_ids.length
                ? event.invited_attendee_ids
                : (Array.isArray(event?.attendee_ids) ? event.attendee_ids : []);
            const rsvpMap = event?.rsvp_statuses && typeof event.rsvp_statuses === 'object' ? event.rsvp_statuses : {};
            return attendees.map((name, index) => {
                const attendeeId = attendeeIds[index] || name;
                return {
                    name,
                    id: attendeeId,
                    status: normalizeScheduleRsvpStatus(rsvpMap[attendeeId] || rsvpMap[name] || 'pending'),
                };
            });
        }

        function eventHasPendingInviteForCurrentUser(event) {
            const current = getScheduleCurrentUsername().toLowerCase();
            if (!current) return false;
            const entry = getScheduleEventRsvpEntries(event).find(item => (
                String(item.id || '').trim().toLowerCase() === current
                || String(item.name || '').trim().toLowerCase() === current
            ));
            return !!entry && entry.status === 'pending';
        }

        function splitScheduleEventsByInviteState(events = []) {
            const pendingInvites = [];
            const acceptedEvents = [];
            (events || []).forEach(event => {
                if (eventHasPendingInviteForCurrentUser(event)) pendingInvites.push(event);
                else acceptedEvents.push(event);
            });
            return { pendingInvites, acceptedEvents };
        }

        function buildScheduleRsvpSummary(event) {
            const counts = { accepted: 0, maybe: 0, declined: 0, pending: 0 };
            getScheduleEventRsvpEntries(event).forEach(entry => {
                counts[entry.status] = (counts[entry.status] || 0) + 1;
            });
            return [
                counts.accepted ? `${counts.accepted} going` : '',
                counts.maybe ? `${counts.maybe} maybe` : '',
                counts.declined ? `${counts.declined} declined` : '',
                counts.pending ? `${counts.pending} pending` : '',
            ].filter(Boolean).join(' · ');
        }

        function renderScheduleRsvpList() {
            const list = document.getElementById('schedule-rsvp-list');
            if (!list) return;
            const attendees = getScheduleSelectedAttendees();
            const rsvpValues = getScheduleRsvpValues();
            if (!attendees.length) {
                list.innerHTML = '<div class="schedule-field-hint">Add invitees to track each RSVP.</div>';
                return;
            }
            list.innerHTML = attendees.map(attendee => {
                const current = normalizeScheduleRsvpStatus(rsvpValues[attendee.id] || rsvpValues[attendee.name] || 'pending');
                return `
                    <div class="schedule-rsvp-row">
                        <div>
                            <div class="schedule-rsvp-name">${escapeHtml(attendee.name)}</div>
                            <div class="schedule-field-hint">RSVP status</div>
                        </div>
                        <div class="schedule-rsvp-buttons">
                            ${SCHEDULE_RSVP_OPTIONS.map(option => `
                                <button type="button" class="schedule-rsvp-btn ${current === option.value ? 'active' : ''}"
                                        onclick="updateScheduleRsvpStatus('${escAttr(attendee.id)}', '${option.value}')">${option.label}</button>
                            `).join('')}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function updateScheduleRsvpStatus(attendeeId, status) {
            const values = getScheduleRsvpValues();
            values[attendeeId] = normalizeScheduleRsvpStatus(status);
            setScheduleRsvpValues(values);
        }

        function getNormalizedAgendaSelection() {
            if (!scheduleAgendaSelection) return null;
            const startSlot = Math.min(scheduleAgendaSelection.startSlot, scheduleAgendaSelection.endSlot);
            const endSlot = Math.max(scheduleAgendaSelection.startSlot, scheduleAgendaSelection.endSlot);
            return { ...scheduleAgendaSelection, startSlot, endSlot };
        }

        function getAgendaSelectionSummary(selection = getNormalizedAgendaSelection()) {
            if (!selection) return null;
            const startTime = scheduleSlotIndexToTime(selection.startSlot);
            const durationMinutes = (selection.endSlot - selection.startSlot + 1) * SCHEDULE_SLOT_MINUTES;
            const startDate = parseScheduleLocalDateTime(selection.date, startTime);
            if (!startDate) return null;
            const endDate = new Date(startDate.getTime() + durationMinutes * 60000);
            return {
                ...selection,
                startTime,
                durationMinutes,
                label: startDate.toLocaleDateString([], {
                    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
                }),
                meta: `${startTime}–${String(endDate.getHours()).padStart(2, '0')}:${String(endDate.getMinutes()).padStart(2, '0')} • ${durationMinutes} min`,
            };
        }

        function setScheduleBodyLock() {
            const anyOpen = ['schedule-modal', 'schedule-game-picker-modal', 'schedule-ical-modal', 'schedule-collection-modal']
                .some(id => document.getElementById(id)?.style.display === 'flex');
            document.body.style.overflow = anyOpen ? 'hidden' : '';
        }

        function getActiveSchedule() {
            return scheduleCollectionsCache.find(schedule => schedule.id === activeScheduleId) || null;
        }

        function getScheduleCurrentUsername() {
            const raw = document.getElementById('current-username')?.textContent
                || document.getElementById('sidebar-username')?.textContent
                || '';
            return raw.trim();
        }

        function isOwnedSchedule(schedule) {
            if (!schedule) return false;
            return String(schedule.owner || '').trim().toLowerCase() === getScheduleCurrentUsername().toLowerCase();
        }

        function isDefaultSchedule(schedule) {
            const currentUsername = getScheduleCurrentUsername().toLowerCase();
            if (!schedule || !currentUsername) return false;
            return String(schedule.id || '').trim().toLowerCase() === `personal:${currentUsername}`;
        }

        function getFilteredScheduleCollections() {
            const query = getFilterValue('schedule-selector-search').trim().toLowerCase();
            if (!query) return scheduleCollectionsCache;
            return scheduleCollectionsCache.filter(schedule => {
                const searchText = [
                    schedule.name,
                    schedule.owner,
                    ...(Array.isArray(schedule.members) ? schedule.members : [])
                ].filter(Boolean).join(' ').toLowerCase();
                return searchText.includes(query);
            });
        }

        function updateScheduleSidebarMeta(visibleSchedules = getFilteredScheduleCollections()) {
            const meta = document.getElementById('schedule-sidebar-meta');
            const active = getActiveSchedule();
            if (!meta) return;
            if (!scheduleCollectionsCache.length) {
                meta.textContent = 'Create a schedule to start planning events.';
                return;
            }
            const sharedCount = Math.max(((active?.members || []).length || 1) - 1, 0);
            const visibleCount = visibleSchedules.length;
            meta.textContent = active
                ? `${active.name || 'Schedule'}${active.is_shared ? ` • shared with ${sharedCount}` : ' • personal'}${visibleCount !== scheduleCollectionsCache.length ? ` • ${visibleCount} shown` : ''}`
                : 'Choose a schedule to review your week.';
        }

        function filterScheduleCollections() {
            renderScheduleSelector();
        }

        function getScheduleCollectionMembers() {
            return (document.getElementById('schedule-collection-member-tags')?.dataset.members || '')
                .split(',')
                .map(value => value.trim())
                .filter(Boolean);
        }

        function updateScheduleCollectionMemberTags() {
            const tags = document.getElementById('schedule-collection-member-tags');
            if (!tags) return;
            const members = getScheduleCollectionMembers();
            tags.innerHTML = members.map(member => `
                <span style="padding:4px 10px; background:#4f46e5; color:white; border-radius:var(--radius-lg,16px); font-size:0.85em; display:inline-flex; align-items:center; gap:6px;">
                    ${escapeHtml(member)}
                    <button type="button" onclick="removeScheduleCollectionMember('${escAttr(member)}')" style="background:none; border:none; color:white; cursor:pointer; padding:0; font-size:1em; line-height:1;">×</button>
                </span>
            `).join('');
        }

        function setScheduleCollectionMembers(members) {
            const tags = document.getElementById('schedule-collection-member-tags');
            if (!tags) return;
            const unique = [];
            const seen = new Set();
            (members || []).forEach(member => {
                const safeMember = String(member || '').trim();
                if (!safeMember) return;
                const key = safeMember.toLowerCase();
                if (seen.has(key)) return;
                seen.add(key);
                unique.push(safeMember);
            });
            tags.dataset.members = unique.join(',');
            updateScheduleCollectionMemberTags();
        }

        function clearScheduleCollectionForm() {
            const editField = document.getElementById('schedule-collection-edit-id');
            const nameField = document.getElementById('schedule-collection-name');
            const searchField = document.getElementById('schedule-collection-members');
            const dropdown = document.getElementById('schedule-collection-members-dropdown');
            const title = document.getElementById('schedule-collection-title');
            if (editField) editField.value = '';
            if (nameField) nameField.value = '';
            if (searchField) searchField.value = '';
            if (dropdown) dropdown.style.display = 'none';
            if (title) title.textContent = '🗂️ New Schedule';
            setScheduleCollectionMembers([]);
        }

        function openScheduleCollectionModal() {
            clearScheduleCollectionForm();
            const modal = document.getElementById('schedule-collection-modal');
            if (modal) modal.style.display = 'flex';
            setScheduleBodyLock();
            setTimeout(() => document.getElementById('schedule-collection-name')?.focus(), 0);
        }

        function openRenameScheduleModal() {
            const schedule = getActiveSchedule();
            if (!schedule) {
                showMessage('Choose a schedule first.', 'warning');
                return;
            }
            clearScheduleCollectionForm();
            document.getElementById('schedule-collection-edit-id').value = schedule.id || '';
            document.getElementById('schedule-collection-name').value = schedule.name || '';
            document.getElementById('schedule-collection-title').textContent = '✏️ Rename Schedule';
            const owner = String(schedule.owner || '').trim().toLowerCase();
            setScheduleCollectionMembers((schedule.members || []).filter(member => String(member || '').trim().toLowerCase() !== owner));
            const modal = document.getElementById('schedule-collection-modal');
            if (modal) modal.style.display = 'flex';
            setScheduleBodyLock();
            setTimeout(() => document.getElementById('schedule-collection-name')?.focus(), 0);
        }

        function closeScheduleCollectionModal(resetForm = true) {
            const modal = document.getElementById('schedule-collection-modal');
            if (modal) modal.style.display = 'none';
            if (resetForm) clearScheduleCollectionForm();
            setScheduleBodyLock();
        }

        function openScheduleCreateModal() {
            clearScheduleForm();
            // Pre-fill today's date and the next 30-minute slot
            const now = new Date();
            const dateField = document.getElementById('sch-date');
            if (dateField && !dateField.value) {
                dateField.value = formatScheduleDateKey(now);
            }
            const timeField = document.getElementById('sch-time');
            if (timeField && !timeField.value) {
                const next = new Date(now);
                next.setMinutes(Math.ceil(next.getMinutes() / SCHEDULE_SLOT_MINUTES) * SCHEDULE_SLOT_MINUTES, 0, 0);
                timeField.value = `${String(next.getHours()).padStart(2, '0')}:${String(next.getMinutes()).padStart(2, '0')}`;
            }
            void ensureScheduleGameFilterData();
            const modal = document.getElementById('schedule-modal');
            if (modal) modal.style.display = 'flex';
            setScheduleBodyLock();
            setTimeout(() => document.getElementById('sch-title')?.focus(), 0);
        }

        function closeScheduleModal(resetForm = true) {
            const modal = document.getElementById('schedule-modal');
            if (modal) modal.style.display = 'none';
            if (resetForm) clearScheduleForm();
            setScheduleBodyLock();
        }

        function closeScheduleCommonGamePicker() {
            const modal = document.getElementById('schedule-game-picker-modal');
            if (modal) modal.style.display = 'none';
            setScheduleBodyLock();
        }

        function closeScheduleIcalSyncModal() {
            const modal = document.getElementById('schedule-ical-modal');
            if (modal) modal.style.display = 'none';
            setScheduleBodyLock();
        }

        function getScheduleFilterBounds() {
            return {
                start: parseScheduleDateTimeInput(document.getElementById('schedule-filter-start')?.value),
                end: parseScheduleDateTimeInput(document.getElementById('schedule-filter-end')?.value),
            };
        }

        function hasScheduleFilters() {
            const { start, end } = getScheduleFilterBounds();
            return !!(start || end);
        }

        function eventMatchesScheduleFilters(event, bounds = getScheduleFilterBounds()) {
            if (!bounds.start && !bounds.end) return true;
            const eventStart = parseScheduleLocalDateTime(event?.date, event?.time);
            if (!eventStart) return false;
            if (bounds.start && eventStart < bounds.start) return false;
            if (bounds.end && eventStart > bounds.end) return false;
            return true;
        }

        function updateScheduleFilterSummary(filteredEvents) {
            const summary = document.getElementById('schedule-filter-summary');
            if (!summary) return;
            if (!hasScheduleFilters()) {
                summary.textContent = '';
                return;
            }
            summary.textContent = `${filteredEvents.length} of ${scheduleEventsCache.length} event${scheduleEventsCache.length === 1 ? '' : 's'} in range`;
        }

        function applyScheduleFilters() {
            scheduleFilteredEventsCache = scheduleEventsCache.filter(event => eventMatchesScheduleFilters(event));
            const bounds = getScheduleFilterBounds();
            if (bounds.start) {
                scheduleAgendaWeekStart = scheduleStartOfWeek(bounds.start);
            } else if (!scheduleAgendaWeekStart) {
                ensureScheduleAgendaWeek(scheduleFilteredEventsCache.length ? scheduleFilteredEventsCache : scheduleEventsCache);
            }
            updateScheduleFilterSummary(scheduleFilteredEventsCache);
            const { pendingInvites, acceptedEvents } = splitScheduleEventsByInviteState(scheduleFilteredEventsCache);
            renderSchedulePendingInvites(pendingInvites);
            renderScheduleList(acceptedEvents);
            renderScheduleAgenda(acceptedEvents);
            hydrateScheduleEventDetails(acceptedEvents);
        }

        function clearScheduleFilters() {
            scheduleAgendaWeekStart = scheduleStartOfWeek(new Date());
            setScheduleFiltersToAgendaWeek();
            applyScheduleFilters();
        }

        function renderScheduleSelector() {
            const selector = document.getElementById('schedule-selector');
            const renameButton = document.getElementById('schedule-rename-btn');
            const deleteButton = document.getElementById('schedule-delete-btn');
            const visibleSchedules = getFilteredScheduleCollections();
            if (!selector) return;
            if (!scheduleCollectionsCache.length) {
                selector.innerHTML = '<option value="">No schedules yet</option>';
                selector.value = '';
                activeScheduleId = '';
                if (renameButton) renameButton.disabled = true;
                 if (deleteButton) deleteButton.disabled = true;
                updateScheduleSidebarMeta([]);
                return;
            }
            if (!visibleSchedules.length) {
                selector.innerHTML = '<option value="">No matching schedules</option>';
                selector.value = '';
                if (renameButton) renameButton.disabled = !activeScheduleId;
                if (deleteButton) deleteButton.disabled = !activeScheduleId;
                updateScheduleSidebarMeta([]);
                return;
            }
            selector.innerHTML = visibleSchedules.map(schedule => {
                const members = Array.isArray(schedule.members) ? schedule.members : [];
                const memberSuffix = schedule.is_shared
                    ? ` · shared with ${Math.max(members.length - 1, 0)}`
                    : '';
                return `<option value="${escAttr(schedule.id || '')}">${escapeHtml(schedule.name || 'Schedule')}${escapeHtml(memberSuffix)}</option>`;
            }).join('');
            if (!activeScheduleId || !scheduleCollectionsCache.some(schedule => schedule.id === activeScheduleId)) {
                activeScheduleId = scheduleCollectionsCache[0].id || '';
            }
            selector.value = visibleSchedules.some(schedule => schedule.id === activeScheduleId) ? (activeScheduleId || '') : '';
            const active = getActiveSchedule();
            if (renameButton) renameButton.disabled = !active || !isOwnedSchedule(active);
            if (deleteButton) deleteButton.disabled = !active || !isOwnedSchedule(active) || isDefaultSchedule(active);
            updateScheduleSidebarMeta(visibleSchedules);
        }

        function changeActiveSchedule(scheduleId) {
            activeScheduleId = String(scheduleId || '').trim();
            clearAgendaSelection(false);
            loadSchedule();
        }

        async function loadSchedule() {
            const listDiv = document.getElementById('schedule-list');
            const pendingListDiv = document.getElementById('schedule-pending-list');
            const agendaDiv = document.getElementById('schedule-agenda');
            if (listDiv) listDiv.innerHTML = renderSkeletonList(5);
            if (pendingListDiv) pendingListDiv.innerHTML = renderSkeletonList(2);
            if (agendaDiv) agendaDiv.innerHTML = '<div class="loading">Loading agenda…</div>';
            try {
                const query = activeScheduleId ? `?schedule_id=${encodeURIComponent(activeScheduleId)}` : '';
                const resp = await fetch(`/api/schedule${query}`);
                if (!resp.ok) {
                    if (listDiv) listDiv.innerHTML = '<div class="error">Could not load schedule</div>';
                    if (pendingListDiv) pendingListDiv.innerHTML = '<div class="error">Could not load invites</div>';
                    if (agendaDiv) agendaDiv.innerHTML = '<div class="error">Could not load agenda</div>';
                    return;
                }
                const data = await resp.json();
                scheduleCollectionsCache = Array.isArray(data.schedules) ? data.schedules : scheduleCollectionsCache;
                activeScheduleId = String(data.active_schedule_id || activeScheduleId || '').trim();
                renderScheduleSelector();
                scheduleEventsCache = Array.isArray(data.events) ? data.events : [];
                if (!scheduleAgendaWeekStart) {
                    ensureScheduleAgendaWeek(scheduleEventsCache);
                }
                setScheduleFiltersToAgendaWeek();
                applyScheduleFilters();
            } catch (e) {
                if (listDiv) listDiv.innerHTML = `<div class="error">Error: ${e.message}</div>`;
                if (pendingListDiv) pendingListDiv.innerHTML = `<div class="error">Error: ${e.message}</div>`;
                if (agendaDiv) agendaDiv.innerHTML = `<div class="error">Error: ${e.message}</div>`;
            }
        }

        function renderScheduleList(events = []) {
            const listDiv = document.getElementById('schedule-list');
            if (!listDiv) return;
            if (!events.length) {
                listDiv.innerHTML = hasScheduleFilters()
                    ? '<div style="color:var(--text-secondary);padding:20px;">No events match the selected date/time filters.</div>'
                    : '<div style="color:var(--text-secondary);padding:20px;">No events scheduled yet. Use the agenda above or create one from the modal.</div>';
                return;
            }
            listDiv.innerHTML = events.map(ev => renderEventCard(ev)).join('');
        }

        function renderSchedulePendingInvites(events = []) {
            const listDiv = document.getElementById('schedule-pending-list');
            if (!listDiv) return;
            if (!events.length) {
                listDiv.innerHTML = '<div style="color:var(--text-secondary);padding:14px;">No pending invites.</div>';
                return;
            }
            listDiv.innerHTML = events.map(ev => {
                const title = escapeHtml(ev.title || 'Game Night');
                const game = escapeHtml(ev.game_name || 'No game selected');
                const timeLabel = escapeHtml(buildScheduleEventListTimeText(ev));
                return `
                    <div class="schedule-event-card pending-invite">
                        <div style="display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap;">
                            <strong>${title}</strong>
                            <span style="color:var(--text-secondary); font-size:0.85em;">${timeLabel}</span>
                        </div>
                        <div style="margin-top:6px; color:var(--text-secondary); font-size:0.88em;">🎮 ${game}</div>
                        <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
                            <button type="button" class="schedule-rsvp-btn active" onclick="submitScheduleRsvp('${escAttr(ev.id)}', 'accepted')">✅ Accept</button>
                            <button type="button" class="schedule-rsvp-btn" onclick="submitScheduleRsvp('${escAttr(ev.id)}', 'maybe')">❔ Maybe</button>
                            <button type="button" class="schedule-rsvp-btn" onclick="submitScheduleRsvp('${escAttr(ev.id)}', 'declined')">❌ Decline</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function submitScheduleRsvp(eventId, status) {
            try {
                const resp = await safeFetch(`/api/schedule/${eventId}/rsvp`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Could not update RSVP.', 'error');
                    return;
                }
                await loadSchedule();
                showMessage('RSVP updated.', 'success');
            } catch (error) {
                showMessage(`Error: ${error.message}`, 'error');
            }
        }

        function buildScheduleGameLinks(appId, gameName) {
            const id = String(appId || '').trim();
            const name = String(gameName || '').trim();
            return {
                steamUrl: id ? `https://store.steampowered.com/app/${id}/` : '',
                steamdbUrl: id ? `https://steamdb.info/app/${id}/` : '',
                keyshopUrl: name ? `https://www.allkeyshop.com/blog/catalogue/search/${encodeURIComponent(name)}/?results=50` : '',
            };
        }

        function hydrateScheduleEventDetails(events) {
            (events || []).forEach(async (ev) => {
                if (!ev || !ev.game_appid) return;
                const descEl = document.getElementById(`schedule-game-desc-${ev.id}`);
                if (!descEl) return;
                try {
                    const details = await loadGameDetailsAsync(ev.game_appid);
                    const description = (details?.description || '').trim();
                    descEl.textContent = description || 'No description available for this game yet.';
                } catch (err) {
                    descEl.textContent = 'No description available for this game yet.';
                }
            });
        }

        function renderEventCard(ev) {
            const attendees = Array.isArray(ev.attendees) ? ev.attendees : [];
            const safeTitle = escapeHtml(ev.title || 'Untitled Event');
            const safeGame = escapeHtml(ev.game_name || '');
            const safeNotes = escapeHtml(ev.notes || '');
            const safeAttendees = escapeHtml(attendees.join(', ') || 'No invitees yet');
            const links = buildScheduleGameLinks(ev.game_appid, ev.game_name || '');
            const timeLabel = escapeHtml(buildScheduleEventListTimeText(ev));
            const eventImageUrl = ev.game_image_url || (ev.game_appid ? `https://cdn.akamai.steamstatic.com/steam/apps/${ev.game_appid}/header.jpg` : '');
            const safeGameJs = escAttr(ev.game_name || '');
            const rsvpSummary = buildScheduleRsvpSummary(ev);
            const attendeeEntries = getScheduleEventRsvpEntries(ev)
                .filter(entry => entry.status === 'accepted')
                .map(entry => ({
                    ...entry,
                    initials: String(entry.name || '?').trim().charAt(0).toUpperCase() || '?',
                }));
            let gameImageHtml = '';
            if (eventImageUrl) {
                gameImageHtml = `<img src="${escAttr(eventImageUrl)}" alt="Game" style="max-width:100px; max-height:60px; border-radius:var(--radius-xs,6px); margin-right:10px; object-fit:cover;">`;
            }
            let discordBadge = '';
            if (ev.discord_event_id) {
                discordBadge = '<span style="margin-left:8px; padding:4px 8px; background:#5865F2; color:white; border-radius:var(--radius-tag,4px); font-size:0.8em;">📢 Discord Event</span>';
            }

            let discordLinkedInfo = '';
            if (ev.discord_event_id) {
                const guildId = String(ev.discord_guild_id || '').trim();
                const eventId = String(ev.discord_event_id || '').trim();
                const discordEventUrl = guildId && eventId ? `https://discord.com/events/${guildId}/${eventId}` : '';
                discordLinkedInfo = `
                    <div style="margin-top:8px; font-size:0.82em; color:var(--text-secondary); display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                        <span>🔗 Linked to Discord${guildId ? ` · Guild: ${guildId}` : ''}${eventId ? ` · Event: ${eventId}` : ''}</span>
                        ${discordEventUrl ? `<a href="${discordEventUrl}" target="_blank" style="color:#5865F2; text-decoration:none;">Open Event ↗</a>` : ''}
                    </div>
                `;
            }

            return `<div class="schedule-event-card" onclick="editScheduleEvent('${ev.id}')">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                    <div style="display:flex; align-items:center; flex:1; min-width:0;">
                        ${gameImageHtml}
                        <div style="flex:1; min-width:0;">
                            <strong style="font-size:1.1em;">${safeTitle}</strong>
                            ${safeGame ? `<span style="margin-left:8px; padding:2px 8px; background:var(--list-hover); border-radius:10px; font-size:0.85em;">🎮 ${safeGame}</span>` : ''}
                            ${discordBadge}
                        </div>
                    </div>
                    <div style="color:var(--text-secondary); font-size:0.9em; white-space:nowrap;">${timeLabel}</div>
                </div>
                <div style="margin-top:6px; color:var(--text-secondary); font-size:0.9em; display:flex; gap:12px; flex-wrap:wrap;">
                    <span>👥 ${safeAttendees}</span>
                    <span>⏱️ ${getScheduleEventDurationMinutes(ev)} min</span>
                    ${rsvpSummary ? `<span>✅ RSVP ${escapeHtml(rsvpSummary)}</span>` : ''}
                    ${safeNotes ? `<span>📝 ${safeNotes}</span>` : ''}
                </div>
                ${attendeeEntries.length ? `
                <div class="schedule-event-status-row">
                    ${attendeeEntries.map(entry => `
                        <span class="schedule-attendee-pill">
                            <span class="schedule-attendee-avatar">${escapeHtml(entry.initials)}</span>
                            <span>${escapeHtml(entry.name)}</span>
                            <span class="schedule-rsvp-chip ${escAttr(entry.status)}">${escapeHtml(entry.status)}</span>
                        </span>
                    `).join('')}
                </div>` : ''}
                ${discordLinkedInfo}
                ${ev.game_appid ? `
                <div style="margin-top:8px; padding:10px; background:var(--list-hover); border-radius:var(--radius-sm,8px);">
                    <div id="schedule-game-desc-${ev.id}" style="font-size:0.9em; line-height:1.5; color:var(--text-primary);">
                        Loading game description...
                    </div>
                    <div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;">
                        ${links.steamUrl ? `<a href="${links.steamUrl}" target="_blank" onclick="event.stopPropagation()" style="padding:5px 10px; background:#000; color:white; text-decoration:none; border-radius:var(--radius-xs,6px); font-size:0.8em;">🔗 Steam Store</a>` : ''}
                        ${links.steamdbUrl ? `<a href="${links.steamdbUrl}" target="_blank" onclick="event.stopPropagation()" style="padding:5px 10px; background:#213956; color:white; text-decoration:none; border-radius:var(--radius-xs,6px); font-size:0.8em;">📊 SteamDB</a>` : ''}
                        ${links.keyshopUrl ? `<a href="${links.keyshopUrl}" target="_blank" onclick="event.stopPropagation()" style="padding:5px 10px; background:#1F1F1F; color:#FFD700; text-decoration:none; border-radius:var(--radius-xs,6px); font-size:0.8em;">💰 AllKeyShop</a>` : ''}
                    </div>
                </div>` : ''}
                <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
                    <button onclick="event.stopPropagation(); editScheduleEvent('${ev.id}')" style="padding:5px 14px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em;">✏️ Edit</button>
                    <button onclick="event.stopPropagation(); focusScheduleInviteField('${ev.id}')" style="padding:5px 14px; background:#10b981; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em;">👥 Invite</button>
                    ${!ev.discord_event_id && ev.game_appid ? `<button onclick="event.stopPropagation(); createDiscordEventForSchedule('${ev.id}', '${safeGameJs}')" style="padding:5px 14px; background:#5865F2; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em;">📢 Create Discord Event</button>` : ''}
                    <button onclick="event.stopPropagation(); deleteScheduleEvent('${ev.id}', ${ev.discord_event_id ? 'true' : 'false'}, '${escAttr(ev.discord_guild_id || '')}')" style="padding:5px 14px; background:#ef4444; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em;">🗑️ Delete</button>
                </div>
            </div>`;
        }

        function renderScheduleAgenda(events = []) {
            const agenda = document.getElementById('schedule-agenda');
            const range = document.getElementById('schedule-agenda-range');
            if (!agenda) return;
            const days = getScheduleAgendaDays();
            const dayKeys = new Set(days.map(formatScheduleDateKey));
            const eventsByDate = new Map(days.map(day => [formatScheduleDateKey(day), []]));
            (events || []).forEach(event => {
                const key = String(event?.date || '').trim();
                if (dayKeys.has(key)) eventsByDate.get(key).push(event);
            });
            if (range) range.textContent = formatScheduleAgendaRange(days);
            const timeLabels = Array.from({ length: 48 }, (_, slotIndex) => (
                `<div class="schedule-agenda-time-label">${scheduleSlotIndexToTime(slotIndex)}</div>`
            )).join('');
            agenda.innerHTML = `
                <div class="schedule-agenda-board">
                    <div class="schedule-agenda-times">
                        <div class="schedule-agenda-times-spacer"></div>
                        ${timeLabels}
                    </div>
                    ${days.map(day => renderScheduleAgendaDay(day, eventsByDate.get(formatScheduleDateKey(day)) || [])).join('')}
                </div>
            `;
            setupScheduleAgendaInteractions();
            syncAgendaSelectionState();
        }

        function renderScheduleAgendaDay(day, dayEvents) {
            const dateKey = formatScheduleDateKey(day);
            const slots = Array.from({ length: 48 }, (_, slotIndex) => (
                `<div class="schedule-agenda-slot" data-date="${dateKey}" data-slot-index="${slotIndex}" data-time="${scheduleSlotIndexToTime(slotIndex)}"></div>`
            )).join('');
            return `
                <div class="schedule-agenda-day" data-date="${dateKey}">
                    <div class="schedule-agenda-day-header">
                        <strong>${day.toLocaleDateString([], { weekday: 'short' })}</strong>
                        <span>${day.toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>
                    </div>
                    <div class="schedule-agenda-day-body">
                        <div class="schedule-agenda-slot-grid">${slots}</div>
                        <div class="schedule-agenda-item-layer">${dayEvents.map(renderScheduleAgendaEvent).join('')}</div>
                    </div>
                </div>
            `;
        }

        function renderScheduleAgendaEvent(event) {
            const start = parseScheduleLocalDateTime(event?.date, event?.time);
            if (!start) return '';
            const slotIndex = Math.max(0, Math.min(47, Math.round((start.getHours() * 60 + start.getMinutes()) / SCHEDULE_SLOT_MINUTES)));
            const duration = getScheduleEventDurationMinutes(event);
            const top = slotIndex * SCHEDULE_SLOT_HEIGHT + 2;
            const height = Math.max((duration / SCHEDULE_SLOT_MINUTES) * SCHEDULE_SLOT_HEIGHT - 4, SCHEDULE_SLOT_HEIGHT - 4);
            const attendees = Array.isArray(event.attendees) ? event.attendees : [];
            return `
                <div class="schedule-agenda-item" draggable="true" data-event-id="${escAttr(event.id)}" style="top:${top}px; height:${height}px;" title="${escapeHtml(event.title || 'Event')} • ${escapeHtml(buildScheduleEventAgendaTimeText(event))}">
                    <div class="schedule-agenda-item-time">${escapeHtml(buildScheduleEventAgendaTimeText(event))}</div>
                    <div class="schedule-agenda-item-title">${escapeHtml(event.title || 'Untitled Event')}</div>
                    <div class="schedule-agenda-item-meta">${escapeHtml((event.game_name || attendees.join(', ')) || 'Click to edit or invite people')}</div>
                </div>
            `;
        }

        function setupScheduleAgendaInteractions() {
            const agenda = document.getElementById('schedule-agenda');
            if (!agenda || agenda.dataset.bound === 'true') return;
            agenda.dataset.bound = 'true';
            agenda.addEventListener('pointerdown', handleScheduleAgendaPointerDown);
            agenda.addEventListener('pointerover', handleScheduleAgendaPointerOver);
            agenda.addEventListener('click', handleScheduleAgendaClick);
            agenda.addEventListener('dragstart', handleScheduleAgendaDragStart);
            agenda.addEventListener('dragover', handleScheduleAgendaDragOver);
            agenda.addEventListener('drop', handleScheduleAgendaDrop);
            agenda.addEventListener('dragend', handleScheduleAgendaDragEnd);
        }

        function syncAgendaSelectionState(resetQuickFields = false) {
            const agenda = document.getElementById('schedule-agenda');
            const quickCreate = document.getElementById('schedule-agenda-quick-create');
            const summary = getAgendaSelectionSummary();
            if (agenda) {
                agenda.querySelectorAll('.schedule-agenda-slot').forEach(slot => {
                    const matches = !!summary
                        && slot.dataset.date === summary.date
                        && Number(slot.dataset.slotIndex) >= summary.startSlot
                        && Number(slot.dataset.slotIndex) <= summary.endSlot;
                    slot.classList.toggle('schedule-agenda-slot-selection', matches);
                });
            }
            if (!quickCreate) return;
            if (!summary) {
                quickCreate.hidden = true;
                return;
            }
            quickCreate.hidden = false;
            const label = document.getElementById('schedule-agenda-selection-label');
            const meta = document.getElementById('schedule-agenda-selection-meta');
            if (label) label.textContent = `New event for ${summary.label}`;
            if (meta) meta.textContent = summary.meta;
        }

        function clearAgendaSelection(resetQuickFields = true) {
            scheduleAgendaSelection = null;
            scheduleAgendaSelectionActive = false;
            syncAgendaSelectionState(resetQuickFields);
        }

        function handleScheduleAgendaPointerDown(event) {
            if (event.target.closest('.schedule-agenda-item')) return;
            const slot = event.target.closest('.schedule-agenda-slot');
            if (!slot) return;
            event.preventDefault();
            scheduleAgendaSelectionActive = true;
            scheduleAgendaSelection = {
                date: slot.dataset.date,
                startSlot: Number(slot.dataset.slotIndex),
                endSlot: Number(slot.dataset.slotIndex),
            };
            syncAgendaSelectionState();
            document.addEventListener('pointerup', finishScheduleAgendaSelection, { once: true });
        }

        function handleScheduleAgendaPointerOver(event) {
            if (!scheduleAgendaSelectionActive || !scheduleAgendaSelection) return;
            const slot = event.target.closest('.schedule-agenda-slot');
            if (!slot || slot.dataset.date !== scheduleAgendaSelection.date) return;
            scheduleAgendaSelection.endSlot = Number(slot.dataset.slotIndex);
            syncAgendaSelectionState();
        }

        function finishScheduleAgendaSelection() {
            if (!scheduleAgendaSelectionActive) return;
            scheduleAgendaSelectionActive = false;
            syncAgendaSelectionState();
            document.getElementById('schedule-agenda-create-btn')?.focus();
        }

        function handleScheduleAgendaClick(event) {
            const item = event.target.closest('.schedule-agenda-item');
            if (!item || scheduleAgendaDraggedEventId) return;
            editScheduleEvent(item.dataset.eventId);
        }

        function clearScheduleAgendaDropTargets() {
            const agenda = document.getElementById('schedule-agenda');
            if (!agenda) return;
            agenda.querySelectorAll('.schedule-agenda-slot-active').forEach(slot => slot.classList.remove('schedule-agenda-slot-active'));
        }

        function handleScheduleAgendaDragStart(event) {
            const item = event.target.closest('.schedule-agenda-item');
            if (!item) return;
            scheduleAgendaDraggedEventId = item.dataset.eventId;
            item.classList.add('dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', scheduleAgendaDraggedEventId);
            }
        }

        function handleScheduleAgendaDragOver(event) {
            const slot = event.target.closest('.schedule-agenda-slot');
            if (!slot || !scheduleAgendaDraggedEventId) return;
            event.preventDefault();
            clearScheduleAgendaDropTargets();
            slot.classList.add('schedule-agenda-slot-active');
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        }

        async function handleScheduleAgendaDrop(event) {
            const slot = event.target.closest('.schedule-agenda-slot');
            if (!slot) return;
            const eventId = scheduleAgendaDraggedEventId || event.dataTransfer?.getData('text/plain');
            clearScheduleAgendaDropTargets();
            if (!eventId) return;
            event.preventDefault();
            const existing = scheduleEventsCache.find(item => item.id === eventId);
            if (!existing) return;
            await updateScheduleEvent(eventId, {
                date: slot.dataset.date,
                time: slot.dataset.time,
                duration_minutes: getScheduleEventDurationMinutes(existing),
            }, 'Event moved on the agenda.');
        }

        function handleScheduleAgendaDragEnd(event) {
            clearScheduleAgendaDropTargets();
            const item = event.target.closest('.schedule-agenda-item');
            if (item) item.classList.remove('dragging');
            scheduleAgendaDraggedEventId = null;
        }

        function changeScheduleAgendaWeek(offset) {
            ensureScheduleAgendaWeek(scheduleFilteredEventsCache.length ? scheduleFilteredEventsCache : scheduleEventsCache);
            const nextWeek = new Date(scheduleAgendaWeekStart);
            nextWeek.setDate(nextWeek.getDate() + offset * 7);
            scheduleAgendaWeekStart = scheduleStartOfWeek(nextWeek);
            setScheduleFiltersToAgendaWeek();
            clearAgendaSelection(false);
            applyScheduleFilters();
        }

        function goToCurrentScheduleAgendaWeek() {
            scheduleAgendaWeekStart = scheduleStartOfWeek(new Date());
            setScheduleFiltersToAgendaWeek();
            clearAgendaSelection(false);
            applyScheduleFilters();
        }

        function applyAgendaSelectionToForm() {
            const summary = getAgendaSelectionSummary();
            if (!summary) return;
            openScheduleCreateModal();
            document.getElementById('sch-date').value = summary.date;
            document.getElementById('sch-time').value = summary.startTime;
            document.getElementById('sch-duration').value = summary.durationMinutes;
            document.getElementById('sch-title').focus();
            clearAgendaSelection(false);
        }

        async function updateScheduleEvent(eventId, payload, successMessage = 'Event updated.') {
            try {
                const resp = await safeFetch(`/api/schedule/${eventId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) {
                    const errorData = await resp.json();
                    showMessage(errorData.error || 'Failed to update event', 'error');
                    return null;
                }
                const updated = await resp.json();
                await loadSchedule();
                if (successMessage) showMessage(successMessage, 'success');
                return updated;
            } catch (error) {
                showMessage(`Error: ${error.message}`, 'error');
                return null;
            }
        }

        function toggleDiscordGuildField() {
            const checkbox = document.getElementById('sch-create-discord');
            const field = document.getElementById('discord-guild-field');
            if (!checkbox || !field) return;
            if (checkbox.checked) {
                field.style.display = 'block';
                loadScheduleDiscordGuilds();
                updateScheduleDiscordGuildMeta();
            } else {
                field.style.display = 'none';
            }
        }

        async function submitScheduleForm() {
            const editId = document.getElementById('schedule-edit-id').value;
            const title = document.getElementById('sch-title').value.trim();
            if (!title) { alert('Title is required'); return; }
            const createDiscord = document.getElementById('sch-create-discord').checked;
            const guildId = document.getElementById('sch-discord-guild-id').value.trim();
            if (createDiscord && !guildId) {
                alert('Please choose a Discord server from the autocomplete list.');
                return;
            }
            const body = {
                title,
                date: document.getElementById('sch-date').value,
                time: document.getElementById('sch-time').value,
                duration_minutes: normalizeScheduleDurationMinutes(document.getElementById('sch-duration').value),
                attendees: getScheduleEventAttendees(),
                attendee_ids: getScheduleEventAttendeeIds(),
                game_name: document.getElementById('sch-game').value.trim(),
                game_appid: document.getElementById('sch-game-appid').value,
                game_image_url: document.getElementById('sch-game-image-url').value,
                schedule_id: activeScheduleId || null,
                notes: document.getElementById('sch-notes').value.trim(),
                create_discord_event: createDiscord,
                discord_guild_id: guildId || null,
                timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
                timezone_offset_minutes: new Date().getTimezoneOffset(),
            };
            if (!editId) {
                body.rsvp_statuses = getScheduleRsvpValues();
            }
            try {
                let resp;
                if (editId) {
                    resp = await safeFetch(`/api/schedule/${editId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                } else {
                    resp = await safeFetch('/api/schedule', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                }
                if (!resp.ok) { const d = await resp.json(); alert(d.error || 'Failed to save event'); return; }
                // Navigate the agenda to the week containing the saved event
                if (body.date) {
                    const eventDate = parseScheduleLocalDateTime(body.date);
                    if (eventDate) scheduleAgendaWeekStart = scheduleStartOfWeek(eventDate);
                }
                closeScheduleModal(true);
                await loadSchedule();
                showMessage(editId ? 'Event updated.' : 'Event created.', 'success');
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function submitScheduleCollectionForm() {
            const editId = document.getElementById('schedule-collection-edit-id').value.trim();
            const name = document.getElementById('schedule-collection-name').value.trim();
            if (!name) {
                showMessage('Schedule name is required.', 'warning');
                document.getElementById('schedule-collection-name')?.focus();
                return;
            }
            const members = getScheduleCollectionMembers();
            const body = {
                name,
                members,
                is_shared: members.length > 0,
            };
            try {
                const resp = await safeFetch(editId ? `/api/schedules/${encodeURIComponent(editId)}` : '/api/schedules', {
                    method: editId ? 'PUT' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Could not save schedule.', 'error');
                    return;
                }
                activeScheduleId = data.id || activeScheduleId;
                closeScheduleCollectionModal(true);
                await loadSchedule();
                showMessage(editId ? 'Schedule updated.' : `Created schedule: ${data.name || 'New schedule'}`, 'success');
            } catch (error) {
                showMessage(`Error: ${error.message}`, 'error');
            }
        }

        async function deleteActiveSchedule() {
            const active = getActiveSchedule();
            if (!active) return;
            if (isDefaultSchedule(active)) {
                showMessage('Your personal schedule cannot be deleted.', 'warning');
                return;
            }
            if (!isOwnedSchedule(active)) {
                showMessage('Only the schedule owner can delete it.', 'warning');
                return;
            }
            if (!confirm(`Delete schedule "${active.name}" and all of its events?`)) return;
            try {
                const resp = await safeFetch(`/api/schedules/${encodeURIComponent(active.id)}`, { method: 'DELETE' });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to delete schedule.', 'error');
                    return;
                }
                activeScheduleId = '';
                await loadSchedule();
                showMessage('Schedule deleted.', 'success');
            } catch (error) {
                showMessage(`Error deleting schedule: ${error.message}`, 'error');
            }
        }

        function buildScheduleGameLookupKeys(game) {
            const keys = [];
            const appId = String(game?.appid || game?.app_id || '').trim();
            const gameId = String(game?.game_id || '').trim().toLowerCase();
            if (appId) keys.push(appId);
            if (gameId) keys.push(gameId);
            return keys;
        }

        function getScheduleGameFromLibrary(game) {
            const keys = buildScheduleGameLookupKeys(game);
            for (const key of keys) {
                if (scheduleGameLibraryById.has(key)) return scheduleGameLibraryById.get(key);
            }
            return null;
        }

        function getScheduleGameBacklogCollectionIds(game) {
            const keys = buildScheduleGameLookupKeys(game);
            const ids = new Set();
            keys.forEach(key => {
                const values = scheduleGameBacklogIndex.get(key) || [];
                values.forEach(value => ids.add(value));
            });
            return Array.from(ids);
        }

        async function ensureScheduleGameLibraryCache(force = false) {
            if (!force && scheduleGameLibraryCache.length) return scheduleGameLibraryCache;
            const resp = await safeFetch('/api/library');
            const data = await resp.json();
            scheduleGameLibraryCache = Array.isArray(data.games) ? data.games : [];
            scheduleGameLibraryById = new Map();
            scheduleGameFavoriteIds = new Set();
            scheduleGameLibraryCache.forEach(game => {
                const appId = String(game.app_id || game.appid || '').trim();
                const gameId = String(game.game_id || '').trim().toLowerCase();
                if (appId) scheduleGameLibraryById.set(appId, game);
                if (gameId) scheduleGameLibraryById.set(gameId, game);
                if (game.is_favorite && appId) scheduleGameFavoriteIds.add(appId);
            });
            return scheduleGameLibraryCache;
        }

        async function ensureScheduleGameBacklogFilterCache(force = false) {
            if (!force && scheduleGameFilterCacheReady) {
                return scheduleBacklogCollectionChoices;
            }
            const collectionsResp = await safeFetch('/api/backlogs');
            const collectionsData = await collectionsResp.json();
            scheduleBacklogCollectionChoices = Array.isArray(collectionsData.backlogs) ? collectionsData.backlogs : [];
            scheduleGameBacklogIndex = new Map();
            await Promise.all(scheduleBacklogCollectionChoices.map(async backlog => {
                const collectionId = String(backlog.id || '').trim();
                if (!collectionId) return;
                try {
                    const resp = await safeFetch(`/api/backlog?collection_id=${encodeURIComponent(collectionId)}`);
                    const data = await resp.json();
                    const games = Array.isArray(data.games) ? data.games : [];
                    games.forEach(game => {
                        buildScheduleGameLookupKeys(game).forEach(key => {
                            if (!key) return;
                            const current = scheduleGameBacklogIndex.get(key) || [];
                            if (!current.includes(collectionId)) current.push(collectionId);
                            scheduleGameBacklogIndex.set(key, current);
                        });
                    });
                } catch (error) {
                    console.warn('Schedule backlog filter cache failed:', error.message);
                }
            }));
            scheduleGameFilterCacheReady = true;
            return scheduleBacklogCollectionChoices;
        }

        async function ensureScheduleGameFilterData(force = false) {
            await Promise.all([
                ensureScheduleGameLibraryCache(force),
                ensureScheduleGameBacklogFilterCache(force),
            ]);
            const listSelect = document.getElementById('sch-game-list-filter');
            if (listSelect) {
                const currentValue = listSelect.value || '';
                listSelect.innerHTML = `<option value="">Any list</option>${scheduleBacklogCollectionChoices.map(backlog => `
                    <option value="${escAttr(backlog.id || '')}">${escapeHtml(backlog.name || 'List')}</option>
                `).join('')}`;
                listSelect.value = scheduleBacklogCollectionChoices.some(backlog => String(backlog.id || '') === currentValue) ? currentValue : '';
            }
            const platformSelect = document.getElementById('sch-game-platform-filter');
            if (platformSelect) {
                const currentValue = platformSelect.value || '';
                const platforms = Array.from(new Set(scheduleGameLibraryCache
                    .map(game => normalisePlatformKey(game.platform))
                    .filter(Boolean))).sort();
                platformSelect.innerHTML = `<option value="">Any platform</option>${platforms.map(platform => `
                    <option value="${escAttr(platform)}">${escapeHtml(platform.charAt(0).toUpperCase() + platform.slice(1))}</option>
                `).join('')}`;
                platformSelect.value = platforms.includes(currentValue) ? currentValue : '';
            }
        }

        function filterScheduleSearchResults(results) {
            const listFilter = String(document.getElementById('sch-game-list-filter')?.value || '').trim();
            const platformFilter = normalisePlatformKey(document.getElementById('sch-game-platform-filter')?.value || '');
            const genreFilter = String(document.getElementById('sch-game-genre-filter')?.value || '').trim().toLowerCase();
            const minPlaytimeValue = parseFloat(document.getElementById('sch-game-min-playtime')?.value || '');
            const maxPlaytimeValue = parseFloat(document.getElementById('sch-game-max-playtime')?.value || '');
            const favoritesOnly = !!document.getElementById('sch-game-favorites-only')?.checked;
            return (results || []).filter(game => {
                const collectionIds = Array.isArray(game.list_ids) ? game.list_ids : [];
                if (listFilter && !collectionIds.includes(listFilter)) return false;
                const platform = normalisePlatformKey(game.platform || '');
                if (platformFilter && platform !== platformFilter) return false;
                const genres = Array.isArray(game.genres) ? game.genres : [];
                if (genreFilter && !genres.some(genre => String(genre || '').toLowerCase().includes(genreFilter))) return false;
                const playtime = Number(game.playtime_hours || 0);
                if (Number.isFinite(minPlaytimeValue) && playtime < minPlaytimeValue) return false;
                if (Number.isFinite(maxPlaytimeValue) && playtime > maxPlaytimeValue) return false;
                if (favoritesOnly && !game.is_favorite) return false;
                return true;
            });
        }

        function renderScheduleGameSearchResults(results) {
            const dropdown = document.getElementById('game-search-dropdown');
            if (!dropdown) return;
            if (!results.length) {
                dropdown.innerHTML = '<div style="padding:10px; color:var(--text-secondary);">No games match your filters</div>';
                dropdown.style.display = 'block';
                return;
            }
            dropdown.innerHTML = results.map(game => `
                <div class="game-search-result" data-appid="${escAttr(game.appid || '')}" data-name="${escAttr(game.name || '')}" data-image-url="${escAttr(game.image_url || '')}"
                     style="padding:10px; cursor:pointer; border-bottom:1px solid var(--card-border); display:flex; align-items:center; gap:8px; transition:background 0.2s;">
                    ${game.image_url ? `<img src="${escAttr(game.image_url)}" alt="" style="width:40px; height:24px; object-fit:cover; border-radius:var(--radius-tag,4px);">` : ''}
                    <div style="min-width:0;">
                        <strong>${escapeHtml(game.name || '')}</strong>
                        <div style="font-size:0.8em; color:var(--text-secondary); margin-top:2px;">
                            <span>App ID: ${escapeHtml(String(game.appid || ''))}</span>
                            ${game.playtime_hours ? `<span> · ${escapeHtml(String(game.playtime_hours))}h</span>` : ''}
                            ${game.platform ? `<span> · ${escapeHtml(String(game.platform))}</span>` : ''}
                            ${game.is_favorite ? '<span> · ⭐ favorite</span>' : ''}
                        </div>
                    </div>
                </div>
            `).join('');
            dropdown.querySelectorAll('.game-search-result').forEach(el => {
                el.onclick = () => selectGame(el.dataset.appid, el.dataset.name, el.dataset.imageUrl);
            });
            dropdown.style.display = 'block';
        }

        function applyScheduleGameFilters() {
            const query = document.getElementById('sch-game')?.value.trim() || '';
            const dropdown = document.getElementById('game-search-dropdown');
            if (!query || query.length < 2 || !dropdown) return;
            const filteredResults = filterScheduleSearchResults(scheduleGameSearchCache);
            renderScheduleGameSearchResults(filteredResults);
        }

        function resetScheduleGameFilters() {
            const ids = [
                'sch-game-list-filter',
                'sch-game-platform-filter',
                'sch-game-genre-filter',
                'sch-game-min-playtime',
                'sch-game-max-playtime'
            ];
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            const favoritesOnly = document.getElementById('sch-game-favorites-only');
            if (favoritesOnly) favoritesOnly.checked = false;
            applyScheduleGameFilters();
        }

        let gameSearchTimeout;
        async function searchGames(query) {
            clearTimeout(gameSearchTimeout);
            if (!query || query.length < 2) {
                document.getElementById('game-search-dropdown').style.display = 'none';
                return;
            }

            gameSearchTimeout = setTimeout(async () => {
                try {
                    await ensureScheduleGameFilterData();
                    const resp = await fetch('/api/schedule/search-games', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({query: query, limit: 25})
                    });
                    if (!resp.ok) return;
                    const data = await resp.json();
                    const baseResults = Array.isArray(data.results) ? data.results : [];
                    scheduleGameSearchCache = baseResults.map(game => {
                        const libraryGame = getScheduleGameFromLibrary(game) || {};
                        const listIds = getScheduleGameBacklogCollectionIds(game);
                        const appId = String(game.appid || game.app_id || '').trim();
                        return {
                            ...game,
                            appid: appId,
                            platform: game.platform || libraryGame.platform || '',
                            playtime_hours: game.playtime_hours ?? libraryGame.playtime_hours ?? 0,
                            genres: Array.isArray(game.genres) ? game.genres : [],
                            is_favorite: Boolean(game.is_favorite ?? libraryGame.is_favorite ?? (appId ? scheduleGameFavoriteIds.has(appId) : false)),
                            list_ids: listIds,
                        };
                    });
                    const filteredResults = filterScheduleSearchResults(scheduleGameSearchCache);
                    renderScheduleGameSearchResults(filteredResults);
                } catch (e) {
                    console.error('Game search error:', e);
                }
            }, 300);
        }

        function showGameSearch() {
            const query = document.getElementById('sch-game').value.trim();
            if (query.length >= 2) {
                searchGames(query);
            }
        }

        function selectGame(appid, name, imageUrl) {
            document.getElementById('sch-game').value = name;
            document.getElementById('sch-game-appid').value = appid;
            const fallbackImageUrl = imageUrl || (appid ? `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg` : '');
            document.getElementById('sch-game-image-url').value = fallbackImageUrl;
            document.getElementById('game-search-dropdown').style.display = 'none';
        }

        async function searchScheduleMembers(query) {
            clearTimeout(scheduleMemberSearchTimeout);
            if (!query || query.length < 1) {
                document.getElementById('schedule-collection-members-dropdown').style.display = 'none';
                return;
            }

            scheduleMemberSearchTimeout = setTimeout(async () => {
                try {
                    const resp = await fetch('/api/schedule/search-attendees', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({query: query, limit: 10})
                    });
                    if (!resp.ok) return;
                    const data = await resp.json();
                    const dropdown = document.getElementById('schedule-collection-members-dropdown');
                    if (!dropdown) return;
                    if (!data.results || data.results.length === 0) {
                        dropdown.innerHTML = '<div style="padding:10px; color:var(--text-secondary);">No people found</div>';
                        dropdown.style.display = 'block';
                        return;
                    }
                    const selectedMembers = new Set(getScheduleCollectionMembers().map(member => member.toLowerCase()));
                    dropdown.innerHTML = data.results.map(user => {
                        const safeName = String(user.name || '').trim();
                        const isSelected = selectedMembers.has(safeName.toLowerCase());
                        return `
                            <div class="attendee-search-result" data-name="${escAttr(safeName)}"
                                 style="padding:10px; cursor:pointer; border-bottom:1px solid var(--card-border); width:100%; opacity:${isSelected ? '0.6' : '1'};">
                                <strong>${escapeHtml(safeName)}</strong>
                                ${isSelected ? '<span style="margin-left:8px; color:var(--text-secondary); font-size:0.82em;">Added</span>' : ''}
                            </div>
                        `;
                    }).join('');
                    dropdown.querySelectorAll('.attendee-search-result').forEach(el => {
                        el.onclick = () => addScheduleCollectionMember(el.dataset.name);
                    });
                    dropdown.style.display = 'block';
                } catch (error) {
                    console.error('Schedule member search error:', error);
                }
            }, 300);
        }

        function showScheduleMemberSearch() {
            const query = document.getElementById('schedule-collection-members')?.value.trim() || '';
            if (query.length >= 1) {
                searchScheduleMembers(query);
            }
        }

        function addScheduleCollectionMember(name) {
            const current = getScheduleCollectionMembers();
            current.push(name);
            setScheduleCollectionMembers(current);
            const dropdown = document.getElementById('schedule-collection-members-dropdown');
            if (dropdown) dropdown.style.display = 'none';
            const searchField = document.getElementById('schedule-collection-members');
            if (searchField) {
                searchField.value = '';
                searchField.focus();
            }
        }

        function removeScheduleCollectionMember(name) {
            setScheduleCollectionMembers(getScheduleCollectionMembers().filter(member => member.toLowerCase() !== String(name || '').trim().toLowerCase()));
        }

        let attendeeSearchTimeout;
        async function searchAttendees(query) {
            clearTimeout(attendeeSearchTimeout);
            if (!query || query.length < 1) {
                document.getElementById('attendee-search-dropdown').style.display = 'none';
                return;
            }

            attendeeSearchTimeout = setTimeout(async () => {
                try {
                    const resp = await fetch('/api/schedule/search-attendees', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({query: query, limit: 10})
                    });
                    if (!resp.ok) return;
                    const data = await resp.json();
                    const dropdown = document.getElementById('attendee-search-dropdown');
                    if (!data.results || data.results.length === 0) {
                        dropdown.innerHTML = '<div style="padding:10px; color:var(--text-secondary);">No friends found</div>';
                        dropdown.style.display = 'block';
                        return;
                    }
                    const selectedIds = new Set(getScheduleEventAttendeeIds());
                    dropdown.innerHTML = data.results.map(user => {
                        const isSelected = selectedIds.has(user.id || user.name);
                        return `
                            <div class="attendee-search-result" data-name="${escAttr(user.name || '')}" data-id="${escAttr(user.id || user.name || '')}"
                                 style="padding:10px; cursor:pointer; border-bottom:1px solid var(--card-border); width:100%; opacity:${isSelected ? '0.6' : '1'};">
                                <strong>${escapeHtml(user.name || '')}</strong>
                                ${isSelected ? '<span style="margin-left:8px; color:var(--text-secondary); font-size:0.82em;">Added</span>' : ''}
                            </div>
                        `;
                    }).join('');
                    dropdown.querySelectorAll('.attendee-search-result').forEach(el => {
                        el.onclick = () => addAttendee(el.dataset.name, el.dataset.id);
                    });
                    dropdown.style.display = 'block';
                } catch (e) {
                    console.error('Attendee search error:', e);
                }
            }, 300);
        }

        function showAttendeeSearch() {
            const query = document.getElementById('sch-attendees').value.trim();
            if (query.length >= 1) {
                searchAttendees(query);
            }
        }

        function addAttendee(name, id = name) {
            const current = getScheduleSelectedAttendees();
            current.push({ name, id: id || name });
            setScheduleSelectedAttendees(current);
            document.getElementById('attendee-search-dropdown').style.display = 'none';
            const searchField = document.getElementById('sch-attendees');
            if (searchField) {
                searchField.value = '';
                searchField.focus();
            }
        }

        function updateAttendeeTagsDisplay() {
            const tags = document.getElementById('attendee-tags');
            if (!tags) return;
            const attendees = getScheduleSelectedAttendees();
            tags.innerHTML = attendees.map(attendee => `
                <span style="padding:4px 10px; background:#4f46e5; color:white; border-radius:var(--radius-lg,16px); font-size:0.85em; display:inline-flex; align-items:center; gap:6px;">
                    ${escapeHtml(attendee.name)}
                    <button type="button" onclick="removeAttendee('${escAttr(attendee.id)}')" style="background:none; border:none; color:white; cursor:pointer; padding:0; font-size:1em; line-height:1;">×</button>
                </span>
            `).join('');
        }

        function removeAttendee(attendeeId) {
            setScheduleSelectedAttendees(getScheduleSelectedAttendees().filter(attendee => attendee.id !== attendeeId));
        }

        async function focusScheduleInviteField(id) {
            const event = await editScheduleEvent(id);
            if (!event) return;
            const searchField = document.getElementById('sch-attendees');
            if (searchField) {
                searchField.focus();
                showMessage('Search for friends to invite, then save the event. Invitees update their own RSVP status.', 'info');
            }
        }

        async function loadScheduleDiscordGuilds(force = false) {
            if (scheduleDiscordGuildsCache.length && !force) return scheduleDiscordGuildsCache;
            try {
                const resp = await safeFetch('/api/schedule/discord-guilds');
                const data = await resp.json();
                scheduleDiscordGuildsCache = Array.isArray(data.guilds) ? data.guilds : [];
            } catch (error) {
                scheduleDiscordGuildsCache = [];
            }
            return scheduleDiscordGuildsCache;
        }

        function updateScheduleDiscordGuildMeta() {
            const meta = document.getElementById('schedule-discord-guild-meta');
            const guildId = document.getElementById('sch-discord-guild-id')?.value || '';
            const selected = scheduleDiscordGuildsCache.find(guild => guild.guild_id === guildId);
            if (!meta) return;
            if (!guildId) {
                meta.textContent = scheduleDiscordGuildsCache.length
                    ? 'Choose one of your cached Discord servers to sync this event.'
                    : 'No cached Discord servers found yet. Talk to the bot in your server first.';
                return;
            }
            meta.textContent = selected
                ? `Selected server: ${selected.guild_name} (${selected.guild_id})`
                : `Selected server ID: ${guildId}`;
        }

        async function showScheduleDiscordGuildSearch() {
            const dropdown = document.getElementById('discord-guild-search-dropdown');
            const input = document.getElementById('sch-discord-guild-search');
            if (!dropdown || !input) return;
            const guilds = await loadScheduleDiscordGuilds();
            const query = input.value.trim().toLowerCase();
            const filtered = guilds.filter(guild => {
                if (!query) return true;
                return String(guild.guild_name || '').toLowerCase().includes(query)
                    || String(guild.guild_id || '').toLowerCase().includes(query);
            });
            if (!filtered.length) {
                dropdown.innerHTML = '<div style="padding:10px; color:var(--text-secondary);">No Discord servers found</div>';
                dropdown.style.display = 'block';
                updateScheduleDiscordGuildMeta();
                return;
            }
            dropdown.innerHTML = filtered.map(guild => `
                <div class="schedule-discord-guild-result" data-guild-id="${escAttr(guild.guild_id || '')}" data-guild-name="${escAttr(guild.guild_name || '')}"
                     style="padding:10px; cursor:pointer; border-bottom:1px solid var(--card-border); width:100%;">
                    <strong>${escapeHtml(guild.guild_name || guild.guild_id || '')}</strong>
                    <div style="color:var(--text-secondary); font-size:0.82em; margin-top:2px;">${escapeHtml(guild.guild_id || '')}</div>
                </div>
            `).join('');
            dropdown.querySelectorAll('.schedule-discord-guild-result').forEach(el => {
                el.onclick = () => selectScheduleDiscordGuild(el.dataset.guildId, el.dataset.guildName);
            });
            dropdown.style.display = 'block';
            updateScheduleDiscordGuildMeta();
        }

        function selectScheduleDiscordGuild(guildId, guildName) {
            document.getElementById('sch-discord-guild-id').value = guildId || '';
            document.getElementById('sch-discord-guild-search').value = guildName || guildId || '';
            document.getElementById('discord-guild-search-dropdown').style.display = 'none';
            updateScheduleDiscordGuildMeta();
        }

        async function createDiscordEventForSchedule(eventId, gameName) {
            await loadScheduleDiscordGuilds();
            const existingEvent = scheduleEventsCache.find(event => event.id === eventId);
            if (!existingEvent) {
                alert('Event not found');
                return;
            }
            await editScheduleEvent(eventId);
            const guildId = document.getElementById('sch-discord-guild-id').value.trim();
            if (!guildId) {
                showMessage('Choose a Discord server in the edit modal first.', 'warning');
                return;
            }

            try {
                const discordResp = await safeFetch(`/api/schedule/${eventId}/create-discord-event`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        guild_id: guildId,
                        timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
                        timezone_offset_minutes: new Date().getTimezoneOffset(),
                    })
                });
                if (!discordResp.ok) {
                    const err = await discordResp.json();
                    alert(err.error || 'Failed to create Discord event');
                    return;
                }
                const result = await discordResp.json();
                alert(`Discord event created successfully for "${gameName || existingEvent.title}"!
Event ID: ${result.discord_event_id}`);
                await loadSchedule();
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function deleteScheduleEvent(id, hasDiscordEvent = false, discordGuildId = '') {
            const confirmMessage = hasDiscordEvent
                ? 'Delete this event and cancel the linked Discord scheduled event?'
                : 'Delete this event?';
            if (!confirm(confirmMessage)) return;

            let guildId = (discordGuildId || '').trim();
            if (hasDiscordEvent && !guildId) {
                const entered = prompt('This event is linked to Discord but no Guild ID is stored. Enter Discord Server/Guild ID to cancel it:');
                if (!entered || !entered.trim()) {
                    alert('Guild ID is required to cancel the linked Discord event. Deletion cancelled.');
                    return;
                }
                guildId = entered.trim();
            }

            try {
                const resp = await safeFetch(`/api/schedule/${id}`, {
                    method:'DELETE',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ guild_id: guildId || null })
                });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.discord_cancelled) {
                        alert('Event deleted and Discord scheduled event cancelled.');
                    }
                    await loadSchedule();
                }
                else {
                    const d=await resp.json();
                    if (d.requires_guild_id) {
                        alert('Guild ID is required to cancel the linked Discord event. Please try delete again and provide the Guild ID.');
                    } else {
                        alert(d.error||'Failed to delete');
                    }
                }
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function editScheduleEvent(id) {
            try {
                const ev = scheduleEventsCache.find(event => event.id === id);
                if (!ev) return null;
                document.getElementById('schedule-edit-id').value = ev.id;
                document.getElementById('schedule-form-title').textContent = '✏️ Edit Event';
                document.getElementById('sch-title').value = ev.title || '';
                document.getElementById('sch-date').value = ev.date || '';
                document.getElementById('sch-time').value = ev.time || '';
                document.getElementById('sch-duration').value = getScheduleEventDurationMinutes(ev);
                document.getElementById('sch-attendees').value = '';
                setScheduleSelectedAttendees((ev.attendees || []).map((name, index) => ({
                    name,
                    id: Array.isArray(ev.attendee_ids) ? (ev.attendee_ids[index] || name) : name,
                })));
                setScheduleRsvpValues(ev.rsvp_statuses || {});
                document.getElementById('sch-game').value = ev.game_name || '';
                document.getElementById('sch-game-appid').value = ev.game_appid || '';
                document.getElementById('sch-game-image-url').value = ev.game_image_url || '';
                document.getElementById('sch-notes').value = ev.notes || '';
                document.getElementById('sch-create-discord').checked = !!ev.discord_event_id || !!ev.discord_guild_id;
                document.getElementById('sch-discord-guild-id').value = ev.discord_guild_id || '';
                const guilds = await loadScheduleDiscordGuilds();
                const guild = guilds.find(item => item.guild_id === (ev.discord_guild_id || ''));
                document.getElementById('sch-discord-guild-search').value = guild?.guild_name || ev.discord_guild_id || '';
                await ensureScheduleGameFilterData();
                toggleDiscordGuildField();
                const modal = document.getElementById('schedule-modal');
                if (modal) modal.style.display = 'flex';
                setScheduleBodyLock();
                return ev;
            } catch (e) {
                alert('Error: ' + e.message);
                return null;
            }
        }

        function clearScheduleForm() {
            document.getElementById('schedule-edit-id').value = '';
            document.getElementById('schedule-form-title').textContent = '➕ New Event';
            ['sch-title','sch-date','sch-time','sch-attendees','sch-game','sch-notes',
             'sch-game-appid','sch-game-image-url','sch-discord-guild-id','sch-discord-guild-search']
                .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
            const durationField = document.getElementById('sch-duration');
            if (durationField) durationField.value = DEFAULT_SCHEDULE_DURATION_MINUTES;
            const attendeeValuesField = document.getElementById('sch-attendee-values');
            if (attendeeValuesField) attendeeValuesField.value = '';
            const attendeeIdsField = document.getElementById('sch-attendee-ids');
            if (attendeeIdsField) attendeeIdsField.value = '';
            const rsvpField = document.getElementById('sch-rsvp-values');
            if (rsvpField) rsvpField.value = '{}';
            document.getElementById('sch-create-discord').checked = false;
            document.getElementById('discord-guild-field').style.display = 'none';
            document.getElementById('attendee-tags').innerHTML = '';
            document.getElementById('schedule-rsvp-list').innerHTML = '<div class="schedule-field-hint">Add invitees to track each RSVP.</div>';
            document.getElementById('game-search-dropdown').style.display = 'none';
            document.getElementById('attendee-search-dropdown').style.display = 'none';
            scheduleGameSearchCache = [];
            resetScheduleGameFilters();
            const discordDropdown = document.getElementById('discord-guild-search-dropdown');
            if (discordDropdown) discordDropdown.style.display = 'none';
            updateScheduleDiscordGuildMeta();
        }

        async function openScheduleCommonGamePicker() {
            const attendees = getScheduleEventAttendees();
            const collectionId = String(document.getElementById('sch-game-list-filter')?.value || '').trim();
            const modal = document.getElementById('schedule-game-picker-modal');
            if (modal) modal.style.display = 'flex';
            setScheduleBodyLock();
            const status = document.getElementById('schedule-common-games-status');
            const search = document.getElementById('schedule-common-games-search');
            const list = document.getElementById('schedule-common-games-list');
            if (search) search.value = '';
            const loadingMsg = attendees.length
                ? 'Loading games shared by you and your invitees…'
                : (collectionId ? 'Loading games from your selected list…' : 'Loading your library…');
            if (status) status.textContent = loadingMsg;
            if (list) list.innerHTML = '<div class="loading">Loading games…</div>';
            try {
                const resp = await safeFetch('/api/schedule/common-games', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ attendees, collection_id: collectionId })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    scheduleCommonGamesCache = [];
                    if (status) status.textContent = data.error || 'Could not load games.';
                    if (list) list.innerHTML = '<div class="error">No games found.</div>';
                    return;
                }
                scheduleCommonGamesCache = Array.isArray(data.games) ? data.games : [];
                const countLabel = `${scheduleCommonGamesCache.length} game${scheduleCommonGamesCache.length === 1 ? '' : 's'}`;
                if (status) status.textContent = attendees.length
                    ? `${countLabel} shared by you and ${attendees.join(', ')}`
                    : (collectionId ? `${countLabel} in your selected list` : `${countLabel} in your library`);
                filterScheduleCommonGames();
            } catch (error) {
                scheduleCommonGamesCache = [];
                if (status) status.textContent = 'Could not load games right now.';
                if (list) list.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
            }
        }

        function filterScheduleCommonGames() {
            const query = document.getElementById('schedule-common-games-search')?.value.trim().toLowerCase() || '';
            const filtered = scheduleCommonGamesCache.filter(game => {
                if (!query) return true;
                return String(game.name || '').toLowerCase().includes(query)
                    || String(game.app_id || '').toLowerCase().includes(query)
                    || String((game.owners || []).join(', ')).toLowerCase().includes(query);
            });
            const list = document.getElementById('schedule-common-games-list');
            if (!list) return;
            if (!filtered.length) {
                list.innerHTML = '<div class="schedule-field-hint">No common games match the current filter.</div>';
                return;
            }
            list.innerHTML = filtered.map(game => `
                <div class="schedule-common-game-item">
                    <div style="display:flex; gap:12px; align-items:center; min-width:0;">
                        ${game.image_url ? `<img src="${escAttr(game.image_url)}" alt="" style="width:84px; height:40px; border-radius:10px; object-fit:cover;">` : ''}
                        <div style="min-width:0;">
                            <strong>${escapeHtml(game.name || 'Unknown')}</strong>
                            <div class="schedule-field-hint">Owners: ${escapeHtml((game.owners || []).join(', ') || 'Shared library')}</div>
                        </div>
                    </div>
                    <button type="button" class="chat-room-secondary-btn" onclick="selectScheduleCommonGame('${escAttr(String(game.app_id || ''))}', '${escAttr(game.name || '')}', '${escAttr(game.image_url || '')}')">Use game</button>
                </div>
            `).join('');
        }

        function selectScheduleCommonGame(appId, name, imageUrl) {
            selectGame(appId, name, imageUrl);
            closeScheduleCommonGamePicker();
            showMessage(`Selected ${name}`, 'success');
        }

        async function pickRandomScheduleCommonGame() {
            const attendees = getScheduleEventAttendees();
            const collectionId = String(document.getElementById('sch-game-list-filter')?.value || '').trim();
            try {
                const resp = await safeFetch('/api/schedule/common-games/random', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ attendees, collection_id: collectionId }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Could not pick a random game.', 'error');
                    return;
                }
                const game = data.game || {};
                selectScheduleCommonGame(String(game.app_id || ''), game.name || 'Random game', game.image_url || '');
            } catch (error) {
                showMessage(`Error: ${error.message}`, 'error');
            }
        }

        async function openScheduleIcalSyncModal() {
            const modal = document.getElementById('schedule-ical-modal');
            if (modal) modal.style.display = 'flex';
            setScheduleBodyLock();
            const urlField = document.getElementById('schedule-ical-url');
            if (urlField) urlField.value = 'Loading private feed…';
            try {
                const resp = await safeFetch('/api/schedule/ical-sync-info');
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Could not load iCal sync info.', 'error');
                    return;
                }
                scheduleIcalSyncInfo = data;
                if (urlField) urlField.value = data.feed_url || '';
                const openLink = document.getElementById('schedule-ical-open-link');
                const webcalLink = document.getElementById('schedule-ical-webcal-link');
                if (openLink) openLink.href = data.feed_url || '#';
                if (webcalLink) webcalLink.href = data.webcal_url || '#';
            } catch (error) {
                if (urlField) urlField.value = '';
                showMessage('Could not load iCal sync info.', 'error');
            }
        }

        async function copyScheduleIcalUrl() {
            const url = document.getElementById('schedule-ical-url')?.value || scheduleIcalSyncInfo?.feed_url || '';
            if (!url) return;
            try {
                await navigator.clipboard.writeText(url);
                showMessage('iCal URL copied.', 'success');
            } catch (error) {
                showMessage('Could not copy the iCal URL.', 'error');
            }
        }

        document.addEventListener('keydown', function(event) {
            if (event.key !== 'Escape') return;
            closeScheduleCollectionModal();
            closeScheduleCommonGamePicker();
            closeScheduleIcalSyncModal();
            closeScheduleModal();
        });
        // =====================================================================
        // Playlists
        // =====================================================================

        async function loadPlaylists() {
            const container = document.getElementById('playlists-container');
            if (!container) return;
            try {
                const resp = await fetch('/api/playlists');
                if (!resp.ok) { container.innerHTML = '<div class="loading">Error loading playlists.</div>'; return; }
                const data = await resp.json();
                const playlists = data.playlists || [];
                if (!playlists.length) {
                    container.innerHTML = '<div class="loading">No playlists yet. Create one from the actions panel.</div>';
                    return;
                }
                container.innerHTML = playlists.map(p => `
                    <div class="backlog-playlist-card" style="padding:16px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <strong style="font-size:1.1em;">📋 ${escapeHtml(p.name || 'Playlist')}</strong>
                            <span style="color:var(--text-secondary); font-size:0.9em;">${p.count} game(s)</span>
                        </div>
                        <div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">
                            <button onclick="viewPlaylist('${escAttr(p.name)}')" style="padding:5px 14px; background:var(--list-hover); border:1px solid var(--card-border); border-radius:var(--radius-sm,8px); cursor:pointer; color:var(--text-primary);">👁 View</button>
                            <button onclick="pickFromPlaylist('${escAttr(p.name)}')" style="padding:5px 14px; background:linear-gradient(135deg,#4f46e5,#7c3aed); color:white; border:none; border-radius:50px; cursor:pointer;">🎲 Pick</button>
                            <button onclick="deletePlaylist('${escAttr(p.name)}')" style="padding:5px 14px; background:#ef4444; color:white; border:none; border-radius:var(--radius-sm,8px); cursor:pointer;">🗑️ Delete</button>
                        </div>
                        <div id="playlist-games-${CSS.escape(p.name)}" style="margin-top:10px; display:none;"></div>
                    </div>`).join('');
            } catch (e) {
                container.innerHTML = `<div class="loading">Error: ${e.message}</div>`;
            }
        }

        async function createPlaylist() {
            const nameInput = document.getElementById('new-playlist-name');
            const name = nameInput.value.trim();
            if (!name) { alert('Enter a playlist name.'); return; }
            try {
                const resp = await fetch('/api/playlists', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({name})
                });
                if (resp.ok) { nameInput.value = ''; loadPlaylists(); }
                else { const d = await resp.json(); alert(d.error || 'Error'); }
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function deletePlaylist(name) {
            if (!confirm(`Delete playlist "${name}"?`)) return;
            try {
                await fetch(`/api/playlists/${encodeURIComponent(name)}`, {method:'DELETE'});
                loadPlaylists();
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function viewPlaylist(name) {
            const containerId = `playlist-games-${CSS.escape(name)}`;
            const div = document.getElementById(containerId);
            if (!div) return;
            if (div.style.display === 'block') { div.style.display = 'none'; return; }
            div.style.display = 'block';
            div.innerHTML = '<em>Loading…</em>';
            try {
                const resp = await fetch(`/api/playlists/${encodeURIComponent(name)}/games`);
                const data = await resp.json();
                const games = data.games || [];
                if (!games.length) { div.innerHTML = '<em style="color:var(--text-secondary)">No games yet. Add from Library tab.</em>'; return; }
                div.innerHTML = '<ul style="margin:0; padding-left:18px;">' +
                    games.map(g => `<li>${g.name || g.game_id} <button onclick="removeFromPlaylist('${name}','${g.game_id}')" style="border:none; background:none; cursor:pointer; color:#ef4444; font-size:0.8em;">✕</button></li>`).join('') +
                    '</ul>';
            } catch (e) { div.innerHTML = `<em>Error: ${e.message}</em>`; }
        }

        async function removeFromPlaylist(name, gameId) {
            try {
                await fetch(`/api/playlists/${encodeURIComponent(name)}/games/${encodeURIComponent(gameId)}`, {method:'DELETE'});
                viewPlaylist(name); loadPlaylists();
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function addCurrentGameToPlaylist() {
            if (!currentGame) { alert('Pick a game first.'); return; }
            const name = prompt('Playlist name (creates if new):');
            if (!name) return;
            try {
                const resp = await fetch(`/api/playlists/${encodeURIComponent(name)}/games`, {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({game_id: currentGame.game_id})
                });
                const d = await resp.json();
                if (resp.ok) alert(`Added to "${name}"!`);
                else alert(d.error || 'Error');
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function pickFromPlaylist(name) {
            try {
                const resp = await fetch(`/api/playlists/${encodeURIComponent(name)}/games`);
                const data = await resp.json();
                const games = data.games || [];
                if (!games.length) { alert('Playlist is empty.'); return; }
                const game = games[Math.floor(Math.random() * games.length)];
                // Redirect to picker tab and show the game
                document.querySelector('.tab[onclick*="picker"]').click();
                // Build a minimal game object for display (real data requires a proper pick call)
                const appId = game.appid || game.app_id;
                const resp2 = await fetch('/api/pick', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({playlist_game_id: game.game_id})
                });
                // Fallback: just display the game info we have
                currentGame = {
                    app_id: appId,
                    game_id: game.game_id,
                    name: game.name || 'Unknown',
                    playtime_hours: ((game.playtime_forever||0)/60).toFixed(1),
                    is_favorite: false,
                    review: null,
                    tags: [],
                    backlog_status: null,
                    steam_url: `https://store.steampowered.com/app/${appId}/`,
                    steamdb_url: `https://steamdb.info/app/${appId}/`
                };
                displayGame(currentGame);
            } catch (e) { alert('Error: ' + e.message); }
        }

        // =====================================================================
        // Backlog
        // =====================================================================

        function getBacklogCurrentUsername() {
            const raw = document.getElementById('current-username')?.textContent
                || document.getElementById('sidebar-username')?.textContent
                || '';
            return raw.trim();
        }

        function isFavoritesBacklog(backlogId) {
            return String(backlogId || '').trim() === FAVORITES_BACKLOG_ID;
        }

        function getBacklogCollectionsForSelector() {
            const me = getBacklogCurrentUsername() || 'You';
            const favoritesCount = Array.isArray(_favoritesData) ? _favoritesData.length : 0;
            return [{
                id: FAVORITES_BACKLOG_ID,
                name: '💖 Favorites',
                owner: me,
                members: [me],
                is_shared: false,
                is_virtual: true,
                entry_count: favoritesCount,
                invited_count: 0,
            }, ...backlogCollectionsCache];
        }

        function getActiveBacklog() {
            return getBacklogCollectionsForSelector().find(backlog => backlog.id === activeBacklogId) || null;
        }

        function getFilteredBacklogCollections() {
            const query = getFilterValue('backlog-selector-search').trim().toLowerCase();
            const allBacklogs = getBacklogCollectionsForSelector();
            if (!query) return allBacklogs;
            return allBacklogs.filter(backlog => {
                const searchText = [
                    backlog.name,
                    backlog.owner,
                    ...(Array.isArray(backlog.members) ? backlog.members : [])
                ].filter(Boolean).join(' ').toLowerCase();
                return searchText.includes(query);
            });
        }

        function filterBacklogCollections() {
            renderBacklogSelector();
        }

        function isDefaultBacklog(backlog) {
            const currentUsername = getBacklogCurrentUsername().toLowerCase();
            if (!backlog || !currentUsername) return false;
            return String(backlog.id || '').trim().toLowerCase() === `personal:${currentUsername}`;
        }

        function isOwnedBacklog(backlog) {
            if (!backlog) return false;
            return String(backlog.owner || '').trim().toLowerCase() === getBacklogCurrentUsername().toLowerCase();
        }

        function updateBacklogSidebarMeta() {
            const meta = document.getElementById('backlog-sidebar-meta');
            const copy = document.getElementById('backlog-active-copy');
            const renameBtn = document.getElementById('backlog-rename-btn');
            const deleteBtn = document.getElementById('backlog-delete-btn');
            const leaveBtn = document.getElementById('backlog-leave-btn');
            const inviteBtn = document.getElementById('backlog-invite-btn');
            const quickAddBtn = document.getElementById('backlog-library-add-btn');
            const active = getActiveBacklog();
            const isFavorites = isFavoritesBacklog(active?.id);
            const owned = isOwnedBacklog(active);
            const sharedCount = Math.max(((active?.members || []).length || 1) - 1, 0);
            if (meta) {
                meta.textContent = active
                    ? (isFavorites
                        ? 'Favorites from your library.'
                        : `${active.name || 'List'} • ${owned ? 'You own this list' : `Owned by ${active.owner || 'someone else'}`}`)
                    : 'Choose a list to preview, edit, share, or leave.';
            }
            if (copy) {
                copy.textContent = active
                    ? (isFavorites
                        ? 'Favorites are managed from your game picker and library.'
                        : `${active.is_shared ? `Shared with ${sharedCount} other${sharedCount === 1 ? '' : 's'}` : 'Personal list'}`)
                    : '';
            }
            const showDelete = Boolean(active && owned && !isFavorites);
            const enableDelete = Boolean(showDelete && !isDefaultBacklog(active));
            const showLeave = Boolean(active && !owned && active.is_shared && !isFavorites);
            if (renameBtn) renameBtn.disabled = !active || !owned || isFavorites;
            if (inviteBtn) {
                inviteBtn.style.display = owned && !isFavorites ? '' : 'none';
                inviteBtn.disabled = !active || !owned || isFavorites;
            }
            if (deleteBtn) {
                deleteBtn.style.display = showDelete ? '' : 'none';
                deleteBtn.disabled = !enableDelete;
            }
            if (leaveBtn) {
                leaveBtn.style.display = showLeave ? '' : 'none';
                leaveBtn.disabled = !showLeave;
            }
            if (quickAddBtn) quickAddBtn.disabled = !active || isFavorites;
        }

        function renderBacklogSelector() {
            const selectorList = document.getElementById('backlog-selector-list');
            const visibleBacklogs = getFilteredBacklogCollections();
            if (!selectorList) return;
            if (!activeBacklogId || !getBacklogCollectionsForSelector().some(backlog => backlog.id === activeBacklogId)) {
                activeBacklogId = backlogCollectionsCache[0]?.id || FAVORITES_BACKLOG_ID;
            }
            if (!visibleBacklogs.some(backlog => backlog.id === activeBacklogId) && visibleBacklogs.length) {
                activeBacklogId = visibleBacklogs[0].id || '';
            }
            if (!visibleBacklogs.length) {
                selectorList.innerHTML = '<div class="backlog-list-widget-empty">No matching lists</div>';
                updateBacklogSidebarMeta();
                return;
            }
            const groups = {
                favorites: [],
                mine: [],
                shared: [],
            };
            visibleBacklogs.forEach(backlog => {
                if (isFavoritesBacklog(backlog.id)) {
                    groups.favorites.push(backlog);
                } else if (isOwnedBacklog(backlog)) {
                    groups.mine.push(backlog);
                } else {
                    groups.shared.push(backlog);
                }
            });
            const formatItem = (backlog) => {
                const entryCount = Number(backlog.entry_count || 0);
                const invitedCount = Number(backlog.invited_count || Math.max(((backlog.members || []).length || 1) - 1, 0));
                const isActive = backlog.id === activeBacklogId;
                const isFav = isFavoritesBacklog(backlog.id);
                const icon = isFav ? '⭐' : (backlog.is_shared ? '🔗' : '📋');
                const ownerSuffix = isOwnedBacklog(backlog) || isFav ? '' : ` • ${escapeHtml(backlog.owner || '')}`;
                const meta = `${entryCount} item${entryCount === 1 ? '' : 's'} • ${invitedCount} invited${ownerSuffix}`;
                return `<button type="button" class="backlog-list-widget-item${isActive ? ' active' : ''}" data-backlog-id="${escAttr(backlog.id || '')}" onclick="changeActiveBacklog('${escAttr(backlog.id || '')}')">
                    <span class="backlog-list-widget-item-prefix">${icon}</span>
                    <span class="backlog-list-widget-item-text">
                        <span class="backlog-list-widget-item-name">${escapeHtml(backlog.name || 'List')}</span>
                        <span class="backlog-list-widget-item-meta">${meta}</span>
                    </span>
                </button>`;
            };
            const htmlParts = [
                { key: 'favorites', label: 'Favorites' },
                { key: 'mine', label: 'My lists' },
                { key: 'shared', label: 'Shared with me' },
            ].map(group => {
                if (!groups[group.key].length) return '';
                return `<div class="backlog-list-widget-group">
                    <div class="backlog-list-widget-group-label">${group.label}</div>
                    ${groups[group.key].map(formatItem).join('')}
                </div>`;
            }).filter(Boolean).join('');
            selectorList.innerHTML = htmlParts;
            updateBacklogSidebarMeta();
        }

        async function ensureBacklogCollectionsLoaded(force = false) {
            if (!force && backlogCollectionsCache.length) {
                renderBacklogSelector();
                return backlogCollectionsCache;
            }
            const query = activeBacklogId && !isFavoritesBacklog(activeBacklogId)
                ? `?collection_id=${encodeURIComponent(activeBacklogId)}`
                : '';
            const resp = await safeFetch(`/api/backlogs${query}`);
            const data = await resp.json();
            backlogCollectionsCache = data.backlogs || [];
            activeBacklogId = String(data.active_backlog_id || activeBacklogId || '').trim();
            renderBacklogSelector();
            return backlogCollectionsCache;
        }

        function populateBacklogModalCollections(selectedId = activeBacklogId) {
            const selector = document.getElementById('backlog-modal-collection');
            if (!selector) return;
            if (!backlogCollectionsCache.length) {
                selector.innerHTML = '<option value="">No lists available</option>';
                selector.value = '';
                return;
            }
            selector.innerHTML = backlogCollectionsCache.map(backlog => `
                <option value="${escAttr(backlog.id || '')}">
                    ${escapeHtml(backlog.name || 'List')}
                </option>
            `).join('');
            const safeSelected = String(selectedId || '').trim();
            selector.value = backlogCollectionsCache.some(backlog => backlog.id === safeSelected)
                ? safeSelected
                : (backlogCollectionsCache[0].id || '');
        }

        async function ensureBacklogLibraryQuickAddData(force = false) {
            if (!force && backlogLibraryQuickAddData.length) return backlogLibraryQuickAddData;
            const resp = await safeFetch('/api/library');
            const data = await resp.json();
            backlogLibraryQuickAddData = Array.isArray(data.games) ? data.games : [];
            updateBacklogLibrarySearchSuggestions();
            return backlogLibraryQuickAddData;
        }

        function getBacklogLibraryGameId(game) {
            return String(game?.game_id || game?.app_id || game?.appid || '').trim();
        }

        function getBacklogEntryGameId(game) {
            return String(game?.game_id || game?.app_id || game?.appid || '').trim();
        }

        function getBacklogEntryAppId(game) {
            const parsed = Number.parseInt(String(game?.app_id || game?.appid || '').trim(), 10);
            return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
        }

        function getBacklogStatusLabel(status) {
            return String(status || '').replace(/_/g, ' ').trim() || 'unknown';
        }

        function getPreviewNotesCollectionId() {
            return isFavoritesBacklog(activeBacklogId) ? '' : String(activeBacklogId || '').trim();
        }

        function findKnownGameIdByAppId(appId) {
            const safeAppId = Number.parseInt(String(appId || '').trim(), 10);
            if (!Number.isFinite(safeAppId) || safeAppId <= 0) return '';
            const pools = [
                Array.isArray(_libraryData?.games) ? _libraryData.games : [],
                Array.isArray(_favoritesData) ? _favoritesData : [],
                Array.isArray(_backlogData) ? _backlogData : [],
                Array.isArray(_recommendationsData) ? _recommendationsData : [],
                currentGame ? [currentGame] : [],
            ];
            for (const pool of pools) {
                const match = pool.find(game => Number.parseInt(String(game?.app_id || game?.appid || '').trim(), 10) === safeAppId);
                const gameId = getBacklogEntryGameId(match);
                if (gameId) return gameId;
            }
            return `steam:${safeAppId}`;
        }

        function renderPreviewNotesState(containerId, options = {}) {
            const container = document.getElementById(containerId);
            if (!container) return;
            const {
                gameId = '',
                status = '',
                notes = '',
                collectionId = '',
                emptyMessage = 'Add this game to a list to save notes here.',
                saveLabel = '💾 Save notes',
            } = options;
            container.dataset.gameId = String(gameId || '').trim();
            container.dataset.status = String(status || '').trim();
            container.dataset.collectionId = String(collectionId || '').trim();
            container.dataset.saveLabel = String(saveLabel || '💾 Save notes');
            if (!container.dataset.gameId || !container.dataset.status) {
                container.innerHTML = `<div class="schedule-field-hint">${escapeHtml(emptyMessage)}</div>`;
                return;
            }
            const inputId = `${containerId}-input`;
            container.innerHTML = `
                <div class="backlog-entry-preview-notes" style="margin-top:0;">
                    <label for="${inputId}" class="schedule-field-hint">Notes for this list entry</label>
                    <textarea id="${inputId}" class="search-input" placeholder="Write a reminder for later…" style="margin-bottom:0;">${escapeHtml(String(notes || '').trim())}</textarea>
                    <div class="schedule-modal-actions schedule-modal-actions-inline" style="margin-top:0;">
                        <button type="button" class="chat-room-secondary-btn" onclick="savePreviewBacklogNotes('${escAttr(containerId)}')">${escapeHtml(saveLabel)}</button>
                    </div>
                </div>
            `;
        }

        async function loadPreviewBacklogNotes(containerId, gameId, options = {}) {
            const container = document.getElementById(containerId);
            if (!container) return;
            const safeGameId = String(gameId || '').trim();
            if (!safeGameId) {
                renderPreviewNotesState(containerId, {emptyMessage: options.emptyMessage});
                return;
            }
            const collectionId = String(options.collectionId || '').trim();
            const query = collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : '';
            container.innerHTML = '<div class="loading">Loading notes…</div>';
            try {
                const resp = await safeFetch(`/api/backlog/${encodeURIComponent(safeGameId)}${query}`);
                const data = resp.ok ? await resp.json() : {};
                renderPreviewNotesState(containerId, {
                    gameId: safeGameId,
                    status: data.status || '',
                    notes: data.notes || '',
                    collectionId,
                    emptyMessage: options.emptyMessage,
                    saveLabel: options.saveLabel,
                });
            } catch (_) {
                renderPreviewNotesState(containerId, {
                    emptyMessage: options.emptyMessage || 'Unable to load notes for this game right now.',
                });
            }
        }

        async function savePreviewBacklogNotes(containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            const gameId = String(container.dataset.gameId || '').trim();
            const status = String(container.dataset.status || '').trim();
            const collectionId = String(container.dataset.collectionId || '').trim();
            const input = document.getElementById(`${containerId}-input`);
            if (!gameId || !status || !input) {
                showMessage('Add this game to a list before saving notes.', 'warning');
                return;
            }
            const notes = String(input.value || '').trim();
            const updated = await updateBacklogEntryStatus(gameId, status, collectionId, notes);
            if (!updated) {
                showMessage('Failed to save notes for this game.', 'error');
                return;
            }
            if (currentGame && getBacklogEntryGameId(currentGame) === gameId) {
                currentGame.backlog_status = status;
                currentGame.backlog_notes = notes;
            }
            const matchingBacklogGame = _backlogData.find(game => getBacklogEntryGameId(game) === gameId);
            if (matchingBacklogGame) matchingBacklogGame.backlog_notes = notes;
            container.dataset.status = status;
            showMessage('✅ Notes saved.', 'success');
            if (containerId === 'backlog-entry-preview') {
                renderBacklogEntryPreview();
                return;
            }
            renderPreviewNotesState(containerId, {
                gameId,
                status,
                notes,
                collectionId,
                emptyMessage: 'Add this game to a list to save notes here.',
                saveLabel: container.dataset.saveLabel || '💾 Save notes',
            });
        }

        function getBacklogGameGenres(game) {
            if (Array.isArray(game?.genres)) return game.genres.map(value => String(value || '').trim()).filter(Boolean);
            if (Array.isArray(game?.tags)) return game.tags.map(value => String(value || '').trim()).filter(Boolean);
            return [];
        }

        function updateBacklogLibrarySearchSuggestions(query = '') {
            const datalist = document.getElementById('backlog-library-search-suggestions');
            if (!datalist) return;
            const queryLower = String(query || '').trim().toLowerCase();
            const options = [];
            backlogLibraryQuickAddData.forEach(game => {
                const platformLabel = getGamePlatforms(game)[0]?.label || (game.platform || 'Unknown');
                options.push(String(game.name || '').trim());
                options.push(String(platformLabel || '').trim());
                getBacklogGameGenres(game).forEach(genre => options.push(genre));
            });
            const unique = Array.from(new Set(options.filter(Boolean).filter(value => !queryLower || value.toLowerCase().includes(queryLower)))).slice(0, 20);
            datalist.innerHTML = unique.map(value => `<option value="${escapeHtml(value)}"></option>`).join('');
        }

        function renderBacklogLibraryQuickAddPreview(game) {
            const preview = document.getElementById('backlog-library-preview');
            if (!preview) return;
            if (!game) {
                preview.innerHTML = 'Select a game to preview playtime and platform.';
                return;
            }
            const gameId = getBacklogLibraryGameId(game);
            const appId = String(game.app_id || game.appid || '').trim();
            const thumb = appId
                ? renderGameListThumb(appId, game.name)
                : '<div class="backlog-list-thumb-placeholder">🎮</div>';
            const platformLabel = getGamePlatforms(game)[0]?.label || (game.platform || 'Unknown platform');
            const playtime = Number(game.playtime_hours || 0);
            const genres = getBacklogGameGenres(game);
            preview.innerHTML = `
                <div class="backlog-library-preview-media">${thumb}</div>
                <div style="min-width:0;">
                    <div style="font-weight:600;">${escapeHtml(game.name || gameId || 'Selected game')}</div>
                    <div class="schedule-agenda-copy">${escapeHtml(platformLabel)} • ${escapeHtml(String(playtime))}h played</div>
                    ${genres.length ? `<div class="schedule-field-hint">${escapeHtml(genres.slice(0, 3).join(', '))}</div>` : ''}
                </div>
            `;
        }

        function setBacklogLibraryQuickAddSelection(gameId) {
            backlogLibraryQuickAddSelectedGameId = String(gameId || '').trim();
            const libList = document.getElementById('backlog-library-add-list');
            if (libList) {
                libList.querySelectorAll('.backlog-list-widget-item[data-game-id]').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.gameId === backlogLibraryQuickAddSelectedGameId);
                });
            }
            const selectedGame = backlogLibraryQuickAddData.find(game => getBacklogLibraryGameId(game) === backlogLibraryQuickAddSelectedGameId);
            renderBacklogLibraryQuickAddPreview(selectedGame || null);
        }

        function renderBacklogLibraryAutocompleteResults(visibleGames = []) {
            const results = document.getElementById('backlog-library-search-results');
            if (!results) return;
            if (!visibleGames.length) {
                results.innerHTML = '';
                results.style.display = 'none';
                return;
            }
            const topMatches = visibleGames.slice(0, 8);
            results.innerHTML = topMatches.map(game => {
                const gameId = getBacklogLibraryGameId(game);
                const appId = String(game.app_id || game.appid || '').trim();
                const platformLabel = getGamePlatforms(game)[0]?.label || (game.platform || 'Unknown');
                const playtime = Number(game.playtime_hours || 0);
                const genres = getBacklogGameGenres(game);
                const thumb = appId
                    ? renderGameListThumb(appId, game.name)
                    : '<div class="backlog-list-thumb-placeholder">🎮</div>';
                return `
                    <button type="button" class="backlog-library-search-result" onclick="event.preventDefault(); chooseBacklogLibrarySearchResult('${escAttr(gameId)}')">
                        <span class="backlog-library-search-result-thumb">${thumb}</span>
                        <span style="min-width:0; text-align:left;">
                            <span class="backlog-library-search-result-title">${escapeHtml(game.name || gameId || 'Unknown game')}</span>
                            <span class="backlog-library-search-result-meta">${escapeHtml(platformLabel)} • ${escapeHtml(String(playtime))}h${genres.length ? ` • ${escapeHtml(genres[0])}` : ''}</span>
                        </span>
                    </button>
                `;
            }).join('');
            results.style.display = 'grid';
        }

        function chooseBacklogLibrarySearchResult(gameId) {
            const safeGameId = String(gameId || '').trim();
            if (!safeGameId) return;
            const selectedGame = backlogLibraryQuickAddData.find(game => getBacklogLibraryGameId(game) === safeGameId);
            if (!selectedGame) return;
            const searchInput = document.getElementById('backlog-library-search');
            if (searchInput) searchInput.value = String(selectedGame.name || '').trim();
            setBacklogLibraryQuickAddSelection(safeGameId);
            renderBacklogLibraryAutocompleteResults([]);
        }

        function selectBacklogEntryGame(gameId) {
            const safeGameId = String(gameId || '').trim();
            if (!safeGameId) return;
            activeBacklogEntryGameId = safeGameId;
            renderBacklogList();
            openBacklogEntryPreviewModal();
        }

        function isBacklogEntryPreviewModalOpen() {
            const modal = document.getElementById('backlog-entry-preview-modal');
            return Boolean(modal && modal.style.display === 'flex');
        }

        function openBacklogEntryPreviewModal() {
            const modal = document.getElementById('backlog-entry-preview-modal');
            if (!modal) return;
            modal.style.display = 'flex';
            renderBacklogEntryPreview();
        }

        function closeBacklogEntryPreviewModal() {
            const modal = document.getElementById('backlog-entry-preview-modal');
            if (!modal) return;
            modal.style.display = 'none';
        }

        async function renderBacklogEntryPreview() {
            const preview = document.getElementById('backlog-entry-preview');
            if (!preview) return;
            if (!activeBacklogEntryGameId) {
                preview.innerHTML = 'Select a game in this list to preview details and save personal notes.';
                return;
            }
            const selectedGameId = activeBacklogEntryGameId;
            const selected = _backlogData.find(game => getBacklogEntryGameId(game) === selectedGameId);
            if (!selected) {
                preview.innerHTML = 'Selected game is hidden by the current filters.';
                return;
            }

            const appId = getBacklogEntryAppId(selected);
            const statusLabel = getBacklogStatusLabel(selected.backlog_status);
            const statusColor = {
                want_to_play: '#4f46e5',
                playing: '#10b981',
                completed: '#f59e0b',
                dropped: '#ef4444',
                favorite: '#f59e0b',
            }[selected.backlog_status] || '#888';
            const platformBadges = renderInlinePlatformBadges(selected);
            const noteValue = String(selected.backlog_notes || '').trim();
            const canEditNotes = selected.backlog_status !== 'favorite';

            let details = null;
            if (appId) {
                preview.innerHTML = '<div class="loading">Loading game details…</div>';
                details = await loadGameDetailsAsync(appId);
                if (selectedGameId !== activeBacklogEntryGameId) return;
            }
            const genres = Array.isArray(details?.genres) ? details.genres.slice(0, 4).join(', ') : '';
            const description = String(details?.description || '').trim() || 'No game description available.';

            preview.innerHTML = `
                <div class="backlog-entry-preview-head">
                    <div style="min-width:0;">
                        <div class="backlog-entry-preview-title">${escapeHtml(selected.name || activeBacklogEntryGameId)}</div>
                        <div class="backlog-entry-preview-meta">${escapeHtml(String(selected.playtime_hours || 0))}h played${appId ? ` • App ID ${escapeHtml(String(appId))}` : ''}</div>
                    </div>
                    <span style="background:${statusColor}; color:white; padding:3px 10px; border-radius:var(--radius,12px); font-size:0.82em; font-weight:600; white-space:nowrap;">${escapeHtml(statusLabel)}</span>
                </div>
                ${platformBadges ? `<div class="game-inline-meta" style="margin-top:8px;">${platformBadges}</div>` : ''}
                ${genres ? `<div class="schedule-field-hint" style="margin-top:8px;">${escapeHtml(genres)}</div>` : ''}
                <div class="backlog-entry-preview-desc">${escapeHtml(description)}</div>
                <div class="backlog-entry-preview-notes">
                    <label for="backlog-entry-notes" class="schedule-field-hint">Your notes for this list entry</label>
                    <textarea id="backlog-entry-notes" class="search-input" placeholder="Write a reminder for later…" style="margin-bottom:0;" ${canEditNotes ? '' : 'disabled'}>${escapeHtml(noteValue)}</textarea>
                    ${canEditNotes
                        ? `<div class="schedule-modal-actions schedule-modal-actions-inline" style="margin-top:0;">
                            <button type="button" class="chat-room-secondary-btn" onclick="saveBacklogEntryNotes()">💾 Save notes</button>
                        </div>`
                        : '<div class="schedule-field-hint">Favorites are read-only in this view.</div>'}
                </div>
            `;
        }

        async function saveBacklogEntryNotes() {
            const selected = _backlogData.find(game => getBacklogEntryGameId(game) === activeBacklogEntryGameId);
            if (!selected) {
                showMessage('Choose a list entry first.', 'warning');
                return;
            }
            if (selected.backlog_status === 'favorite') {
                showMessage('Notes can only be saved for regular list entries.', 'warning');
                return;
            }
            const notesField = document.getElementById('backlog-entry-notes');
            const nextNotes = String(notesField?.value || '').trim();
            try {
                const updated = await updateBacklogEntryStatus(
                    getBacklogEntryGameId(selected),
                    selected.backlog_status,
                    activeBacklogId,
                    nextNotes
                );
                if (!updated) {
                    showMessage('Failed to save notes for this entry.', 'error');
                    return;
                }
                selected.backlog_notes = nextNotes;
                showMessage('✅ List notes saved.', 'success');
                renderBacklogEntryPreview();
            } catch (error) {
                showMessage(`Failed to save notes: ${error.message}`, 'error');
            }
        }

        function filterBacklogLibraryQuickAdd() {
            const libList = document.getElementById('backlog-library-add-list');
            if (!libList) return;
            const queryRaw = String(document.getElementById('backlog-library-search')?.value || '').trim().toLowerCase();
            const queryTerms = queryRaw.split(/\s+/).filter(Boolean);
            updateBacklogLibrarySearchSuggestions(queryRaw);
            const visibleGames = backlogLibraryQuickAddData
                .filter(game => {
                    const platformText = getGamePlatforms(game).map(platform => platform.label).join(' ');
                    const genres = getBacklogGameGenres(game);
                    const searchable = [
                        game.name,
                        game.game_id,
                        game.app_id,
                        game.appid,
                        game.platform,
                        platformText,
                        ...genres,
                    ].filter(Boolean).join(' ').toLowerCase();
                    const queryMatch = !queryTerms.length || queryTerms.every(term => searchable.includes(term));
                    return queryMatch;
                })
                .slice(0, 250);
            renderBacklogLibraryAutocompleteResults(queryRaw ? visibleGames : []);
            if (!visibleGames.length) {
                libList.innerHTML = '<div class="backlog-list-widget-empty">No matching games</div>';
                backlogLibraryQuickAddSelectedGameId = '';
                renderBacklogLibraryQuickAddPreview(null);
                return;
            }
            const currentSelectionStillVisible = visibleGames.some(game => {
                const gameId = getBacklogLibraryGameId(game);
                return gameId && gameId === backlogLibraryQuickAddSelectedGameId;
            });
            if (!currentSelectionStillVisible) {
                backlogLibraryQuickAddSelectedGameId = getBacklogLibraryGameId(visibleGames[0]);
            }
            libList.innerHTML = visibleGames.map(game => {
                const gameId = getBacklogLibraryGameId(game);
                const playtime = Number(game.playtime_hours || 0);
                const platform = getGamePlatforms(game)[0]?.label || normalisePlatformKey(game.platform || '') || 'platform?';
                const genres = getBacklogGameGenres(game);
                const isActive = gameId === backlogLibraryQuickAddSelectedGameId;
                return `<button type="button" class="backlog-list-widget-item${isActive ? ' active' : ''}" data-game-id="${escAttr(gameId)}" onclick="setBacklogLibraryQuickAddSelection('${escAttr(gameId)}')">
                    <span class="backlog-list-widget-item-text">
                        <span class="backlog-list-widget-item-name">${escapeHtml(game.name || 'Unknown game')}</span>
                        <span class="backlog-list-widget-item-meta">${escapeHtml(platform)} • ${escapeHtml(String(playtime))}h${genres.length ? ` • ${escapeHtml(genres[0])}` : ''}</span>
                    </span>
                </button>`;
            }).join('');
            const selectedGame = visibleGames.find(game => getBacklogLibraryGameId(game) === backlogLibraryQuickAddSelectedGameId) || visibleGames[0];
            renderBacklogLibraryQuickAddPreview(selectedGame || null);
        }

        async function quickAddSelectedLibraryGameToBacklog() {
            const selectedGameId = String(backlogLibraryQuickAddSelectedGameId || '').trim();
            if (!selectedGameId) {
                showMessage('Select a game from your library first.', 'warning');
                return;
            }
            const selectedGame = backlogLibraryQuickAddData.find(game => getBacklogLibraryGameId(game) === selectedGameId);
            await quickAddToBacklog(selectedGameId, selectedGame?.name || 'Selected game');
        }

        async function loadBacklog() {
            const list = document.getElementById('backlog-list');
            const statusFilter = document.getElementById('backlog-filter').value;
            list.innerHTML = renderSkeletonList(5);
            if (isFavoritesBacklog(activeBacklogId)) {
                try {
                    if (!_favoritesData.length) await loadFavorites();
                    const favorites = _favoritesData.map(game => ({
                        ...game,
                        game_id: String(game.game_id || game.app_id || '').trim(),
                        backlog_status: 'favorite',
                    }));
                    _backlogData = favorites;
                    renderBacklogSelector();
                    renderBacklogList();
                } catch (e) {
                    list.innerHTML = `<div class="loading">Error: ${e.message}</div>`;
                    activeBacklogEntryGameId = '';
                    renderBacklogEntryPreview();
                }
                return;
            }
            const params = new URLSearchParams();
            if (statusFilter) params.set('status', statusFilter);
            if (activeBacklogId) params.set('collection_id', activeBacklogId);
            const url = `/api/backlog${params.toString() ? `?${params.toString()}` : ''}`;
            try {
                const resp = await safeFetch(url);
                if (!resp.ok) { list.innerHTML = '<div class="loading">Error loading list.</div>'; return; }
                const data = await resp.json();
                backlogCollectionsCache = data.backlogs || backlogCollectionsCache;
                activeBacklogId = String(data.active_backlog_id || activeBacklogId || '').trim();
                renderBacklogSelector();
                _backlogData = data.games || [];
                populateBacklogModalCollections(activeBacklogId);
                await ensureBacklogLibraryQuickAddData();
                filterBacklogLibraryQuickAdd();
                renderBacklogList();
            } catch (e) {
                list.innerHTML = `<div class="loading">Error: ${e.message}</div>`;
                activeBacklogEntryGameId = '';
                closeBacklogEntryPreviewModal();
            }
        }

        function changeActiveBacklog(backlogId) {
            activeBacklogId = String(backlogId || '').trim();
            activeBacklogEntryGameId = '';
            loadBacklog();
        }

        function renderBacklogList() {
            const list = document.getElementById('backlog-list');
            const games = filterGamesByControls(_backlogData, 'backlog-search', 'backlog-platform-filter');
            const activeBacklog = getActiveBacklog();
            updateBacklogSidebarMeta();
            if (!activeBacklog) {
                list.innerHTML = '<div class="loading">No list selected yet. Create one from the sidebar to get started.</div>';
                activeBacklogEntryGameId = '';
                closeBacklogEntryPreviewModal();
                return;
            }
            if (!_backlogData.length) {
                list.innerHTML = '<div class="loading">No list entries yet. Add games from your library using the panel on the right.</div>';
                activeBacklogEntryGameId = '';
                closeBacklogEntryPreviewModal();
                return;
            }
            if (!games.length) {
                list.innerHTML = '<div class="loading">No list entries match your current filters.</div>';
                activeBacklogEntryGameId = '';
                closeBacklogEntryPreviewModal();
                return;
            }

            if (!games.some(game => getBacklogEntryGameId(game) === activeBacklogEntryGameId)) {
                activeBacklogEntryGameId = getBacklogEntryGameId(games[0]);
            }
            const statusColors = {want_to_play:'#4f46e5', playing:'#10b981', completed:'#f59e0b', dropped:'#ef4444', favorite:'#f59e0b'};
            const BATCH_SIZE = 10;
            let allHtml = '';

            const renderBatch = (startIdx) => {
                const endIdx = Math.min(startIdx + BATCH_SIZE, games.length);
                let batchHtml = '';

                for (let i = startIdx; i < endIdx; i++) {
                    const g = games[i];
                    const gameId = getBacklogEntryGameId(g);
                    const isActive = gameId && gameId === activeBacklogEntryGameId;
                    const color = statusColors[g.backlog_status] || '#888';
                    const label = (g.backlog_status || '').replace(/_/g,' ');
                    const platformBadges = renderInlinePlatformBadges(g);
                    const appId = String(g.app_id || g.appid || '').trim();
                    const thumb = appId
                        ? renderGameListThumb(appId, g.name)
                        : '<div class="backlog-list-thumb-placeholder">🎮</div>';
                    batchHtml += `<div class="list-item backlog-list-item ${isActive ? 'is-active' : ''}" onclick="selectBacklogEntryGame('${escAttr(gameId)}')">
                        <div class="list-item-media">
                            ${thumb}
                            <div style="min-width:0;">
                                <div style="font-weight:600;">${escapeHtml(g.name || g.game_id || 'Unknown game')}</div>
                                ${platformBadges ? `<div class="game-inline-meta" style="margin-top:6px;">${platformBadges}</div>` : ''}
                                ${g.backlog_notes ? `<div class="schedule-field-hint" style="margin-top:6px;">📝 ${escapeHtml(String(g.backlog_notes).slice(0, 90))}</div>` : ''}
                            </div>
                        </div>
                        <span style="background:${color}; color:white; padding:3px 10px; border-radius:var(--radius,12px); font-size:0.82em; font-weight:600; white-space:nowrap;">${escapeHtml(label || 'unknown')}</span>
                    </div>`;
                }

                allHtml += batchHtml;
                list.innerHTML = allHtml;
                if (endIdx < games.length) {
                    requestAnimationFrame(() => renderBatch(endIdx));
                } else {
                    if (isBacklogEntryPreviewModalOpen()) {
                        renderBacklogEntryPreview();
                    }
                }
            };

            renderBatch(0);
        }

        async function loadBacklogShareCandidates(force = false) {
            if (!force && backlogShareCandidatesCache.length) return backlogShareCandidatesCache;
            const resp = await safeFetch('/api/users/list');
            const data = await resp.json();
            const currentUsername = getBacklogCurrentUsername().toLowerCase();
            backlogShareCandidatesCache = (data.users || [])
                .map(user => String(user.username || '').trim())
                .filter(Boolean)
                .filter(name => name.toLowerCase() !== currentUsername);
            return backlogShareCandidatesCache;
        }

        function renderBacklogShareList(selectedMembers = []) {
            const list = document.getElementById('backlog-collection-share-list');
            if (!list) return;
            const selected = new Set((selectedMembers || []).map(member => String(member || '').trim().toLowerCase()));
            if (!backlogShareCandidatesCache.length) {
                list.innerHTML = '<div class="loading">No other users available to share with.</div>';
                return;
            }
            list.innerHTML = backlogShareCandidatesCache.map(name => `
                <label class="backlog-share-option">
                    <input type="checkbox" class="backlog-share-checkbox" value="${escAttr(name)}" ${selected.has(name.toLowerCase()) ? 'checked' : ''}>
                    <span>${escapeHtml(name)}</span>
                </label>
            `).join('');
        }

        async function openBacklogCollectionModal(editMode = false) {
            const active = getActiveBacklog();
            if (editMode && (!active || !isOwnedBacklog(active))) {
                showMessage('Only the list owner can rename or re-share it.', 'warning');
                return;
            }
            document.getElementById('backlog-collection-edit-id').value = editMode ? (active.id || '') : '';
            document.getElementById('backlog-collection-title').textContent = editMode ? '✏️ Edit List' : '📚 New List';
            document.getElementById('backlog-collection-name').value = editMode ? (active.name || '') : '';
            document.getElementById('backlog-collection-modal').style.display = 'flex';
            try {
                await loadBacklogShareCandidates(editMode || !backlogShareCandidatesCache.length);
                renderBacklogShareList(editMode ? (active.members || []).filter(member => String(member || '').trim().toLowerCase() !== String(active.owner || '').trim().toLowerCase()) : []);
            } catch (error) {
                document.getElementById('backlog-collection-share-list').innerHTML = `<div class="error">Error loading users: ${error.message}</div>`;
            }
            setTimeout(() => document.getElementById('backlog-collection-name')?.focus(), 0);
        }

        function closeBacklogCollectionModal() {
            const modal = document.getElementById('backlog-collection-modal');
            if (modal) modal.style.display = 'none';
        }

        function getSelectedBacklogCollectionMembers() {
            return Array.from(document.querySelectorAll('.backlog-share-checkbox:checked'))
                .map(input => String(input.value || '').trim())
                .filter(Boolean);
        }

        async function submitBacklogCollectionForm() {
            const editId = document.getElementById('backlog-collection-edit-id').value.trim();
            const name = document.getElementById('backlog-collection-name').value.trim();
            if (!name) {
                showMessage('Please enter a list name.', 'warning');
                document.getElementById('backlog-collection-name')?.focus();
                return;
            }
            const payload = {
                name,
                members: getSelectedBacklogCollectionMembers(),
                is_shared: getSelectedBacklogCollectionMembers().length > 0,
            };
            try {
                const resp = await safeFetch(editId ? `/api/backlogs/${encodeURIComponent(editId)}` : '/api/backlogs', {
                    method: editId ? 'PUT' : 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to save list', 'error');
                    return;
                }
                activeBacklogId = String(data.id || activeBacklogId || '').trim();
                scheduleGameFilterCacheReady = false;
                closeBacklogCollectionModal();
                await ensureBacklogCollectionsLoaded(true);
                await loadBacklog();
                showMessage(editId ? 'List updated.' : 'List created.', 'success');
            } catch (error) {
                showMessage(`Error saving list: ${error.message}`, 'error');
            }
        }

        async function deleteActiveBacklog() {
            const active = getActiveBacklog();
            if (!active) return;
            if (isDefaultBacklog(active)) {
                showMessage('Your personal list cannot be deleted.', 'warning');
                return;
            }
            if (!isOwnedBacklog(active)) {
                showMessage('Only the list owner can delete it.', 'warning');
                return;
            }
            if (!confirm(`Delete list "${active.name}"?`)) return;
            try {
                const resp = await safeFetch(`/api/backlogs/${encodeURIComponent(active.id)}`, { method: 'DELETE' });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to delete list', 'error');
                    return;
                }
                activeBacklogId = '';
                scheduleGameFilterCacheReady = false;
                await ensureBacklogCollectionsLoaded(true);
                await loadBacklog();
                showMessage('List deleted.', 'success');
            } catch (error) {
                showMessage(`Error deleting list: ${error.message}`, 'error');
            }
        }

        async function leaveActiveBacklog() {
            const active = getActiveBacklog();
            if (!active) return;
            if (isOwnedBacklog(active)) {
                showMessage('Owners delete shared lists instead of leaving them.', 'warning');
                return;
            }
            if (!confirm(`Leave list "${active.name}"?`)) return;
            try {
                const resp = await safeFetch(`/api/backlogs/${encodeURIComponent(active.id)}/leave`, { method: 'POST' });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to leave list', 'error');
                    return;
                }
                activeBacklogId = '';
                scheduleGameFilterCacheReady = false;
                await ensureBacklogCollectionsLoaded(true);
                await loadBacklog();
                showMessage('You left the list.', 'success');
            } catch (error) {
                showMessage(`Error leaving list: ${error.message}`, 'error');
            }
        }
        
        // ==============================================================================================
        // Authentication Functions
        // ==============================================================================================
        
        function setAuthenticatedUI(isAuthenticated, userRole, username = null) {
            console.log('🔐 setAuthenticatedUI called:', { isAuthenticated, userRole, username });
            const authModal = document.getElementById('auth-modal');
            const userInfo = document.getElementById('user-info');
            const topbarUserInfo = document.getElementById('topbar-user-info');
            const topbarLoginBtn = document.getElementById('topbar-login-btn');
            const currentUsernameEl = document.getElementById('current-username');
            const sidebarAvatar = document.getElementById('sidebar-avatar');
            const sidebarUsername = document.getElementById('sidebar-username');
            const sidebarUserInfo = document.getElementById('sidebar-user-info');
            const sidebarActionBtns = document.getElementById('sidebar-action-btns');
            const sidebarStatusDot = document.getElementById('sidebar-status-dot');
            const authTabs = [
                document.getElementById('nav-sessions'),
                document.getElementById('nav-chat'),
                document.getElementById('nav-friends'),
                document.getElementById('nav-recommendations'),
                document.getElementById('nav-achievements'),
                document.getElementById('nav-notifications')
            ];
            const adminTab = document.getElementById('nav-admin');

            if (isAuthenticated) {
                if (authModal) authModal.style.display = 'none';
                if (userInfo) userInfo.style.display = 'block';
                if (currentUsernameEl) currentUsernameEl.textContent = username || '';

                if (sidebarAvatar) sidebarAvatar.textContent = (username || '?')[0].toUpperCase();
                if (sidebarUsername) sidebarUsername.textContent = username || '';
                if (sidebarUserInfo) sidebarUserInfo.style.display = '';
                if (sidebarActionBtns) sidebarActionBtns.style.display = '';
                if (sidebarStatusDot) sidebarStatusDot.classList.remove('offline');
                if (topbarUserInfo) topbarUserInfo.style.display = '';
                if (topbarLoginBtn) topbarLoginBtn.style.display = 'none';

                authTabs.forEach(tab => {
                    if (tab) tab.style.setProperty('display', 'flex', 'important');
                });
                if (adminTab) adminTab.style.display = userRole === 'admin' ? 'flex' : 'none';

                if (username && typeof initRealtime !== 'undefined') {
                    try {
                        if (window.realtimeClient) {
                            window.realtimeClient.reconnect(username);
                        } else {
                            initRealtime(username);
                        }
                    } catch (err) {
                        console.error('Real-time initialization failed:', err);
                    }
                }
            } else {
                if (authModal) authModal.style.display = 'flex';
                if (userInfo) userInfo.style.display = 'none';
                if (currentUsernameEl) currentUsernameEl.textContent = '';
                if (sidebarAvatar) sidebarAvatar.textContent = '?';
                if (sidebarUsername) sidebarUsername.textContent = '';
                if (sidebarUserInfo) sidebarUserInfo.style.display = 'none';
                if (sidebarActionBtns) sidebarActionBtns.style.display = 'none';
                if (sidebarStatusDot) sidebarStatusDot.classList.add('offline');
                if (topbarUserInfo) topbarUserInfo.style.display = 'none';
                if (topbarLoginBtn) topbarLoginBtn.style.display = 'inline-block';
                window.currentUser = null;
                window.currentUserRole = null;

                authTabs.forEach(tab => {
                    if (tab) tab.style.setProperty('display', 'none', 'important');
                });
                if (adminTab) adminTab.style.display = 'none';

                if (window.realtimeClient) {
                    try {
                        window.realtimeClient.disconnect();
                    } catch (err) {
                        console.error('Real-time disconnect failed:', err);
                    }
                }
            }
        }

        async function checkAuthStatus() {
            console.log('🔍 Checking auth status...');
            try {
                const response = await fetch('/api/auth/current');
                const data = await response.json();
                console.log('📥 Auth response:', data);
                
                if (data.username) {
                    // User is logged in
                    console.log('✅ User logged in:', data.username, 'role:', data.role);
                    document.getElementById('current-username').textContent = data.username;
                    
                    // Store user role and username for UI controls
                    window.currentUserRole = data.role || 'user';
                    window.currentUser = data.username;
                    
                    // Update UI based on auth state
                    setAuthenticatedUI(true, data.role || 'user', data.username);
                    
                    loadSettings();
                    init();
                } else {
                    // User is not logged in
                    console.log('❌ User not logged in');
                    setAuthenticatedUI(false, null, null);
                }
            } catch (error) {
                console.error('❌ Error checking auth status:', error);
                setAuthenticatedUI(false, null, null);
            }
        }
        
        function switchAuthForm(showLogin) {
            const isLogin = showLogin === true;
            const isForgot = showLogin === 'forgot';
            document.getElementById('login-form-div').style.display = isLogin ? 'block' : 'none';
            document.getElementById('register-form-div').style.display = (!isLogin && !isForgot) ? 'block' : 'none';
            document.getElementById('forgot-form-div').style.display = isForgot ? 'block' : 'none';
            if (document.getElementById('login-error')) document.getElementById('login-error').style.display = 'none';
            if (document.getElementById('register-error')) document.getElementById('register-error').style.display = 'none';
            if (document.getElementById('forgot-error')) document.getElementById('forgot-error').style.display = 'none';
            if (document.getElementById('forgot-success')) document.getElementById('forgot-success').style.display = 'none';
        }
        // Ensure inline onclick handlers can call this even if script is evaluated in a module/closure
        try { window.switchAuthForm = switchAuthForm; } catch (e) { /* ignore in non-browser tests */ }

        async function submitForgotPassword() {
            const usernameEl = document.getElementById('forgot-username');
            const errorDiv = document.getElementById('forgot-error');
            const successDiv = document.getElementById('forgot-success');
            errorDiv.style.display = 'none';
            successDiv.style.display = 'none';
            const username = (usernameEl ? usernameEl.value : '').trim();
            if (!username) {
                errorDiv.textContent = 'Please enter your username.';
                errorDiv.style.display = 'block';
                return;
            }
            try {
                const resp = await fetch('/api/password-reset-request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    successDiv.textContent = data.message || 'Request submitted. An admin will assist you.';
                    successDiv.style.display = 'block';
                    if (usernameEl) usernameEl.value = '';
                } else {
                    errorDiv.textContent = data.error || 'Failed to submit request.';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.textContent = 'Network error. Please try again.';
                errorDiv.style.display = 'block';
            }
        }
        try { window.submitForgotPassword = submitForgotPassword; } catch (e) { /* ignore in non-browser tests */ }

        async function handleLogin(event) {
            if (event && event.preventDefault) event.preventDefault();
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value.trim();
            const errorDiv = document.getElementById('login-error');
            
            // Clear previous errors
            errorDiv.style.display = 'none';
            
            if (!username || !password) {
                errorDiv.textContent = 'Username and password required';
                errorDiv.style.display = 'block';
                console.warn('Login: Missing username or password');
                return;
            }
            
            try {
                console.log('Attempting login for user:', username);
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    credentials: 'same-origin',
                    body: JSON.stringify({username, password})
                });
                
                const data = await response.json();
                console.log('Login response:', response.status, data);
                
                if (!response.ok) {
                    errorDiv.textContent = data.error || 'Login failed';
                    errorDiv.style.display = 'block';
                    console.error('Login failed:', data.error);
                    toastr.error(data.error || 'Login failed');
                    return;
                }
                
                // Successful login - clear form and check auth status
                console.log('Login successful');
                document.getElementById('login-password').value = '';
                toastr.success('Login successful');
                await checkAuthStatus();
            } catch (error) {
                console.error('Login error:', error);
                errorDiv.textContent = 'Error: ' + error.message;
                errorDiv.style.display = 'block';
                toastr.error('Server error: ' + error.message);
            }
        }
        
        async function handleRegister(event) {
            if (event && event.preventDefault) event.preventDefault();
            const username = document.getElementById('register-username').value.trim();
            const password = document.getElementById('register-password').value.trim();
            const errorDiv = document.getElementById('register-error');
            
            // Clear previous errors
            errorDiv.style.display = 'none';
            
            if (!username || !password) {
                errorDiv.textContent = 'Username and password required';
                errorDiv.style.display = 'block';
                return;
            }
            
            if (username.length < 3) {
                errorDiv.textContent = 'Username must be at least 3 characters';
                errorDiv.style.display = 'block';
                return;
            }
            
            if (password.length < 6) {
                errorDiv.textContent = 'Password must be at least 6 characters';
                errorDiv.style.display = 'block';
                return;
            }
            
            try {
                console.log('Attempting registration for user:', username);
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    credentials: 'same-origin',
                    body: JSON.stringify({username, password})
                });
                
                const data = await response.json();
                console.log('Register response:', response.status, data);
                
                if (!response.ok) {
                    errorDiv.textContent = data.error || 'Registration failed';
                    errorDiv.style.display = 'block';
                    console.error('Registration failed:', data.error);
                    toastr.error(data.error || 'Registration failed');
                    return;
                }
                
                // Successful registration, switch to login form
                console.log('Registration successful');
                document.getElementById('register-username').value = '';
                document.getElementById('register-password').value = '';
                switchAuthForm(true);
                document.getElementById('login-username').value = username;
                document.getElementById('login-password').focus();
                toastr.success('✅ Registration successful! Please log in.');
            } catch (error) {
                console.error('Registration error:', error);
                errorDiv.textContent = 'Error: ' + error.message;
                errorDiv.style.display = 'block';
                toastr.error('Server error: ' + error.message);
            }
        }
        
        async function handleLogout() {
            if (!confirm('Are you sure you want to sign out?')) {
                return;
            }
            
            try {
                await safeFetch('/api/auth/logout', {method: 'POST'});
                document.getElementById('login-username').value = '';
                document.getElementById('login-password').value = '';
                // Clear all user-specific data from the DOM so a subsequent
                // login shows fresh data for the new user and not stale data
                // from the previously logged-in user.
                clearUserData();
                toastr.success('Signed out successfully');
                checkAuthStatus();
            } catch (error) {
                toastr.error('Error signing out: ' + error.message);
            }
        }
        
        async function loadSettings() {
            try {
                const response = await fetch('/api/auth/get-ids');
                
                if (!response.ok) return;
                
                const data = await response.json();
                document.getElementById('settings-steam-id').value = data.steam_id || '';
                document.getElementById('settings-epic-id').value = data.epic_id || '';
                document.getElementById('settings-gog-id').value = data.gog_id || '';
                document.getElementById('settings-discord-id').value = data.discord_id || '';

                await loadSyncStatus();
                await loadSyncSettings();
                await loadMigrations();
                await refreshPlatformFilters();
            } catch (error) {
                console.error('Error loading settings:', error);
            }
        }

        async function checkInitialSetup() {
            try {
                const response = await fetch('/api/setup/status');
                if (!response.ok) return;
                const data = await response.json();
                if (data.needs_setup) {
                    const modal = document.getElementById('setup-modal');
                    if (modal) {
                        modal.style.display = 'flex';
                    }
                }
            } catch (error) {
                console.error('Error checking setup status:', error);
            }
        }

        async function runInitialSetup() {
            const username = document.getElementById('setup-admin-username').value.trim();
            const password = document.getElementById('setup-admin-password').value.trim();

            if (!username || !password) {
                toastr.error('Username and password are required');
                return;
            }

            try {
                const response = await fetch('/api/setup/initial-admin', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password })
                });
                const data = await response.json();
                if (response.ok) {
                    toastr.success('Admin user created. Please log in.');
                    const modal = document.getElementById('setup-modal');
                    if (modal) {
                        modal.style.display = 'none';
                    }
                } else {
                    toastr.error(data.error || 'Failed to create admin');
                }
            } catch (error) {
                toastr.error('Setup error: ' + error.message);
            }
        }

        async function loadSyncStatus() {
            try {
                const response = await fetch('/api/library/sync/status');
                if (!response.ok) return;
                const data = await response.json();

                const lastSyncEl = document.getElementById('last-sync-time');
                const gamesCachedEl = document.getElementById('games-cached-count');
                const cacheAgeEl = document.getElementById('cache-age-display');
                const syncBtn = document.getElementById('sync-library-btn');

                if (lastSyncEl) {
                    lastSyncEl.textContent = data.last_sync ? new Date(data.last_sync).toLocaleString() : 'Never';
                }
                if (gamesCachedEl) {
                    gamesCachedEl.textContent = data.games_cached || 0;
                }
                if (cacheAgeEl) {
                    cacheAgeEl.textContent = data.cache_age_hours !== null && data.cache_age_hours !== undefined
                        ? `${data.cache_age_hours}h`
                        : '—';
                }
                if (syncBtn) {
                    if (data.is_syncing) {
                        syncBtn.disabled = true;
                        syncBtn.textContent = '⏳ Syncing...';
                    } else {
                        syncBtn.disabled = false;
                        syncBtn.textContent = '🔄 Sync Library Now';
                    }
                }
            } catch (error) {
                console.error('Error loading sync status:', error);
            }
        }

        async function loadSyncSettings() {
            try {
                const authResponse = await fetch('/api/auth/current');
                if (!authResponse.ok) return;
                const authData = await authResponse.json();

                const syncSettingsDiv = document.getElementById('sync-interval-settings');
                if (!syncSettingsDiv) return;

                const migrationsDiv = document.getElementById('admin-migrations');

                if (authData.role !== 'admin') {
                    syncSettingsDiv.style.display = 'none';
                    if (migrationsDiv) {
                        migrationsDiv.style.display = 'none';
                    }
                    return;
                }

                const response = await fetch('/api/library/sync/settings');
                if (!response.ok) return;
                const data = await response.json();

                const intervalInput = document.getElementById('sync-interval-input');
                if (intervalInput && data.sync_interval_hours) {
                    intervalInput.value = data.sync_interval_hours;
                }

                syncSettingsDiv.style.display = 'block';
                if (migrationsDiv) {
                    migrationsDiv.style.display = 'block';
                }
            } catch (error) {
                console.error('Error loading sync settings:', error);
            }
        }

        async function loadMigrations() {
            const select = document.getElementById('migration-select');
            const description = document.getElementById('migration-description');
            const sqlArea = document.getElementById('migration-sql');
            if (!select || !description || !sqlArea) return;

            try {
                const response = await fetch('/api/admin/migrations');
                if (!response.ok) {
                    return;
                }
                const data = await response.json();
                const migrations = data.migrations || [];

                select.innerHTML = '';
                migrations.forEach((mig, idx) => {
                    const option = document.createElement('option');
                    option.value = mig.id;
                    option.textContent = mig.label;
                    option.dataset.description = mig.description || '';
                    option.dataset.sql = mig.sql || '';
                    select.appendChild(option);
                    if (idx === 0) {
                        select.value = mig.id;
                        description.textContent = mig.description || '';
                        sqlArea.value = mig.sql || '';
                    }
                });

                select.onchange = () => {
                    const selected = select.options[select.selectedIndex];
                    description.textContent = selected.dataset.description || '';
                    sqlArea.value = selected.dataset.sql || '';
                };
            } catch (error) {
                console.error('Error loading migrations:', error);
            }
        }

        async function runMigration() {
            const select = document.getElementById('migration-select');
            const sqlArea = document.getElementById('migration-sql');
            if (!select || !sqlArea) return;

            const id = select.value;
            const sql = sqlArea.value;
            if (!id) {
                toastr.error('Select a migration first');
                return;
            }

            if (!confirm('Run this migration now? This will execute SQL against the database.')) {
                return;
            }

            try {
                const response = await fetch('/api/admin/migrations/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id, sql })
                });

                const data = await response.json();
                if (response.ok) {
                    toastr.success(data.message || 'Migration executed');
                } else {
                    toastr.error(data.error || 'Migration failed');
                }
            } catch (error) {
                toastr.error('Error running migration: ' + error.message);
            }
        }

        async function triggerLibrarySync() {
            const syncBtn = document.getElementById('sync-library-btn');
            if (syncBtn) {
                syncBtn.disabled = true;
                syncBtn.textContent = '⏳ Syncing...';
            }

            try {
                const response = await safeFetch('/api/library/sync', { method: 'POST' });
                const data = await response.json();

                if (response.ok) {
                    toastr.success(data.message || 'Library sync started');
                } else {
                    toastr.error(data.error || 'Failed to start sync');
                }
            } catch (error) {
                toastr.error('Error starting sync: ' + error.message);
            } finally {
                setTimeout(() => loadSyncStatus(), 1500);
            }
        }

        async function updateSyncInterval() {
            const intervalInput = document.getElementById('sync-interval-input');
            if (!intervalInput) return;

            const interval = intervalInput.value;

            try {
                const response = await fetch('/api/library/sync/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ sync_interval_hours: interval })
                });

                const data = await response.json();

                if (response.ok) {
                    toastr.success('Sync interval updated');
                    intervalInput.value = data.sync_interval_hours;
                } else {
                    toastr.error(data.error || 'Failed to update interval');
                }
            } catch (error) {
                toastr.error('Error updating interval: ' + error.message);
            }
        }
        
        async function saveSettings() {
            const steamId = document.getElementById('settings-steam-id').value.trim();
            const epicId = document.getElementById('settings-epic-id').value.trim();
            const gogId = document.getElementById('settings-gog-id').value.trim();
            const discordId = document.getElementById('settings-discord-id').value.trim();
            const messageDiv = document.getElementById('settings-message');
            
            try {
                const response = await fetch('/api/auth/update-ids', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        steam_id: steamId,
                        epic_id: epicId,
                        gog_id: gogId,
                        discord_id: discordId
                    })
                });
                
                const data = await response.json();
                
                messageDiv.style.display = 'block';
                if (response.ok) {
                    messageDiv.style.background = 'rgba(16,185,129,0.12)';
                    messageDiv.style.color = '#10b981';
                    messageDiv.textContent = '✅ Settings saved! Games are loading...';
                    toastr.success('Settings saved — games are loading');
                    setTimeout(() => {
                        messageDiv.style.display = 'none';
                        updateStatus();
                        loadSyncStatus();
                        refreshPlatformFilters();
                    }, 2000);
                } else {
                    messageDiv.style.background = 'rgba(239,68,68,0.1)';
                    messageDiv.style.color = '#ef4444';
                    messageDiv.textContent = '❌ ' + (data.error || 'Failed to save settings');
                    toastr.error(data.error || 'Failed to save settings');
                }
            } catch (error) {
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'rgba(239,68,68,0.1)';
                messageDiv.style.color = '#ef4444';
                messageDiv.textContent = '❌ Error: ' + error.message;
                toastr.error('Error saving settings: ' + error.message);
            }
        }
        
        async function changePassword() {
            const currentPassword = document.getElementById('password-current').value;
            const newPassword = document.getElementById('password-new').value;
            const confirmPassword = document.getElementById('password-confirm').value;
            const messageDiv = document.getElementById('password-message');
            
            // Clear previous messages
            messageDiv.style.display = 'none';
            
            // Validate inputs
            if (!currentPassword || !newPassword || !confirmPassword) {
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'rgba(239,68,68,0.1)';
                messageDiv.style.color = '#ef4444';
                messageDiv.textContent = '❌ Please fill in all password fields';
                toastr.error('Please fill in all password fields');
                return;
            }
            
            if (newPassword !== confirmPassword) {
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'rgba(239,68,68,0.1)';
                messageDiv.style.color = '#ef4444';
                messageDiv.textContent = '❌ New passwords do not match';
                toastr.error('New passwords do not match');
                return;
            }
            
            if (newPassword.length < 6) {
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'rgba(239,68,68,0.1)';
                messageDiv.style.color = '#ef4444';
                messageDiv.textContent = '❌ New password must be at least 6 characters';
                toastr.error('New password must be at least 6 characters');
                return;
            }
            
            try {
                const response = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });
                
                const data = await response.json();
                
                messageDiv.style.display = 'block';
                if (response.ok) {
                    messageDiv.style.background = 'rgba(16,185,129,0.12)';
                    messageDiv.style.color = '#10b981';
                    messageDiv.textContent = '✅ Password changed successfully!';
                    toastr.success('Password changed successfully');
                    
                    // Clear the form
                    document.getElementById('password-current').value = '';
                    document.getElementById('password-new').value = '';
                    document.getElementById('password-confirm').value = '';
                    
                    setTimeout(() => {
                        messageDiv.style.display = 'none';
                    }, 3000);
                } else {
                    messageDiv.style.background = 'rgba(239,68,68,0.1)';
                    messageDiv.style.color = '#ef4444';
                    messageDiv.textContent = '❌ ' + (data.error || 'Failed to change password');
                    toastr.error(data.error || 'Failed to change password');
                }
            } catch (error) {
                messageDiv.style.display = 'block';
                messageDiv.style.background = 'rgba(239,68,68,0.1)';
                messageDiv.style.color = '#ef4444';
                messageDiv.textContent = '❌ Error: ' + error.message;
                toastr.error('Error changing password: ' + error.message);
            }
        }
        
        // ==============================================================================================
        // Ignored Games Functions
        // ==============================================================================================
        
        async function loadIgnoredGames() {
            const listDiv = document.getElementById('ignored-games-list');
            listDiv.innerHTML = renderSkeletonList(4);
            
            try {
                const response = await fetch('/api/ignored-games');
                const data = await response.json();
                
                if (data.ignored_games && data.ignored_games.length > 0) {
                    let html = '';
                    data.ignored_games.forEach(game => {
                        html += `
                            <div class="list-item" style="display: grid; grid-template-columns: 1fr 1fr auto; gap: 15px; align-items: center; padding: 15px; background: var(--list-hover); border-radius: var(--radius-sm, 8px); margin-bottom: 10px;">
                                <div>
                                    <strong>${game.game_name}</strong><br>
                                    <small style="color: var(--text-secondary);">App ID: ${game.app_id}</small>
                                </div>
                                <div>
                                    <small style="color: var(--text-secondary);">Reason:</small><br>
                                    <span>${game.reason || '(none)'}</span>
                                </div>
                                <button onclick="removeIgnoredGame(${game.app_id})" style="padding: 6px 12px; background: #ef4444; color: white; border: none; border-radius: var(--radius-xs, 6px); cursor: pointer; font-size: 0.85em;">Remove</button>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div style="padding: 20px; color: var(--text-secondary);">No ignored games yet. Add one above!</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading ignored games: ' + error.message + '</div>';
            }
        }
        
        async function addIgnoredGame() {
            const appId = document.getElementById('ignore-app-id').value.trim();
            const gameName = document.getElementById('ignore-game-name').value.trim();
            const reason = document.getElementById('ignore-reason').value.trim();
            
            if (!appId || !gameName) {
                alert('App ID and game name are required');
                return;
            }
            
            try {
                const response = await fetch('/api/ignored-games', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        app_id: parseInt(appId),
                        game_name: gameName,
                        reason: reason
                    })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    document.getElementById('ignore-app-id').value = '';
                    document.getElementById('ignore-game-name').value = '';
                    document.getElementById('ignore-reason').value = '';
                    loadIgnoredGames();
                } else {
                    alert(data.error || 'Failed to add game');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        async function removeIgnoredGame(appId) {
            if (!confirm('Remove this game from your no-play list?')) return;
            
            try {
                const response = await fetch('/api/ignored-games', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        app_id: appId,
                        game_name: '',
                        reason: ''
                    })
                });
                
                if (response.ok) {
                    loadIgnoredGames();
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        // ==============================================================================================
        // Achievements Functions
        // ==============================================================================================
        
        let achievementGamesData = [];
        let achievementHuntLibraryData = [];
        let achievementBacklogCollections = [];
        let achievementCollectionGameIds = {};
        let achievementsLibrarySyncAttempted = false;

        function getAchievementAppIdToken(item) {
            const appId = item?.app_id ?? item?.appid;
            if (appId !== undefined && appId !== null && String(appId).trim()) {
                return String(appId).trim();
            }
            const gameId = String(item?.game_id || '').trim();
            if (!gameId) return '';
            if (gameId.includes(':')) {
                return gameId.split(':').pop()?.trim() || '';
            }
            return gameId;
        }

        function populateAchievementListFilterOptions(backlogs) {
            const options = ['<option value="all">All library games</option>'];
            (backlogs || []).forEach(backlog => {
                const id = String(backlog?.id || '').trim();
                if (!id) return;
                const name = String(backlog?.name || 'Unnamed list').trim() || 'Unnamed list';
                options.push(`<option value="${id}">${name}</option>`);
            });
            ['achievements-list-filter', 'achievement-hunt-list-filter'].forEach(id => {
                const listFilterEl = document.getElementById(id);
                if (!listFilterEl) return;
                const existingValue = listFilterEl.value;
                listFilterEl.innerHTML = options.join('');
                if (existingValue && options.some(option => option.includes(`value="${existingValue}"`))) {
                    listFilterEl.value = existingValue;
                }
            });
        }

        async function loadAchievementBacklogFilters() {
            try {
                const response = await safeFetch('/api/backlogs');
                if (!response.ok) return;
                const data = await response.json();
                achievementBacklogCollections = Array.isArray(data.backlogs) ? data.backlogs : [];
                populateAchievementListFilterOptions(achievementBacklogCollections);
            } catch (_error) {
                achievementBacklogCollections = [];
                populateAchievementListFilterOptions([]);
            }
        }

        async function getAchievementGameIdsForCollection(collectionId) {
            const safeCollectionId = String(collectionId || '').trim();
            if (!safeCollectionId) return null;
            if (achievementCollectionGameIds[safeCollectionId]) {
                return achievementCollectionGameIds[safeCollectionId];
            }
            try {
                const response = await safeFetch(`/api/backlog?collection_id=${encodeURIComponent(safeCollectionId)}`);
                if (!response.ok) return null;
                const data = await response.json();
                const games = Array.isArray(data.games) ? data.games : [];
                const gameIds = new Set(
                    games
                        .map(item => getAchievementAppIdToken(item))
                        .filter(Boolean)
                );
                achievementCollectionGameIds[safeCollectionId] = gameIds;
                return gameIds;
            } catch (_error) {
                return null;
            }
        }

        async function renderUserAchievements() {
            const listDiv = document.getElementById('achievements-list');
            if (!listDiv) return;

            const searchEl = document.getElementById('achievements-search');
            const listFilterEl = document.getElementById('achievements-list-filter');
            const query = String(searchEl?.value || '').trim().toLowerCase();
            const listFilter = String(listFilterEl?.value || 'all').trim();

            let achievements = Array.isArray(achievementGamesData) ? [...achievementGamesData] : [];
            if (query) {
                achievements = achievements.filter(game => {
                    const name = String(game?.game_name || '').toLowerCase();
                    const appId = String(game?.app_id || '');
                    return name.includes(query) || appId.includes(query);
                });
            }

            if (listFilter && listFilter !== 'all') {
                const collectionGameIds = await getAchievementGameIdsForCollection(listFilter);
                if (collectionGameIds instanceof Set) {
                    achievements = achievements.filter(game => collectionGameIds.has(String(game?.app_id || '').trim()));
                } else {
                    achievements = [];
                }
            }

            if (!achievements.length) {
                listDiv.innerHTML = '<div style="padding: 20px; color: var(--text-secondary);">No achievements found for the selected filters.</div>';
                return;
            }

            const BATCH_SIZE = 5;
            let allHtml = '';
            const renderBatch = (startIdx) => {
                const endIdx = Math.min(startIdx + BATCH_SIZE, achievements.length);
                let batchHtml = '';
                for (let i = startIdx; i < endIdx; i++) {
                    const game = achievements[i];
                    const unlockedCount = (game.achievements || []).filter(a => a.unlocked).length;
                    const totalCount = (game.achievements || []).length;
                    const progressPercent = totalCount > 0 ? (unlockedCount / totalCount * 100) : 0;
                    batchHtml += `
                        <div style="padding: 15px; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius-sm, 8px); margin-bottom: 10px;">
                            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-bottom: 10px;">
                                <div>
                                    <strong>${game.game_name}</strong><br>
                                    <small style="color: var(--text-secondary);">App ID: ${game.app_id}</small>
                                </div>
                                <div>
                                    <small style="color: var(--text-secondary);">Progress:</small><br>
                                    <div style="background: var(--list-hover); border-radius: var(--radius-sm, 8px); height: 20px; overflow: hidden; margin-top: 5px;">
                                        <div style="background: linear-gradient(90deg, #4f46e5, #7c3aed); height: 100%; width: ${progressPercent}%; transition: width 0.3s;"></div>
                                    </div>
                                </div>
                                <div style="text-align: center;">
                                    <strong style="font-size: 1.2em; color: #4f46e5;">${unlockedCount}/${totalCount}</strong><br>
                                    <small style="color: var(--text-secondary);">Unlocked</small>
                                </div>
                            </div>
                        </div>
                    `;
                }
                allHtml += batchHtml;
                listDiv.innerHTML = allHtml;
                if (endIdx < achievements.length) {
                    requestAnimationFrame(() => renderBatch(endIdx));
                }
            };
            renderBatch(0);
        }

        async function ensureAchievementHuntLibrary(force = false) {
            if (!force && achievementHuntLibraryData.length) return achievementHuntLibraryData;
            const response = await safeFetch('/api/library');
            const data = await response.json();
            achievementHuntLibraryData = Array.isArray(data.games) ? data.games : [];
            return achievementHuntLibraryData;
        }

        async function loadUserAchievements(forceSync = false) {
            const listDiv = document.getElementById('achievements-list');
            if (!listDiv) return;
            listDiv.innerHTML = renderSkeletonList(4);

            await loadAchievementBacklogFilters();

            if (forceSync || !achievementsLibrarySyncAttempted) {
                try {
                    const syncResp = await safeFetch('/api/achievements/sync', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({})
                    });
                    if (syncResp.ok) achievementCollectionGameIds = {};
                } catch (_error) {
                    // Best effort: keep rendering cached achievements if sync fails.
                }
                achievementsLibrarySyncAttempted = true;
            }

            try {
                const response = await safeFetch('/api/achievements');
                const data = await response.json();
                achievementGamesData = Array.isArray(data.achievements) ? data.achievements : [];
                await renderUserAchievements();
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading achievements: ' + error.message + '</div>';
            }
        }
        
        async function openAchievementHuntModal() {
            const modal = document.getElementById('achievement-hunt-modal');
            if (!modal) return;
            modal.style.display = 'flex';
            await loadAchievementBacklogFilters();
            try {
                await ensureAchievementHuntLibrary();
            } catch (_error) {
                achievementHuntLibraryData = [];
            }
            if (!achievementGamesData.length) {
                await loadUserAchievements();
            }
            renderAchievementHuntLibrary();
        }

        function closeAchievementHuntModal() {
            const modal = document.getElementById('achievement-hunt-modal');
            if (modal) modal.style.display = 'none';
        }

        function updateAchievementHuntSearchSuggestions(games, query = '') {
            const datalist = document.getElementById('achievement-hunt-search-suggestions');
            if (!datalist) return;
            const queryLower = String(query || '').trim().toLowerCase();
            const options = [];
            (games || []).forEach(game => {
                const name = String(game?.name || '').trim();
                const appId = String(game?.app_id || game?.appid || '').trim();
                if (name) options.push(name);
                if (appId) options.push(appId);
            });
            const unique = Array.from(new Set(
                options.filter(Boolean).filter(value => !queryLower || value.toLowerCase().includes(queryLower))
            )).slice(0, 20);
            datalist.innerHTML = unique.map(value => `<option value="${escapeHtml(value)}"></option>`).join('');
        }

        function renderAchievementHuntLibrary() {
            const listEl = document.getElementById('achievement-hunt-library');
            if (!listEl) return;
            const searchEl = document.getElementById('achievement-hunt-search');
            const listFilterEl = document.getElementById('achievement-hunt-list-filter');
            const query = String(searchEl?.value || '').trim().toLowerCase();
            const listFilter = String(listFilterEl?.value || 'all').trim();

            let games = Array.isArray(achievementHuntLibraryData) ? [...achievementHuntLibraryData] : [];
            if (listFilter && listFilter !== 'all') {
                const cachedSet = achievementCollectionGameIds[String(listFilter).trim()];
                if (cachedSet instanceof Set) {
                    games = games.filter(game => cachedSet.has(String(game?.app_id || game?.appid || '').trim()));
                } else {
                    listEl.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); border:1px solid var(--card-border); border-radius: var(--radius-sm, 8px);">Loading list games…</div>';
                    getAchievementGameIdsForCollection(listFilter).then(gameIds => {
                        const hydrated = gameIds instanceof Set
                            ? achievementHuntLibraryData.filter(game => gameIds.has(String(game?.app_id || game?.appid || '').trim()))
                            : [];
                        updateAchievementHuntSearchSuggestions(hydrated, query);
                        renderAchievementHuntLibrary();
                    });
                    return;
                }
            }

            updateAchievementHuntSearchSuggestions(games, query);
            if (query) {
                games = games.filter(game => {
                    const name = String(game?.name || game?.game_name || '').toLowerCase();
                    const appId = String(game?.app_id || game?.appid || '');
                    return name.includes(query) || appId.includes(query);
                });
            }

            if (!games.length) {
                listEl.innerHTML = '<div style="padding: 20px; color: var(--text-secondary); border:1px solid var(--card-border); border-radius: var(--radius-sm, 8px);">No games found in your synced library.</div>';
                return;
            }

            listEl.innerHTML = games.map(game => {
                const appId = parseInt(game?.app_id || game?.appid, 10);
                const gameName = String(game?.name || game?.game_name || `App ${game?.app_id || game?.appid || ''}`);
                const playtime = Number(game?.playtime_hours || 0);
                const imageUrl = appId
                    ? `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`
                    : '';
                if (!Number.isInteger(appId)) return '';
                return `
                    <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; border:1px solid var(--card-border); border-radius:var(--radius-sm,8px); padding:12px; background:var(--card-bg);">
                        <div style="display:flex; align-items:center; gap:10px; min-width:0;">
                            ${imageUrl ? `<img src="${escAttr(imageUrl)}" alt="" style="width:88px; height:42px; object-fit:cover; border-radius:var(--radius-tag,4px); flex-shrink:0;">` : ''}
                            <div style="min-width:0;">
                                <strong style="display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(gameName)}</strong>
                                <small style="color:var(--text-secondary);">App ID: ${appId}${playtime ? ` • ${escapeHtml(String(playtime))}h played` : ''}</small>
                            </div>
                        </div>
                        <button onclick="startAchievementHunt(${appId}, '${escAttr(gameName)}')" style="padding: var(--space-8) var(--space-lg); background:#4f46e5; color:white; border:none; border-radius:50px; cursor:pointer; white-space:nowrap;">Start Hunt</button>
                    </div>
                `;
            }).join('');
        }

        async function startAchievementHunt(appId, gameName) {
            if (!appId || !gameName) {
                alert('Please choose a game from your library.');
                return;
            }

            try {
                const response = await fetch('/api/achievement-hunt', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        app_id: parseInt(appId, 10),
                        game_name: gameName,
                        difficulty: 'medium',
                        target_achievements: 0
                    })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    closeAchievementHuntModal();
                    alert('Achievement hunt started!');
                    loadUserAchievements(true);
                } else {
                    alert(data.error || 'Failed to start hunt');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }
        
        // Initialize auth status on page load
        document.addEventListener('DOMContentLoaded', () => {
            console.log('🚀 Page loaded, checking auth status...');
            initPresenceToggle();
            const topbarLoginBtn = document.getElementById('topbar-login-btn');
            if (topbarLoginBtn) topbarLoginBtn.style.display = 'inline-block';
            checkAuthStatus();
            // Load dashboard data for the default page
            loadDashboard();

            const loginForm = document.getElementById('login-form');
            if (loginForm) loginForm.addEventListener('submit', handleLogin);

            const registerForm = document.getElementById('register-form');
            if (registerForm) registerForm.addEventListener('submit', handleRegister);

            const showRegisterLink = document.getElementById('show-register-link');
            if (showRegisterLink) showRegisterLink.addEventListener('click', (e) => { e.preventDefault(); switchAuthForm(false); });

            const showLoginLink = document.getElementById('show-login-link');
            if (showLoginLink) showLoginLink.addEventListener('click', (e) => { e.preventDefault(); switchAuthForm(true); });
        });

        // Configure toastr defaults if toastr is present; otherwise rely on showMessage fallback
        try {
            if (window.toastr && typeof window.toastr === 'object') {
                window.toastr.options = {
                    "closeButton": true,
                    "debug": false,
                    "newestOnTop": true,
                    "progressBar": true,
                    "positionClass": "toast-bottom-right",
                    "preventDuplicates": true,
                    "onclick": null,
                    "showDuration": "300",
                    "hideDuration": "1000",
                    "timeOut": "5000",
                    "extendedTimeOut": "1000",
                    "showEasing": "swing",
                    "hideEasing": "linear",
                    "showMethod": "fadeIn",
                    "hideMethod": "fadeOut"
                };
            }
        } catch (e) { console.warn('toastr config skipped:', e); }

        // Ensure toastr calls won't break if the CDN version requires jQuery or is otherwise faulty.
        (function(){
            const original = window.toastr;
            function isWorking() {
                try {
                    if (!original) return false;
                    if (typeof original.success !== 'function') return false;
                    // try a harmless call path check
                    return true;
                } catch (e) { return false; }
            }
            if (!isWorking()) {
                window.toastr = {
                    success: (msg) => showMessage(msg, 'success'),
                    error: (msg) => showMessage(msg, 'error'),
                    info: (msg) => showMessage(msg, 'info'),
                    warning: (msg) => showMessage(msg, 'warning')
                };
            }
        })();

        // ==============================================================================================
        // Friends Activity Functions
        // ==============================================================================================

        const PERSONA_STATE = ['Offline', 'Online', 'Busy', 'Away', 'Snooze', 'Looking to trade', 'Looking to play'];

        async function loadFriends() {
            const listDiv = document.getElementById('friends-list');
            listDiv.innerHTML = renderSkeletonList(4);
            try {
                const response = await fetch('/api/friends');
                if (response.status === 503) {
                    const data = await response.json();
                    updatePresenceCache([], data.error || 'Steam is not configured.');
                    renderPresenceContainers([], {
                        emptyTitle: 'Friend activity is unavailable.',
                        emptyDetail: data.error || 'Steam is not configured.'
                    });
                    listDiv.innerHTML = `<div style="padding:20px; color:var(--text-secondary);">⚠️ ${data.error || 'Steam not configured. Add your Steam ID in ⚙️ Settings.'}</div>`;
                    return;
                }
                const data = await response.json();
                updatePresenceCache(data.friends || []);
                void updatePresenceStrip();
                if (!data.friends || data.friends.length === 0) {
                    listDiv.innerHTML = '<div style="padding:20px; color:var(--text-secondary);">No friends found, or your friend list is private.</div>';
                    return;
                }
                let html = `<p style="color:var(--text-secondary); margin-bottom:15px;">${data.friends.length} friend${data.friends.length !== 1 ? 's' : ''}</p>`;
                data.friends.forEach(friend => {
                    const stateLabel = PERSONA_STATE[friend.personastate] || 'Offline';
                    const stateColor = friend.personastate > 0 ? '#10b981' : 'var(--text-secondary)';
                    const avatar = friend.avatarfull
                        ? `<img src="${friend.avatarfull}" style="width:40px;height:40px;border-radius:var(--radius-xs,6px);object-fit:cover;margin-right:12px;" loading="lazy">`
                        : `<span style="width:40px;height:40px;border-radius:var(--radius-xs,6px);background:var(--card-border);display:inline-block;margin-right:12px;"></span>`;
                    const inGame = friend.current_game
                        ? `<span style="display:inline-block;margin-left:8px;padding:2px 8px;border-radius:10px;background:#1b2838;color:#c7d5e0;font-size:0.8em;">🎮 ${friend.current_game}</span>`
                        : '';
                    let recentHtml = '';
                    if (friend.recently_played && friend.recently_played.length > 0) {
                        recentHtml = '<div style="margin-top:8px; font-size:0.85em; color:var(--text-secondary);">'
                            + '<span style="font-weight:600;">Recently played: </span>'
                            + friend.recently_played.map(g => {
                                const hrs = (g.playtime_2weeks / 60).toFixed(1);
                                return `<a href="https://store.steampowered.com/app/${g.appid}/" target="_blank" style="color:var(--tab-active-color); text-decoration:none;">${g.name}</a> (${hrs}h this week)`;
                            }).join(', ')
                            + '</div>';
                    }
                    html += `
                        <div class="list-item" style="display:flex; align-items:flex-start; padding:14px; margin-bottom:10px; background:var(--list-hover); border-radius:var(--radius,12px); cursor:default;">
                            ${avatar}
                            <div style="flex:1;">
                                <div>
                                    <strong>${friend.personaname}</strong>
                                    <span style="margin-left:8px; font-size:0.82em; color:${stateColor}; font-weight:600;">${stateLabel}</span>
                                    ${inGame}
                                </div>
                                ${recentHtml}
                            </div>
                        </div>`;
                });
                listDiv.innerHTML = html;
            } catch (error) {
                listDiv.innerHTML = `<div class="error">Error loading friends: ${error.message}</div>`;
            }
        }

        async function quickIgnoreGame(appId, gameName) {
            if (!confirm(`Add "${gameName}" to your No-Play List?`)) return;
            try {
                const response = await fetch('/api/ignored-games', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({app_id: appId, game_name: gameName, reason: ''})
                });
                const data = await response.json();
                if (response.ok) {
                    alert(`"${gameName}" added to No-Play List.`);
                } else {
                    alert(data.error || 'Failed to ignore game');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        let currentPlaylistGameId = null;
        let currentPlaylistGameName = null;
        let currentBacklogGameId = null;
        let currentBacklogGameName = null;

        async function quickAddToPlaylist(gameId, gameName) {
            currentPlaylistGameId = gameId;
            currentPlaylistGameName = gameName;
            
            const playlistList = document.getElementById('playlist-list');
            playlistList.innerHTML = renderSkeletonList(3);
            
            try {
                const response = await fetch('/api/playlists');
                if (!response.ok) {
                    const data = await response.json();
                    playlistList.innerHTML = `<p style="color:var(--error-red);">⚠️ ${data.error || 'Failed to load playlists'}</p>`;
                    document.getElementById('playlist-modal').style.display = 'flex';
                    return;
                }
                const data = await response.json();
                
                if (data.playlists && data.playlists.length > 0) {
                    playlistList.innerHTML = data.playlists.map(p => `
                        <button onclick="addToPlaylistAndClose('${p.name}')" style="padding:12px; background:var(--card-border); color:var(--text-primary); border:1px solid var(--input-border); border-radius:var(--radius-sm,8px); cursor:pointer; text-align:left; transition:all 0.2s; font-weight:500;">
                            📋 ${p.name} (${p.count} games)
                        </button>
                    `).join('');
                } else {
                    playlistList.innerHTML = '<p style="color:var(--text-secondary);">No playlists yet. Create one below.</p>';
                }
            } catch (error) {
                console.error('Playlist load error:', error);
                playlistList.innerHTML = `<p style="color:var(--error-red);">⚠️ Failed to load playlists: ${error.message}</p>`;
            }
            
            document.getElementById('new-playlist-input').value = '';
            document.getElementById('playlist-modal').style.display = 'flex';
        }

        async function addToPlaylistAndClose(playlistName) {
            if (!currentPlaylistGameId) return;
            
            try {
                const response = await fetch(`/api/playlists/${encodeURIComponent(playlistName)}/games`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({game_id: currentPlaylistGameId})
                });
                const data = await response.json();
                if (response.ok) {
                    showMessage(`✅ Added "${currentPlaylistGameName}" to "${playlistName}"!`, 'success');
                    closePlaylistModal();
                } else {
                    showMessage(data.error || 'Failed to add to playlist', 'error');
                }
            } catch (error) {
                console.error('Add to playlist error:', error);
                showMessage('Error: ' + error.message, 'error');
            }
        }

        async function createNewPlaylistFromModal() {
            const playlistName = document.getElementById('new-playlist-input').value.trim();
            if (!playlistName) {
                showMessage('Please enter a playlist name', 'error');
                return;
            }
            if (!currentPlaylistGameId) return;
            
            try {
                const response = await fetch(`/api/playlists/${encodeURIComponent(playlistName)}/games`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({game_id: currentPlaylistGameId})
                });
                const data = await response.json();
                if (response.ok) {
                    showMessage(`✅ Created playlist "${playlistName}" and added "${currentPlaylistGameName}"!`, 'success');
                    closePlaylistModal();
                } else {
                    showMessage(data.error || 'Failed to create playlist', 'error');
                }
            } catch (error) {
                console.error('Create playlist error:', error);
                showMessage('Error: ' + error.message, 'error');
            }
        }

        function closePlaylistModal() {
            document.getElementById('playlist-modal').style.display = 'none';
            currentPlaylistGameId = null;
            currentPlaylistGameName = null;
        }

        async function quickAddToBacklog(gameId, gameName) {
            currentBacklogGameId = gameId;
            currentBacklogGameName = gameName;
            document.getElementById('backlog-modal-title').textContent = `📚 Add "${gameName}" to List`;
            try {
                await ensureBacklogCollectionsLoaded();
            } catch (error) {
                showMessage(`Failed to load lists: ${error.message}`, 'error');
            }
            populateBacklogModalCollections(activeBacklogId);
            document.getElementById('backlog-modal').style.display = 'flex';
        }

        async function selectBacklogStatus(status) {
            if (!currentBacklogGameId) return;
            const collectionId = document.getElementById('backlog-modal-collection')?.value || activeBacklogId;
            const collection = backlogCollectionsCache.find(backlog => backlog.id === collectionId) || null;
            
            try {
                const updated = await updateBacklogEntryStatus(currentBacklogGameId, status, collectionId);
                if (updated) {
                    const statusLabel = status.replace(/_/g, ' ').charAt(0).toUpperCase() + status.replace(/_/g, ' ').slice(1);
                    const backlogLabel = collection?.name ? ` in "${collection.name}"` : '';
                    showMessage(`✅ Added "${currentBacklogGameName}" to list${backlogLabel} as "${statusLabel}"!`, 'success');
                    closeBacklogModal();
                    if (activeBacklogId && collectionId === activeBacklogId && document.getElementById('backlog-tab')?.classList.contains('active')) {
                        await loadBacklog();
                    }
                } else {
                    showMessage('Failed to add to list', 'error');
                }
            } catch (error) {
                console.error('Add to list error:', error);
                showMessage('Error: ' + error.message, 'error');
            }
        }

        function closeBacklogModal() {
            document.getElementById('backlog-modal').style.display = 'none';
            currentBacklogGameId = null;
            currentBacklogGameName = null;
            populateBacklogModalCollections(activeBacklogId);
        }

        // ==============================================================================================
        // Recommendations Functions
        // ==============================================================================================

        function renderRecommendationsList() {
            const listDiv = document.getElementById('recommendations-list');
            const recs = filterGamesByControls(_recommendationsData, 'rec-search', 'rec-platform');
            if (!_recommendationsData.length) {
                listDiv.innerHTML = '<div style="padding:20px; color:var(--text-secondary);">No recommendations yet. Play some games and come back!</div>';
                return;
            }
            if (!recs.length) {
                listDiv.innerHTML = '<div style="padding:20px; color:var(--text-secondary);">No recommendations match your current filters.</div>';
                return;
            }

            let html = `<p style="color:var(--text-secondary); margin-bottom:15px;">${recs.length} recommendation${recs.length !== 1 ? 's' : ''}</p>`;
            const appIds = [];
            recs.forEach((game, idx) => {
                const appId = game.appid || game.app_id || 0;
                appIds.push(appId);
                const safeName = escAttr(game.name);
                const scoreStars = '⭐'.repeat(Math.min(Math.round(game.recommendation_score), 5));
                const platformBadges = renderInlinePlatformBadges(game);
                html += `
                    <div class="list-item" style="cursor:pointer; padding:14px; margin-bottom:10px; background:var(--list-hover); border-radius:var(--radius,12px);"
                         onclick="showGameDetails(${appId}, '${safeName}', ${game.playtime_hours || 0}, '')">
                        <div style="display:flex; gap:12px; align-items:flex-start; flex:1; min-width:0;">
                            ${renderGameListThumb(appId, game.name)}
                            <div style="flex:1; min-width:0;">
                            <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <span style="background:linear-gradient(135deg,#4f46e5,#7c3aed); color:white; border-radius:50%; width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; font-weight:700; font-size:0.9em; flex-shrink:0;">${idx + 1}</span>
                                <strong class="list-item-title">${game.name}</strong>
                                <span style="font-size:0.85em; color:var(--text-secondary);">${game.playtime_hours > 0 ? game.playtime_hours + 'h played' : 'Never played'}</span>
                                ${scoreStars ? `<span style="font-size:0.85em; color:#fbbf24;">${scoreStars}</span>` : ''}
                            </div>
                            ${platformBadges ? `<div class="game-inline-meta" style="margin-top:6px; padding-left:38px;">${platformBadges}</div>` : ''}
                            <div style="margin-top:6px; font-size:0.85em; color:var(--text-secondary); padding-left:38px;">
                                💡 ${game.recommendation_reason || 'Unplayed game'}
                            </div>
                            <div style="display:flex; gap:8px; align-items:center; margin-top:4px; padding-left:38px;">
                            <a href="https://store.steampowered.com/app/${appId}/" target="_blank" onclick="event.stopPropagation()" style="font-size:0.8em; color:var(--tab-active-color); text-decoration:none;">Steam →</a>
                            <span onclick="event.stopPropagation(); toggleFavorite(${appId})" style="cursor:pointer; font-size:1.1em;" title="Add to favorites">☆</span>
                            <span onclick="event.stopPropagation(); quickAddToBacklog('${game.game_id || appId}', '${safeName}')" style="cursor:pointer; font-size:1.0em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" title="Add to List">📚</span>
                            <span onclick="event.stopPropagation(); quickIgnoreGame(${appId}, '${safeName}')" style="cursor:pointer; font-size:1.0em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" title="Ignore">🚫</span>
                            </div>
                            </div>
                        </div>
                    </div>`;
            });
            listDiv.innerHTML = html;
            preloadGameDetails(appIds).catch(err => console.log('Pre-load complete or errored'));
        }

        async function loadRecommendations() {
            const listDiv = document.getElementById('recommendations-list');
            const count = document.getElementById('rec-count').value;
            const platform = document.getElementById('rec-platform').value;
            const budget = document.getElementById('rec-budget').value;
            const includeNew = document.getElementById('rec-new-releases').checked;
            
            listDiv.innerHTML = renderSkeletonList(parseInt(count) || 5);
            try {
                let url = `/api/recommendations?count=${count}&refresh_seed=${Date.now()}`;
                if (platform) {
                    url += `&platforms=${encodeURIComponent(platform)}`;
                }
                if (budget) {
                    url += `&max_budget=${encodeURIComponent(budget)}`;
                }
                if (includeNew) {
                    url += `&include_new=true`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                if (response.status === 400) {
                    listDiv.innerHTML = `<div style="padding:20px; color:var(--text-secondary);">⚠️ ${data.error || 'Not initialized. Add your Steam ID in ⚙️ Settings.'}</div>`;
                    return;
                }
                _recommendationsData = data.recommendations || [];
                renderRecommendationsList();
            } catch (error) {
                listDiv.innerHTML = `<div class="error">Error loading recommendations: ${error.message}</div>`;
            }
        }

// ==============================================================================================
        // User Profile Card helpers
        // ==============================================================================================

        function buildUserCard(card, actions) {
            const initials = (card.display_name || card.username || '?')[0].toUpperCase();
            const avatar = card.avatar_url
                ? `<img class="user-card-avatar" src="${card.avatar_url.replace(/"/g,'%22').replace(/'/g,'%27')}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
                   <div class="user-card-avatar-placeholder" style="display:none">${initials}</div>`
                : `<div class="user-card-avatar-placeholder">${initials}</div>`;
            const roles = (card.roles || []).map(r =>
                `<span class="user-card-badge${r === 'admin' ? ' admin' : ''}">${r}</span>`
            ).join('');
            const stats = card.stats || {};
            const actionsHtml = (actions || []).map(a =>
                `<button onclick="${a.onclick}" style="background:${a.bg || 'var(--card-border)'}; color:${a.color || 'var(--text-primary)'};">${a.label}</button>`
            ).join('');
            return `
                <div class="user-card">
                    <div class="user-card-header">
                        ${avatar}
                        <div class="user-card-info">
                            <div class="user-card-name">${card.display_name || card.username}</div>
                            ${card.display_name && card.display_name !== card.username ? `<div class="user-card-username">@${card.username}</div>` : ''}
                            ${roles ? `<div class="user-card-badges" style="margin-top:4px">${roles}</div>` : ''}
                        </div>
                    </div>
                    ${card.bio ? `<div class="user-card-bio">"${card.bio}"</div>` : ''}
                    <div class="user-card-stats">
                        <div>
                            <div class="user-card-stat-value">${(stats.total_playtime_hours || 0).toLocaleString()}h</div>
                            <div class="user-card-stat-label">Playtime</div>
                        </div>
                        <div>
                            <div class="user-card-stat-value">${(stats.total_games || 0).toLocaleString()}</div>
                            <div class="user-card-stat-label">Games</div>
                        </div>
                        <div>
                            <div class="user-card-stat-value">${(stats.total_achievements || 0).toLocaleString()}</div>
                            <div class="user-card-stat-label">Achievements</div>
                        </div>
                    </div>
                    ${actionsHtml ? `<div class="user-card-actions">${actionsHtml}</div>` : ''}
                </div>`;
        }

        // ==============================================================================================
        // GAPI In-app Friends
        // ==============================================================================================

        async function loadAppFriends() {
            const grid = document.getElementById('app-friends-list');
            const reqSection = document.getElementById('friend-requests-section');
            const reqList = document.getElementById('friend-requests-list');
            grid.innerHTML = renderSkeletonList(3);
            try {
                const resp = await fetch('/api/app-friends');
                if (!resp.ok) { grid.innerHTML = '<div class="loading">Not available (no DB).</div>'; return; }
                const data = await resp.json();
                // Pending received requests
                if (data.received && data.received.length > 0) {
                    reqSection.style.display = 'block';
                    reqList.innerHTML = data.received.map(r => `
                        <div style="display:flex; align-items:center; gap:10px; padding:10px; background:var(--list-hover); border-radius:var(--radius-sm,8px); margin-bottom:8px;">
                            <strong>${r.display_name}</strong><span style="color:var(--text-secondary);">(@${r.username})</span>
                            <button onclick="respondFriendRequest('${r.username}', true)" style="padding:5px 14px; background:#10b981; color:white; border:none; border-radius:50px; cursor:pointer; font-weight:600; font-family:inherit;">✅ Accept</button>
                            <button onclick="respondFriendRequest('${r.username}', false)" style="padding:5px 14px; background:#ef4444; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-weight:600;">❌ Decline</button>
                        </div>`).join('');
                } else {
                    reqSection.style.display = 'none';
                }
                // Friend cards
                if (!data.friends || data.friends.length === 0) {
                    let hint = data.sent && data.sent.length > 0
                        ? `<div style="color:var(--text-secondary); font-size:0.9em; margin-top:8px;">⏳ Pending sent requests: ${data.sent.map(s => s.username).join(', ')}</div>`
                        : '';
                    grid.innerHTML = `<div style="color:var(--text-secondary);">No GAPI friends yet. Add someone above!${hint}</div>`;
                    return;
                }
                // Fetch full cards for each friend
                const cards = await Promise.all(data.friends.map(f =>
                    fetch(`/api/user/${encodeURIComponent(f.username)}/card`).then(r => r.ok ? r.json() : f)
                ));
                grid.innerHTML = cards.map(card =>
                    buildUserCard(card, [
                        { label: '👤 View Card', onclick: `showUserCardModal('${card.username}')`, bg: 'linear-gradient(135deg,#4f46e5,#7c3aed)', color: 'white' },
                        { label: '❌ Remove', onclick: `removeAppFriend('${card.username}')`, bg: 'rgba(239,68,68,0.1)', color: '#ef4444' },
                    ])
                ).join('');
            } catch (err) {
                grid.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        async function sendFriendRequest(targetUsername) {
            // If no username provided, get from input field (friends tab)
            let username = targetUsername;
            if (!username) {
                const input = document.getElementById('friend-request-input');
                username = (input.value || '').trim();
                if (!username) return;
            }
            
            try {
                const resp = await fetch('/api/app-friends/request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    if (!targetUsername) {
                        // Clear input field if called from friends form
                        const input = document.getElementById('friend-request-input');
                        input.value = '';
                    }
                    showMessage(data.message || `Friend request sent to ${username}!`, 'success');
                    loadAppFriends();
                } else {
                    showMessage(data.error || 'Failed to send friend request', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function respondFriendRequest(username, accept) {
            try {
                const resp = await fetch('/api/app-friends/respond', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, accept }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage(accept ? '✅ Friend request accepted!' : 'Request declined.', accept ? 'success' : 'info');
                    loadAppFriends();
                } else {
                    showMessage(data.error || 'Failed', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function removeAppFriend(username) {
            if (!confirm(`Remove ${username} from your GAPI friends?`)) return;
            try {
                const resp = await fetch('/api/app-friends/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username }),
                });
                if (resp.ok) {
                    showMessage('Friend removed.', 'info');
                    loadAppFriends();
                } else {
                    const d = await resp.json();
                    showMessage(d.error || 'Failed', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        // User card modal
        async function showUserCardModal(username) {
            try {
                const resp = await fetch(`/api/user/${encodeURIComponent(username)}/card`);
                if (!resp.ok) { showMessage('User not found', 'error'); return; }
                const card = await resp.json();
                const html = buildUserCard(card, []);
                // Reuse share modal as a simple card display
                const modalContent = document.getElementById('share-text');
                if (modalContent) {
                    // Build a mini modal-like overlay
                    const overlay = document.createElement('div');
                    overlay.id = 'user-card-overlay';
                    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:3000;display:flex;align-items:center;justify-content:center;';
                    overlay.innerHTML = `
                        <div style="background:var(--card-bg);border-radius:var(--radius-lg,16px);padding:28px;max-width:360px;width:90%;box-shadow:var(--shadow-xl,0 8px 32px rgba(0,0,0,0.3));">
                            ${html}
                            <div style="margin-top:14px;text-align:right;">
                                <button onclick="document.getElementById('user-card-overlay').remove()"
                                        style="padding:8px 20px;background:var(--card-border);color:var(--text-primary);border:none;border-radius:var(--radius-sm,8px);cursor:pointer;">Close</button>
                            </div>
                        </div>`;
                    document.body.appendChild(overlay);
                    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
                }
            } catch (err) {
                showMessage('Error loading card: ' + err.message, 'error');
            }
        }

        // ==============================================================================================
        // Profile Card Settings
        // ==============================================================================================

        async function loadMyProfileCard() {
            try {
                const resp = await fetch('/api/auth/current');
                if (!resp.ok) return;
                const me = await resp.json();
                const username = me.username;
                if (!username) return;
                const cardResp = await fetch(`/api/user/${encodeURIComponent(username)}/card`);
                if (!cardResp.ok) return;
                const card = await cardResp.json();
                // Populate form fields
                document.getElementById('profile-display-name').value = card.display_name !== card.username ? card.display_name : '';
                document.getElementById('profile-bio').value = card.bio || '';
                document.getElementById('profile-avatar-url').value = card.avatar_url || '';
                // Show preview
                const preview = document.getElementById('my-profile-card-preview');
                if (preview) preview.innerHTML = buildUserCard(card, []);
            } catch (err) {
                console.log('Profile card load error:', err);
            }
        }

        async function saveProfileCard() {
            const display_name = document.getElementById('profile-display-name').value.trim();
            const bio = document.getElementById('profile-bio').value.trim();
            const avatar_url = document.getElementById('profile-avatar-url').value.trim();
            const msgEl = document.getElementById('profile-card-message');
            try {
                const resp = await fetch('/api/user/profile', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ display_name: display_name || null, bio: bio || null, avatar_url: avatar_url || null }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    msgEl.style.display = 'block';
                    msgEl.style.background = 'rgba(16,185,129,0.12)';
                    msgEl.style.color = '#10b981';
                    msgEl.textContent = '✅ Profile card saved!';
                    loadMyProfileCard();
                    setTimeout(() => { msgEl.style.display = 'none'; }, 3000);
                } else {
                    msgEl.style.display = 'block';
                    msgEl.style.background = 'rgba(239,68,68,0.1)';
                    msgEl.style.color = '#ef4444';
                    msgEl.textContent = data.error || 'Failed to save';
                }
            } catch (err) {
                msgEl.style.display = 'block';
                msgEl.style.background = 'rgba(239,68,68,0.1)';
                msgEl.style.color = '#ef4444';
                msgEl.textContent = 'Error: ' + err.message;
            }
        }

        // ==============================================================================================
        // Leaderboard
        // ==============================================================================================

        async function loadLeaderboard(options = {}) {
            const listId = options.listId || 'leaderboard-list';
            const metricId = options.metricId || 'leaderboard-metric';
            const limit = Number(options.limit || 20);
            const listDiv = document.getElementById(listId);
            const metricSelect = document.getElementById(metricId);
            if (!listDiv || !metricSelect) return;
            const metric = metricSelect.value;
            const labels = { playtime: '⏱️ h played', games: '🎮 games', achievements: '🏅 achievements' };
            listDiv.innerHTML = renderSkeletonList(10);
            try {
                const resp = await fetch(`/api/leaderboard?metric=${metric}&limit=${limit}`);
                if (!resp.ok) { listDiv.innerHTML = '<div class="loading">Leaderboard not available (no DB).</div>'; return; }
                const data = await resp.json();
                if (!data.entries || data.entries.length === 0) {
                    listDiv.innerHTML = '<div style="color:var(--text-secondary);">No data yet. Sync libraries to populate the leaderboard.</div>';
                    return;
                }
                const medals = ['🥇','🥈','🥉'];
                listDiv.innerHTML = data.entries.map((e, i) => `
                    <div class="list-item" style="display:flex; align-items:center; gap:14px; padding:14px; cursor:pointer;"
                         onclick="showUserCardModal('${e.username}')">
                        <span style="font-size:1.5em; width:36px; text-align:center; flex-shrink:0;">${medals[i] || ('#' + e.rank)}</span>
                        <div style="flex:1;">
                            <strong>${e.username}</strong>
                        </div>
                        <div style="font-weight:700; color:var(--tab-active-color); font-size:1.1em;">
                            ${e.score.toLocaleString()} <small style="font-weight:400; color:var(--text-secondary);">${labels[metric] || ''}</small>
                        </div>
                    </div>`).join('');
            } catch (err) {
                listDiv.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        // ==============================================================================================
        // Chat
        // ==============================================================================================

        function getChatRoomDisplayParts(option) {
            const raw = String(option?.textContent || option?.value || '').trim();
            const match = raw.match(/^(\S+)\s+(.+)$/);
            if (match) {
                return { prefix: match[1], label: match[2] };
            }
            return { prefix: '#', label: raw || 'room' };
        }

        function updateChatRoomHeader() {
            const roomSelect = document.getElementById('chat-room');
            if (!roomSelect) return;
            const activeOption = roomSelect.options[roomSelect.selectedIndex];
            const iconEl = document.querySelector('.chat-main-room-icon');
            const labelEl = document.getElementById('chat-active-room-label');
            const metaEl = document.getElementById('chat-active-room-meta');
            const parts = getChatRoomDisplayParts(activeOption);
            if (iconEl) iconEl.textContent = parts.prefix;
            if (labelEl) labelEl.textContent = activeOption ? activeOption.textContent.trim() : '# room';
            if (metaEl) metaEl.textContent = `Room · ${parts.label} conversation`;
        }

        function renderChatRoomList() {
            const roomSelect = document.getElementById('chat-room');
            const roomList = document.getElementById('chat-room-list');
            if (!roomSelect || !roomList) return;
            roomList.innerHTML = '';

            Array.from(roomSelect.options).forEach(option => {
                const parts = getChatRoomDisplayParts(option);
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'chat-room-item' + (option.value === roomSelect.value ? ' active' : '');

                const prefix = document.createElement('span');
                prefix.className = 'chat-room-item-prefix';
                prefix.textContent = parts.prefix;

                const textWrap = document.createElement('span');
                textWrap.className = 'chat-room-item-text';

                const name = document.createElement('span');
                name.className = 'chat-room-item-name';
                name.textContent = parts.label;

                const meta = document.createElement('span');
                meta.className = 'chat-room-item-meta';
                meta.textContent = option.value === roomSelect.value ? 'Active room' : 'Click to switch';

                textWrap.appendChild(name);
                textWrap.appendChild(meta);
                button.appendChild(prefix);
                button.appendChild(textWrap);
                button.addEventListener('click', () => {
                    if (roomSelect.value !== option.value) {
                        roomSelect.value = option.value;
                    }
                    switchChatRoom();
                });
                roomList.appendChild(button);
            });

            updateChatRoomHeader();
        }

        let chatPollInterval = null;
        let onlineUsersPollInterval = null;
        let sessionsPollInterval = null;
        let activeLiveSessionId = null;
        let activeSessionEventSource = null;
        let liveSessionDiscordGuilds = [];
        let liveSessionLootboxTimer = null;
        let liveSessionLootboxSessionId = null;
        let chatLastId = 0;
        let chatOldestId = null;
        let hasMoreOldMessages = true;
        let editingMessageId = null;
        let replyToMessageId = null;
        let emojiPickerCallback = null;
        const commonEmojis = ['😀', '😂', '😍', '🤔', '👍', '👎', '❤️', '🔥', '✅', '❌', '🎮', '🎯', '🎲', '🏆', '⭐', '💯', '🙌', '👏', '🤝', '💪', '🎉', '🎊', '😎', '🤩', '😜', '😅', '😭', '😤', '😱', '🤯', '👀', '🙏', '💀', '🤡', '👻', '💩', '🤖', '👾', '🍕', '🍔', '🍺', '☕', '🌟', '🌈', '⚡', '💥', '✨', '🚀', '🎁', '📱', '💻', '🎵', '🎸', '🎬', '📚', '💼', '⚽', '🏀', '🎾', '🏈', '🏐', '🏓', '🎳', '🎰'];
        
        // Typing indicators
        let typingPollInterval = null;
        let typingTimeoutId = null;
        let isCurrentlyTyping = false;

        // Emoji picker functions
        function openEmojiPicker() {
            const modal = document.getElementById('emoji-picker-modal');
            if (!modal) return;
            initEmojiGrid();
            emojiPickerCallback = (emoji) => {
                const input = document.getElementById('chat-input');
                input.value += emoji;
                input.focus();
            };
            modal.style.display = 'flex';
        }

        function openEmojiPickerForMessage(messageId) {
            const modal = document.getElementById('emoji-picker-modal');
            if (!modal) return;
            initEmojiGrid();
            emojiPickerCallback = (emoji) => {
                addReaction(messageId, emoji);
            };
            modal.style.display = 'flex';
        }

        function closeEmojiPicker() {
            const modal = document.getElementById('emoji-picker-modal');
            if (modal) modal.style.display = 'none';
            emojiPickerCallback = null;
        }

        function initEmojiGrid() {
            const grid = document.getElementById('emoji-grid');
            if (!grid || grid.children.length > 0) return;
            commonEmojis.forEach(emoji => {
                const btn = document.createElement('button');
                btn.textContent = emoji;
                btn.style.cssText = 'padding:8px; border:1px solid var(--input-border); border-radius:var(--radius-xs,6px); background:var(--card-bg); cursor:pointer; font-size:1.5em; transition:all 0.2s;';
                btn.onmouseover = () => btn.style.transform = 'scale(1.2)';
                btn.onmouseout = () => btn.style.transform = 'scale(1)';
                btn.onclick = () => {
                    if (emojiPickerCallback) emojiPickerCallback(emoji);
                    closeEmojiPicker();
                };
                grid.appendChild(btn);
            });
        }

        // Message action functions
        function showMessageActions(messageId, isMe) {
            if (!isMe) return;
            const actions = document.getElementById(`msg-actions-${messageId}`);
            if (actions) actions.style.display = 'flex';
        }

        function hideMessageActions(messageId) {
            const actions = document.getElementById(`msg-actions-${messageId}`);
            if (actions) actions.style.display = 'none';
        }

        async function addReaction(messageId, emoji) {
            try {
                const resp = await fetch(`/api/chat/message/${messageId}/react`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({emoji})
                });
                if (resp.ok) {
                    await loadChatMessages(true);
                } else {
                    const data = await resp.json();
                    showMessage(data.error || 'Failed to add reaction', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function toggleReaction(messageId, emoji) {
            try {
                const resp = await fetch(`/api/chat/message/${messageId}/react?emoji=${encodeURIComponent(emoji)}`, {
                    method: 'DELETE'
                });
                if (resp.ok) {
                    await loadChatMessages(true);
                } else {
                    const data = await resp.json();
                    showMessage(data.error || 'Failed to toggle reaction', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function editChatMessage(messageId, currentText) {
            editingMessageId = messageId;
            const input = document.getElementById('chat-input');
            const sendBtn = document.getElementById('chat-send-btn');
            const cancelBtn = document.getElementById('chat-cancel-edit-btn');
            
            input.value = currentText;
            input.focus();
            sendBtn.textContent = 'Save';
            cancelBtn.style.display = 'block';
        }

        async function cancelEditMessage() {
            editingMessageId = null;
            const input = document.getElementById('chat-input');
            const sendBtn = document.getElementById('chat-send-btn');
            const cancelBtn = document.getElementById('chat-cancel-edit-btn');
            
            input.value = '';
            sendBtn.textContent = 'Send';
            cancelBtn.style.display = 'none';
        }

        async function deleteChatMessage(messageId) {
            if (!confirm('Delete this message?')) return;
            try {
                const resp = await fetch(`/api/chat/message/${messageId}`, {
                    method: 'DELETE'
                });
                if (resp.ok) {
                    showMessage('Message deleted', 'success');
                    await loadChatMessages(false);
                } else {
                    const data = await resp.json();
                    showMessage(data.error || 'Failed to delete', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        // Typing indicators
        async function setTypingStatus(typing) {
            const room = document.getElementById('chat-room').value;
            try {
                await fetch('/api/chat/typing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room, typing }),
                });
            } catch (err) {
                console.error('Failed to set typing status:', err);
            }
        }

        function handleTypingInput() {
            // Clear any existing timeout
            if (typingTimeoutId) {
                clearTimeout(typingTimeoutId);
            }
            
            // Set typing to true if not already
            if (!isCurrentlyTyping) {
                isCurrentlyTyping = true;
                setTypingStatus(true);
            }
            
            // Set timeout to clear typing after 3 seconds of inactivity
            typingTimeoutId = setTimeout(() => {
                isCurrentlyTyping = false;
                setTypingStatus(false);
            }, 3000);
        }

        async function loadTypingUsers() {
            const room = document.getElementById('chat-room').value;
            try {
                const resp = await fetch(`/api/chat/typing/${encodeURIComponent(room)}`);
                if (resp.ok) {
                    const data = await resp.json();
                    showTypingIndicator(data.typing_users || []);
                }
            } catch (err) {
                console.error('Failed to load typing users:', err);
            }
        }

        function showTypingIndicator(typingUsers) {
            const indicator = document.getElementById('typing-indicator');
            if (!indicator) return;
            
            if (typingUsers.length === 0) {
                indicator.style.display = 'none';
                return;
            }
            
            indicator.style.display = 'block';
            let text;
            if (typingUsers.length === 1) {
                text = `${typingUsers[0]} is typing...`;
            } else if (typingUsers.length === 2) {
                text = `${typingUsers[0]} and ${typingUsers[1]} are typing...`;
            } else {
                text = `${typingUsers[0]}, ${typingUsers[1]} and ${typingUsers.length - 2} other${typingUsers.length > 3 ? 's' : ''} are typing...`;
            }
            indicator.textContent = text;
        }

        // Message threading / replies
        function startReply(messageId, sender, messagePreview) {
            replyToMessageId = messageId;
            const replyPreview = document.getElementById('reply-preview');
            if (!replyPreview) return;
            
            replyPreview.style.display = 'flex';
            replyPreview.innerHTML = `
                <div style="flex:1;">
                    <div style="font-weight:600; font-size:0.85em;">Replying to @${sender}</div>
                    <div style="font-size:0.8em; color:var(--text-secondary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${messagePreview}</div>
                </div>
                <button onclick="cancelReply()" style="background:none; border:none; color:var(--text-secondary); cursor:pointer; font-size:1.2em; padding:0 8px;">×</button>
            `;
            document.getElementById('chat-input').focus();
        }

        function cancelReply() {
            replyToMessageId = null;
            const replyPreview = document.getElementById('reply-preview');
            if (replyPreview) {
                replyPreview.style.display = 'none';
                replyPreview.innerHTML = '';
            }
        }

        // Pinned Messages Management
        let pinnedMessages = {};

        function togglePinMessage(messageId) {
            const room = document.getElementById('chat-room').value;
            if (!pinnedMessages[room]) {
                pinnedMessages[room] = [];
            }
            
            const roomPinned = pinnedMessages[room];
            const index = roomPinned.indexOf(messageId);
            
            if (index > -1) {
                roomPinned.splice(index, 1);
            } else {
                if (roomPinned.length >= 5) {
                    showMessage('Maximum 5 pinned messages per room', 'error');
                    return;
                }
                roomPinned.push(messageId);
            }
            
            updatePinnedCount();
            renderPinnedMessages();
        }

        function updatePinnedCount() {
            const room = document.getElementById('chat-room').value;
            const count = pinnedMessages[room]?.length || 0;
            document.getElementById('pinned-count').textContent = count;
        }

        function togglePinnedMessages() {
            const container = document.getElementById('pinned-messages-container');
            if (container.style.display === 'none') {
                container.style.display = 'block';
                renderPinnedMessages();
            } else {
                container.style.display = 'none';
            }
        }

        function renderPinnedMessages() {
            const room = document.getElementById('chat-room').value;
            const listDiv = document.getElementById('pinned-messages-list');
            const roomPinned = pinnedMessages[room] || [];
            
            if (roomPinned.length === 0) {
                listDiv.innerHTML = '<div style="color:var(--text-secondary); font-size:0.9em; padding:10px;text-align:center;">No pinned messages yet</div>';
                return;
            }
            
            let html = '';
            const messagesDiv = document.getElementById('chat-messages');
            
            roomPinned.forEach(messageId => {
                const msgElement = document.getElementById(`msg-${messageId}`);
                if (msgElement) {
                    const msgText = msgElement.innerText.substring(0, 100) || 'Message';
                    html += `<div style="padding:10px; background:rgba(255,255,255,0.05); border-radius:var(--radius-xs,6px); margin-bottom:8px; cursor:pointer; border-left:3px solid #ef4444;" onclick="scrollToMessage(${messageId})">
                        <div style="font-size:0.85em; color:var(--text-primary);max-width:100%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${msgText}</div>
                        <div style="font-size:0.75em; color:var(--text-secondary); margin-top:4px;">
                            <button onclick="event.stopPropagation(); removePinMessage(${messageId})" style="background:none; border:none; color:#ef4444; cursor:pointer; text-decoration:underline; padding:0;">Unpin</button>
                        </div>
                    </div>`;
                }
            });
            
            listDiv.innerHTML = html;
        }

        function removePinMessage(messageId) {
            const room = document.getElementById('chat-room').value;
            if (pinnedMessages[room]) {
                pinnedMessages[room] = pinnedMessages[room].filter(id => id !== messageId);
                updatePinnedCount();
                renderPinnedMessages();
            }
        }

        function scrollToMessage(messageId) {
            const msgElement = document.getElementById(`msg-${messageId}`);
            if (msgElement) {
                msgElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                msgElement.style.animation = 'pulse 0.5s';
            }
        }

        // Message Search
        function filterChatMessages() {
            const searchText = document.getElementById('chat-search').value.toLowerCase();
            const messagesDiv = document.getElementById('chat-messages');
            const allMessages = messagesDiv.querySelectorAll('[id^="msg-"]');
            
            allMessages.forEach(msg => {
                const text = msg.innerText.toLowerCase();
                if (searchText === '' || text.includes(searchText)) {
                    msg.style.display = 'flex';
                    msg.style.opacity = '1';
                } else {
                    msg.style.display = 'none';
                }
            });
            
            if (searchText && allMessages.length > 0) {
                const visibleCount = Array.from(allMessages).filter(m => m.style.display !== 'none').length;
                if (visibleCount === 0) {
                    messagesDiv.innerHTML += `<div style="color:var(--text-secondary); text-align:center; padding:20px; grid-column:1/-1;">No messages match "${searchText}"</div>`;
                }
            }
        }

        // Text formatting helpers
        function linkifyText(text) {
            // Detect URLs and make them clickable
            const urlPattern = /(https?:\/\/[^\s<]+[^<.,:;"'\]\s])/gi;
            return text.replace(urlPattern, (url) => {
                return `<a href="${url}" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:underline; opacity:0.9;">${url}</a>`;
            });
        }

        function parseMarkdown(text) {
            // Simple markdown parser for common formatting
            let formatted = text;
            
            // Code blocks: `code`
            formatted = formatted.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:var(--radius-tag,4px); font-family:monospace; font-size:0.9em;">$1</code>');
            
            // Bold: **text** or __text__
            formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            formatted = formatted.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            
            // Italic: *text* or _text_
            formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            formatted = formatted.replace(/_([^_]+)_/g, '<em>$1</em>');
            
            // Strikethrough: ~~text~~
            formatted = formatted.replace(/~~([^~]+)~~/g, '<del>$1</del>');
            
            return formatted;
        }

        function highlightMentions(text, currentUsername) {
            // Highlight @mentions - make current user's mention more prominent
            return text.replace(/@(\w+)/g, (match, username) => {
                const isMe = username === currentUsername;
                const bgColor = isMe ? 'rgba(102, 126, 234, 0.3)' : 'rgba(102, 126, 234, 0.15)';
                const fontWeight = isMe ? '700' : '600';
                return `<span style="background:${bgColor}; padding:2px 4px; border-radius:var(--radius-tag,4px); font-weight:${fontWeight};">@${username}</span>`;
            });
        }

        function formatMessageText(text, isInReplyContext = false, currentUsername = '') {
            // Escape HTML first
            let formatted = escapeHtml(text);
            
            // Apply markdown formatting (unless in reply context where we want plain text)
            if (!isInReplyContext) {
                formatted = parseMarkdown(formatted);
                formatted = highlightMentions(formatted, currentUsername);
                formatted = linkifyText(formatted);
            }
            
            return formatted;
        }

        function renderChatMessage(msg, isMe, myUsername) {
            const messagesDiv = document.getElementById('chat-messages');
            const time = msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
            const editedLabel = msg.edited_at ? ' <span style=\"font-size:0.7em; opacity:0.7;\">(edited)</span>' : '';
            
            // Build reply context if this is a reply
            let replyContextHtml = '';
            if (msg.reply_to) {
                const replyMsg = escapeHtml(msg.reply_to.message);
                replyContextHtml = `<div style=\"padding:6px 10px; margin-bottom:6px; border-left:3px solid ${isMe?'rgba(255,255,255,0.5)':'var(--input-border)'}; background:${isMe?'rgba(0,0,0,0.2)':'var(--input-bg)'}; border-radius:var(--radius-xs,6px); font-size:0.8em; opacity:0.9;\">
                    <div style=\"font-weight:600; margin-bottom:2px;\">@${escapeHtml(msg.reply_to.sender)}</div>
                    <div style=\"opacity:0.8;\">${replyMsg}</div>
                </div>`;
            }
            
            // Build reactions display
            let reactionsHtml = '';
            if (msg.reactions && Object.keys(msg.reactions).length > 0) {
                reactionsHtml = '<div style=\"display:flex; gap:4px; flex-wrap:wrap; margin-top:6px;\">';
                for (const [emoji, users] of Object.entries(msg.reactions)) {
                    const hasReacted = users.some(u => u.username === myUsername);
                    const userList = users.map(u => u.username).join(', ');
                    reactionsHtml += `<button onclick=\"toggleReaction(${msg.id}, '${emoji}')\" title=\"${userList}\" style=\"padding:3px 8px; border-radius:var(--radius,12px); border:1px solid ${hasReacted ? '#4f46e5' : 'var(--input-border)'}; background:${hasReacted ? 'rgba(79,70,229,0.08)' : 'var(--card-bg)'}; color:var(--text-primary); cursor:pointer; font-size:0.85em; display:flex; align-items:center; gap:4px;\"><span>${emoji}</span><span style=\"font-size:0.8em;\">${users.length}</span></button>`;
                }
                reactionsHtml += `<button onclick=\"openEmojiPickerForMessage(${msg.id})\" style=\"padding:3px 8px; border-radius:var(--radius,12px); border:1px solid var(--input-border); background:var(--card-bg); color:var(--text-secondary); cursor:pointer; font-size:0.85em;\">+</button>`;
                reactionsHtml += '</div>';
            } else {
                reactionsHtml = `<div style=\"margin-top:6px;\"><button onclick=\"openEmojiPickerForMessage(${msg.id})\" style=\"padding:3px 8px; border-radius:var(--radius,12px); border:1px solid var(--input-border); background:var(--card-bg); color:var(--text-secondary); cursor:pointer; font-size:0.75em; opacity:0.6;\">Add reaction</button></div>`;
            }
            
            // Format message text with markdown, links, and mentions
            const formattedMessage = formatMessageText(msg.message, false, myUsername);
            const fullDateTime = msg.created_at ? new Date(msg.created_at).toLocaleString() : '';
            
            const escapedMessage = escAttr(msg.message);
            const escapedSender = escAttr(msg.sender);
            const escapedPreview = escAttr(msg.message.substring(0, 50));
            
            const bubble = document.createElement('div');
            bubble.id = `msg-${msg.id}`;
            bubble.style.cssText = `display:flex; flex-direction:column; align-items:${isMe?'flex-end':'flex-start'}; gap:2px; position:relative; padding:4px 0;`;
            bubble.innerHTML = `
                <span style=\"font-size:0.75em; color:var(--text-secondary);\">${isMe ? 'You' : escapeHtml(msg.sender)} · ${time}</span>
                <div class=\"chat-message-wrapper\" style=\"position:relative; max-width:75%;\" onmouseenter=\"showMessageActions(${msg.id}, ${isMe})\" onmouseleave=\"hideMessageActions(${msg.id})\">
                    <div title=\"${fullDateTime}\" style=\"padding:10px 14px; border-radius:${isMe?'16px 16px 4px 16px':'16px 16px 16px 4px'};
                         background:${isMe?'linear-gradient(135deg,#4f46e5,#7c3aed)':'var(--list-hover)'};
                         color:${isMe?'white':'var(--text-primary)'}; word-break:break-word; font-size:0.95em; position:relative; cursor:default;\">
                        ${replyContextHtml}
                        ${formattedMessage}${editedLabel}
                    </div>
                    <div id=\"msg-actions-${msg.id}\" class=\"message-actions\" style=\"display:none; position:absolute; top:-8px; ${isMe?'right':'left'}:-8px; background:var(--card-bg); border:1px solid var(--input-border); border-radius:var(--radius-sm,8px); padding:2px; box-shadow:0 2px 8px rgba(0,0,0,0.15); z-index:10;\">
                        <button onclick=\"startReply(${msg.id}, '${escapedSender}', '${escapedPreview}')\" title=\"Reply\" style=\"padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;\">↩️</button>
                        <button onclick=\"togglePinMessage(${msg.id})\" title=\"Pin message\" style=\"padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;\">📌</button>
                        ${isMe ? `<button onclick=\"editChatMessage(${msg.id}, '${escapedMessage}')\" title=\"Edit\" style=\"padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;\">✏️</button>
                        <button onclick=\"deleteChatMessage(${msg.id})\" title=\"Delete\" style=\"padding:4px 8px; border:none; background:transparent; cursor:pointer; font-size:0.9em;\">🗑️</button>` : ''}
                    </div>
                    ${reactionsHtml}
                </div>`;
            messagesDiv.appendChild(bubble);
            return bubble;
        }

        async function loadChatMessages(append) {
            const messagesDiv = document.getElementById('chat-messages');
            const room = document.getElementById('chat-room').value;
            try {
                const resp = await fetch(`/api/chat/messages?room=${encodeURIComponent(room)}&since_id=${chatLastId}&limit=50`);
                if (!resp.ok) {
                    if (!append) messagesDiv.innerHTML = '<div class="loading">Chat not available (no DB).</div>';
                    return;
                }
                const data = await resp.json();
                if (!data.messages || data.messages.length === 0) {
                    if (!append) messagesDiv.innerHTML = '<div style="color:var(--text-secondary); text-align:center; padding:20px;">No messages yet. Say hello! 👋</div>';
                    return;
                }
                if (!append) {
                    messagesDiv.innerHTML = '';
                    chatOldestId = null;
                    hasMoreOldMessages = true;
                }
                const meResp = await fetch('/api/auth/current').catch(() => null);
                const me = meResp && meResp.ok ? await meResp.json().catch(() => ({})) : {};
                data.messages.forEach(msg => {
                    if (msg.id > chatLastId) chatLastId = msg.id;
                    if (chatOldestId === null || msg.id < chatOldestId) chatOldestId = msg.id;
                    const isMe = msg.sender === me.username;
                    renderChatMessage(msg, isMe, me.username);
                });
                
                // Add "Load older messages" button at top if there might be more messages
                if (!append && data.messages.length >= 50 && hasMoreOldMessages) {
                    const loadMoreBtn = document.createElement('button');
                    loadMoreBtn.id = 'load-more-btn';
                    loadMoreBtn.textContent = '↑ Load older messages';
                    loadMoreBtn.onclick = loadOlderMessages;
                    loadMoreBtn.style.cssText = 'width:100%; padding:8px; margin-bottom:8px; background:var(--input-border); color:var(--text-primary); border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-weight:600;';
                    messagesDiv.insertBefore(loadMoreBtn, messagesDiv.firstChild);
                }
                
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            } catch (err) {
                if (!append) messagesDiv.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        async function loadOlderMessages() {
            const messagesDiv = document.getElementById('chat-messages');
            const room = document.getElementById('chat-room').value;
            const loadMoreBtn = document.getElementById('load-more-btn');
            
            if (loadMoreBtn) loadMoreBtn.textContent = 'Loading...';
            
            try {
                const resp = await fetch(`/api/chat/messages?room=${encodeURIComponent(room)}&before_id=${chatOldestId}&limit=50`);
                if (!resp.ok) {
                    showMessage('Failed to load older messages', 'error');
                    if (loadMoreBtn) loadMoreBtn.textContent = '↑ Load older messages';
                    return;
                }
                const data = await resp.json();
                
                if (!data.messages || data.messages.length === 0) {
                    hasMoreOldMessages = false;
                    if (loadMoreBtn) loadMoreBtn.remove();
                    showMessage('No more messages to load', 'info');
                    return;
                }
                
                // Save current scroll position
                const scrollHeight = messagesDiv.scrollHeight;
                const scrollTop = messagesDiv.scrollTop;
                
                // Remove load more button temporarily
                if (loadMoreBtn) loadMoreBtn.remove();
                
                const meResp = await fetch('/api/auth/current').catch(() => null);
                const me = meResp && meResp.ok ? await meResp.json().catch(() => ({})) : {};
                
                // Render messages at the top (in reverse order to maintain chronological order)
                data.messages.reverse().forEach(msg => {
                    if (chatOldestId === null || msg.id < chatOldestId) chatOldestId = msg.id;
                    const isMe = msg.sender === me.username;
                    const bubble = renderChatMessage(msg, isMe, me.username);
                    // Insert at beginning (after load more button if it exists)
                    messagesDiv.insertBefore(bubble, messagesDiv.children[0]);
                });
                
                // Re-add load more button if there might be more messages
                if (data.messages.length >= 50) {
                    const newLoadMoreBtn = document.createElement('button');
                    newLoadMoreBtn.id = 'load-more-btn';
                    newLoadMoreBtn.textContent = '↑ Load older messages';
                    newLoadMoreBtn.onclick = loadOlderMessages;
                    newLoadMoreBtn.style.cssText = 'width:100%; padding:8px; margin-bottom:8px; background:var(--input-border); color:var(--text-primary); border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-weight:600;';
                    messagesDiv.insertBefore(newLoadMoreBtn, messagesDiv.firstChild);
                } else {
                    hasMoreOldMessages = false;
                }
                
                // Restore scroll position (adjusted for new content)
                const newScrollHeight = messagesDiv.scrollHeight;
                messagesDiv.scrollTop = scrollTop + (newScrollHeight - scrollHeight);
                
            } catch (err) {
                showMessage('Error loading older messages: ' + err.message, 'error');
                if (loadMoreBtn) loadMoreBtn.textContent = '↑ Load older messages';
            }
        }

        function switchChatRoom() {
            chatLastId = 0;
            chatOldestId = null;
            hasMoreOldMessages = true;
            const room = document.getElementById('chat-room').value;
            renderChatRoomList();
            
            // Update backend with current room
            fetch('/api/chat/update-room', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room }),
            }).catch(err => console.error('Failed to update room:', err));
            
            loadChatMessages(false);
            loadOnlineUsers();
            loadRoomInfo();
        }

        async function sendChatMessage() {
            const input = document.getElementById('chat-input');
            const message = (input.value || '').trim();
            if (!message) return;
            const room = document.getElementById('chat-room').value;
            
            // Clear typing indicator
            if (isCurrentlyTyping) {
                isCurrentlyTyping = false;
                setTypingStatus(false);
                if (typingTimeoutId) {
                    clearTimeout(typingTimeoutId);
                    typingTimeoutId = null;
                }
            }
            
            // Check if editing
            if (editingMessageId) {
                try {
                    const resp = await fetch(`/api/chat/message/${editingMessageId}`, {
                        method: 'PATCH',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message})
                    });
                    if (resp.ok) {
                        showMessage('Message updated', 'success');
                        await loadChatMessages(false);
                    } else {
                        const data = await resp.json();
                        showMessage(data.error || 'Failed to edit', 'error');
                    }
                } catch (err) {
                    showMessage('Error: ' + err.message, 'error');
                }
                cancelEditMessage();
                return;
            }
            
            input.value = '';
            
            // Build request body with optional reply_to_id
            const body = { room, message };
            if (replyToMessageId) {
                body.reply_to_id = replyToMessageId;
            }
            
            try {
                const resp = await safeFetch('/api/chat/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (resp.ok) {
                    loadChatMessages(true);
                    loadOnlineUsers();
                    // Clear reply state after successful send
                    if (replyToMessageId) {
                        cancelReply();
                    }
                } else {
                    const d = await resp.json();
                    showMessage(d.error || 'Failed to send', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function loadOnlineUsers() {
            const listDiv = document.getElementById('online-users-list');
            const currentRoom = document.getElementById('chat-room').value;
            
            try {
                const resp = await fetch('/api/chat/online-users');
                if (!resp.ok) {
                    listDiv.innerHTML = '<div class="error" style="font-size:0.85em;">Failed to load users</div>';
                    return;
                }
                const data = await resp.json();
                const onlineUsers = data.online_users || {};
                
                // Build HTML showing users in each room
                let html = '';
                const sortedRooms = Object.keys(onlineUsers).sort((a, b) => b === currentRoom ? -1 : a.localeCompare(b));
                
                if (sortedRooms.length === 0) {
                    listDiv.innerHTML = '<div style="color:var(--text-secondary); font-size:0.85em;">No users online</div>';
                    return;
                }
                
                for (const room of sortedRooms) {
                    const users = onlineUsers[room];
                    const icon = room === currentRoom ? '📍' : '💬';
                    html += `<div style="margin-bottom:12px;">
                        <div style="font-weight:600; color:var(--text-primary); margin-bottom:6px; font-size:0.85em;">${icon} ${room}</div>
                        <div style="padding-left:12px;">`;
                    
                    for (const user of users) {
                        html += `<div style="display:flex; align-items:center; gap:6px; padding:4px 0; color:var(--text-secondary); flex-wrap:wrap;">
                            <span style="cursor:pointer; color:#4f46e5; text-decoration:underline;" onclick="showUserPreview('${user}')">👤 ${user}</span>
                            <div style="margin-left:auto; display:flex; gap:4px;">`;
                        
                        // Show room invite button if in a private room
                        if (room === currentRoom) {
                            html += `<button onclick="inviteUserToRoom('${user}')" title="Invite to room" style="padding:2px 6px; background:#4f46e5; color:white; border:none; border-radius:3px; cursor:pointer; font-size:0.7em;">🎫 Room</button>`;
                        }
                        
                        // Always show friend invite button
                        html += `<button onclick="sendFriendRequest('${user}')" title="Send friend request" style="padding:2px 6px; background:#f59e0b; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.7em; font-family:inherit;">👥 Friend</button>`;
                        
                        html += `</div></div>`;
                    }
                    html += `</div></div>`;
                }
                listDiv.innerHTML = html;
            } catch (err) {
                listDiv.innerHTML = `<div class="error" style="font-size:0.85em;">Error: ${err.message}</div>`;
            }
        }

        let roomInfo = {};
        async function loadRoomInfo() {
            const room = document.getElementById('chat-room').value;
            try {
                const resp = await fetch(`/api/chat/room-users?room=${encodeURIComponent(room)}`);
                if (resp.ok) {
                    roomInfo = await resp.json();
                }
            } catch (err) {
                console.error('Failed to load room info:', err);
            }
        }

        async function inviteUserToRoom(username) {
            const room = document.getElementById('chat-room').value;
            
            // Check if current user is the room owner
            if (!roomInfo.owner) {
                await loadRoomInfo();
            }
            
            // Only allow room owner to invite
            if (!roomInfo.is_private) {
                showMessage('Can only invite users to private rooms', 'error');
                return;
            }
            
            try {
                const resp = await fetch('/api/chat/invite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ room, target_username: username }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage(data.message || 'Invite sent!', 'success');
                    loadOnlineUsers();
                } else {
                    showMessage(data.message || 'Failed to invite user', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function showUserPreview(username) {
            const modal = document.getElementById('userPreviewModal');
            const previewDiv = document.getElementById('user-preview-content');
            
            previewDiv.innerHTML = '<div class="loading" style="padding:20px; text-align:center;">Loading profile…</div>';
            modal.style.display = 'flex';
            
            try {
                const resp = await fetch(`/api/user-profile/${encodeURIComponent(username)}`);
                if (!resp.ok) {
                    previewDiv.innerHTML = `<div class="error" style="padding:20px;">Failed to load profile</div>`;
                    return;
                }
                
                const profile = await resp.json();
                const avatar = profile.avatar_url 
                    ? `<img src="${profile.avatar_url}" style="width:60px; height:60px; border-radius:var(--radius-sm,8px); object-fit:cover; margin:0 auto 12px;">`
                    : `<div style="width:60px; height:60px; border-radius:var(--radius-sm,8px); background:var(--card-border); margin:0 auto 12px;"></div>`;
                
                const rolesBadges = (profile.roles || []).map(role => 
                    `<span style="display:inline-block; padding:3px 8px; margin:0 4px 4px 0; background:linear-gradient(135deg,#4f46e5,#7c3aed); color:white; border-radius:var(--radius,12px); font-size:0.75em; font-weight:600;font-family:inherit;">${role}</span>`
                ).join('');
                
                const joinDate = profile.joined ? new Date(profile.joined).toLocaleDateString() : 'Unknown';
                const stats = profile.stats || {};
                
                let html = `
                    <div style="text-align:center;">
                        ${avatar}
                        <h3 style="margin:0 0 4px; color:var(--text-primary);">${profile.display_name}</h3>
                        <div style="font-size:0.85em; color:var(--text-secondary); margin-bottom:12px;">@${profile.username}</div>
                        ${profile.bio ? `<div style="color:var(--text-secondary); font-size:0.9em; margin-bottom:12px; font-style:italic;">"${profile.bio}"</div>` : ''}
                        ${rolesBadges ? `<div style="margin-bottom:12px;">${rolesBadges}</div>` : ''}
                    </div>
                    <div style="border-top:1px solid var(--input-border); padding:12px 0; margin:12px 0;">
                        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; text-align:center;">
                            <div>
                                <div style="font-size:1.2em; font-weight:700; color:var(--text-primary);">${stats.total_games || 0}</div>
                                <div style="font-size:0.75em; color:var(--text-secondary);">Games</div>
                            </div>
                            <div>
                                <div style="font-size:1.2em; font-weight:700; color:var(--text-primary);">${stats.total_playtime_hours || 0}h</div>
                                <div style="font-size:0.75em; color:var(--text-secondary);">Playtime</div>
                            </div>
                            <div>
                                <div style="font-size:1.2em; font-weight:700; color:var(--text-primary);">${stats.total_achievements || 0}</div>
                                <div style="font-size:0.75em; color:var(--text-secondary);">Achievements</div>
                            </div>
                        </div>
                    </div>
                    <div style="font-size:0.8em; color:var(--text-secondary); text-align:center;">
                        Joined ${joinDate}
                    </div>
                `;
                
                previewDiv.innerHTML = html;
            } catch (err) {
                previewDiv.innerHTML = `<div class="error" style="padding:20px;">Error: ${err.message}</div>`;
            }
        }

        function closeUserPreview() {
            document.getElementById('userPreviewModal').style.display = 'none';
        }

        function sendPickerCommand(commandText) {
            const input = document.getElementById('chat-input');
            if (!input) return;
            input.value = commandText;
            sendChatMessage();
        }

        function openSessionsTab() {
            const sessionsTabButton = document.getElementById('nav-sessions');
            if (sessionsTabButton) {
                switchTab('sessions', { target: sessionsTabButton });
            }
        }

        function getCurrentUsername() {
            const el = document.getElementById('current-username');
            return (el && el.textContent ? el.textContent.trim() : '');
        }

        function populateLiveSessionDiscordChannels() {
            const guildSelect = document.getElementById('session-discord-guild');
            const channelSelect = document.getElementById('session-discord-channel');
            if (!guildSelect || !channelSelect) return;
            const guild = liveSessionDiscordGuilds.find(g => g.guild_id === guildSelect.value);
            const channels = guild ? (guild.channels || []) : [];
            channelSelect.innerHTML = '<option value="">Choose Discord channel</option>';
            channels.forEach(channel => {
                const option = document.createElement('option');
                option.value = channel.channel_id;
                option.textContent = `#${channel.channel_name}`;
                channelSelect.appendChild(option);
            });
            channelSelect.disabled = !guild;
        }

        async function loadLiveSessionDiscordLocations() {
            const guildSelect = document.getElementById('session-discord-guild');
            const hintEl = document.getElementById('session-discord-hint');
            if (!guildSelect) return;
            try {
                const resp = await fetch('/api/live-session/discord-locations');
                const data = await resp.json();
                const guilds = data.guilds || [];
                liveSessionDiscordGuilds = guilds;
                guildSelect.innerHTML = '<option value="">No Discord sync</option>';
                guilds.forEach(guild => {
                    const option = document.createElement('option');
                    option.value = guild.guild_id;
                    option.textContent = guild.guild_name;
                    guildSelect.appendChild(option);
                });
                if (hintEl) {
                    if (guilds.length) {
                        hintEl.textContent = 'Choose a Discord server and channel to mirror the session through the bot.';
                    } else {
                        hintEl.textContent = data.error || 'Link your Discord ID in Settings, then talk to the bot in your server so it can cache your available channels.';
                    }
                }
                populateLiveSessionDiscordChannels();
            } catch (err) {
                if (hintEl) hintEl.textContent = 'Could not load Discord channels right now.';
            }
        }

        async function createLiveSession() {
            const nameInput = document.getElementById('session-name-input');
            const coopOnly = document.getElementById('session-coop-only').checked;
            const guildSelect = document.getElementById('session-discord-guild');
            const channelSelect = document.getElementById('session-discord-channel');
            const name = (nameInput.value || '').trim();
            const discordGuildId = (guildSelect && guildSelect.value) || '';
            const discordChannelId = (channelSelect && channelSelect.value) || '';
            if (discordGuildId && !discordChannelId) {
                showMessage('Choose a Discord channel for the selected server', 'error');
                return;
            }
            try {
                const resp = await safeFetch('/api/live-session/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name || undefined,
                        coop_only: coopOnly,
                        discord_guild_id: discordGuildId || undefined,
                        discord_channel_id: discordChannelId || undefined,
                    }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to create session', 'error');
                    return;
                }
                showMessage('Session created!', 'success');
                if (nameInput) nameInput.value = '';
                if (guildSelect) guildSelect.value = '';
                populateLiveSessionDiscordChannels();
                activeLiveSessionId = data.session_id;
                await loadLiveSessions();
                renderLiveSessionDetails(data);
                subscribeToLiveSession(activeLiveSessionId);
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function loadLiveSessions(_retriedAuth = false) {
            const listDiv = document.getElementById('sessions-list');
            if (!listDiv) return;
            try {
                const resp = await fetch('/api/live-session/active');
                if (resp.status === 401) {
                    await checkAuthStatus();
                    if (!_retriedAuth && getCurrentUsername()) {
                        await loadLiveSessions(true);
                        return;
                    }
                    listDiv.innerHTML = '<div class="error">Please sign in to load sessions</div>';
                    return;
                }
                if (!resp.ok) {
                    listDiv.innerHTML = '<div class="error">Failed to load sessions</div>';
                    return;
                }
                const data = await resp.json();
                const sessions = data.sessions || [];
                if (!sessions.length) {
                    listDiv.innerHTML = '<div class="schedule-agenda-copy">No active sessions yet.</div>';
                    return;
                }

                const me = getCurrentUsername();
                listDiv.innerHTML = sessions.map(s => {
                    const joined = (s.participants || []).includes(me);
                    const isHost = s.host === me;
                    const pickedGame = s.picked_game || {};
                    const appId = String(pickedGame.appid || pickedGame.app_id || '').trim();
                    const discordSummary = s.discord && s.discord.guild_name && s.discord.channel_name
                        ? `<div class="schedule-agenda-copy" style="margin-top:4px;">Discord: ${s.discord.guild_name} / #${s.discord.channel_name}</div>`
                        : '';
                    return `
                        <div class="session-list-item">
                            <div class="session-list-item-main">
                                <div class="session-list-thumb">
                                    ${appId ? renderGameListThumb(appId, pickedGame.name || s.name || 'Session') : '<span>🎯</span>'}
                                </div>
                                <div style="min-width:0; flex:1;">
                                    <div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">
                                        <strong class="list-item-title" style="max-width:100%;">${s.name || s.session_id}</strong>
                                        <span class="schedule-field-hint">${s.status}</span>
                                    </div>
                                    <div class="schedule-agenda-copy" style="margin-top:4px;">Host: ${s.host} · Players: ${(s.participants || []).length}</div>
                                    ${discordSummary}
                                </div>
                            </div>
                            <div class="session-list-actions">
                                <button onclick="openLiveSession('${s.session_id}')" class="chat-room-secondary-btn">Open</button>
                                ${joined
                                    ? `<button onclick="leaveLiveSession('${s.session_id}')" class="session-danger-btn">Leave</button>`
                                    : `<button onclick="joinLiveSession('${s.session_id}')" class="chat-room-create-btn">Join</button>`}
                                ${isHost
                                    ? `<button onclick="pickLiveSessionGame('${s.session_id}')" class="chat-room-secondary-btn">Pick</button>`
                                    : ''}
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (err) {
                listDiv.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        async function openLiveSession(sessionId) {
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(sessionId)}`);
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to load session', 'error');
                    return;
                }
                activeLiveSessionId = sessionId;
                renderLiveSessionDetails(data);
                subscribeToLiveSession(sessionId);
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function joinLiveSession(sessionId, _retriedAuth = false) {
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(sessionId)}/join`, { method: 'POST' });
                if (resp.status === 401) {
                    await checkAuthStatus();
                    if (!_retriedAuth && getCurrentUsername()) {
                        await joinLiveSession(sessionId, true);
                        return;
                    }
                    showMessage('Please sign in to join a session', 'error');
                    return;
                }
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to join session', 'error');
                    return;
                }
                activeLiveSessionId = sessionId;
                renderLiveSessionDetails(data);
                subscribeToLiveSession(sessionId);
                loadLiveSessions();
                showMessage('Joined session!', 'success');
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function leaveLiveSession(sessionId) {
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(sessionId)}/leave`, { method: 'POST' });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to leave session', 'error');
                    return;
                }
                if (activeLiveSessionId === sessionId) {
                    activeLiveSessionId = null;
                    if (activeSessionEventSource) {
                        activeSessionEventSource.close();
                        activeSessionEventSource = null;
                    }
                    const detailsDiv = document.getElementById('session-details');
                    if (detailsDiv) detailsDiv.innerHTML = '<div style="color:var(--text-secondary);">Select or join a session to view details.</div>';
                }
                loadLiveSessions();
                showMessage('Left session', 'success');
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function pickLiveSessionGame(sessionId) {
            const coopOnly = document.getElementById('session-coop-only').checked;
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(sessionId)}/pick`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ coop_only: coopOnly }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Failed to pick game', 'error');
                    return;
                }
                const sessionView = data.session || null;
                if (sessionView) {
                    renderLiveSessionDetails(sessionView);
                }
                loadLiveSessions();
                showMessage('Game picked - vote now!', 'success');
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function voteLiveSession(accept) {
            if (!activeLiveSessionId) {
                showMessage('Open a session first', 'error');
                return;
            }
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(activeLiveSessionId)}/vote`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ accept: !!accept }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    showMessage(data.error || 'Vote failed', 'error');
                    return;
                }
                if (data.session) renderLiveSessionDetails(data.session);
                loadLiveSessions();
                if (data.result === 'accepted') {
                    showMessage('Majority accepted this game ✅', 'success');
                } else if (String(data.result).startsWith('rejected')) {
                    showMessage('Majority rejected. New game picked and vote restarted.', 'info');
                } else {
                    showMessage('Vote recorded', 'success');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        function openInviteUsersModal(sessionId) {
            const modal = document.getElementById('invite-users-modal');
            if (!modal) return;
            modal.style.display = 'flex';
            modal.setAttribute('data-session-id', sessionId);
        }

        function closeInviteUsersModal() {
            const modal = document.getElementById('invite-users-modal');
            if (modal) modal.style.display = 'none';
            document.getElementById('invite-usernames-input').value = '';
        }

        async function inviteLiveSessionUsers() {
            const sessionId = document.getElementById('invite-users-modal').getAttribute('data-session-id');
            const usernamesInput = document.getElementById('invite-usernames-input').value.trim();
            if (!usernamesInput) {
                showMessage('Please enter at least one username', 'error');
                return;
            }
            const usernames = usernamesInput.split(',').map(u => u.trim()).filter(u => u);
            try {
                const resp = await fetch(`/api/live-session/${encodeURIComponent(sessionId)}/invite`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({usernames})
                });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage(`Invitations sent to ${data.sent.length} user(s)`, 'success');
                    if (data.failed && data.failed.length > 0) {
                        showMessage(`Failed to invite: ${data.failed.join(', ')}`, 'warning');
                    }
                } else {
                    showMessage(data.error || 'Failed to send invitations', 'error');
                }
                closeInviteUsersModal();
            } catch (err) {
                showMessage('Error sending invitations: ' + err.message, 'error');
            }
        }

        function renderPickedGameCard(game) {
            if (!game) return '<div class="schedule-agenda-copy">No game picked yet.</div>';
            const appId = game.appid || game.app_id || game.game_id || '';
            const name = game.name || 'Unknown game';
            const playtimeMinutes = Number(game.playtime_forever || 0);
            const playtimeHours = (playtimeMinutes / 60).toFixed(1);
            const owners = Array.isArray(game.owners) ? game.owners.join(', ') : '';
            const steamUrl = appId ? `https://store.steampowered.com/app/${appId}/` : null;
            const steamDbUrl = appId ? `https://steamdb.info/app/${appId}/` : null;
            return `
                <div class="session-picked-card">
                    <div class="session-picked-header">
                        <div class="session-picked-thumb">
                            ${appId ? renderGameListThumb(appId, name) : '<span>🎮</span>'}
                        </div>
                        <div>
                            <div style="font-size:1.08em; font-weight:700; color:var(--text-primary);">🎮 ${name}</div>
                            <div class="schedule-agenda-copy" style="margin-top:4px;">Playtime: ${playtimeHours}h</div>
                        </div>
                    </div>
                    ${owners ? `<div style="font-size:0.85em; color:var(--text-secondary); margin-top:4px;">Owners: ${owners}</div>` : ''}
                    <div class="session-list-actions" style="margin-top:10px;">
                        ${steamUrl ? `<a href="${steamUrl}" target="_blank" class="chat-room-secondary-btn">Steam</a>` : ''}
                        ${steamDbUrl ? `<a href="${steamDbUrl}" target="_blank" class="chat-room-secondary-btn">SteamDB</a>` : ''}
                    </div>
                </div>
            `;
        }

        function playLiveSessionLootboxReveal(session) {
            const revealEl = document.getElementById('live-session-lootbox');
            if (!revealEl || !session || session.status !== 'completed' || !session.picked_game) return;
            if (liveSessionLootboxSessionId === session.session_id) return;
            liveSessionLootboxSessionId = session.session_id;
            if (liveSessionLootboxTimer) {
                clearInterval(liveSessionLootboxTimer);
                liveSessionLootboxTimer = null;
            }
            const finalName = session.picked_game.name || 'Unknown game';
            const tease = ['🎁', '🎲', '🎮', '⭐', '🔥', '💥', '✨'];
            let step = 0;
            revealEl.style.display = 'block';
            revealEl.innerHTML = '<div style="font-size:0.9em; color:var(--text-secondary);">Rolling final pick…</div>';
            liveSessionLootboxTimer = setInterval(() => {
                step += 1;
                if (step >= 10) {
                    clearInterval(liveSessionLootboxTimer);
                    liveSessionLootboxTimer = null;
                    revealEl.innerHTML = `
                        <div style="padding:14px; border:1px solid rgba(124,58,237,0.45); border-radius:12px; background:linear-gradient(135deg, rgba(79,70,229,0.18), rgba(124,58,237,0.25)); text-align:center;">
                            <div style="font-size:0.82em; color:var(--text-secondary); margin-bottom:6px;">Lootbox reveal</div>
                            <div style="font-size:1.3em; font-weight:700; color:var(--text-primary);">🎉 ${finalName}</div>
                        </div>
                    `;
                    return;
                }
                const randomTag = tease[Math.floor(Math.random() * tease.length)];
                revealEl.innerHTML = `
                    <div style="padding:14px; border:1px solid rgba(124,58,237,0.25); border-radius:12px; background:linear-gradient(135deg, rgba(79,70,229,0.12), rgba(124,58,237,0.18)); text-align:center;">
                        <div style="font-size:0.82em; color:var(--text-secondary); margin-bottom:6px;">Lootbox reveal</div>
                        <div style="font-size:1.1em; font-weight:700; color:var(--text-primary); letter-spacing:1px;">${randomTag} ${finalName}</div>
                    </div>
                `;
            }, 140);
        }

        function renderLiveSessionDetails(session) {
            const detailsDiv = document.getElementById('session-details');
            if (!detailsDiv || !session) return;
            const me = getCurrentUsername();
            const participants = session.participants || [];
            const isHost = session.host === me;
            const joined = participants.includes(me);
            const voteState = session.vote_state || {};
            const required = voteState.required_for_majority || Math.floor((participants.length || 1) / 2) + 1;
            const yesCount = voteState.yes_count || 0;
            const noCount = voteState.no_count || 0;
            const canVote = joined && session.status === 'awaiting_vote' && !!session.picked_game;
            const pendingJoins = session.pending_joins || [];
            const discordInfo = session.discord || {};

            detailsDiv.innerHTML = `
                <div class="session-detail-grid">
                    <div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">
                        <strong style="font-size:1.05em; color:var(--text-primary);">${session.name || session.session_id}</strong>
                        <span class="schedule-field-hint">${session.status}</span>
                    </div>
                    <div class="schedule-agenda-copy">Host: ${session.host} · Round: ${session.round || 0}</div>
                    <div class="schedule-agenda-copy">Players: ${participants.join(', ') || 'None'}</div>
                    ${discordInfo.guild_name && discordInfo.channel_name
                        ? `<div class="schedule-agenda-copy">Discord sync: ${discordInfo.guild_name} / #${discordInfo.channel_name} · Pending joins: ${session.pending_join_count || 0}</div>`
                        : ''}
                    <div class="session-list-actions">
                        ${joined
                            ? `<button onclick="leaveLiveSession('${session.session_id}')" class="session-danger-btn">Leave</button>`
                            : `<button onclick="joinLiveSession('${session.session_id}')" class="chat-room-create-btn">Join</button>`}
                        ${isHost
                            ? `<button onclick="pickLiveSessionGame('${session.session_id}')" class="chat-room-secondary-btn">Pick Game</button>
                               <button onclick="openInviteUsersModal('${session.session_id}')" class="chat-room-secondary-btn">Invite Users</button>`
                            : ''}
                    </div>
                    <div id="live-session-lootbox" style="display:${session.status === 'completed' && session.picked_game ? 'block' : 'none'};"></div>
                    ${renderPickedGameCard(session.picked_game)}
                    ${pendingJoins.length
                        ? `<div class="session-queue-card">
                               <div style="font-size:0.9em; font-weight:600; color:var(--text-primary); margin-bottom:6px;">Discord onboarding queue</div>
                               <div style="display:grid; gap:6px;">${pendingJoins.map(join => `
                                   <div class="schedule-agenda-copy">
                                       Discord user <code>${join.discord_user_id}</code> — ${join.status}
                                   </div>
                               `).join('')}</div>
                           </div>`
                        : ''}
                    <div class="session-vote-panel">
                        <div style="font-size:0.9em; color:var(--text-primary); font-weight:600; margin-bottom:6px;">Majority Vote</div>
                        <div class="schedule-agenda-copy" style="margin-bottom:8px;">Need ${required} votes · ✅ ${yesCount} · ❌ ${noCount}</div>
                        ${canVote
                            ? `<div class="session-list-actions">
                                   <button onclick="voteLiveSession(true)" class="chat-room-create-btn">✅ Accept</button>
                                   <button onclick="voteLiveSession(false)" class="session-danger-btn">❌ Reject</button>
                               </div>`
                            : `<div class="schedule-agenda-copy">${session.status === 'awaiting_vote' ? 'Join this session to vote.' : 'Vote starts after a game is picked.'}</div>`}
                    </div>
                </div>
            `;
            if (session.status === 'completed' && session.picked_game) {
                playLiveSessionLootboxReveal(session);
            } else {
                liveSessionLootboxSessionId = null;
            }
        }

        function subscribeToLiveSession(sessionId) {
            if (!sessionId) return;
            if (activeSessionEventSource) {
                activeSessionEventSource.close();
                activeSessionEventSource = null;
            }
            activeSessionEventSource = new EventSource(`/api/live-session/${encodeURIComponent(sessionId)}/events`);
            activeSessionEventSource.addEventListener('session', (event) => {
                try {
                    const payload = JSON.parse(event.data || '{}');
                    if (payload && payload.session_id) {
                        activeLiveSessionId = payload.session_id;
                        renderLiveSessionDetails(payload);
                    }
                    loadLiveSessions();
                } catch (_) {
                    // Ignore malformed SSE payloads
                }
            });
            activeSessionEventSource.onerror = () => {
                if (activeSessionEventSource) {
                    activeSessionEventSource.close();
                    activeSessionEventSource = null;
                }
            };
        }

        function startSessionsPolling() {
            if (sessionsPollInterval) return;
            sessionsPollInterval = setInterval(() => {
                if (document.getElementById('sessions-tab')?.classList.contains('active')) {
                    loadLiveSessions();
                    if (activeLiveSessionId) {
                        openLiveSession(activeLiveSessionId);
                    }
                }
            }, 6000);
        }

        function stopSessionsPolling() {
            if (sessionsPollInterval) {
                clearInterval(sessionsPollInterval);
                sessionsPollInterval = null;
            }
            if (activeSessionEventSource) {
                activeSessionEventSource.close();
                activeSessionEventSource = null;
            }
        }

        function startChatPolling() {
            if (chatPollInterval) return;
            chatPollInterval = setInterval(() => loadChatMessages(true), 5000);
            if (onlineUsersPollInterval) return;
            onlineUsersPollInterval = setInterval(() => loadOnlineUsers(), 6000);
            if (typingPollInterval) return;
            typingPollInterval = setInterval(() => loadTypingUsers(), 2000);
        }
        function stopChatPolling() {
            if (chatPollInterval) { clearInterval(chatPollInterval); chatPollInterval = null; }
            if (onlineUsersPollInterval) { clearInterval(onlineUsersPollInterval); onlineUsersPollInterval = null; }
            if (typingPollInterval) { clearInterval(typingPollInterval); typingPollInterval = null; }
            // Clear typing status when leaving chat
            if (isCurrentlyTyping) {
                isCurrentlyTyping = false;
                setTypingStatus(false);
            }
        }

        // ==============================================================================================
        // Notifications / Alerts
        // ==============================================================================================

        let notifPollInterval = null;

        async function loadNotifications() {
            const listDiv = document.getElementById('notifications-list');
            const unreadOnly = document.getElementById('notif-unread-only').checked;
            listDiv.innerHTML = renderSkeletonList(5);
            try {
                const resp = await fetch(`/api/notifications?unread_only=${unreadOnly}`);
                if (!resp.ok) { listDiv.innerHTML = '<div class="loading">Notifications not available (no DB).</div>'; return; }
                const data = await resp.json();
                updateNotifBadge(data.unread_count || 0);
                if (!data.notifications || data.notifications.length === 0) {
                    listDiv.innerHTML = '<div style="color:var(--text-secondary);">No notifications yet.</div>';
                    return;
                }
                const typeIcon = { info:'ℹ️', success:'✅', warning:'⚠️', error:'❌', friend_request:'👥' };
                const typeBg   = { info:'rgba(79,70,229,0.06)', success:'rgba(16,185,129,0.12)', warning:'rgba(245,158,11,0.1)', error:'rgba(239,68,68,0.1)', friend_request:'rgba(79,70,229,0.06)' };
                listDiv.innerHTML = data.notifications.map(n => `
                    <div style="padding:14px; border-radius:var(--radius,12px); margin-bottom:10px; background:${n.is_read ? 'var(--list-hover)' : typeBg[n.type] || 'rgba(79,70,229,0.06)'};
                                border-left:4px solid ${n.is_read ? 'var(--card-border)' : '#4f46e5'}; opacity:${n.is_read ? '0.75' : '1'};">
                        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                            <span style="font-size:1.1em;">${typeIcon[n.type] || 'ℹ️'}</span>
                            <strong style="color:var(--text-primary);">${n.title}</strong>
                            <span style="margin-left:auto; font-size:0.78em; color:var(--text-secondary);">${n.created_at ? new Date(n.created_at).toLocaleString() : ''}</span>
                            ${!n.is_read ? `<button onclick="markNotifRead(${n.id})" style="padding:3px 10px; background:var(--card-border); border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.78em;">Mark read</button>` : ''}
                        </div>
                        <div style="color:var(--text-secondary); font-size:0.9em; padding-left:28px;">${n.message}</div>
                    </div>`).join('');
            } catch (err) {
                listDiv.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        async function markNotifRead(id) {
            await safeFetch('/api/notifications/read', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ids:[id]}) });
            loadNotifications();
        }

        async function markAllNotificationsRead() {
            await safeFetch('/api/notifications/read', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({}) });
            loadNotifications();
        }

        function updateNotifBadge(count) {
            const badge = document.getElementById('notif-badge');
            if (!badge) return;
            if (count > 0) { badge.textContent = String(count); badge.style.display = 'inline-flex'; }
            else { badge.style.display = 'none'; }
        }

        async function pollNotifications() {
            try {
                // Only poll if user is logged in
                const username = getCurrentUsername();
                if (!username) return;
                
                const resp = await fetch('/api/notifications?unread_only=true');
                if (resp.ok) {
                    const data = await resp.json();
                    updateNotifBadge(data.unread_count || 0);
                }
            } catch (e) {}
        }

        async function sendAdminNotification() {
            const username = document.getElementById('notif-target-user').value.trim();
            const title    = document.getElementById('notif-title').value.trim();
            const message  = document.getElementById('notif-message').value.trim();
            const type     = document.getElementById('notif-type').value;
            if (!username || !title || !message) { showMessage('Fill in all fields', 'error'); return; }
            try {
                const resp = await fetch('/api/notifications/send', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ username, title, message, type }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage('Notification sent!', 'success');
                    document.getElementById('notif-target-user').value = '';
                    document.getElementById('notif-title').value = '';
                    document.getElementById('notif-message').value = '';
                } else {
                    showMessage(data.error || 'Failed', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        // ==============================================================================================
        // Plugins / Addons
        // ==============================================================================================

        async function loadPlugins() {
            const listDiv = document.getElementById('plugins-list');
            listDiv.innerHTML = renderSkeletonList(3);
            try {
                const resp = await fetch('/api/plugins');
                if (!resp.ok) { listDiv.innerHTML = '<div class="loading">Plugins not available (no DB).</div>'; return; }
                const data = await resp.json();
                const plugins = data.plugins || [];
                if (plugins.length === 0) {
                    listDiv.innerHTML = '<div style="color:var(--text-secondary);">No plugins registered yet. Admins can register plugins above.</div>';
                    return;
                }
                listDiv.innerHTML = plugins.map(p => `
                    <div class="list-item" style="padding:16px; margin-bottom:10px; background:var(--list-hover); border-radius:var(--radius,12px);">
                        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                            <span style="font-size:1.4em;">🧩</span>
                            <div style="flex:1;">
                                <strong style="font-size:1.05em;">${p.name}</strong>
                                <span style="margin-left:8px; font-size:0.8em; padding:2px 8px; border-radius:10px; background:${p.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.1)'}; color:${p.enabled ? '#10b981' : '#ef4444'};">${p.enabled ? '✅ enabled' : '❌ disabled'}</span>
                            </div>
                            <span style="font-size:0.82em; color:var(--text-secondary);">v${p.version}</span>
                            <div id="plugin-toggle-admin-${p.id}" style="display:none;">
                                <button onclick="togglePlugin(${p.id}, ${!p.enabled})"
                                        style="padding:5px 14px; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-weight:600; background:${p.enabled ? '#ef4444' : '#10b981'}; color:white;">
                                    ${p.enabled ? '⏸ Disable' : '▶ Enable'}
                                </button>
                            </div>
                        </div>
                        ${p.description ? `<div style="margin-top:6px; color:var(--text-secondary); font-size:0.9em;">${p.description}</div>` : ''}
                        ${p.author ? `<div style="font-size:0.8em; color:var(--text-secondary); margin-top:3px;">by ${p.author}</div>` : ''}
                    </div>`).join('');
                // Show toggle buttons for admins
                checkIfAdmin(isAdmin => {
                    if (isAdmin) plugins.forEach(p => {
                        const el = document.getElementById(`plugin-toggle-admin-${p.id}`);
                        if (el) el.style.display = 'block';
                    });
                });
            } catch (err) {
                listDiv.innerHTML = `<div class="error">Error: ${err.message}</div>`;
            }
        }

        async function registerPlugin() {
            const name    = document.getElementById('plugin-name').value.trim();
            const desc    = document.getElementById('plugin-description').value.trim();
            const version = document.getElementById('plugin-version').value.trim() || '1.0.0';
            const author  = document.getElementById('plugin-author').value.trim();
            if (!name) { showMessage('Plugin name is required', 'error'); return; }
            try {
                const resp = await fetch('/api/plugins', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ name, description: desc, version, author }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    showMessage('Plugin registered!', 'success');
                    document.getElementById('plugin-name').value = '';
                    document.getElementById('plugin-description').value = '';
                    loadPlugins();
                } else {
                    showMessage(data.error || 'Failed', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function togglePlugin(id, enabled) {
            try {
                const resp = await fetch(`/api/plugins/${id}`, {
                    method:'PUT',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ enabled }),
                });
                if (resp.ok) { showMessage(enabled ? 'Plugin enabled' : 'Plugin disabled', 'success'); loadPlugins(); }
                else { const d = await resp.json(); showMessage(d.error || 'Failed', 'error'); }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        function checkIfAdmin(callback) {
            fetch('/api/auth/current').then(r => r.ok ? r.json() : {}).then(me => {
                callback(me.roles && me.roles.includes('admin'));
            }).catch(() => callback(false));
        }

        // ==============================================================================================
        // Hook new tabs into switchTab + init
        // ==============================================================================================

        const _origSwitchTab = window.switchTab;
        window.switchTab = function(tabName, event) {
            if (_origSwitchTab) _origSwitchTab(tabName, event);
            if (tabName === 'chat') { chatLastId = 0; loadChatMessages(false); startChatPolling(); }
            else if (typeof stopChatPolling === 'function') stopChatPolling();
            if (tabName === 'notifications') loadNotifications();
            if (tabName === 'plugins') { loadPlugins(); checkIfAdmin(isAdmin => {
                const adminBox = document.getElementById('admin-register-plugin');
                if (adminBox) adminBox.style.display = isAdmin ? 'block' : 'none';
            }); }
            if (tabName === 'friends') loadAppFriends();
            if (tabName === 'settings') loadMyProfileCard();
        };

        // Poll notifications badge every 30s
        setInterval(pollNotifications, 30000);
        pollNotifications();

        // Show admin notification sender and admin tab for admins
        checkIfAdmin(isAdmin => {
            const adminSend = document.getElementById('admin-send-notification');
            if (adminSend) adminSend.style.display = isAdmin ? 'block' : 'none';
            const adminTabBtn = document.getElementById('nav-admin');
            if (adminTabBtn) adminTabBtn.style.display = isAdmin ? 'flex' : 'none';
        });

        // Load and show site announcement banner
        (async function loadAnnouncement() {
            try {
                const resp = await fetch('/api/admin/settings/public');
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.announcement && data.announcement.trim()) {
                    const banner = document.getElementById('site-announcement');
                    const text = document.getElementById('site-announcement-text');
                    if (banner && text) {
                        text.textContent = data.announcement;
                        banner.style.display = 'block';
                    }
                }
            } catch (e) { console.warn('Could not load announcement:', e); }
        })();

        // ==============================================================================================

        async function loadAdminSettings() {
            try {
                const resp = await fetch('/api/admin/settings');
                if (!resp.ok) {
                    showMessage('Admin access required', 'error');
                    return;
                }
                const data = await resp.json();
                const map = {};
                (data.settings || []).forEach(s => map[s.key] = s.value);
                // Populate form
                const ann = document.getElementById('admin-announcement');
                if (ann) ann.value = map['announcement'] || '';
                const setChk = (id, key) => {
                    const el = document.getElementById(id);
                    if (el) el.checked = (map[key] === 'true');
                };
                setChk('admin-registration-open', 'registration_open');
                setChk('admin-chat-enabled', 'chat_enabled');
                setChk('admin-leaderboard-public', 'leaderboard_public');
                setChk('admin-plugins-enabled', 'plugins_enabled');
                const maxPick = document.getElementById('admin-max-pick-count');
                if (maxPick) maxPick.value = map['max_pick_count'] || '10';
                const defPlatform = document.getElementById('admin-default-platform');
                if (defPlatform) defPlatform.value = map['default_platform'] || 'all';
            } catch (err) {
                showMessage('Error loading settings: ' + err.message, 'error');
            }
        }

        async function saveAdminSettings() {
            const msgEl = document.getElementById('admin-settings-message');
            const getVal = id => { const el = document.getElementById(id); return el ? el.value : null; };
            const getChk = id => { const el = document.getElementById(id); return el ? String(el.checked) : 'false'; };
            const settings = {
                announcement: getVal('admin-announcement') || '',
                registration_open: getChk('admin-registration-open'),
                chat_enabled: getChk('admin-chat-enabled'),
                leaderboard_public: getChk('admin-leaderboard-public'),
                plugins_enabled: getChk('admin-plugins-enabled'),
                max_pick_count: getVal('admin-max-pick-count') || '10',
                default_platform: getVal('admin-default-platform') || 'all',
            };
            try {
                const resp = await fetch('/api/admin/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    msgEl.style.display = 'block';
                    msgEl.style.background = 'rgba(16,185,129,0.12)';
                    msgEl.style.color = '#10b981';
                    msgEl.textContent = '✅ Settings saved successfully!';
                    setTimeout(() => { msgEl.style.display = 'none'; }, 3000);
                    // Refresh announcement banner
                    const annEl = document.getElementById('site-announcement-text');
                    const banner = document.getElementById('site-announcement');
                    if (settings.announcement.trim()) {
                        if (annEl) annEl.textContent = settings.announcement;
                        if (banner) banner.style.display = 'block';
                    } else {
                        if (banner) banner.style.display = 'none';
                    }
                } else {
                    msgEl.style.display = 'block';
                    msgEl.style.background = 'rgba(239,68,68,0.1)';
                    msgEl.style.color = '#ef4444';
                    msgEl.textContent = data.error || 'Failed to save settings';
                }
            } catch (err) {
                msgEl.style.display = 'block';
                msgEl.style.background = 'rgba(239,68,68,0.1)';
                msgEl.style.color = '#ef4444';
                msgEl.textContent = 'Error: ' + err.message;
            }
        }

        // ==============================================================================================
        // Discord Bot Management
        // ==============================================================================================

        function _discordBotShowMsg(msg, type) {
            const el = document.getElementById('discord-bot-message');
            if (!el) return;
            el.style.display = 'block';
            el.style.background = type === 'error' ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.12)';
            el.style.color = type === 'error' ? '#ef4444' : '#10b981';
            el.textContent = msg;
            setTimeout(() => { el.style.display = 'none'; }, 4000);
        }

        async function loadDiscordBotStatus() {
            try {
                const [statusResp, statsResp] = await Promise.all([
                    fetch('/api/admin/discord-bot/status'),
                    fetch('/api/admin/discord-bot/stats'),
                ]);
                if (!statusResp.ok) return;
                const status = await statusResp.json();
                const dot = document.getElementById('discord-bot-status-dot');
                const text = document.getElementById('discord-bot-status-text');
                const pidEl = document.getElementById('discord-bot-pid');
                if (dot) dot.style.background = status.running ? '#10b981' : '#ef4444';
                if (text) text.textContent = status.running ? 'Running' : 'Stopped';
                if (pidEl) pidEl.textContent = status.pid ? `PID: ${status.pid}` : '';

                const logEl = document.getElementById('discord-bot-log');
                if (logEl) {
                    logEl.textContent = (status.log && status.log.length)
                        ? status.log.join('\n')
                        : 'No log entries yet.';
                    logEl.scrollTop = logEl.scrollHeight;
                }

                if (statsResp.ok) {
                    const stats = await statsResp.json();
                    const luEl = document.getElementById('discord-bot-linked-users');
                    if (luEl) luEl.textContent = stats.linked_users ?? '—';
                }
            } catch (e) {
                console.warn('Could not load bot status:', e);
            }
        }

        async function loadDiscordBotConfig() {
            try {
                const resp = await fetch('/api/admin/discord-bot/config');
                if (!resp.ok) return;
                const data = await resp.json();
                const cfgStatus = document.getElementById('discord-bot-config-status');
                if (cfgStatus) {
                    const parts = [];
                    parts.push(data.discord_token_set ? '✅ Discord token is set' : '❌ Discord token not set');
                    parts.push(data.steam_api_key_set ? '✅ Steam API key is set' : '❌ Steam API key not set');
                    cfgStatus.textContent = parts.join(' · ');
                }
            } catch (e) { /* ignore */ }
        }

        async function discordBotStart() {
            const btn = document.getElementById('discord-bot-start-btn');
            if (btn) btn.disabled = true;
            try {
                const resp = await safeFetch('/api/admin/discord-bot/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg(`✅ Discord bot started (PID ${data.pid})`, 'success');
                    setTimeout(loadDiscordBotStatus, 1000);
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to start bot'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        async function discordBotStop() {
            const btn = document.getElementById('discord-bot-stop-btn');
            if (btn) btn.disabled = true;
            try {
                const resp = await safeFetch('/api/admin/discord-bot/stop', { method: 'POST' });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg('✅ Discord bot stopped', 'success');
                    setTimeout(loadDiscordBotStatus, 500);
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to stop bot'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        async function saveDiscordBotConfig() {
            const token = (document.getElementById('discord-bot-token-input') || {}).value || '';
            const clientId = (document.getElementById('discord-bot-client-id-input') || {}).value || '';
            const steamKey = (document.getElementById('discord-bot-steam-key-input') || {}).value || '';
            if (!token && !clientId && !steamKey) {
                _discordBotShowMsg('❌ Provide at least one value to save', 'error');
                return;
            }
            try {
                const body = {};
                if (token) body.discord_bot_token = token;
                if (clientId) body.discord_bot_client_id = clientId;
                if (steamKey) body.steam_api_key = steamKey;
                const resp = await safeFetch('/api/admin/discord-bot/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg('✅ Config saved', 'success');
                    const tokenInput = document.getElementById('discord-bot-token-input');
                    const clientIdInput = document.getElementById('discord-bot-client-id-input');
                    const steamInput = document.getElementById('discord-bot-steam-key-input');
                    if (tokenInput) tokenInput.value = '';
                    if (clientIdInput) clientIdInput.value = '';
                    if (steamInput) steamInput.value = '';
                    loadDiscordBotConfig();
                    loadDiscordBotDiagnostics();
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to save config'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            }
        }

        async function discordBotRestart() {
            const btn = document.getElementById('discord-bot-restart-btn');
            if (btn) btn.disabled = true;
            try {
                const resp = await safeFetch('/api/admin/discord-bot/restart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg(`✅ Discord bot restarted (PID ${data.pid})`, 'success');
                    setTimeout(loadDiscordBotStatus, 1000);
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to restart bot'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        let _discordBotAutoRefreshTimer = null;

        function toggleDiscordBotAutoRefresh(enabled) {
            if (enabled) {
                _discordBotAutoRefreshTimer = setInterval(loadDiscordBotStatus, 5000);
            } else {
                clearInterval(_discordBotAutoRefreshTimer);
                _discordBotAutoRefreshTimer = null;
            }
        }

        // Stop auto-refresh when page unloads to avoid dangling timers
        window.addEventListener('beforeunload', () => {
            if (_discordBotAutoRefreshTimer) clearInterval(_discordBotAutoRefreshTimer);
        });

        async function loadDiscordBotUsers() {
            const container = document.getElementById('discord-bot-users-list');
            if (!container) return;
            container.innerHTML = '<p style="color:var(--text-secondary); font-size:0.9em;">Loading…</p>';
            try {
                const resp = await fetch('/api/admin/discord-bot/users');
                if (!resp.ok) {
                    container.innerHTML = '<p style="color:#ef4444;">Failed to load users.</p>';
                    return;
                }
                const data = await resp.json();
                const users = data.users || [];
                if (!users.length) {
                    container.innerHTML = '<p style="color:var(--text-secondary); font-size:0.9em;">No linked users found.</p>';
                    return;
                }
                let html = '<table style="width:100%; border-collapse:collapse; font-size:0.88em;">';
                html += '<thead><tr><th style="text-align:left; padding:6px 8px; border-bottom:1px solid var(--card-border);">Username</th><th style="text-align:left; padding:6px 8px; border-bottom:1px solid var(--card-border);">Discord ID</th><th style="text-align:left; padding:6px 8px; border-bottom:1px solid var(--card-border);">Steam ID</th><th style="padding:6px 8px; border-bottom:1px solid var(--card-border);"></th></tr></thead><tbody>';
                users.forEach(u => {
                    html += `<tr>
                        <td style="padding:6px 8px; font-weight:600;">${u.username || 'N/A'}</td>
                        <td style="padding:6px 8px; color:var(--text-secondary);">${u.discord_id}</td>
                        <td style="padding:6px 8px;">${u.steam_id}</td>
                        <td style="padding:6px 8px; text-align:right;">
                            <button onclick="discordBotRemoveUser('${u.discord_id}')" style="padding:4px 10px; background:#ef4444; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-family:inherit;">🗑 Remove</button>
                        </td>
                    </tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = `<p style="color:#ef4444;">Error: ${e.message}</p>`;
            }
        }

        async function discordBotAddUser() {
            const discordIdEl = document.getElementById('discord-link-discord-id');
            const steamIdEl = document.getElementById('discord-link-steam-id');
            const usernameEl = document.getElementById('discord-link-username');
            const discordId = ((discordIdEl && discordIdEl.value) || '').trim();
            const steamId = ((steamIdEl && steamIdEl.value) || '').trim();
            const username = ((usernameEl && usernameEl.value) || '').trim();

            if (!discordId || !steamId) {
                _discordBotShowMsg('❌ Discord ID and Steam ID are required', 'error');
                return;
            }

            try {
                const resp = await fetch('/api/admin/discord-bot/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ discord_id: discordId, steam_id: steamId, username }),
                });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg('✅ Discord user linked successfully', 'success');
                    if (discordIdEl) discordIdEl.value = '';
                    if (steamIdEl) steamIdEl.value = '';
                    if (usernameEl) usernameEl.value = '';
                    loadDiscordBotUsers();
                    loadDiscordBotStatus();
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to link user'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            }
        }

        async function discordBotRemoveUser(discordId) {
            if (!confirm(`Remove Discord user ${discordId} from linked accounts?`)) return;
            try {
                const resp = await fetch(`/api/admin/discord-bot/users/${encodeURIComponent(discordId)}`, { method: 'DELETE' });
                const data = await resp.json();
                if (resp.ok) {
                    _discordBotShowMsg('✅ User removed', 'success');
                    loadDiscordBotUsers();
                    loadDiscordBotStatus(); // refresh stats
                } else {
                    _discordBotShowMsg('❌ ' + (data.error || 'Failed to remove user'), 'error');
                }
            } catch (e) {
                _discordBotShowMsg('❌ Error: ' + e.message, 'error');
            }
        }

        async function loadDiscordBotDiagnostics() {
            try {
                const resp = await fetch('/api/admin/discord-bot/diagnostics');
                if (!resp.ok) return;
                const data = await resp.json();

                // Steam API Key Status
                const steamKeyEl = document.getElementById('diag-steam-key-status');
                if (steamKeyEl) {
                    if (data.steam_api_key_set) {
                        const source = data.steam_api_key_source === 'env' ? '.env file' : 'config.json';
                        steamKeyEl.innerHTML = `<span style="color:#10b981;">✅ Configured from ${source}</span>`;
                    } else {
                        steamKeyEl.innerHTML = '<span style="color:#ef4444;">❌ Not configured</span>';
                    }
                }

                // Discord Token Status
                const tokenEl = document.getElementById('diag-discord-token-status');
                if (tokenEl) {
                    if (data.discord_token_set) {
                        tokenEl.innerHTML = '<span style="color:#10b981;">✅ Configured</span>';
                    } else {
                        tokenEl.innerHTML = '<span style="color:#ef4444;">❌ Not configured</span>';
                    }
                }

                // Config Files
                const configEl = document.getElementById('diag-config-files');
                if (configEl) {
                    const config = data.config_file_exists ? '✅ config.json' : '❌ config.json';
                    const discordConfig = data.discord_config_exists ? '✅ Discord links DB' : '❌ Discord links DB';
                    configEl.innerHTML = `${config} | ${discordConfig}`;
                }

                // Python Version
                const pythonEl = document.getElementById('diag-python-version');
                if (pythonEl) {
                    pythonEl.textContent = data.python_version || 'Unknown';
                }

                // Bot Invite URL
                const inviteContainer = document.getElementById('bot-invite-url-container');
                const inviteInput = document.getElementById('bot-invite-url');
                if (data.bot_invite_url && inviteContainer && inviteInput) {
                    inviteInput.value = data.bot_invite_url;
                    inviteContainer.style.display = 'block';
                } else if (inviteContainer) {
                    inviteContainer.style.display = 'none';
                }
            } catch (e) {
                console.error('Failed to load Discord bot diagnostics:', e);
            }
        }

        function copyBotInviteUrl() {
            const input = document.getElementById('bot-invite-url');
            if (!input) return;
            input.select();
            input.setSelectionRange(0, 99999); // For mobile
            navigator.clipboard.writeText(input.value).then(() => {
                _discordBotShowMsg('✅ Bot invite URL copied to clipboard!', 'success');
            }).catch(err => {
                _discordBotShowMsg('❌ Failed to copy: ' + err.message, 'error');
            });
        }

        // ==============================================================================================
        // Library Grid / List view toggle
        // ==============================================================================================

        let _libraryView = localStorage.getItem('gapi_library_view') || 'list';
        let _libraryData = null; // cache last loaded data

        function setLibraryView(view) {
            _libraryView = view;
            localStorage.setItem('gapi_library_view', view);
            const listBtn = document.getElementById('library-view-list-btn');
            const gridBtn = document.getElementById('library-view-grid-btn');
            const activeStyle = 'linear-gradient(135deg,#4f46e5,#7c3aed)';
            const inactiveStyle = 'var(--card-bg)';
            const activeColor = 'white';
            const inactiveColor = 'var(--text-primary)';
            if (listBtn) { listBtn.style.background = view === 'list' ? activeStyle : inactiveStyle; listBtn.style.color = view === 'list' ? activeColor : inactiveColor; }
            if (gridBtn) { gridBtn.style.background = view === 'grid' ? activeStyle : inactiveStyle; gridBtn.style.color = view === 'grid' ? activeColor : inactiveColor; }
            if (_libraryData) renderLibraryData(_libraryData);
        }

        function getGamePlatforms(game) {
            const sourceText = [
                game.platform,
                game.platform_name,
                game.source,
                game.store,
                game.storefront,
                game.client,
                Array.isArray(game.platforms) ? game.platforms.join(', ') : game.platforms,
                Array.isArray(game.tags) ? game.tags.join(', ') : game.tags
            ].filter(Boolean).join(' ').toLowerCase();

            const platforms = [];
            if (/epic/.test(sourceText)) platforms.push({ key: 'epic', label: 'Epic', shortLabel: 'E', className: 'platform-epic' });
            if (/\bgog\b|good old games/.test(sourceText)) platforms.push({ key: 'gog', label: 'GOG', shortLabel: 'GOG', className: 'platform-gog' });
            if (/xbox/.test(sourceText)) platforms.push({ key: 'xbox', label: 'Xbox', shortLabel: 'XB', className: 'platform-steam' });
            if (/playstation|\bpsn\b/.test(sourceText)) platforms.push({ key: 'playstation', label: 'PlayStation', shortLabel: 'PS', className: 'platform-gog' });
            if (/nintendo|switch/.test(sourceText)) platforms.push({ key: 'nintendo', label: 'Nintendo', shortLabel: 'N', className: 'platform-epic' });
            if (/steam/.test(sourceText) || (!platforms.length && (game.app_id || game.appid))) {
                platforms.unshift({ key: 'steam', label: 'Steam', shortLabel: 'S', className: 'platform-steam' });
            }

            return Array.from(new Map(platforms.map(platform => [platform.key, platform])).values()).slice(0, 3);
        }

        function getGameRating(game) {
            const candidates = [game.metacritic, game.rating, game.user_rating, game.score];
            for (const candidate of candidates) {
                const value = Number(candidate);
                if (Number.isFinite(value) && value > 0) return Math.round(value);
            }
            return null;
        }

        function renderInlinePlatformBadges(game) {
            return getGamePlatforms(game).map(platform =>
                `<span class="game-inline-badge ${platform.className}" title="${platform.label}">${platform.shortLabel}</span>`
            ).join('');
        }

        function renderGameCard(game) {
            const appId = game.app_id || game.appid || 0;
            const safeName = escapeHtml(game.name || 'Untitled Game');
            const safeNameJs = escAttr(game.name || 'Untitled Game');
            const safeTagsJs = escAttr((game.tags || []).join(', '));
            const coverSrc = getGameThumbUrl(appId);
            const favoriteLabel = game.is_favorite ? 'Unsave' : 'Save';
            const platforms = getGamePlatforms(game);
            const rating = getGameRating(game);
            const playtime = `${game.playtime_hours || 0}h played`;
            const platformBadges = platforms.map(platform =>
                `<span class="game-card-platform-badge ${platform.className}" title="${platform.label}">${platform.shortLabel}</span>`
            ).join('');

            return `
                <div class="game-card" onclick="showGameDetails(${appId}, '${safeNameJs}', ${game.playtime_hours || 0}, '${safeTagsJs}')">
                    <div class="game-card-cover-wrap">
                        <img class="game-card-cover" src="${coverSrc}"
                             onerror="handleMissingCover(this)"
                             alt="${safeName}" loading="lazy">
                        ${platformBadges ? `<div class="game-card-platform-badges">${platformBadges}</div>` : ''}
                        ${rating ? `<div class="game-card-rating-badge">★ ${rating}</div>` : ''}
                        <div class="game-card-overlay">
                            <div class="game-card-overlay-content">
                                <div class="game-card-overlay-chips">
                                    <span class="game-card-overlay-chip">⏱ ${playtime}</span>
                                    ${platforms[0] ? `<span class="game-card-overlay-chip">${platforms[0].label}</span>` : ''}
                                </div>
                                <div class="game-card-overlay-actions">
                                    <button class="game-card-overlay-btn primary" onclick="event.stopPropagation(); showGameDetails(${appId}, '${safeNameJs}', ${game.playtime_hours || 0}, '${safeTagsJs}')">Details</button>
                                    <button class="game-card-overlay-btn" onclick="event.stopPropagation(); toggleFavorite(${appId})">${favoriteLabel}</button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="game-card-body">
                        <div class="game-card-title" title="${safeName}">${safeName}</div>
                        <div class="game-card-meta">
                            <span>${game.playtime_hours || 0}h</span>
                            <span class="game-card-actions-inline">
                                <span class="game-card-action-icon" title="Favorite" onclick="event.stopPropagation(); toggleFavorite(${appId})">${game.is_favorite ? '⭐' : '☆'}</span>
                            </span>
                        </div>
                    </div>
                </div>`;
        }

        function renderLibraryData(data) {
            _libraryData = data;
            const listDiv = document.getElementById('library-list');
            const filteredGames = filterGamesByControls(data.games || [], 'library-search', 'library-platform-filter');
            if (!data.games || data.games.length === 0) {
                listDiv.innerHTML = '<div class="loading">No games found</div>';
                return;
            }
            if (!filteredGames.length) {
                listDiv.innerHTML = '<div class="loading">No games match your current filters.</div>';
                return;
            }
            if (_libraryView === 'grid') {
                listDiv.innerHTML = `<div class="library-grid">${filteredGames.map(game => renderGameCard(game)).join('')}</div>`;
            } else {
                // Original list view
                let html = '';
                filteredGames.forEach(game => {
                    const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
                    const safeNameJs = (game.name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/`/g, '\\`');
                    const platformBadges = renderInlinePlatformBadges(game);
                    html += `
                        <div class="list-item" style="cursor:pointer;" onclick="showGameDetails(${game.app_id}, '${safeNameJs}', ${game.playtime_hours || 0}, '${(game.tags || []).join(', ')}')">
                            <div class="list-item-media">
                                ${renderGameListThumb(game.app_id, game.name)}
                                <div>
                                    ${favoriteIcon}<strong class="list-item-title">${game.name}</strong>
                                    ${platformBadges ? `<div class="game-inline-meta" style="margin-top:6px;">${platformBadges}</div>` : ''}
                                </div>
                            </div>
                            <div style="display:flex; gap:8px; align-items:center;">
                                <span>${game.playtime_hours}h</span>
                                <span title="Favorite" style="cursor:pointer; font-size:1.2em; color: ${game.is_favorite ? '#ffc107' : 'inherit'};" onclick="event.stopPropagation(); toggleFavorite(${game.app_id})">
                                    ${game.is_favorite ? '⭐' : '☆'}
                                </span>
                                <span title="Add to List" style="cursor:pointer; font-size:1.1em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" onclick="event.stopPropagation(); quickAddToBacklog('${escAttr(game.game_id || game.app_id || game.appid || '')}', '${safeNameJs}')">📚</span>
                                <span title="Add to No-Play List" style="cursor:pointer; font-size:1.1em; opacity:0.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'" onclick="event.stopPropagation(); quickIgnoreGame(${game.app_id}, '${safeNameJs}')">🚫</span>
                            </div>
                        </div>`;
                });
                listDiv.innerHTML = html;
            }
            // Pre-load details for all games in background
            const appIds = filteredGames.map(g => g.app_id);
            preloadGameDetails(appIds).catch(() => {});
        }

        // ==============================================================================================
        // Hook admin tab + grid view into existing switchTab + loadLibrary
        // ==============================================================================================

        // Patch loadLibrary to use renderLibraryData
        const _origLoadLibrary = window.loadLibrary;
        window.loadLibrary = async function() {
            const listDiv = document.getElementById('library-list');
            listDiv.innerHTML = renderSkeletonList(8);
            try {
                const response = await fetch('/api/library');
                const data = await response.json();
                _libraryData = data;
                renderLibraryData(data);
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading library</div>';
            }
            // Also load duplicates if the original function did
            if (typeof loadDuplicates === 'function') loadDuplicates();
        };

        // Initialise the view toggle buttons on page load
        setLibraryView(_libraryView);

        // Extend switchTab to handle admin tab
        const _origSwitchTab2 = window.switchTab;
        window.switchTab = function(tabName, event) {
            if (_origSwitchTab2) _origSwitchTab2(tabName, event);
            // Show/hide admin-tab div (it's outside the normal tab-content set)
            const adminDiv = document.getElementById('admin-tab');
            if (adminDiv) adminDiv.classList.toggle('active', tabName === 'admin');
            if (tabName === 'admin') { loadAdminSettings(); loadDiscordBotStatus(); loadDiscordBotConfig(); loadDiscordBotDiagnostics(); }
            // Pause auto-refresh when leaving the admin tab
            if (tabName !== 'admin' && _discordBotAutoRefreshTimer) {
                toggleDiscordBotAutoRefresh(false);
                const cb = document.getElementById('discord-bot-autorefresh');
                if (cb) cb.checked = false;
            }
        };

        // Create Room Modal Functions
        function openCreateRoomModal() {
            document.getElementById('createRoomModal').style.display = 'flex';
            document.getElementById('roomNameInput').focus();
        }
        function closeCreateRoomModal() {
            document.getElementById('createRoomModal').style.display = 'none';
            document.getElementById('roomNameInput').value = '';
            document.getElementById('roomPrivateCheckbox').checked = false;
        }
        function createRoomFromModal() {
            const roomName = document.getElementById('roomNameInput').value.trim();
            const isPrivate = document.getElementById('roomPrivateCheckbox').checked;
            
            if (!roomName) {
                alert('Please enter a room name');
                return;
            }
            if (roomName.length > 30) {
                alert('Room name must be 30 characters or less');
                return;
            }
            
            const command = isPrivate ? `/room create-private ${roomName}` : `/room create ${roomName}`;
            const chatInput = document.getElementById('chat-input');
            chatInput.value = command;
            sendChatMessage();
            
            // Auto-add room to dropdown
            const roomDropdown = document.getElementById('chat-room');
            const icon = isPrivate ? '🔒' : '💬';
            const optionText = `${icon} ${roomName}`;
            
            // Check if room already exists
            let existingOption = Array.from(roomDropdown.options).find(opt => opt.value === roomName);
            if (!existingOption) {
                const newOption = document.createElement('option');
                newOption.value = roomName;
                newOption.textContent = optionText;
                roomDropdown.appendChild(newOption);
            }
            
            // Switch to new room
            roomDropdown.value = roomName;
            switchChatRoom();
            renderChatRoomList();
            
            // Close modal
            closeCreateRoomModal();
        }

        // User Profiles
        async function showUserProfiles() {
            const modal = document.getElementById('user-profiles-modal');
            modal.style.display = 'flex';
            
            try {
                const resp = await fetch('/api/users/list');
                const data = await resp.json();
                const users = data.users || [];
                
                const listDiv = document.getElementById('user-profiles-list');
                if (users.length === 0) {
                    listDiv.innerHTML = '<p style="color: var(--text-secondary); grid-column: 1/-1;">No users found</p>';
                    return;
                }
                
                let html = '';
                users.forEach(user => {
                    html += `
                        <div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:var(--radius,12px); padding:16px; cursor:pointer; transition:all 0.2s; text-align:center;" onclick="showUserProfile('${user.username}')">
                            <div style="font-size:2.5em; margin-bottom:8px;">👤</div>
                            <h4 style="margin:0 0 4px 0; color:var(--text-primary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${user.username}</h4>
                            <p style="margin:0 0 8px 0; font-size:0.85em; color:var(--text-secondary);">Member since ${new Date(user.created_at || Date.now()).toLocaleDateString()}</p>
                            <div style="display:flex; gap:4px; justify-content:center; flex-wrap:wrap;">
                                <span style="background:rgba(102, 126, 234, 0.2); color:var(--accent); padding:4px 8px; border-radius:var(--radius-tag,4px); font-size:0.8em;">📜 ${user.stats?.sessions || 0} sessions</span>
                                <span style="background:rgba(59,130,246,0.15); color:#3b82f6; padding:4px 8px; border-radius:var(--radius-tag,4px); font-size:0.8em;">🎲 ${user.stats?.picks || 0} picks</span>
                            </div>
                        </div>
                    `;
                });
                listDiv.innerHTML = html;
            } catch (err) {
                document.getElementById('user-profiles-list').innerHTML = '<p style="color: var(--text-secondary); grid-column: 1/-1;">Error loading user profiles</p>';
            }
        }

        function closeUserProfiles() {
            const modal = document.getElementById('user-profiles-modal');
            if (modal) modal.style.display = 'none';
        }

        async function showUserProfile(username) {
            const modal = document.getElementById('user-preview-modal');
            modal.style.display = 'flex';
            
            try {
                const resp = await fetch(`/api/users/${encodeURIComponent(username)}/profile`);
                const user = await resp.json();
                
                const contentDiv = document.getElementById('user-preview-content');
                let profileHtml = `
                    <div style="text-align:center;">
                        <div style="font-size:3.5em; margin-bottom:12px;">👤</div>
                        <h2 style="margin:0 0 4px 0; color:var(--text-primary);">${user.username}</h2>
                        <p style="margin:0 0 8px 0; color:var(--text-secondary);">${user.status || 'No status'}</p>
                        <p style="font-size:0.9em; color:var(--text-secondary); margin:0 0 16px 0;">Joined ${new Date(user.created_at || Date.now()).toLocaleDateString()}</p>
                    </div>
                    
                    <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); margin-bottom:12px;">
                        <h3 style="margin:0 0 12px 0; color:var(--text-primary); border-bottom:1px solid var(--input-border); padding-bottom:8px;">📊 Statistics</h3>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                            <div>
                                <div style="font-size:0.85em; color:var(--text-secondary);">Sessions Hosted</div>
                                <div style="font-size:1.8em; font-weight:bold; color:var(--accent);">${user.stats?.sessions_hosted || 0}</div>
                            </div>
                            <div>
                                <div style="font-size:0.85em; color:var(--text-secondary);">Total Picks</div>
                                <div style="font-size:1.8em; font-weight:bold; color:#3b82f6;">${user.stats?.picks || 0}</div>
                            </div>
                            <div>
                                <div style="font-size:0.85em; color:var(--text-secondary);">Votes Cast</div>
                                <div style="font-size:1.8em; font-weight:bold; color:#10b981;">${user.stats?.votes || 0}</div>
                            </div>
                            <div>
                                <div style="font-size:0.85em; color:var(--text-secondary);">Accuracy</div>
                                <div style="font-size:1.8em; font-weight:bold; color:#f59e0b;">${user.stats?.accuracy || 0}%</div>
                            </div>
                        </div>
                    </div>
                    
                    ${user.achievements && user.achievements.length > 0 ? `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); margin-bottom:12px;">
                            <h3 style="margin:0 0 12px 0; color:var(--text-primary); border-bottom:1px solid var(--input-border); padding-bottom:8px;">🏆 Achievements</h3>
                            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                                ${user.achievements.map(badge => `<span style="font-size:1.8em;" title="${badge.name}">${badge.icon}</span>`).join('')}
                            </div>
                        </div>
                    ` : ''}
                    
                    <button onclick="openUserChat('${user.username}')" style="width:100%; padding:10px; background:linear-gradient(135deg,#4f46e5,#7c3aed); color:white; border:none; border-radius:50px; cursor:pointer; font-weight:600;font-family:inherit; margin-bottom:8px;">💬 Send Message</button>
                    <button onclick="closeUserPreviewPhase5()" style="width:100%; padding:10px; background:var(--input-border); color:var(--text-primary); border:none; border-radius:var(--radius-sm,8px); cursor:pointer; font-weight:600;">Close</button>
                `;
                contentDiv.innerHTML = profileHtml;
            } catch (err) {
                document.getElementById('user-preview-content').innerHTML = '<p style="color: var(--text-secondary);">Error loading user profile</p>';
            }
        }

        function closeUserPreviewPhase5() {
            const modal = document.getElementById('user-preview-modal');
            if (modal) modal.style.display = 'none';
        }

        function openUserChat(username) {
            closeUserPreview();
            // Optionally switch to a direct message room or highlight in chat
            showMessage(`To chat with ${username}, mention them with @${username}`, 'info');
        }

        // Notifications System
        let userNotifications = [];
        let notificationFilter = 'all';

        async function showNotifications() {
            const modal = document.getElementById('notifications-modal');
            modal.style.display = 'flex';
            await loadNotificationsPhase5();
        }

        function closeNotifications() {
            const modal = document.getElementById('notifications-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadNotificationsPhase5() {
            try {
                const resp = await fetch('/api/notifications');
                const data = await resp.json();
                userNotifications = data.notifications || [];
                renderNotifications();
            } catch (err) {
                console.error('Error loading notifications:', err);
            }
        }

        function filterNotifications(category) {
            notificationFilter = category;
            renderNotifications();
        }

        function renderNotifications() {
            const list = document.getElementById('notifications-list');
            let filtered = userNotifications;
            
            if (notificationFilter !== 'all') {
                filtered = userNotifications.filter(n => n.type === notificationFilter);
            }
            
            if (filtered.length === 0) {
                list.innerHTML = '<p style="color: var(--text-secondary); text-align:center; padding:20px;">No notifications</p>';
                return;
            }
            
            let html = '';
            filtered.forEach(notif => {
                const icons = {mentions: '💬', invites: '📨', picks: '🎲', achievements: '🏆', votes: '⚖️'};
                const icon = icons[notif.type] || '📢';
                const time = new Date(notif.created_at).toLocaleString();
                
                html += `
                    <div style="background:rgba(255,255,255,0.05); padding:12px; border-left:3px solid ${notif.unread ? '#4f46e5' : 'var(--card-border)'}; border-radius:var(--radius-xs,6px);">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <div style="flex:1;">
                                <p style="margin:0 0 6px 0; color:var(--text-primary); font-weight:600;">${icon} ${notif.title}</p>
                                <p style="margin:0 0 8px 0; color:var(--text-secondary); font-size:0.9em;">${notif.message}</p>
                                <p style="margin:0; color:var(--text-secondary); font-size:0.8em;">${time}</p>
                            </div>
                            <button onclick="dismissNotification('${notif.id}')" style="padding:4px 8px; background:var(--input-border); color:var(--text-primary); border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.9em;">×</button>
                        </div>
                    </div>
                `;
            });
            list.innerHTML = html;
        }

        async function dismissNotification(notifId) {
            userNotifications = userNotifications.filter(n => n.id !== notifId);
            renderNotifications();
        }

        // Challenges & Quests
        let userXP = 0;
        let challenges = [];

        async function showChallenges() {
            const modal = document.getElementById('challenges-modal');
            modal.style.display = 'flex';
            await loadChallenges();
        }

        function closeChallenges() {
            const modal = document.getElementById('challenges-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadChallenges() {
            try {
                const resp = await fetch('/api/challenges');
                const data = await resp.json();
                userXP = data.total_xp || 0;
                challenges = data.challenges || [];
                renderChallenges();
            } catch (err) {
                console.error('Error loading challenges:', err);
            }
        }

        function renderChallenges() {
            const xpBar = document.getElementById('xp-bar');
            const xpDisplay = document.getElementById('xp-display');
            xpDisplay.textContent = `${userXP} XP`;
            xpBar.style.width = `${Math.min(userXP / 1000 * 100, 100)}%`;
            
            const list = document.getElementById('challenges-list');
            if (!challenges || challenges.length === 0) {
                list.innerHTML = '<p style="color: var(--text-secondary); grid-column:1/-1;">No active challenges</p>';
                return;
            }
            
            let html = '';
            challenges.forEach(ch => {
                const progress = Math.min(ch.progress / ch.goal * 100, 100);
                const completed = progress >= 100;
                
                html += `
                    <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); border:1px solid ${completed ? '#10b981' : 'var(--input-border)'};">
                        <h4 style="margin:0 0 8px 0; color:var(--text-primary);">${ch.icon} ${ch.name}</h4>
                        <p style="margin:0 0 8px 0; font-size:0.9em; color:var(--text-secondary);">${ch.description}</p>
                        <div style="background:rgba(0,0,0,0.3); border-radius:var(--radius-tag,4px); height:8px; margin-bottom:6px;">
                            <div style="background:linear-gradient(90deg, #4f46e5, #7c3aed); height:100%; width:${progress}%; border-radius:var(--radius-tag,4px);"></div>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.85em;">
                            <span style="color:var(--text-secondary);">${ch.progress}/${ch.goal}</span>
                            <span style="color:var(--accent); font-weight:bold;">+${ch.reward_xp} XP</span>
                        </div>
                    </div>
                `;
            });
            list.innerHTML = html;
        }

        // Friends & Social
        let friendsList = [];

        async function showFriendsModal() {
            const modal = document.getElementById('friends-modal');
            modal.style.display = 'flex';
            await loadFriendsPhase5();
        }

        function closeFriendsModal() {
            const modal = document.getElementById('friends-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadFriendsPhase5() {
            try {
                const resp = await fetch('/api/friends');
                const data = await resp.json();
                friendsList = data.friends || [];
                renderFriendsList();
            } catch (err) {
                console.error('Error loading friends:', err);
            }
        }

        function renderFriendsList() {
            const friends = friendsList.filter(f => f.status === 'accepted');
            const following = friendsList.filter(f => f.status === 'following');
            
            const friendsDiv = document.getElementById('friends-list');
            const followingDiv = document.getElementById('following-list');
            
            friendsDiv.innerHTML = friends.length ? friends.map(f => `
                <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:var(--radius-xs,6px); display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-primary);">👤 ${f.username}</span>
                    <button onclick="removeFriend('${f.username}')" style="padding:4px 10px; background:#ef4444; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">Remove</button>
                </div>
            `).join('') : '<p style="color:var(--text-secondary);">No friends yet</p>';
            
            followingDiv.innerHTML = following.length ? following.map(f => `
                <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:var(--radius-xs,6px); display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:var(--text-primary);">👀 ${f.username}</span>
                    <button onclick="unfollowUser('${f.username}')" style="padding:4px 10px; background:var(--input-border); color:var(--text-primary); border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">Unfollow</button>
                </div>
            `).join('') : '<p style="color:var(--text-secondary);">Not following anyone</p>';
        }

        async function addFriendFromInput() {
            const username = document.getElementById('add-friend-input').value.trim();
            if (!username) return;
            
            try {
                const resp = await fetch('/api/friends/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username})
                });
                if (resp.ok) {
                    showMessage(`Friend request sent to ${username}`, 'success');
                    document.getElementById('add-friend-input').value = '';
                    await loadFriends();
                } else {
                    const data = await resp.json();
                    showMessage(data.error || 'Error adding friend', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        async function removeFriend(username) {
            try {
                await fetch(`/api/friends/${encodeURIComponent(username)}`, {method: 'DELETE'});
                await loadFriends();
            } catch (err) {
                console.error('Error removing friend:', err);
            }
        }

        async function unfollowUser(username) {
            try {
                await fetch(`/api/friends/follow/${encodeURIComponent(username)}`, {method: 'DELETE'});
                await loadFriends();
            } catch (err) {
                console.error('Error unfollowing:', err);
            }
        }

        // Direct Messaging
        let dmConversations = [];
        let currentDMUser = null;

        async function showMessagesModal() {
            const modal = document.getElementById('messages-modal');
            modal.style.display = 'flex';
            await loadDMConversations();
        }

        function closeMessagesModal() {
            const modal = document.getElementById('messages-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadDMConversations() {
            try {
                const resp = await fetch('/api/messages/conversations');
                const data = await resp.json();
                dmConversations = data.conversations || [];
                renderDMConversations();
            } catch (err) {
                console.error('Error loading conversations:', err);
            }
        }

        function renderDMConversations() {
            const conv = document.getElementById('dm-conversations');
            conv.innerHTML = dmConversations.map(c => `
                <div onclick="selectDMConversation('${c.username}')" style="padding:12px; border-right:1px solid var(--input-border); cursor:pointer; background:${currentDMUser === c.username ? 'rgba(79,70,229,0.12)' : 'transparent'}; border-left:3px solid ${c.unread ? '#4f46e5' : 'transparent'};">
                    <p style="margin:0 0 4px 0; color:var(--text-primary); font-weight:600;">${c.username}</p>
                    <p style="margin:0; font-size:0.85em; color:var(--text-secondary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.last_message}</p>
                </div>
            `).join('');
        }

        async function selectDMConversation(username) {
            currentDMUser = username;
            renderDMConversations();
            await loadDMMessages(username);
        }

        async function loadDMMessages(username) {
            try {
                const resp = await fetch(`/api/messages/${encodeURIComponent(username)}`);
                const data = await resp.json();
                const messages = data.messages || [];
                renderDMMessages(messages);
            } catch (err) {
                console.error('Error loading messages:', err);
            }
        }

        function renderDMMessages(messages) {
            const messagesDiv = document.getElementById('dm-messages');
            messagesDiv.innerHTML = messages.map(m => {
                const isMe = m.sender === currentUser;
                return `
                    <div style="display:flex; justify-content:${isMe ? 'flex-end' : 'flex-start'};">
                        <div style="background:${isMe ? 'linear-gradient(135deg,#4f46e5,#7c3aed)' : 'var(--list-hover)'}; color:var(--text-primary); padding:10px 12px; border-radius:var(--radius-sm,8px); max-width:70%; word-wrap:break-word;">
                            <p style="margin:0; font-size:0.9em;">${m.message}</p>
                            <p style="margin:4px 0 0 0; font-size:0.75em; color:var(--text-secondary);">${new Date(m.created_at).toLocaleTimeString()}</p>
                        </div>
                    </div>
                `;
            }).join('');
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        async function sendDirectMessage() {
            if (!currentDMUser) return;
            const msg = document.getElementById('dm-input').value.trim();
            if (!msg) return;
            
            try {
                const resp = await fetch(`/api/messages/${encodeURIComponent(currentDMUser)}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg})
                });
                if (resp.ok) {
                    document.getElementById('dm-input').value = '';
                    await loadDMMessages(currentDMUser);
                }
            } catch (err) {
                console.error('Error sending message:', err);
            }
        }

        // Library Comparison
        async function showLibraryCompare() {
            const modal = document.getElementById('library-compare-modal');
            modal.style.display = 'flex';
        }

        function closeLibraryCompare() {
            const modal = document.getElementById('library-compare-modal');
            if (modal) modal.style.display = 'none';
        }

        async function compareLibraries() {
            const username = document.getElementById('compare-username').value.trim();
            if (!username) return;
            
            try {
                const resp = await fetch(`/api/library/compare/${encodeURIComponent(username)}`);
                const data = await resp.json();
                
                const result = document.getElementById('library-comparison-result');
                result.innerHTML = `
                    <div>
                        <h4 style="color:var(--text-primary); margin-top:0;">You Own</h4>
                        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:8px;">
                            ${(data.your_games || []).slice(0, 6).map(g => `<div style="font-size:0.85em; padding:8px; background:rgba(255,255,255,0.05); border-radius:var(--radius-tag,4px);">${g}</div>`).join('')}
                        </div>
                        <p style="margin-top:10px; color:var(--text-secondary);">Total: ${data.your_count || 0} games</p>
                    </div>
                    <div>
                        <h4 style="color:var(--text-primary); margin-top:0;">${username} Owns</h4>
                        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:8px;">
                            ${(data.their_games || []).slice(0, 6).map(g => `<div style="font-size:0.85em; padding:8px; background:rgba(255,255,255,0.05); border-radius:var(--radius-tag,4px);">${g}</div>`).join('')}
                        </div>
                        <p style="margin-top:10px; color:var(--text-secondary);">Total: ${data.their_count || 0} games</p>
                    </div>
                    <div style="grid-column:1/-1; background:rgba(79,70,229,0.08); padding:15px; border-radius:var(--radius-sm,8px); border-left:3px solid #4f46e5;">
                        <h4 style="color:var(--accent); margin:0 0 8px 0;">🎮 Shared Games</h4>
                        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:8px; margin-bottom:12px;">
                            ${(data.shared_games || []).slice(0, 8).map(g => `<div style="font-size:0.85em; padding:8px; background:rgba(255,255,255,0.1); border-radius:var(--radius-tag,4px);">${g}</div>`).join('')}
                        </div>
                        <p style="margin:0; color:var(--text-secondary); font-weight:bold;">You have ${data.shared_count || 0} games in common</p>
                    </div>
                `;
            } catch (err) {
                document.getElementById('library-comparison-result').innerHTML = '<p style="color:var(--text-secondary);">Error loading comparison</p>';
            }
        }

        // Session History
        async function showSessionHistory() {
            const modal = document.getElementById('session-history-modal');
            modal.style.display = 'flex';
            await loadSessionHistory();
        }

        function closeSessionHistory() {
            const modal = document.getElementById('session-history-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadSessionHistory() {
            try {
                const resp = await fetch('/api/sessions/history');
                const data = await resp.json();
                const sessions = data.sessions || [];
                
                const list = document.getElementById('session-history-list');
                if (sessions.length === 0) {
                    list.innerHTML = '<p style="color:var(--text-secondary);">No session history</p>';
                    return;
                }
                
                let html = '';
                sessions.forEach(s => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px);">
                            <h4 style="margin:0 0 8px 0; color:var(--text-primary);">${s.name || 'Unnamed Session'}</h4>
                            <p style="margin:0 0 6px 0; font-size:0.9em; color:var(--text-secondary);">Played: ${new Date(s.played_at).toLocaleDateString()}</p>
                            <p style="margin:0 0 8px 0; font-size:0.9em;"><strong style="color:var(--accent);">🎲 Winning Pick:</strong> <span style="color:var(--text-primary);">${s.winning_pick}</span></p>
                            <p style="margin:0 0 8px 0; font-size:0.85em; color:var(--text-secondary);">Players: ${s.player_count} | Your Vote: ${s.your_vote ? '✓' : '✗'}</p>
                            <div style="display:flex; gap:8px; font-size:0.85em;">
                                ${s.your_vote ? `<span style="background:rgba(16,185,129,0.12); color:#10b981; padding:4px 8px; border-radius:var(--radius-tag,4px);">✓ You voted correctly</span>` : ''}
                                ${s.you_picked ? `<span style="background:rgba(59,130,246,0.15); color:#3b82f6; padding:4px 8px; border-radius:var(--radius-tag,4px);">🎲 You picked</span>` : ''}
                            </div>
                        </div>
                    `;
                });
                list.innerHTML = html;
            } catch (err) {
                console.error('Error loading session history:', err);
            }
        }

        // Profile Customization
        async function showProfileEdit() {
            const modal = document.getElementById('profile-edit-modal');
            modal.style.display = 'flex';
            
            try {
                const resp = await fetch('/api/profile/me');
                const profile = await resp.json();
                document.getElementById('profile-bio').value = profile.bio || '';
                document.getElementById('profile-status').value = profile.status || '';
                document.getElementById('profile-favorite-game').value = profile.favorite_game || '';
                document.getElementById('profile-private').checked = profile.is_private || false;
            } catch (err) {
                console.error('Error loading profile:', err);
            }
        }

        function closeProfileEdit() {
            const modal = document.getElementById('profile-edit-modal');
            if (modal) modal.style.display = 'none';
        }

        async function saveProfileChanges() {
            try {
                const resp = await fetch('/api/profile/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        bio: document.getElementById('profile-bio').value,
                        status: document.getElementById('profile-status').value,
                        favorite_game: document.getElementById('profile-favorite-game').value,
                        is_private: document.getElementById('profile-private').checked
                    })
                });
                if (resp.ok) {
                    showMessage('Profile updated successfully!', 'success');
                    closeProfileEdit();
                } else {
                    showMessage('Error updating profile', 'error');
                }
            } catch (err) {
                showMessage('Error: ' + err.message, 'error');
            }
        }

        // Seasonal Leaderboards
        let currentSeason = 'alltime';

        async function showSeasonalLeaderboards() {
            const modal = document.getElementById('seasonal-lb-modal');
            modal.style.display = 'flex';
            await loadSeasonalLeaderboards();
        }

        function closeSeasonalLB() {
            const modal = document.getElementById('seasonal-lb-modal');
            if (modal) modal.style.display = 'none';
        }

        async function switchSeasonTab(season) {
            currentSeason = season;
            await loadSeasonalLeaderboards();
        }

        async function loadSeasonalLeaderboards() {
            try {
                const resp = await fetch(`/api/leaderboards/seasonal?period=${currentSeason}`);
                const data = await resp.json();
                const leaderboard = data.leaderboard || [];
                
                const statusDiv = document.getElementById('seasonal-status');
                statusDiv.textContent = data.period_info || `Showing ${currentSeason} rankings`;
                
                const list = document.getElementById('seasonal-lb-list');
                if (leaderboard.length === 0) {
                    list.innerHTML = '<p style="color:var(--text-secondary);">No data available</p>';
                    return;
                }
                
                let html = '';
                leaderboard.forEach((entry, idx) => {
                    const medal = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `${idx + 1}.`;
                    const seasonalBadge = entry.seasonal_title || '';
                    
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <span style="font-size:1.3em; min-width:40px;">${medal}</span>
                                <span style="color:var(--text-primary); font-weight:600; margin-left:8px;">${entry.username}</span>
                                ${seasonalBadge ? `<span style="margin-left:8px; font-size:0.85em; background:rgba(243,156,18,0.2); color:#f59e0b; padding:2px 6px; border-radius:var(--radius-tag,4px);">${seasonalBadge}</span>` : ''}
                            </div>
                            <span style="color:var(--accent); font-weight:bold;">${entry.value}</span>
                        </div>
                    `;
                });
                list.innerHTML = html;
            } catch (err) {
                console.error('Error loading seasonal leaderboards:', err);
            }
        }

        // Achievements & Badges
        let achievementsFilter = 'all';

        async function showAchievements() {
            const modal = document.getElementById('achievements-modal');
            modal.style.display = 'flex';
            await loadAchievementsPhase5();
        }

        function closeAchievements() {
            const modal = document.getElementById('achievements-modal');
            if (modal) modal.style.display = 'none';
        }

        function filterAchievements(filter) {
            achievementsFilter = filter;
            loadAchievementsPhase5();
        }

        async function loadAchievementsPhase5() {
            try {
                const resp = await fetch('/api/achievements');
                const data = await resp.json();
                let achievements = data.achievements || [];
                
                if (achievementsFilter !== 'all') {
                    achievements = achievements.filter(a => a.tier === achievementsFilter || (achievementsFilter === 'unlocked' && a.unlocked));
                }
                
                const grid = document.getElementById('achievements-grid');
                let html = '';
                achievements.forEach(ach => {
                    html += `
                        <div style="background:${ach.unlocked ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.3)'}; padding:12px; border-radius:var(--radius-sm,8px); text-align:center; opacity:${ach.unlocked ? '1' : '0.5'}; cursor:help;" title="${ach.name}">
                            <div style="font-size:2em; margin-bottom:6px;">${ach.icon}</div>
                            <p style="margin:0; font-size:0.8em; color:var(--text-primary); font-weight:600;">${ach.name}</p>
                            <p style="margin:4px 0 0 0; font-size:0.75em; color:var(--text-secondary);">${ach.tier}</p>
                        </div>
                    `;
                });
                grid.innerHTML = html;
            } catch (err) {
                console.error('Error loading achievements:', err);
            }
        }

        // Reviews & Ratings
        let currentReviewRating = 0;

        function showReviews() {
            const modal = document.getElementById('reviews-modal');
            modal.style.display = 'flex';
            loadReviews();
        }

        function closeReviews() {
            const modal = document.getElementById('reviews-modal');
            if (modal) modal.style.display = 'none';
        }

        function setRating(stars) {
            currentReviewRating = stars;
            for (let i = 1; i <= 5; i++) {
                const star = document.getElementById(`star-${i}`);
                if (star) star.style.opacity = i <= stars ? '1' : '0.3';
            }
        }

        async function submitReview() {
            const game = document.getElementById('review-game-title').value.trim();
            const review = document.getElementById('review-text').value.trim();
            if (!game || !currentReviewRating || !review) {
                showMessage('Please complete all fields', 'error');
                return;
            }
            try {
                await safeFetch('/api/reviews', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({game, rating: currentReviewRating, review})});
                showMessage('Review posted!', 'success');
                document.getElementById('review-game-title').value = '';
                document.getElementById('review-text').value = '';
                currentReviewRating = 0;
                setRating(0);
                await loadReviews();
            } catch (err) {
                showMessage('Error posting review', 'error');
            }
        }

        async function loadReviews() {
            try {
                const resp = await fetch('/api/reviews');
                const data = await resp.json();
                const reviews = data.reviews || [];
                
                const list = document.getElementById('reviews-list');
                let html = '';
                reviews.forEach(r => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); border-left:3px solid #f59e0b;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <h5 style="margin:0 0 4px 0; color:var(--text-primary);">${r.game_name}</h5>
                                <span style="font-size:0.9em;">${'⭐'.repeat(r.rating)}</span>
                            </div>
                            <p style="margin:0 0 6px 0; font-size:0.85em; color:var(--text-secondary);">by ${r.author}</p>
                            <p style="margin:0; font-size:0.85em;">${r.review}</p>
                            <div style="margin-top:8px; display:flex; gap:8px; font-size:0.8em;">
                                <button style="background:transparent; border:1px solid var(--input-border); padding:4px 8px; border-radius:var(--radius-tag,4px); color:var(--text-primary); cursor:pointer;">👍 Helpful</button>
                                <button style="background:transparent; border:1px solid var(--input-border); padding:4px 8px; border-radius:var(--radius-tag,4px); color:var(--text-primary); cursor:pointer;">👎 Not Helpful</button>
                            </div>
                        </div>
                    `;
                });
                list.innerHTML = html;
            } catch (err) {
                console.error('Error loading reviews:', err);
            }
        }

        // Events
        // Analytics
        async function showAnalytics() {
            const modal = document.getElementById('analytics-modal');
            modal.style.display = 'flex';
            await loadAnalytics();
        }

        function closeAnalytics() {
            const modal = document.getElementById('analytics-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadAnalytics() {
            try {
                const resp = await fetch('/api/analytics');
                const data = await resp.json();
                
                document.getElementById('stat-picks').textContent = data.picks || 0;
                document.getElementById('stat-votes').textContent = data.votes || 0;
                document.getElementById('stat-accuracy').textContent = (data.accuracy || 0) + '%';
                document.getElementById('stat-streak').textContent = (data.streak || 0) + ' 🔥';
                
                const chartsDiv = document.getElementById('analytics-charts');
                chartsDiv.innerHTML = `
                    <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:var(--radius-sm,8px);">
                        <h4 style="margin:0 0 12px 0; color:var(--text-primary);">📈 Activity Over Time</h4>
                        <div style="height:150px; background:rgba(0,0,0,0.2); border-radius:var(--radius-xs,6px); display:flex; align-items:flex-end; justify-content:space-around; padding:10px; gap:5px;">
                            ${[30, 45, 35, 60, 55, 70, 65].map((h, i) => `<div style="flex:1; background:linear-gradient(180deg, #4f46e5, #7c3aed); border-radius:var(--radius-tag,4px); height:${h}%; opacity:0.8;"></div>`).join('')}
                        </div>
                    </div>
                    <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:var(--radius-sm,8px);">
                        <h4 style="margin:0 0 12px 0; color:var(--text-primary);">🎯 Top Categories</h4>
                        <div style="display:flex; flex-direction:column; gap:8px;">
                            <div style="display:flex; justify-content:space-between;"><span>Action</span><span style="font-weight:bold; color:#4f46e5;">45%</span></div>
                            <div style="display:flex; justify-content:space-between;"><span>RPG</span><span style="font-weight:bold; color:#7c3aed;">30%</span></div>
                            <div style="display:flex; justify-content:space-between;"><span>Puzzle</span><span style="font-weight:bold; color:#3b82f6;">25%</span></div>
                        </div>
                    </div>
                `;
            } catch (err) {
                console.error('Error loading analytics:', err);
            }
        }

        // Activity Feed
        async function showActivityFeed() {
            const modal = document.getElementById('activity-feed-modal');
            modal.style.display = 'flex';
            await loadActivityFeed();
        }

        function closeActivityFeed() {
            const modal = document.getElementById('activity-feed-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadActivityFeed() {
            try {
                const resp = await fetch('/api/activity-feed');
                const data = await resp.json();
                const activities = data.activities || [];
                
                const list = document.getElementById('activity-list');
                let html = '';
                activities.forEach(a => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); border-left:3px solid ${a.color};">
                            <p style="margin:0 0 4px 0; color:var(--text-primary);">${a.icon} <strong>${a.user}</strong> ${a.action}</p>
                            <p style="margin:0; font-size:0.85em; color:var(--text-secondary);">${new Date(a.created_at).toLocaleString()}</p>
                        </div>
                    `;
                });
                list.innerHTML = html || '<p style="color:var(--text-secondary);">No recent activity</p>';
            } catch (err) {
                console.error('Error loading activity:', err);
            }
        }

        // Game Series
        async function showSeriesModal() {
            const modal = document.getElementById('series-modal');
            modal.style.display = 'flex';
            await loadSeries();
        }

        function closeSeriesModal() {
            const modal = document.getElementById('series-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadSeries() {
            try {
                const resp = await fetch('/api/game-series');
                const data = await resp.json();
                const series = data.series || [];
                
                const list = document.getElementById('series-list');
                let html = '';
                series.forEach(s => {
                    const completion = Math.round((s.owned_games / s.total_games) * 100);
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px);">
                            <h4 style="margin:0 0 8px 0; color:var(--text-primary);">${s.icon} ${s.name}</h4>
                            <p style="margin:0 0 8px 0; font-size:0.9em; color:var(--text-secondary);">Progress: ${s.owned_games}/${s.total_games}</p>
                            <div style="background:rgba(0,0,0,0.3); border-radius:var(--radius-tag,4px); height:8px; margin-bottom:8px;">
                                <div style="background:linear-gradient(90deg, #4f46e5, #7c3aed); height:100%; width:${completion}%; border-radius:var(--radius-tag,4px);"></div>
                            </div>
                            <button onclick="viewSeries('${s.id}')" style="padding:6px 10px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">View Series</button>
                        </div>
                    `;
                });
                list.innerHTML = html || '<p style="color:var(--text-secondary);">Not tracking any series</p>';
            } catch (err) {
                console.error('Error loading series:', err);
            }
        }

        // Cosmetics & Themes
        async function showCosmetics() {
            const modal = document.getElementById('cosmetics-modal');
            modal.style.display = 'flex';
            await loadCosmetics();
        }

        function closeCosmetics() {
            const modal = document.getElementById('cosmetics-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadCosmetics() {
            try {
                const resp = await fetch('/api/cosmetics');
                const data = await resp.json();
                const themes = data.themes || [];
                const titles = data.titles || [];
                
                const themesDiv = document.getElementById('themes-list');
                let themesHtml = '';
                themes.forEach(t => {
                    themesHtml += `
                        <div style="background:${t.color}; padding:12px; border-radius:var(--radius-sm,8px); cursor:pointer; opacity:${t.owned ? '1' : '0.5'}; border:2px solid ${t.active ? 'var(--accent)' : 'transparent'};" onclick="applyTheme('${t.id}')">
                            <p style="margin:0; text-align:center; font-weight:600;">${t.name}</p>
                        </div>
                    `;
                });
                themesDiv.innerHTML = themesHtml;
                
                const titlesDiv = document.getElementById('titles-list');
                let titlesHtml = '';
                titles.forEach(t => {
                    titlesHtml += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); text-align:center; cursor:pointer; opacity:${t.owned ? '1' : '0.4'}; border:2px solid ${t.active ? 'var(--accent)' : 'transparent'};" onclick="activateTitle('${t.id}')">
                            <p style="margin:0; font-weight:600;">${t.title}</p>
                        </div>
                    `;
                });
                titlesDiv.innerHTML = titlesHtml;
            } catch (err) {
                console.error('Error loading cosmetics:', err);
            }
        }

        // =========================================================================
        // Phase 6: Advanced Features
        // =========================================================================

        // Shop & Marketplace
        async function showShop() {
            const modal = document.getElementById('shop-modal');
            modal.style.display = 'flex';
            await loadShop();
        }

        function closeShop() {
            const modal = document.getElementById('shop-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadShop() {
            try {
                const resp = await fetch('/api/shop');
                const data = await resp.json();
                const items = data.items || [];
                
                const grid = document.getElementById('shop-grid');
                let html = '';
                items.forEach(item => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); text-align:center; border:2px solid ${item.premium ? '#d4af37' : 'transparent'};">
                            <div style="font-size:2em; margin-bottom:6px;">${item.icon}</div>
                            <h5 style="margin:0 0 4px 0; color:var(--text-primary); font-size:0.9em;">${item.name}</h5>
                            <p style="margin:0 0 8px 0; font-size:0.85em; color:var(--text-secondary);">${item.price} ${item.currency === 'xp' ? '⭐' : '💎'}</p>
                            <button onclick="purchaseItem('${item.id}')" style="padding:6px 12px; background:${item.owned ? '#9ca3af' : '#4f46e5'}; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em; width:100%;">${item.owned ? '✓ Owned' : 'Buy'}</button>
                        </div>
                    `;
                });
                grid.innerHTML = html;
            } catch (err) {
                console.error('Error loading shop:', err);
            }
        }

        async function purchaseItem(itemId) {
            try {
                const resp = await safeFetch('/api/shop/purchase', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({item_id: itemId})});
                const data = await resp.json();
                if (data.success) {
                    showMessage('Purchase successful!', 'success');
                    await loadShop();
                } else {
                    showMessage(data.error || 'Purchase failed', 'error');
                }
            } catch (err) {
                showMessage('Error purchasing item', 'error');
            }
        }

        // Streaming Center
        async function showStreaming() {
            const modal = document.getElementById('streaming-modal');
            modal.style.display = 'flex';
            await loadStreaming();
        }

        function closeStreaming() {
            const modal = document.getElementById('streaming-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadStreaming() {
            try {
                const resp = await fetch('/api/streaming/vods');
                const data = await resp.json();
                const vods = data.vods || [];
                
                const list = document.getElementById('vod-list');
                let html = '';
                vods.forEach(vod => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px);">
                            <h5 style="margin:0 0 4px 0; color:var(--text-primary);">${vod.title}</h5>
                            <p style="margin:0 0 6px 0; font-size:0.85em; color:var(--text-secondary);">📺 ${vod.duration} • 👁️ ${vod.views} views</p>
                            <button onclick="playVOD('${vod.id}')" style="padding:6px 12px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">▶️ Watch</button>
                        </div>
                    `;
                });
                list.innerHTML = html || '<p style="color:var(--text-secondary);">No VODs yet</p>';
            } catch (err) {
                console.error('Error loading VODs:', err);
            }
        }

        async function startStream() {
            const title = document.getElementById('stream-title').value.trim();
            if (!title) return;
            try {
                await safeFetch('/api/streaming/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title})});
                showMessage('Stream started!', 'success');
                document.getElementById('stream-title').value = '';
                await loadStreaming();
            } catch (err) {
                showMessage('Error starting stream', 'error');
            }
        }

        // Trading System
        async function showTrading() {
            const modal = document.getElementById('trading-modal');
            modal.style.display = 'flex';
            await loadTrades();
        }

        function closeTrading() {
            const modal = document.getElementById('trading-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadTrades() {
            try {
                const resp = await fetch('/api/trades');
                const data = await resp.json();
                const trades = data.trades || [];
                
                const list = document.getElementById('trades-list');
                let html = '';
                trades.forEach(t => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); border-left:3px solid #10b981;">
                            <h5 style="margin:0 0 6px 0; color:var(--text-primary);">From: ${t.from_user}</h5>
                            <p style="margin:0 0 8px 0; font-size:0.9em; color:var(--text-secondary);">${t.offer}</p>
                            <div style="display:flex; gap:8px;">
                                <button onclick="acceptTrade('${t.id}')" style="padding:6px 10px; background:#10b981; color:white; border:none; border-radius:var(--radius-xs,6px); cursor:pointer; font-size:0.85em; font-family:inherit;">✓ Accept</button>
                                <button onclick="declineTrade('${t.id}')" style="padding:6px 10px; background:#ef4444; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">✕ Decline</button>
                            </div>
                        </div>
                    `;
                });
                list.innerHTML = html || '<p style="color:var(--text-secondary);">No pending trades</p>';
            } catch (err) {
                console.error('Error loading trades:', err);
            }
        }

        async function createTradeOffer() {
            const username = document.getElementById('trade-username').value.trim();
            const offer = document.getElementById('trade-offer').value.trim();
            
            if (!username || !offer) {
                showMessage('Please fill in all fields', 'error');
                return;
            }
            
            try {
                await safeFetch('/api/trades/create', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, offer})});
                showMessage('Trade offer sent!', 'success');
                document.getElementById('trade-username').value = '';
                document.getElementById('trade-offer').value = '';
                await loadTrades();
            } catch (err) {
                showMessage('Error creating trade', 'error');
            }
        }

        async function acceptTrade(tradeId) {
            try {
                await safeFetch(`/api/trades/${tradeId}/accept`, {method: 'POST'});
                showMessage('Trade accepted!', 'success');
                await loadTrades();
            } catch (err) {
                showMessage('Error accepting trade', 'error');
            }
        }

        async function declineTrade(tradeId) {
            try {
                await safeFetch(`/api/trades/${tradeId}/decline`, {method: 'POST'});
                await loadTrades();
            } catch (err) {
                console.error('Error declining trade:', err);
            }
        }

        // AI Recommendations
        async function showAIRecommend() {
            const modal = document.getElementById('ai-recommend-modal');
            modal.style.display = 'flex';
            await loadAIRecommendations();
        }

        function closeAIRecommend() {
            const modal = document.getElementById('ai-recommend-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadAIRecommendations() {
            try {
                const resp = await fetch('/api/recommendations/ai');
                const data = await resp.json();
                const games = data.recommendations || [];
                
                const grid = document.getElementById('ai-recommendations');
                let html = '';
                games.forEach(game => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); text-align:center; cursor:pointer; transition:0.3s;" onmouseover="this.style.background='rgba(102,126,234,0.2)'" onmouseout="this.style.background='rgba(255,255,255,0.05)';">
                            <h5 style="margin:0 0 4px 0; color:var(--text-primary); font-size:0.9em;">${game.name}</h5>
                            <p style="margin:0 0 6px 0; font-size:0.8em; color:#4f46e5; font-weight:600;">Match: ${game.match_score}%</p>
                            <p style="margin:0 0 8px 0; font-size:0.85em; color:var(--text-secondary);">${game.reason}</p>
                            <button onclick="addGameToWishlist('${game.id}')" style="padding:6px 12px; background:#4f46e5; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em; width:100%;">+ Wishlist</button>
                        </div>
                    `;
                });
                grid.innerHTML = html;
            } catch (err) {
                console.error('Error loading recommendations:', err);
            }
        }

        // Clans & Teams
        async function showTeams() {
            const modal = document.getElementById('teams-modal');
            modal.style.display = 'flex';
            await loadTeams();
        }

        function closeTeams() {
            const modal = document.getElementById('teams-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadTeams() {
            try {
                const resp = await fetch('/api/teams');
                const data = await resp.json();
                const teams = data.teams || [];
                
                const list = document.getElementById('teams-list');
                let html = '';
                teams.forEach(t => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:var(--radius-sm,8px); border-left:3px solid ${t.color};">
                            <h4 style="margin:0 0 6px 0; color:var(--text-primary);">${t.name}</h4>
                            <p style="margin:0 0 8px 0; font-size:0.9em; color:var(--text-secondary);">👥 ${t.members.length}/${t.max_members} | Win Rate: ${t.winrate}%</p>
                            <button onclick="joinTeam('${t.id}')" style="padding:6px 10px; background:${t.is_member ? '#9ca3af' : '#4f46e5'}; color:white; border:none; border-radius:var(--radius-tag,4px); cursor:pointer; font-size:0.85em;">${t.is_member ? '✓ Member' : 'Join'}</button>
                        </div>
                    `;
                });
                list.innerHTML = html;
            } catch (err) {
                console.error('Error loading teams:', err);
            }
        }

        async function createTeam() {
            const name = document.getElementById('team-name-input').value.trim();
            if (!name) return;
            try {
                await safeFetch('/api/teams/create', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
                showMessage('Team created!', 'success');
                document.getElementById('team-name-input').value = '';
                await loadTeams();
            } catch (err) {
                showMessage('Error creating team', 'error');
            }
        }

        async function joinTeam(teamId) {
            try {
                await safeFetch(`/api/teams/${teamId}/join`, {method: 'POST'});
                showMessage('Joined team!', 'success');
                await loadTeams();
            } catch (err) {
                showMessage('Error joining team', 'error');
            }
        }

        // Ranked & Tier System
        async function showRanked() {
            const modal = document.getElementById('ranked-modal');
            modal.style.display = 'flex';
            await loadRankedInfo();
        }

        function closeRanked() {
            const modal = document.getElementById('ranked-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadRankedInfo() {
            try {
                const resp = await fetch('/api/ranked');
                const data = await resp.json();
                
                document.getElementById('current-rank').textContent = data.current_rank_emoji + ' ' + data.current_rank;
                
                const tierList = document.getElementById('tier-list');
                let html = '';
                const tiers = ['🥚 Bronze', '🥈 Silver', '🥇 Gold', '💎 Diamond', '👑 Master'];
                tiers.forEach((tier, idx) => {
                    const isCurrent = idx === data.current_tier_index;
                    html += `
                        <div style="padding:12px; background:${isCurrent ? 'rgba(79,70,229,0.25)' : 'rgba(255,255,255,0.05)'}; border-radius:var(--radius-sm,8px); text-align:center; border:2px solid ${isCurrent ? '#4f46e5' : 'transparent'};">
                            <p style="margin:0; font-weight:600; color:var(--text-primary);">${tier}</p>
                        </div>
                    `;
                });
                tierList.innerHTML = html;
            } catch (err) {
                console.error('Error loading ranked info:', err);
            }
        }

        // Anti-Cheat Dashboard
        async function showAntiCheat() {
            const modal = document.getElementById('anticheat-modal');
            modal.style.display = 'flex';
            await loadAntiCheatInfo();
        }

        function closeAntiCheat() {
            const modal = document.getElementById('anticheat-modal');
            if (modal) modal.style.display = 'none';
        }

        async function loadAntiCheatInfo() {
            try {
                const resp = await fetch('/api/anticheat');
                const data = await resp.json();
                
                const list = document.getElementById('flagged-picks');
                let html = '';
                (data.flagged_picks || []).forEach(pick => {
                    html += `
                        <div style="background:rgba(231,76,60,0.1); padding:8px; border-radius:var(--radius-xs,6px); border-left:3px solid #ef4444;">
                            <p style="margin:0; color:var(--text-primary); font-size:0.9em;">⚠️ Session: ${pick.session} | Variance: ${pick.variance}% | Pick: ${pick.pick}</p>
                        </div>
                    `;
                });
                list.innerHTML = html || '<p style="color:var(--text-secondary); margin:0;">No flagged picks - you\'re clean!</p>';
            } catch (err) {
                console.error('Error loading anti-cheat info:', err);
            }
        }

        // Advanced Notifications
        async function showAdvancedNotif() {
            const modal = document.getElementById('notifications-advanced-modal');
            modal.style.display = 'flex';
        }

        function closeAdvancedNotif() {
            const modal = document.getElementById('notifications-advanced-modal');
            if (modal) modal.style.display = 'none';
        }
