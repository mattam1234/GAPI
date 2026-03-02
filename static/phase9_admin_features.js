/**
 * PHASE 9: ADMIN EXCELLENCE & USER EXPERIENCE UI
 * Modals, tabs, and functions for analytics, audit logs, search, and moderation
 */

// ═══════════════════════════════════════════════════════════════════════════
// ANALYTICS DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════

async function openAnalyticsDashboard() {
    const modal = document.getElementById('analytics-modal');
    if (!modal) return;

    modal.style.display = 'flex';

    try {
        const resp = await fetch('/api/analytics/dashboard');
        if (!resp.ok) {
            showMessage('Failed to load analytics', 'error');
            return;
        }

        const data = await resp.json();
        
        // Update summary cards
        document.getElementById('analytics-total-users').textContent = 
            data.summary.total_users || 0;
        document.getElementById('analytics-active-7d').textContent = 
            data.summary.active_users_7d || 0;
        document.getElementById('analytics-total-picks').textContent = 
            data.summary.total_picks || 0;
        document.getElementById('analytics-avg-picks').textContent = 
            (data.summary.avg_picks_per_user || 0).toFixed(2);

        // Render pick trends chart
        if (data.pick_trends_7d && data.pick_trends_7d.length > 0) {
            renderPickTrendsChart(data.pick_trends_7d);
        }

        // Render top games
        if (data.top_games && data.top_games.length > 0) {
            const gamesList = data.top_games.map(g => 
                `<div style="padding:8px; border-bottom:1px solid #ddd;">
                    <strong>Game #${g.game_id}</strong> - ${g.pick_count} picks
                </div>`
            ).join('');
            document.getElementById('analytics-top-games').innerHTML = gamesList;
        }

        // Platform stats
        if (data.platform_stats) {
            const platformsList = Object.entries(data.platform_stats).map(
                ([platform, count]) => 
                `<div style="padding:6px;">${platform.toUpperCase()}: ${count}</div>`
            ).join('');
            document.getElementById('analytics-platforms').innerHTML = platformsList;
        }

    } catch (err) {
        showMessage('Error loading analytics: ' + err.message, 'error');
    }
}

function closeAnalyticsDashboard() {
    const modal = document.getElementById('analytics-modal');
    if (modal) modal.style.display = 'none';
}

function renderPickTrendsChart(trendsData) {
    const container = document.getElementById('analytics-trends-chart');
    if (!container) return;

    const html = trendsData.map(t => 
        `<div style="display:flex; gap:8px; padding:4px; align-items:center;">
            <span style="width:80px;">${t.date}:</span>
            <div style="height:20px; width:${Math.max(t.picks * 2, 10)}px; 
                        background:#3498db; border-radius:3px;"></div>
            <span>${t.picks}</span>
        </div>`
    ).join('');

    container.innerHTML = html || '<p>No data available</p>';
}

