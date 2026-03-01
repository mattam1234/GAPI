/**
 * INTERACTIVE FEATURES - Advanced UI Components
 * - Enhanced Charts & Data Visualization
 * - Live Search & Autocomplete
 * - Drag & Drop
 * - Auto-save
 * - Export Utilities
 * - Infinite Scroll
 */

// ═══════════════════════════════════════════════════════════════════════════
// ENHANCED CHART UTILITIES (Chart.js wrapper)
// ═══════════════════════════════════════════════════════════════════════════

const ChartManager = {
    charts: {},
    
    /**
     * Create or update a line chart
     */
    createLineChart(canvasId, data, options = {}) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        
        // Destroy existing chart
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        
        const defaultOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            ...options
        };
        
        this.charts[canvasId] = new Chart(ctx, {
            type: 'line',
            data: data,
            options: defaultOptions
        });
        
        return this.charts[canvasId];
    },
    
    /**
     * Create or update a bar chart
     */
    createBarChart(canvasId, data, options = {}) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        
        const defaultOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            ...options
        };
        
        this.charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: data,
            options: defaultOptions
        });
        
        return this.charts[canvasId];
    },
    
    /**
     * Create or update a doughnut chart
     */
    createDoughnutChart(canvasId, data, options = {}) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        
        const defaultOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'right'
                }
            },
            ...options
        };
        
        this.charts[canvasId] = new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: defaultOptions
        });
        
        return this.charts[canvasId];
    },
    
    /**
     * Update existing chart data
     */
    updateChart(canvasId, newData) {
        if (!this.charts[canvasId]) return;
        
        this.charts[canvasId].data = newData;
        this.charts[canvasId].update();
    },
    
    /**
     * Destroy a chart
     */
    destroyChart(canvasId) {
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
            delete this.charts[canvasId];
        }
    }
};

// ═══════════════════════════════════════════════════════════════════════════
// LIVE SEARCH WITH DEBOUNCE
// ═══════════════════════════════════════════════════════════════════════════

class LiveSearch {
    constructor(inputId, resultsId, searchFunction, debounceMs = 300) {
        this.input = document.getElementById(inputId);
        this.results = document.getElementById(resultsId);
        this.searchFunction = searchFunction;
        this.debounceMs = debounceMs;
        this.debounceTimer = null;
        
        if (this.input) {
            this.init();
        }
    }
    
    init() {
        this.input.addEventListener('input', (e) => {
            clearTimeout(this.debounceTimer);
            
            const query = e.target.value.trim();
            
            if (query.length === 0) {
                this.hideResults();
                return;
            }
            
            this.showLoading();
            
            this.debounceTimer = setTimeout(() => {
                this.performSearch(query);
            }, this.debounceMs);
        });
        
        // Hide results when clicking outside
        document.addEventListener('click', (e) => {
            if (!this.input.contains(e.target) && !this.results.contains(e.target)) {
                this.hideResults();
            }
        });
    }
    
    async performSearch(query) {
        try {
            const results = await this.searchFunction(query);
            this.displayResults(results);
        } catch (error) {
            this.displayError(error.message);
        }
    }
    
    showLoading() {
        if (!this.results) return;
        this.results.innerHTML = '<div class="suggestion-item">Searching...</div>';
        this.results.style.display = 'block';
    }
    
    displayResults(results) {
        if (!this.results) return;
        
        if (results.length === 0) {
            this.results.innerHTML = '<div class="suggestion-item">No results found</div>';
            return;
        }
        
        this.results.innerHTML = results.map(result => 
            `<div class="suggestion-item" onclick="selectSearchResult(${JSON.stringify(result).replace(/"/g, '&quot;')})">
                ${this.formatResult(result)}
            </div>`
        ).join('');
        
        this.results.style.display = 'block';
    }
    
    formatResult(result) {
        // Override this method for custom formatting
        return result.name || result.title || result.label || String(result);
    }
    
    displayError(message) {
        if (!this.results) return;
        this.results.innerHTML = `<div class="suggestion-item" style="color:var(--text-secondary);">Error: ${message}</div>`;
    }
    
