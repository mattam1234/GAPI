/**
 * Frontend Performance Optimization Module
 * Handles lazy loading, caching, pagination UI, and performance monitoring
 */

class FrontendCache {
    constructor(maxSize = 100, defaultTTL = 300000) {
        this.cache = new Map();
        this.maxSize = maxSize;
        this.defaultTTL = defaultTTL;
    }

    set(key, value, ttl = null) {
        if (this.cache.size >= this.maxSize) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }

        const entry = {
            value,
            createdAt: Date.now(),
            ttl: ttl || this.defaultTTL
        };

        this.cache.set(key, entry);
    }

    get(key) {
        if (!this.cache.has(key)) return null;

        const entry = this.cache.get(key);
        const age = Date.now() - entry.createdAt;

        if (age > entry.ttl) {
            this.cache.delete(key);
            return null;
        }

        return entry.value;
    }

    clear() {
        this.cache.clear();
    }

    stats() {
        return {
            size: this.cache.size,
            maxSize: this.maxSize
        };
    }
}

// Global frontend cache
const frontendCache = new FrontendCache();

class PaginationHelper {
    static createPageSelector(totalPages, currentPage, onPageChange) {
        let html = '<div style="display:flex; gap:8px; justify-content:center; align-items:center; margin:16px 0;">';
        
        // Previous button
        if (currentPage > 1) {
            html += `<button onclick="${onPageChange}(${currentPage - 1})" style="padding:6px 12px; background:#667eea; color:white; border:none; border-radius:4px; cursor:pointer;">← Previous</button>`;
        }

        // Page numbers
        for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
            if (i === currentPage) {
                html += `<span style="padding:6px 12px; background:#667eea; color:white; border-radius:4px; font-weight:bold;">${i}</span>`;
            } else {
                html += `<button onclick="${onPageChange}(${i})" style="padding:6px 12px; background:transparent; color:#667eea; border:1px solid #667eea; border-radius:4px; cursor:pointer;">${i}</button>`;
            }
        }

        // Next button
        if (currentPage < totalPages) {
            html += `<button onclick="${onPageChange}(${currentPage + 1})" style="padding:6px 12px; background:#667eea; color:white; border:none; border-radius:4px; cursor:pointer;">Next →</button>`;
        }

        // Page info
        html += `<span style="color:var(--text-secondary); font-size:0.9em;">Page ${currentPage} of ${totalPages}</span>`;
        html += '</div>';

        return html;
    }

    static createPerPageSelector(onPerPageChange) {
        return `
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
                <label for="per-page-select" style="color:var(--text-secondary); font-size:0.9em;">Per page:</label>
                <select id="per-page-select" onchange="${onPerPageChange}(this.value)" style="padding:6px 12px; border:1px solid var(--input-border); border-radius:4px; background:var(--input-bg); color:var(--text-primary);">
                    <option value="10">10</option>
                    <option value="20" selected>20</option>
                    <option value="50">50</option>
                    <option value="100">100</option>
                </select>
            </div>
        `;
    }
}

class LazyLoader {
    constructor(container, loadMoreThreshold = 200) {
        this.container = container;
        this.loadMoreThreshold = loadMoreThreshold;
        this.isLoading = false;
        this.hasMore = true;
        this.currentPage = 1;
        this.setupIntersectionObserver();
    }

    setupIntersectionObserver() {
        if (!('IntersectionObserver' in window)) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && this.hasMore && !this.isLoading) {
                    this.onNearBottom?.();
                }
            });
        }, { rootMargin: `${this.loadMoreThreshold}px` });

        observer.observe(this.container);
    }

    onNearBottom(callback) {
        this.onNearBottom = callback;
    }

    setLoading(loading) {
        this.isLoading = loading;
    }

    setHasMore(hasMore) {
        this.hasMore = hasMore;
    }
}

class PerformanceMonitor {
    constructor() {
        this.metrics = {};
        this.startTimes = {};
    }

    startTimer(name) {
        this.startTimes[name] = performance.now();
    }

    endTimer(name) {
        if (!this.startTimes[name]) return 0;

        const elapsed = performance.now() - this.startTimes[name];

        if (!this.metrics[name]) {
            this.metrics[name] = [];
        }

        this.metrics[name].push(elapsed);

        // Keep only last 50 measurements
        if (this.metrics[name].length > 50) {
            this.metrics[name] = this.metrics[name].slice(-50);
        }

        delete this.startTimes[name];
        return elapsed;
    }

    getStats(name) {
        if (!this.metrics[name] || this.metrics[name].length === 0) {
            return null;
        }

        const values = this.metrics[name];
        return {
            count: values.length,
            min: Math.round(Math.min(...values) * 100) / 100,
            max: Math.round(Math.max(...values) * 100) / 100,
            avg: Math.round(values.reduce((a, b) => a + b, 0) / values.length * 100) / 100,
            last: Math.round(values[values.length - 1] * 100) / 100
        };
    }

    getAllStats() {
        const stats = {};
        for (const name in this.metrics) {
            const s = this.getStats(name);
            if (s) stats[name] = s;
        }
        return stats;
    }

    displayStats(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const stats = this.getAllStats();
        let html = '<table style="width:100%; border-collapse:collapse; font-size:0.85em;">';
        html += '<tr style="border-bottom:1px solid var(--input-border);"><th style="text-align:left; padding:8px;">Metric</th><th>Avg (ms)</th><th>Min</th><th>Max</th></tr>';

        for (const [name, stat] of Object.entries(stats)) {
            html += `<tr style="border-bottom:1px solid var(--input-border);">`;
            html += `<td style="padding:8px;">${name}</td>`;
            html += `<td style="padding:8px; text-align:center;">${stat.avg}</td>`;
            html += `<td style="padding:8px; text-align:center;">${stat.min}</td>`;
            html += `<td style="padding:8px; text-align:center;">${stat.max}</td>`;
            html += `</tr>`;
        }

        html += '</table>';
        container.innerHTML = html;
    }
}