async function exportAnalytics() {
    try {
        const resp = await fetch('/api/analytics/export');
        if (!resp.ok) throw new Error('Export failed');

        const data = await resp.json();
        const json = JSON.stringify(data, null, 2);
        
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `analytics_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        showMessage('Analytics exported', 'success');
    } catch (err) {
        showMessage('Export failed: ' + err.message, 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// AUDIT LOGGING
// ═══════════════════════════════════════════════════════════════════════════

async function openAuditLog() {
    const modal = document.getElementById('audit-log-modal');
    if (!modal) return;

    modal.style.display = 'flex';
    await loadAuditLogs(1);
}

function closeAuditLog() {
    const modal = document.getElementById('audit-log-modal');
    if (modal) modal.style.display = 'none';
}

async function loadAuditLogs(page = 1) {
    try {
        const username = document.getElementById('audit-filter-user')?.value || '';
        const action = document.getElementById('audit-filter-action')?.value || '';

        let url = `/api/admin/audit-logs?page=${page}&limit=25`;
        if (username) url += `&user=${username}`;
        if (action) url += `&action=${action}`;

        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Failed to load audit logs');

        const data = await resp.json();

        const logsHtml = (data.logs || []).map(log => `
            <tr style="border-bottom:1px solid #ddd;">
                <td style="padding:8px; font-size:0.85em;">${log.timestamp}</td>
                <td style="padding:8px;">${log.username}</td>
                <td style="padding:8px; background:#f5f5f5;">${log.action}</td>
                <td style="padding:8px;">${log.resource_type || '-'}</td>
                <td style="padding:8px; color:${log.status === 'success' ? '#27ae60' : '#e74c3c'};
                    font-weight:600;">${log.status}</td>
            </tr>
        `).join('');

        document.getElementById('audit-logs-table').innerHTML = logsHtml || 
            '<tr><td colspan="5" style="padding:20px; text-align:center;">No logs found</td></tr>';

        // Pagination
        const totalPages = Math.ceil((data.total || 0) / 25);
        const paginationHtml = Array.from({length: Math.min(5, totalPages)}, (_, i) => {
            const p = i + 1;
            const isActive = p === page;
            return `<button onclick="loadAuditLogs(${p})" style="padding:6px 10px; 
                ${isActive ? 'background:#3498db; color:white;' : 'background:#ecf0f1;'}
                border:none; border-radius:4px; cursor:pointer; margin:0 2px;">${p}</button>`;
        }).join('');

        document.getElementById('audit-pagination').innerHTML = paginationHtml;

    } catch (err) {
        showMessage('Error loading audit logs: ' + err.message, 'error');
    }
}