    hideResults() {
        if (this.results) {
            this.results.style.display = 'none';
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// AUTO-SAVE FUNCTIONALITY
// ═══════════════════════════════════════════════════════════════════════════

class AutoSave {
    constructor(formId, saveFunction, intervalMs = 30000) {
        this.form = document.getElementById(formId);
        this.saveFunction = saveFunction;
        this.intervalMs = intervalMs;
        this.saveTimer = null;
        this.lastSaved = null;
        this.isDirty = false;
        
        if (this.form) {
            this.init();
        }
    }
    
    init() {
        // Monitor form changes
        this.form.addEventListener('input', () => {
            this.isDirty = true;
            this.scheduleAutoSave();
        });
        
        // Save on page unload
        window.addEventListener('beforeunload', (e) => {
            if (this.isDirty) {
                e.preventDefault();
                e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
            }
        });
    }
    
    scheduleAutoSave() {
        clearTimeout(this.saveTimer);
        
        this.saveTimer = setTimeout(() => {
            this.save();
        }, this.intervalMs);
    }
    
    async save(showNotification = true) {
        if (!this.isDirty) return;
        
        try {
            const formData = new FormData(this.form);
            await this.saveFunction(formData);
            
            this.isDirty = false;
            this.lastSaved = new Date();
            
            if (showNotification) {
                showToast('✅ Saved', 'success', 2000);
            }
            
            this.updateSaveIndicator();
        } catch (error) {
            showToast('Failed to auto-save: ' + error.message, 'error');
        }
    }
    
    updateSaveIndicator() {
        const indicator = document.getElementById('save-indicator');
        if (!indicator) return;
        
        if (this.isDirty) {
            indicator.textContent = '● Unsaved changes';
            indicator.style.color = '#f39c12';
        } else if (this.lastSaved) {
            const timeAgo = this.getTimeAgo(this.lastSaved);
            indicator.textContent = `✓ Saved ${timeAgo}`;
            indicator.style.color = '#27ae60';
        }
    }
    
    getTimeAgo(date) {
        const seconds = Math.floor((new Date() - date) / 1000);
        
        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// DRAG & DROP REORDERING
// ═══════════════════════════════════════════════════════════════════════════

class DragDropList {
    constructor(containerId, onReorder) {
        this.container = document.getElementById(containerId);
        this.onReorder = onReorder;
        this.draggedElement = null;
        
        if (this.container) {
            this.init();
        }
    }
    
    init() {
        this.makeItemsDraggable();
        
        // Re-init when container content changes
        const observer = new MutationObserver(() => {
            this.makeItemsDraggable();
        });
        
        observer.observe(this.container, { childList: true });
    }
    
    makeItemsDraggable() {
        const items = this.container.querySelectorAll('.draggable-item');
        
        items.forEach(item => {
            item.draggable = true;
            item.style.cursor = 'move';
            
            item.addEventListener('dragstart', (e) => {
                this.draggedElement = item;
                item.style.opacity = '0.5';
                e.dataTransfer.effectAllowed = 'move';
            });
            
            item.addEventListener('dragend', (e) => {
                item.style.opacity = '1';
                this.draggedElement = null;
            });
            
            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                
                if (this.draggedElement === item) return;
                
                const bounding = item.getBoundingClientRect();
                const offset = bounding.y + (bounding.height / 2);
                
                if (e.clientY > offset) {
                    item.parentNode.insertBefore(this.draggedElement, item.nextSibling);
                } else {
                    item.parentNode.insertBefore(this.draggedElement, item);
                }
            });
            
            item.addEventListener('drop', (e) => {
                e.preventDefault();
                
                if (this.onReorder) {
                    const newOrder = Array.from(this.container.children).map((el, idx) => ({
                        element: el,
                        index: idx,
                        id: el.dataset.id || idx
                    }));
                    
                    this.onReorder(newOrder);
                }
            });
        });
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// INFINITE SCROLL
// ═══════════════════════════════════════════════════════════════════════════

class InfiniteScroll {
    constructor(containerId, loadMoreFunction, options = {}) {
        this.container = document.getElementById(containerId);
        this.loadMoreFunction = loadMoreFunction;
        this.options = {
            threshold: 200, // px from bottom
            loadingMessage: 'Loading more...',
            ...options
        };
        this.isLoading = false;
        this.hasMore = true;
        
        if (this.container) {
            this.init();
        }
    }
    
    init() {
        this.container.addEventListener('scroll', () => {
            if (this.shouldLoadMore()) {
                this.loadMore();
            }
        });
    }
    
    shouldLoadMore() {
        if (this.isLoading || !this.hasMore) return false;
        
        const scrollTop = this.container.scrollTop;
        const scrollHeight = this.container.scrollHeight;
        const clientHeight = this.container.clientHeight;
        
        return scrollHeight - scrollTop - clientHeight < this.options.threshold;
    }
    
    async loadMore() {
        this.isLoading = true;
        this.showLoading();
        
        try {
            const result = await this.loadMoreFunction();
            
            if (result && result.hasMore !== undefined) {
                this.hasMore = result.hasMore;
            }
            
            this.hideLoading();
        } catch (error) {
            showToast('Failed to load more: ' + error.message, 'error');
            this.hideLoading();
        }
        
        this.isLoading = false;
    }
    
    showLoading() {
        const existing = this.container.querySelector('.infinite-scroll-loader');
        if (existing) return;
        
        const loader = document.createElement('div');
        loader.className = 'infinite-scroll-loader';
        loader.style.cssText = 'padding:20px; text-align:center; color:var(--text-secondary);';
        loader.innerHTML = `
            <div class="spinner-small" style="margin:0 auto 10px;"></div>
            <div>${this.options.loadingMessage}</div>
        `;
        
        this.container.appendChild(loader);
    }
    
    hideLoading() {
        const loader = this.container.querySelector('.infinite-scroll-loader');
        if (loader) loader.remove();
    }
    
    reset() {
        this.hasMore = true;
        this.isLoading = false;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// DATA EXPORT UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

const DataExporter = {
    /**
     * Export data as CSV
     */
    exportAsCSV(data, filename = 'export.csv') {
        if (!Array.isArray(data) || data.length === 0) {
            showToast('No data to export', 'warning');
            return;
        }
        
        // Get headers from first object
        const headers = Object.keys(data[0]);
        
        // Build CSV content
        let csv = headers.join(',') + '\n';
        
        data.forEach(row => {
            const values = headers.map(header => {
                const value = row[header];
                // Escape commas and quotes
                if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
                    return `"${value.replace(/"/g, '""')}"`;
                }
                return value;
            });
            csv += values.join(',') + '\n';
        });
        
        this.downloadFile(csv, filename, 'text/csv');
        showToast(`Exported ${data.length} rows to ${filename}`, 'success');
    },
    
    /**
     * Export data as JSON
     */
    exportAsJSON(data, filename = 'export.json') {
        const json = JSON.stringify(data, null, 2);
        this.downloadFile(json, filename, 'application/json');
        showToast(`Exported data to ${filename}`, 'success');
    },
    
    /**
     * Export HTML table to CSV
     */
    exportTableToCSV(tableId, filename = 'table.csv') {
        const table = document.getElementById(tableId);
        if (!table) {
            showToast('Table not found', 'error');
            return;
        }
        
        let csv = '';
        
        // Get headers
        const headers = Array.from(table.querySelectorAll('thead th'))
            .map(th => th.textContent.trim());
        csv += headers.join(',') + '\n';
        
        // Get rows
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const cells = Array.from(row.querySelectorAll('td'))
                .map(td => {
                    const text = td.textContent.trim();
                    return text.includes(',') ? `"${text}"` : text;
                });
            csv += cells.join(',') + '\n';
        });
        
        this.downloadFile(csv, filename, 'text/csv');
        showToast(`Exported table to ${filename}`, 'success');
    },
    
    /**
     * Trigger file download
     */
    downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        URL.revokeObjectURL(url);
    }
};

// ═══════════════════════════════════════════════════════════════════════════
// CLIPBOARD UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

const ClipboardUtils = {
    /**
     * Copy text to clipboard
     */
    async copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast('Copied to clipboard!', 'success', 2000);
            return true;
        } catch (error) {
            // Fallback for older browsers
            return this.copyTextFallback(text);
        }
    },
    
    /**
     * Fallback copy method
     */
    copyTextFallback(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        
        try {
            document.execCommand('copy');
            showToast('Copied to clipboard!', 'success', 2000);
            return true;
        } catch (error) {
            showToast('Failed to copy', 'error');
            return false;
        } finally {
            document.body.removeChild(textarea);
        }
    },
    
    /**
     * Copy element content to clipboard
     */
    async copyElementContent(elementId) {
        const element = document.getElementById(elementId);
        if (!element) {
            showToast('Element not found', 'error');
            return false;
        }
        
        return this.copyText(element.textContent || element.innerText);
    }
};

// ═══════════════════════════════════════════════════════════════════════════
// FORM VALIDATION
// ═══════════════════════════════════════════════════════════════════════════

class FormValidator {
    constructor(formId) {
        this.form = document.getElementById(formId);
        this.errors = {};
        
        if (this.form) {
            this.init();
        }
    }
    
