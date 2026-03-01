/**
 * UX ENHANCEMENTS - Modern Interactive Features
 * - Advanced Toast Notifications
 * - Loading States & Skeletons
 * - Tooltip System
 * - Keyboard Shortcuts
 * - Quick Actions FAB
 * - Onboarding Tour
 * - Search Autocomplete
 * - Progress Indicators
 */

// ═══════════════════════════════════════════════════════════════════════════
// ADVANCED TOAST NOTIFICATION SYSTEM
// ═══════════════════════════════════════════════════════════════════════════

const toastContainer = (() => {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        `;
        document.body.appendChild(container);
    }
    return container;
})();

let toastCounter = 0;

/**
 * Show beautiful toast notification with icons and animations
 * @param {string} message - Notification message
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (0 = persistent)
 * @param {object} options - Additional options {action, actionText, icon}
 */
function showToast(message, type = 'info', duration = 4000, options = {}) {
    const toast = document.createElement('div');
    const toastId = `toast-${toastCounter++}`;
    toast.id = toastId;
    
    // Icon mapping
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️',
        loading: '⏳'
    };
    
    // Color mapping
    const colors = {
        success: '#27ae60',
        error: '#e74c3c',
        warning: '#f39c12',
        info: '#3498db',
        loading: '#667eea'
    };
    
    const icon = options.icon || icons[type] || icons.info;
    const color = colors[type] || colors.info;
    
    // Build action button if provided
    let actionHtml = '';
    if (options.action && options.actionText) {
        actionHtml = `
            <button onclick="${options.action}" 
                style="padding:4px 12px; border:none; background:rgba(255,255,255,0.2); 
                       color:white; border-radius:4px; cursor:pointer; font-weight:600; 
                       font-size:0.85em; margin-left:auto;">
                ${options.actionText}
            </button>
        `;
    }
    
    toast.innerHTML = `
        <div style="display:flex; align-items:center; gap:12px; padding:16px; 
                    background:${color}; color:white; border-radius:10px; 
                    box-shadow:0 4px 12px rgba(0,0,0,0.15); min-width:280px;
                    animation:slideInRight 0.3s ease-out;">
            <span style="font-size:1.5em;">${icon}</span>
            <span style="flex:1; font-weight:500; line-height:1.4;">${message}</span>
            ${actionHtml}
            <button onclick="dismissToast('${toastId}')" 
                style="padding:4px 8px; border:none; background:transparent; 
                       color:white; cursor:pointer; font-size:1.2em; opacity:0.8;
                       line-height:1;">
                ×
            </button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => dismissToast(toastId), duration);
    }
    
    return toastId;
}

function dismissToast(toastId) {
    const toast = document.getElementById(toastId);
    if (!toast) return;
    
    toast.style.animation = 'slideOutRight 0.3s ease-in';
    setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
}

// Enhanced showMessage wrapper for backward compatibility
const originalShowMessage = window.showMessage || function() {};
window.showMessage = function(message, type = 'info') {
    showToast(message, type);
    // Also call original if it exists
    if (originalShowMessage !== window.showMessage) {
        originalShowMessage(message, type);
    }
};

// ═══════════════════════════════════════════════════════════════════════════
// LOADING STATES & SKELETON SCREENS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Show loading overlay on an element
 */
function showLoadingState(elementId, message = 'Loading...') {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const overlay = document.createElement('div');
    overlay.className = 'loading-overlay';
    overlay.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; gap:16px;">
            <div class="spinner"></div>
            <span style="color:var(--text-primary); font-weight:600;">${message}</span>
        </div>
    `;
    
    overlay.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(255,255,255,0.9);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 100;
        border-radius: inherit;
    `;
    
    element.style.position = element.style.position || 'relative';
    element.appendChild(overlay);
}

function hideLoadingState(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const overlay = element.querySelector('.loading-overlay');
    if (overlay) {
        overlay.style.opacity = '0';
        setTimeout(() => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }, 300);
    }
}

/**
 * Create skeleton loader HTML
 */