async function exportAuditLogs() {
    try {
        const resp = await fetch('/api/admin/audit-logs/export');
        if (!resp.ok) throw new Error('Export failed');

        const csv = await resp.text();
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `audit_logs_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        showMessage('Audit logs exported', 'success');
    } catch (err) {
        showMessage('Export failed: ' + err.message, 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// ADVANCED SEARCH
// ═══════════════════════════════════════════════════════════════════════════

async function openAdvancedSearch() {
    const modal = document.getElementById('advanced-search-modal');
    if (modal) modal.style.display = 'flex';

    await loadSavedSearches();
    await loadTrendingSearches();
}

function closeAdvancedSearch() {
    const modal = document.getElementById('advanced-search-modal');
    if (modal) modal.style.display = 'none';
}

async function performAdvancedSearch() {
    try {
        const query = document.getElementById('search-query')?.value || '';
        const filters = {
            genres: (document.getElementById('search-genres')?.value || '').split(',').filter(g => g),
            min_year: document.getElementById('search-min-year')?.value,
            max_year: document.getElementById('search-max-year')?.value,
            platforms: (document.getElementById('search-platforms')?.value || '').split(',').filter(p => p),
        };

        const resp = await safeFetch('/api/search/advanced', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, filters }),
        });

        if (!resp.ok) throw new Error('Search failed');

        const data = await resp.json();
        const resultsHtml = (data.results || []).map(game => `
            <div style="padding:12px; border:1px solid #ddd; border-radius:6px; margin-bottom:8px;
                        cursor:pointer;" onclick="selectSearchResult(${game.app_id})">
                <strong>${game.name}</strong>
                <div style="color:#666; font-size:0.9em; margin-top:4px;">
                    ${game.genres || ''} • ${game.release_date || 'N/A'}
                </div>
            </div>
        `).join('');

        document.getElementById('search-results').innerHTML = resultsHtml || 
            '<p style="color:#999;">No games found</p>';

    } catch (err) {
        showMessage('Search error: ' + err.message, 'error');
    }
}

async function saveCurrentSearch() {
    try {
        const name = prompt('Save search as:');
        if (!name) return;

        const query = document.getElementById('search-query')?.value || '';
        const filters = {
            genres: (document.getElementById('search-genres')?.value || '').split(',').filter(g => g),
            min_year: document.getElementById('search-min-year')?.value,
            max_year: document.getElementById('search-max-year')?.value,
        };

        const resp = await safeFetch('/api/search/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, query, filters }),
        });

        if (!resp.ok) throw new Error('Save failed');
        showMessage('Search saved!', 'success');
        await loadSavedSearches();
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function loadSavedSearches() {
    try {
        const resp = await fetch('/api/search/saved');
        if (!resp.ok) return;

        const data = await resp.json();
        const html = (data.searches || []).map(s => `
            <div style="padding:8px; background:#f5f5f5; border-radius:4px; margin-bottom:6px;
                        display:flex; justify-content:space-between; align-items:center;">
                <div style="cursor:pointer; flex:1;" onclick="applySavedSearch('${s.query}')">
                    <strong>${s.name}</strong>
                    <div style="color:#666; font-size:0.85em;">${s.query}</div>
                </div>
                <button onclick="deleteSavedSearch(${s.id})" style="padding:4px 8px; 
                    background:#e74c3c; color:white; border:none; border-radius:4px; cursor:pointer;">
                    Delete
                </button>
            </div>
        `).join('');

        document.getElementById('saved-searches-list').innerHTML = html || 
            '<p style="color:#999;">No saved searches</p>';
    } catch (err) {
        // Silently fail
    }
}

async function loadTrendingSearches() {
    try {
        const resp = await fetch('/api/search/trending?days=7&limit=5');
        if (!resp.ok) return;

        const data = await resp.json();
        const html = (data.trending || []).map(t => `
            <div style="padding:8px; cursor:pointer;" onclick="applySavedSearch('${t.query}')">
                🔥 ${t.query} <span style="color:#999;">(${t.count})</span>
            </div>
        `).join('');

        document.getElementById('trending-searches').innerHTML = html || '';
    } catch (err) {
        // Silently fail
    }
}

async function deleteSavedSearch(searchId) {
    try {
        const resp = await safeFetch(`/api/search/saved/${searchId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Delete failed');
        await loadSavedSearches();
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

function applySavedSearch(query) {
    document.getElementById('search-query').value = query;
    performAdvancedSearch();
}

function selectSearchResult(appId) {
    showMessage(`Selected game #${appId}`, 'success');
    // Could add to favorites, playlist, etc.
}


// ═══════════════════════════════════════════════════════════════════════════
// MODERATION
// ═══════════════════════════════════════════════════════════════════════════

async function openModerationPanel() {
    const modal = document.getElementById('moderation-modal');
    if (modal) modal.style.display = 'flex';
    await loadPendingReports();
}

function closeModerationPanel() {
    const modal = document.getElementById('moderation-modal');
    if (modal) modal.style.display = 'none';
}

async function loadPendingReports(page = 1) {
    try {
        const resp = await fetch(`/api/admin/moderation/reports?page=${page}&limit=20`);
        if (!resp.ok) throw new Error('Load failed');

        const data = await resp.json();
        const reportsHtml = (data.reports || []).map(report => `
            <div style="padding:12px; border:2px solid ${
                report.priority === 2 ? '#e74c3c' : '#f39c12'
            }; border-radius:6px; margin-bottom:8px; background:#f9f9f9;">
                <div style="display:flex; justify-content:space-between;">
                    <div>
                        <strong style="color: ${
                            report.priority === 2 ? '#e74c3c' : '#f39c12'
                        };">High Priority</strong> Report #${report.id}
                    </div>
                    <span style="background:#ecf0f1; padding:4px 8px; border-radius:4px; 
                        font-size:0.85em;">${report.status}</span>
                </div>
                <div style="margin-top:8px; font-size:0.9em;">
                    <p><strong>Reporter:</strong> ${report.reporter}</p>
                    <p><strong>Reason:</strong> ${report.reason}</p>
                    ${report.reported_user ? `<p><strong>Reported User:</strong> ${report.reported_user}</p>` : ''}
                    ${report.description ? `<p><strong>Description:</strong> ${report.description}</p>` : ''}
                </div>
                <div style="display:flex; gap:8px; margin-top:10px;">
                    <button onclick="moderateReport(${report.id}, 'warn')" 
                        style="padding:6px 12px; background:#f39c12; color:white; border:none; 
                        border-radius:4px; cursor:pointer;">⚠️ Warn</button>
                    <button onclick="moderateReport(${report.id}, 'mute')" 
                        style="padding:6px 12px; background:#e74c3c; color:white; border:none; 
                        border-radius:4px; cursor:pointer;">🔇 Mute</button>
                    <button onclick="moderateReport(${report.id}, 'dismiss')" 
                        style="padding:6px 12px; background:#95a5a6; color:white; border:none; 
                        border-radius:4px; cursor:pointer;">✓ Dismiss</button>
                </div>
            </div>
        `).join('');

        document.getElementById('reports-list').innerHTML = reportsHtml || 
            '<p style="color:#999; padding:20px; text-align:center;">No pending reports</p>';

    } catch (err) {
        showMessage('Error loading reports: ' + err.message, 'error');
    }
}

async function moderateReport(reportId, action) {
    try {
        const notes = prompt('Moderation notes (optional):');
        const resp = await safeFetch('/api/admin/moderation/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                report_id: reportId,
                action: action,
                notes: notes,
                duration: action === 'mute' ? 60 : null,
            }),
        });

        if (!resp.ok) throw new Error('Action failed');
        showMessage(`Applied ${action} action`, 'success');
        await loadPendingReports();
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function reportContent(type, reason) {
    try {
        const description = prompt('Tell us more (optional):');
        const resp = await safeFetch('/api/moderation/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: type,
                reason: reason,
                description: description,
            }),
        });

        if (!resp.ok) throw new Error('Report failed');
        showMessage('Thank you for reporting. Our team will review it.', 'success');
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// BATCH OPERATIONS
// ═══════════════════════════════════════════════════════════════════════════

function openBatchOperations() {
    const modal = document.getElementById('batch-operations-modal');
    if (modal) modal.style.display = 'flex';
}

function closeBatchOperations() {
    const modal = document.getElementById('batch-operations-modal');
    if (modal) modal.style.display = 'none';
}

async function batchTagGames() {
    try {
        const ids = (document.getElementById('batch-game-ids')?.value || '')
            .split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id));
        const tags = (document.getElementById('batch-tags')?.value || '')
            .split(',').map(tag => tag.trim()).filter(t => t);

        if (!ids.length || !tags.length) {
            showMessage('Enter game IDs and tags', 'error');
            return;
        }

        const resp = await safeFetch('/api/batch/tag-games', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_ids: ids, tags: tags }),
        });

        if (!resp.ok) throw new Error('Batch operation failed');
        const data = await resp.json();
        showMessage(`Tagged ${data.tagged} games`, 'success');
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function batchChangeStatus() {
    try {
        const ids = (document.getElementById('batch-game-ids')?.value || '')
            .split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id));
        const status = document.getElementById('batch-status')?.value || '';

        if (!ids.length || !status) {
            showMessage('Enter game IDs and status', 'error');
            return;
        }

        const resp = await safeFetch('/api/batch/change-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_ids: ids, status: status }),
        });

        if (!resp.ok) throw new Error('Batch operation failed');
        const data = await resp.json();
        showMessage(`Updated ${data.updated} games`, 'success');
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}

async function batchExportGames() {
    try {
        const ids = (document.getElementById('batch-game-ids')?.value || '')
            .split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id));

        if (!ids.length) {
            showMessage('Enter game IDs', 'error');
            return;
        }

        const resp = await safeFetch('/api/batch/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_ids: ids, format: 'csv' }),
        });

        if (!resp.ok) throw new Error('Export failed');

        const csv = await resp.text();
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `games_export_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        showMessage('Games exported', 'success');
    } catch (err) {
        showMessage('Error: ' + err.message, 'error');
    }
}