    init() {
        this.form.addEventListener('submit', (e) => {
            if (!this.validate()) {
                e.preventDefault();
                this.showErrors();
            }
        });
        
        // Real-time validation
        this.form.querySelectorAll('input, textarea, select').forEach(field => {
            field.addEventListener('blur', () => {
                this.validateField(field);
            });
        });
    }
    
    validate() {
        this.errors = {};
        
        this.form.querySelectorAll('input, textarea, select').forEach(field => {
            this.validateField(field);
        });
        
        return Object.keys(this.errors).length === 0;
    }
    
    validateField(field) {
        const name = field.name;
        if (!name) return;
        
        // Required validation
        if (field.hasAttribute('required') && !field.value.trim()) {
            this.errors[name] = 'This field is required';
            this.markFieldError(field, this.errors[name]);
            return;
        }
        
        // Email validation
        if (field.type === 'email' && field.value) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(field.value)) {
                this.errors[name] = 'Invalid email address';
                this.markFieldError(field, this.errors[name]);
                return;
            }
        }
        
        // Min length validation
        if (field.hasAttribute('minlength')) {
            const minLength = parseInt(field.getAttribute('minlength'));
            if (field.value.length < minLength) {
                this.errors[name] = `Minimum ${minLength} characters required`;
                this.markFieldError(field, this.errors[name]);
                return;
            }
        }
        