function createSkeletonCard() {
    return `
        <div class="skeleton-card" style="padding:20px; background:var(--card-bg); 
             border-radius:10px; margin-bottom:16px; animation:pulse 1.5s ease-in-out infinite;">
            <div class="skeleton-line" style="height:24px; background:var(--list-hover); 
                 border-radius:4px; margin-bottom:12px; width:60%;"></div>
            <div class="skeleton-line" style="height:16px; background:var(--list-hover); 
                 border-radius:4px; margin-bottom:8px; width:100%;"></div>
            <div class="skeleton-line" style="height:16px; background:var(--list-hover); 
                 border-radius:4px; margin-bottom:8px; width:90%;"></div>
            <div class="skeleton-line" style="height:16px; background:var(--list-hover); 
                 border-radius:4px; width:70%;"></div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════════════════
// TOOLTIP SYSTEM
// ═══════════════════════════════════════════════════════════════════════════

const tooltipInstance = (() => {
    let tooltip = document.getElementById('app-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'app-tooltip';
        tooltip.style.cssText = `
            position: fixed;
            padding: 8px 12px;
            background: rgba(0,0,0,0.9);
            color: white;
            border-radius: 6px;
            font-size: 0.85em;
            max-width: 250px;
            z-index: 10001;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        `;
        document.body.appendChild(tooltip);
    }
    return tooltip;
})();

/**
 * Initialize tooltips for all elements with data-tooltip attribute
 */
function initTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(element => {
        element.addEventListener('mouseenter', showTooltip);
        element.addEventListener('mouseleave', hideTooltip);
        element.addEventListener('mousemove', positionTooltip);
    });
}

function showTooltip(e) {
    const text = e.target.getAttribute('data-tooltip');
    if (!text) return;
    
    tooltipInstance.textContent = text;
    tooltipInstance.style.opacity = '1';
    positionTooltip(e);
}

function hideTooltip() {
    tooltipInstance.style.opacity = '0';
}

function positionTooltip(e) {
    const x = e.clientX;
    const y = e.clientY;
    
    tooltipInstance.style.left = `${x + 10}px`;
    tooltipInstance.style.top = `${y + 10}px`;
}

// ═══════════════════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════════════════════════════════

const shortcuts = {
    'Ctrl+P': () => { document.querySelector('[onclick*="picker"]')?.click(); },
    'Ctrl+L': () => { document.querySelector('[onclick*="library"]')?.click(); },
    'Ctrl+F': () => { document.querySelector('[onclick*="favorites"]')?.click(); },
    'Ctrl+S': () => { document.querySelector('[onclick*="stats"]')?.click(); },
    'Ctrl+K': () => { openCommandPalette(); },
    '?': () => { showKeyboardShortcutsHelp(); },
    'Escape': () => { closeAllModals(); }
};

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ignore if typing in input/textarea
        if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
        
        const key = [];
        if (e.ctrlKey) key.push('Ctrl');
        if (e.shiftKey) key.push('Shift');
        if (e.altKey) key.push('Alt');
        key.push(e.key);
        
        const combo = key.join('+');
        
        if (shortcuts[combo]) {
            e.preventDefault();
            shortcuts[combo]();
        }
    });
}

function showKeyboardShortcutsHelp() {
    const shortcutsList = Object.entries(shortcuts)
        .map(([key, _]) => `<li><code>${key}</code> - ${getShortcutDescription(key)}</li>`)
        .join('');
    
    showToast(`
        <div style="text-align:left;">
            <strong style="display:block; margin-bottom:8px;">⌨️ Keyboard Shortcuts:</strong>
            <ul style="margin:0; padding-left:20px; line-height:1.8;">
                ${shortcutsList}
            </ul>
        </div>
    `, 'info', 8000);
}

function getShortcutDescription(key) {
    const descriptions = {
        'Ctrl+P': 'Pick a Game',
        'Ctrl+L': 'View Library',
        'Ctrl+F': 'View Favorites',
        'Ctrl+S': 'View Statistics',
        'Ctrl+K': 'Command Palette',
        '?': 'Show Shortcuts',
        'Escape': 'Close Modals'
    };
    return descriptions[key] || 'Action';
}

// ═══════════════════════════════════════════════════════════════════════════
// QUICK ACTIONS FAB (Floating Action Button)
// ═══════════════════════════════════════════════════════════════════════════

function createQuickActionsFAB() {
    const fab = document.createElement('div');
    fab.id = 'quick-actions-fab';
    fab.innerHTML = `
        <button id="fab-main-btn" onclick="toggleQuickActions()" 
            data-tooltip="Quick Actions (Ctrl+K)"
            style="width:60px; height:60px; border-radius:50%; 
                   background:linear-gradient(135deg,#667eea,#764ba2); 
                   color:white; border:none; box-shadow:0 4px 12px rgba(0,0,0,0.3);
                   cursor:pointer; font-size:1.5em; transition:all 0.3s;
                   display:flex; align-items:center; justify-content:center;">
            ⚡
        </button>
        <div id="fab-menu" style="position:absolute; bottom:70px; right:0; 
             background:var(--card-bg); border-radius:12px; padding:8px;
             box-shadow:0 4px 16px rgba(0,0,0,0.2); display:none; min-width:200px;
             border:1px solid var(--card-border);">
            <button onclick="quickPickGame(); toggleQuickActions();" 
                class="fab-menu-item">🎮 Quick Pick</button>
            <button onclick="openAdvancedSearch(); toggleQuickActions();" 
                class="fab-menu-item">🔍 Advanced Search</button>
            <button onclick="openAnalyticsDashboard(); toggleQuickActions();" 
                class="fab-menu-item">📊 Analytics</button>
            <button onclick="openAuditLog(); toggleQuickActions();" 
                class="fab-menu-item">📋 Audit Log</button>
            <button onclick="openModerationPanel(); toggleQuickActions();" 
                class="fab-menu-item">🛡️ Moderation</button>
            <button onclick="openBatchOperations(); toggleQuickActions();" 
                class="fab-menu-item">⚡ Batch Ops</button>
            <button onclick="showKeyboardShortcutsHelp(); toggleQuickActions();" 
                class="fab-menu-item">⌨️ Shortcuts</button>
        </div>
    `;
    
    fab.style.cssText = `
        position: fixed;
        bottom: 30px;
        right: 30px;
        z-index: 9999;
    `;
    
    document.body.appendChild(fab);
    
    // Add hover effect
    const mainBtn = document.getElementById('fab-main-btn');
    mainBtn.addEventListener('mouseenter', () => {
        mainBtn.style.transform = 'scale(1.1) rotate(90deg)';
    });
    mainBtn.addEventListener('mouseleave', () => {
        mainBtn.style.transform = 'scale(1) rotate(0deg)';
    });
}

function toggleQuickActions() {
    const menu = document.getElementById('fab-menu');
    const mainBtn = document.getElementById('fab-main-btn');
    if (!menu) return;
    
    const isOpen = menu.style.display !== 'none';
    menu.style.display = isOpen ? 'none' : 'block';
    mainBtn.textContent = isOpen ? '⚡' : '✕';
    
    if (!isOpen) {
        menu.style.animation = 'fadeInUp 0.3s ease-out';
    }
}

function quickPickGame() {
    // Trigger the pick button
    const pickBtn = document.querySelector('.pick-button');
    if (pickBtn) pickBtn.click();
    else showToast('Pick button not found', 'error');
}

// ═══════════════════════════════════════════════════════════════════════════
// COMMAND PALETTE (Ctrl+K)
// ═══════════════════════════════════════════════════════════════════════════

function openCommandPalette() {
    const existing = document.getElementById('command-palette-modal');
    if (existing) {
        existing.style.display = 'flex';
        document.getElementById('command-palette-input')?.focus();
        return;
    }
    
    const modal = document.createElement('div');
    modal.id = 'command-palette-modal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.5);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: flex-start;
        justify-content: center;
        z-index: 10002;
        padding-top: 100px;
    `;
    
    modal.innerHTML = `
        <div style="width:90%; max-width:600px; background:var(--card-bg); 
             border-radius:12px; box-shadow:0 8px 32px rgba(0,0,0,0.3); 
             overflow:hidden; animation:fadeInDown 0.3s ease-out;">
            <input id="command-palette-input" type="text" 
                placeholder="Type a command or search..." 
                oninput="filterCommands(this.value)"
                style="width:100%; padding:20px; border:none; background:var(--input-bg); 
                       color:var(--text-primary); font-size:1.1em; border-bottom:1px solid var(--card-border);">
            <div id="command-palette-results" style="max-height:400px; overflow-y:auto;">
                <!-- Results populated by filterCommands -->
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeCommandPalette();
    });
    
    document.getElementById('command-palette-input')?.focus();
    filterCommands('');
}

function closeCommandPalette() {
    const modal = document.getElementById('command-palette-modal');
    if (modal) {
        modal.style.animation = 'fadeOut 0.2s ease-in';
        setTimeout(() => {
            if (modal.parentNode) modal.parentNode.removeChild(modal);
        }, 200);
    }
}

const commands = [
    { name: '🎮 Pick a Game', action: () => switchTab('picker') },
    { name: '📚 View Library', action: () => switchTab('library') },
    { name: '⭐ View Favorites', action: () => switchTab('favorites') },
    { name: '📊 View Statistics', action: () => switchTab('stats') },
    { name: '👥 View Users', action: () => switchTab('users') },
    { name: '🔍 Advanced Search', action: () => openAdvancedSearch?.() },
    { name: '📈 Analytics Dashboard', action: () => openAnalyticsDashboard?.() },
    { name: '📋 Audit Log', action: () => openAuditLog?.() },
    { name: '🛡️ Moderation Panel', action: () => openModerationPanel?.() },
    { name: '⚡ Batch Operations', action: () => openBatchOperations?.() },
    { name: '🌙 Toggle Dark Mode', action: () => toggleDarkMode?.() },
    { name: '⌨️ Show Shortcuts', action: () => showKeyboardShortcutsHelp() }
];

function filterCommands(query) {
    const results = document.getElementById('command-palette-results');
    if (!results) return;
    
    const filtered = query 
        ? commands.filter(cmd => cmd.name.toLowerCase().includes(query.toLowerCase()))
        : commands;
    
    if (filtered.length === 0) {
        results.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-secondary);">No commands found</div>';
        return;
    }
    
    results.innerHTML = filtered.map(cmd => `
        <div onclick="${cmd.action.toString()}(); closeCommandPalette();" 
             style="padding:16px 20px; cursor:pointer; transition:background 0.2s; 
                    color:var(--text-primary); border-bottom:1px solid var(--card-border);"
             onmouseenter="this.style.background='var(--list-hover)'"
             onmouseleave="this.style.background='transparent'">
            ${cmd.name}
        </div>
    `).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// ONBOARDING TOUR
// ═══════════════════════════════════════════════════════════════════════════

const tourSteps = [
    {
        element: '.pick-button',
        title: 'Pick a Game',
        description: 'Click here to randomly pick a game from your library based on your preferences.'
    },
    {
        element: '.tabs',
        title: 'Navigation Tabs',
        description: 'Use these tabs to navigate between different sections of the app.'
    },
    {
        element: '#dark-mode-btn',
        title: 'Dark Mode',
        description: 'Toggle between light and dark themes for better viewing comfort.'
    },
    {
        element: '#quick-actions-fab',
        title: 'Quick Actions',
        description: 'Access frequently used features quickly with this menu.'
    }
];

let currentTourStep = 0;

function startOnboardingTour() {
    if (localStorage.getItem('tour_completed') === 'true') {
        if (!confirm('You\'ve already completed the tour. Start again?')) return;
    }
    
    currentTourStep = 0;
    showTourStep(currentTourStep);
}

function showTourStep(stepIndex) {
    if (stepIndex >= tourSteps.length) {
        endTour();
        return;
    }
    
    const step = tourSteps[stepIndex];
    const element = document.querySelector(step.element);
    
    if (!element) {
        // Skip if element not found
        showTourStep(stepIndex + 1);
        return;
    }
    
    // Create spotlight overlay
    const overlay = document.createElement('div');
    overlay.id = 'tour-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.7);
        z-index: 10003;
        pointer-events: none;
    `;
    
    // Create tour popup
    const rect = element.getBoundingClientRect();
    const popup = document.createElement('div');
    popup.id = 'tour-popup';
    popup.style.cssText = `
        position: fixed;
        top: ${rect.bottom + 20}px;
        left: ${rect.left}px;
        background: var(--card-bg);
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        z-index: 10004;
        max-width: 300px;
        animation: fadeInUp 0.3s ease-out;
    `;
    
    popup.innerHTML = `
        <h3 style="margin:0 0 10px; color:var(--text-primary);">${step.title}</h3>
        <p style="margin:0 0 20px; color:var(--text-secondary); line-height:1.6;">${step.description}</p>
        <div style="display:flex; gap:10px; justify-content:space-between; align-items:center;">
            <span style="color:var(--text-secondary); font-size:0.85em;">${stepIndex + 1} / ${tourSteps.length}</span>
            <div style="display:flex; gap:8px;">
                <button onclick="skipTour()" 
                    style="padding:8px 16px; border:1px solid var(--input-border); 
                           background:transparent; color:var(--text-primary); 
                           border-radius:6px; cursor:pointer;">Skip</button>
                <button onclick="nextTourStep()" 
                    style="padding:8px 16px; border:none; 
                           background:linear-gradient(135deg,#667eea,#764ba2); 
                           color:white; border-radius:6px; cursor:pointer; font-weight:600;">
                    ${stepIndex === tourSteps.length - 1 ? 'Finish' : 'Next'}
                </button>
            </div>
        </div>
    `;
    
    // Highlight the target element
    element.style.position = 'relative';
    element.style.zIndex = '10005';
    element.style.boxShadow = '0 0 0 4px #667eea, 0 0 20px rgba(102,126,234,0.5)';
    
    document.body.appendChild(overlay);
    document.body.appendChild(popup);
}

function nextTourStep() {
    clearTour();
    currentTourStep++;
    showTourStep(currentTourStep);
}

function skipTour() {
    clearTour();
    showToast('Tour skipped. You can restart it anytime from the Quick Actions menu.', 'info');
}

function endTour() {
    clearTour();
    localStorage.setItem('tour_completed', 'true');
    showToast('🎉 Tour complete! You\'re ready to explore GAPI!', 'success', 5000);
}

function clearTour() {
    // Remove overlay and popup
    const overlay = document.getElementById('tour-overlay');
    const popup = document.getElementById('tour-popup');
    if (overlay) overlay.remove();
    if (popup) popup.remove();
    
    // Remove highlights
    tourSteps.forEach(step => {
        const element = document.querySelector(step.element);
        if (element) {
            element.style.boxShadow = '';
            element.style.zIndex = '';
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// PROGRESS INDICATORS
// ═══════════════════════════════════════════════════════════════════════════

function showProgressBar(containerId, progress, label = '') {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    const existing = container.querySelector('.progress-bar-wrapper');
    if (existing) existing.remove();
    
    const wrapper = document.createElement('div');
    wrapper.className = 'progress-bar-wrapper';
    wrapper.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="color:var(--text-secondary); font-size:0.9em;">${label}</span>
            <span style="color:var(--text-primary); font-weight:600;">${progress}%</span>
        </div>
        <div style="height:8px; background:var(--list-hover); border-radius:4px; overflow:hidden;">
            <div style="height:100%; width:${progress}%; 
                 background:linear-gradient(90deg,#667eea,#764ba2); 
                 transition:width 0.3s; border-radius:4px;"></div>
        </div>
    `;
    
    container.appendChild(wrapper);
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

function closeAllModals() {
    // Close all modals with display:flex
    document.querySelectorAll('[id$="-modal"]').forEach(modal => {
        if (modal.style.display === 'flex') {
            modal.style.display = 'none';
        }
    });
    
    // Close command palette
    closeCommandPalette();
    
    // Close FAB menu
    const fabMenu = document.getElementById('fab-menu');
    if (fabMenu && fabMenu.style.display !== 'none') {
        toggleQuickActions();
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════

function initUXEnhancements() {
    // Initialize all UX features
    initTooltips();
    initKeyboardShortcuts();
    createQuickActionsFAB();
    
    // Show welcome toast on first visit
    if (!localStorage.getItem('tour_completed')) {
        setTimeout(() => {
            showToast(
                'Welcome to GAPI! 👋 Press ? for keyboard shortcuts or click ⚡ for quick actions.',
                'info',
                6000,
                {
                    action: 'startOnboardingTour()',
                    actionText: 'Take Tour'
                }
            );
        }, 1000);
    }
    
    console.log('✨ UX Enhancements initialized');
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUXEnhancements);
} else {
    initUXEnhancements();
}
