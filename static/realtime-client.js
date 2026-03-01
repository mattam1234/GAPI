/**
 * Real-time Client Module for GAPI
 * Handles SSE, WebSocket, and polling for live updates
 */

class RealtimeClient {
    constructor(username) {
        this.username = username;
        this.eventSource = null;
        this.listeners = {};
        this.pollInterval = null;
        this.lastEventTime = null;
        this.useSSE = true;  // Try SSE first
        this.usePolling = false;  // Fallback to polling
        
        this.init();
    }
    
    /**
     * Initialize real-time connection
     */
    init() {
        // Try SSE first
        if (typeof EventSource !== 'undefined') {
            this.initSSE();
        } else {
            // Fallback to polling
            this.initPolling();
        }
    }
    
    /**
     * Initialize Server-Sent Events connection
     */
    initSSE() {
        try {
            this.eventSource = new EventSource('/api/events/stream', {
                headers: { 'X-Username': this.username }
            });
            
            // Handle connection
            this.eventSource.addEventListener('connected', (e) => {
                const data = JSON.parse(e.data);
                console.log('✅ Real-time connected:', data);
                this.emit('connected', data);
            });
            
            // Handle all event types dynamically
            const eventTypes = [
                'leaderboard_update', 'activity', 'trade_notification',
                'team_joined', 'team_created', 'team_match',
                'rank_promotion', 'rank_update',
                'achievement_unlocked',
                'pick_result',
                'shop_purchase',
                'stream_started',
                'notification'
            ];
            
            eventTypes.forEach(eventType => {
                this.eventSource.addEventListener(eventType, (e) => {
                    const data = JSON.parse(e.data);
                    console.log(`📡 Event: ${eventType}`, data);
                    this.emit(eventType, data);
                });
            });
            
            this.eventSource.onerror = (e) => {
                console.error('❌ SSE error:', e);
                this.fallbackToPolling();
            };
            
        } catch (err) {
            console.error('SSE init failed:', err);
            this.fallbackToPolling();
        }
    }
    
    /**
     * Fallback to polling if SSE unavailable
     */
    fallbackToPolling() {
        console.warn('⚠️ Falling back to polling...');
        this.useSSE = false;
        this.usePolling = true;
        this.initPolling();
    }
    
    /**
     * Initialize polling connection
     */
    initPolling() {
        this.lastEventTime = new Date().toISOString();
        
        // Poll for new events every 2 seconds
        this.pollInterval = setInterval(() => {
            this.poll();
        }, 2000);
        
        // Initial poll
        this.poll();
    }
    
    /**
     * Poll for new events
     */
    async poll() {
        try {
            const resp = await fetch(`/api/events/poll?since=${encodeURIComponent(this.lastEventTime)}`, {
                headers: { 'X-Username': this.username }
            });
            
            if (!resp.ok) return;
            
            const data = await resp.json();
            if (data.events && data.events.length > 0) {
                data.events.forEach(event => {
                    console.log('📡 Polled event:', event);
                    const eventType = event.type || 'update';
                    this.emit(eventType, event);
                });
                this.lastEventTime = data.timestamp;
            }
        } catch (err) {
            console.error('Polling error:', err);
        }
    }
    
    /**
     * Subscribe to event type
     */
    on(eventType, callback) {
        if (!this.listeners[eventType]) {
            this.listeners[eventType] = [];
        }
        this.listeners[eventType].push(callback);
        return () => this.off(eventType, callback);  // Return unsubscribe function
    }
    
    /**
     * Unsubscribe from event type
     */
    off(eventType, callback) {
        if (this.listeners[eventType]) {
            this.listeners[eventType] = this.listeners[eventType].filter(cb => cb !== callback);
        }
    }
    
    /**
     * Emit event to all listeners
     */
    emit(eventType, data) {
        if (this.listeners[eventType]) {
            this.listeners[eventType].forEach(cb => {
                try {
                    cb(data);
                } catch (err) {
                    console.error(`Error in listener for ${eventType}:`, err);
                }
            });
        }
    }
    
    /**
     * Cleanup and disconnect
     */
    disconnect() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        console.log('🔌 Real-time disconnected');
    }
    
    /**
     * Check real-time status
     */
    async getStatus() {
        try {
            const resp = await fetch('/api/events/status', {
                headers: { 'X-Username': this.username }
            });
            return resp.json();
        } catch (err) {
            return { error: err.message };
        }
    }
}

/**
 * Initialize real-time for page
 */