// Global performance monitor
const frontendMonitor = new PerformanceMonitor();

/**
 * Optimized data loading functions
 */

async function loadPagedData(endpoint, page = 1, perPage = 20) {
    const cacheKey = `${endpoint}:${page}:${perPage}`;
    const cached = frontendCache.get(cacheKey);

    if (cached) {
        console.log(`📦 Loaded from cache: ${cacheKey}`);
        return cached;
    }

    frontendMonitor.startTimer(`fetch_${endpoint}`);

    try {
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set('page', page);
        url.searchParams.set('per_page', perPage);

        const resp = await fetch(url);
        const data = await resp.json();

        frontendMonitor.endTimer(`fetch_${endpoint}`);

        // Cache for 5 minutes
        frontendCache.set(cacheKey, data, 300000);

        return data;
    } catch (err) {
        console.error('Error loading paged data:', err);
        return { items: [], page: 1, total: 0 };
    }
}

async function loadWithPagination(endpoint, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    let currentPage = 1;
    let perPage = 20;

    async function renderPage(page, perPage) {
        container.innerHTML = '<div class="loading">Loading...</div>';

        try {
            const data = await loadPagedData(endpoint, page, perPage);

            let html = PaginationHelper.createPerPageSelector(`changePerPage_${containerId}`);

            if (data.items && data.items.length > 0) {
                html += '<div style="display:grid; grid-template-columns:1fr; gap:12px; margin:16px 0;">';

                data.items.forEach((item, idx) => {
                    html += `
                        <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;">
                            <span style="color:var(--text-primary);">${item.username || item.name || JSON.stringify(item).slice(0, 50)}</span>
                            <span style="color:var(--text-secondary); font-size:0.9em;">${item.value || item.email || ''}</span>
                        </div>
                    `;
                });

                html += '</div>';
            } else {
                html += '<p style="color:var(--text-secondary); text-align:center;">No results found</p>';
            }

            if (data.total_pages > 1) {
                html += PaginationHelper.createPageSelector(data.total_pages, page, `changePage_${containerId}`);
            }

            container.innerHTML = html;
            currentPage = page;
            perPage = perPage;
        } catch (err) {
            container.innerHTML = `<p style="color:#e74c3c;">Error loading data: ${err.message}</p>`;
        }
    }

    // Make page change function global
    window[`changePage_${containerId}`] = (page) => renderPage(page, perPage);
    window[`changePerPage_${containerId}`] = (value) => renderPage(1, parseInt(value));

    // Initial load
    await renderPage(1, 20);
}

/**
 * Monitoring display
 */

function showPerformanceStats() {
    const modal = document.createElement('div');
    modal.id = 'performance-stats-modal';
    modal.onclick = (e) => {
        if (e.target.id === 'performance-stats-modal') {
            modal.remove();
        }
    };
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        z-index: 10000;
        display: flex;
        align-items: center;
        justify-content: center;
    `;

    modal.innerHTML = `
        <div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:12px; padding:20px; max-width:600px; width:90%; max-height:80vh; overflow-y:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                <h2 style="margin:0; color:var(--text-primary);">⚡ Performance Stats</h2>
                <button onclick="document.getElementById('performance-stats-modal').remove()" style="background:transparent; border:none; font-size:1.5em; cursor:pointer;">✕</button>
            </div>
            
            <div id="perf-cache-stats" style="background:rgba(102,126,234,0.1); padding:15px; border-radius:8px; margin-bottom:20px;">
                <h3 style="color:#667eea; margin-top:0;">Cache Statistics</h3>
                <p id="perf-cache-info" style="margin:0; color:var(--text-secondary);">Loading...</p>
            </div>
            
            <div id="perf-timing-stats" style="background:rgba(102,126,234,0.1); padding:15px; border-radius:8px;">
                <h3 style="color:#667eea; margin-top:0;">Operation Timings</h3>
                <div id="perf-timing-table"></div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Fetch server stats if available
    fetch('/api/system/cache/stats')
        .then(r => r.json())
        .then(data => {
            document.getElementById('perf-cache-info').innerHTML = `
                <strong>Server Cache:</strong><br>
                Size: ${data.cache.size}/${data.cache.max_size}<br>
                Hit Rate: ${data.cache.hit_rate}%<br>
                <strong>Client Cache:</strong><br>
                Size: ${frontendCache.stats().size}/${frontendCache.stats().maxSize}
            `;
        })
        .catch(() => {
            document.getElementById('perf-cache-info').innerHTML = '<strong>Client Cache:</strong><br>Size: ' + frontendCache.stats().size + '/' + frontendCache.stats().maxSize;
        });

    // Display frontend timing stats
    frontendMonitor.displayStats('perf-timing-table');
}

// Add performance button to UI if available
function addPerformancePanel() {
    const perfButton = document.createElement('button');
    perfButton.onclick = showPerformanceStats;
    perfButton.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 10px 15px;
        background: #667eea;
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.9em;
        z-index: 9999;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;
    perfButton.textContent = '⚡ Perf';
    perfButton.title = 'Click to view performance metrics';
    
    document.body.appendChild(perfButton);
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    addPerformancePanel();
});