        // Clear error if validation passed
        this.clearFieldError(field);
    }
    
    markFieldError(field, message) {
        field.style.borderColor = '#e74c3c';
        
        // Remove existing error message
        const existingError = field.parentNode.querySelector('.field-error');
        if (existingError) existingError.remove();
        
        // Add error message
        const errorDiv = document.createElement('div');
        errorDiv.className = 'field-error';
        errorDiv.style.cssText = 'color:#e74c3c; font-size:0.85em; margin-top:4px;';
        errorDiv.textContent = message;
        field.parentNode.appendChild(errorDiv);
    }
    
    clearFieldError(field) {
        field.style.borderColor = '';
        
        const errorDiv = field.parentNode.querySelector('.field-error');
        if (errorDiv) errorDiv.remove();
    }
    
    showErrors() {
        const errorMessages = Object.values(this.errors).join('\n');
        if (errorMessages) {
            showToast('Please fix the following errors:\n' + errorMessages, 'error', 5000);
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════

console.log('✨ Interactive features loaded');

// Export to window for global access
window.ChartManager = ChartManager;
window.LiveSearch = LiveSearch;
window.AutoSave = AutoSave;
window.DragDropList = DragDropList;
window.InfiniteScroll = InfiniteScroll;
window.DataExporter = DataExporter;
window.ClipboardUtils = ClipboardUtils;
window.FormValidator = FormValidator;