function initRealtime(username) {
    window.realtimeClient = new RealtimeClient(username);
    
    // Leaderboard updates
    window.realtimeClient.on('leaderboard_update', (data) => {
        console.log(`🏆 ${data.username} #${data.position} in ${data.category}`);
        // Update UI leaderboard if visible
        const leaderboardContainer = document.getElementById('leaderboard-list');
        if (leaderboardContainer) {
            updateLeaderboardUI(data);
        }
    });
    
    // Activity feed updates
    window.realtimeClient.on('activity', (data) => {
        console.log(`⚡ ${data.user} ${data.action}`);
        const activityContainer = document.getElementById('activity-list');
        if (activityContainer) {
            addActivityToUI(data);
        }
    });
    
    // Trade notifications
    window.realtimeClient.on('trade_notification', (data) => {
        showNotification(`Trade offer from ${data.from_user}`, 'info');
        if (window.loadTrades) {
            window.loadTrades();
        }
    });
    
    // Team notifications
    window.realtimeClient.on('team_joined', (data) => {
        showNotification(`You joined ${data.team_name}!`, 'success');
    });
    
    window.realtimeClient.on('team_match', (data) => {
        showNotification(`Match started in ${data.team_name}!`, 'info');
    });
    
    // Rank promotions
    window.realtimeClient.on('rank_promotion', (data) => {
        showNotification(`🎉 Promoted to ${data.new_tier}!`, 'success');
        if (window.loadRankedInfo) {
            window.loadRankedInfo();
        }
    });
    
    // Achievement unlocks
    window.realtimeClient.on('achievement_unlocked', (data) => {
        showNotification(`${data.icon} Achievement: ${data.achievement}!`, 'success');
        if (window.loadAchievements) {
            window.loadAchievements();
        }
    });
    
    // Pick results
    window.realtimeClient.on('pick_result', (data) => {
        showNotification(`🎮 ${data.winning_game} won!`, 'info');
    });
    
    // Shop purchases
    window.realtimeClient.on('shop_purchase', (data) => {
        showNotification(`${data.username} purchased ${data.item}!`, 'info');
    });
    
    // Stream notifications
    window.realtimeClient.on('stream_started', (data) => {
        showNotification(`🔴 ${data.streamer} started streaming: ${data.title}`, 'info');
    });
    
    // Generic notifications
    window.realtimeClient.on('notification', (data) => {
        showNotification(data.message, data.notif_type || 'info');
    });
    
    console.log('✨ Real-time client initialized');
    return window.realtimeClient;
}

/**
 * Helper functions for UI updates
 */

function updateLeaderboardUI(data) {
    const item = document.createElement('div');
    item.style.cssText = 'background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; margin-bottom:8px; animation:slideIn 0.3s;';
    item.innerHTML = `
        <div style="display:flex; justify-content:space-between;">
            <span style="color:var(--text-primary); font-weight:600;">#${data.position} ${data.username}</span>
            <span style="color:#667eea; font-weight:bold;">${data.value} ${data.category}</span>
        </div>
    `;
    
    const container = document.getElementById('leaderboard-list');
    if (container) {
        container.insertBefore(item, container.firstChild);
        if (container.children.length > 20) {
            container.removeChild(container.lastChild);
        }
    }
}

function addActivityToUI(data) {
    const item = document.createElement('div');
    item.style.cssText = 'background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; margin-bottom:8px; animation:slideIn 0.3s; border-left:3px solid #667eea;';
    item.innerHTML = `
        <p style="margin:0; color:var(--text-primary);">${data.icon} <strong>${data.user}</strong> ${data.action}${data.game ? ' ' + data.game : ''}</p>
        <p style="margin:4px 0 0 0; font-size:0.8em; color:var(--text-secondary);">${new Date().toLocaleTimeString()}</p>
    `;
    
    const container = document.getElementById('activity-list');
    if (container) {
        container.insertBefore(item, container.firstChild);
        if (container.children.length > 20) {
            container.removeChild(container.lastChild);
        }
    }
}

function showNotification(message, type = 'info') {
    const notifContainer = document.getElementById('notifications-container') || createNotificationsContainer();
    
    const notif = document.createElement('div');
    const colors = {
        success: '#27ae60',
        error: '#e74c3c',
        info: '#3498db',
        warning: '#f39c12'
    };
    
    notif.style.cssText = `
        background:${colors[type] || colors.info}88;
        border-left:4px solid ${colors[type] || colors.info};
        color:white;
        padding:12px 16px;
        border-radius:6px;
        margin-bottom:8px;
        animation:slideInRight 0.3s;
        cursor:pointer;
    `;
    notif.textContent = message;
    notif.onclick = () => notif.remove();
    
    notifContainer.appendChild(notif);
    
    // Auto-remove after 5 seconds
    setTimeout(() => notif.remove(), 5000);
}

function createNotificationsContainer() {
    const container = document.createElement('div');
    container.id = 'notifications-container';
    container.style.cssText = `
        position:fixed;
        top:20px;
        right:20px;
        max-width:400px;
        z-index:10000;
    `;
    document.body.appendChild(container);
    return container;
}

// Add animation styles if not already present
if (!document.getElementById('realtime-styles')) {
    const style = document.createElement('style');
    style.id = 'realtime-styles';
    style.textContent = `
        @keyframes slideIn {
            from { opacity:0; transform:translateY(-10px); }
            to { opacity:1; transform:translateY(0); }
        }
        @keyframes slideInRight {
            from { opacity:0; transform:translateX(100px); }
            to { opacity:1; transform:translateX(0); }
        }
    `;
    document.head.appendChild(style);
}
