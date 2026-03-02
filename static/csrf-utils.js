/**
 * CSRF Protection Utilities
 * Handles CSRF token retrieval and inclusion in API requests
 */

// Get CSRF token from cookie
function getCsrfTokenFromCookie() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token') {
            return value;
        }
    }
    return null;
}

// Fetch a new CSRF token from the server
async function fetchCsrfToken() {
    try {
        const resp = await fetch('/api/csrf-token', {
            method: 'GET',
            credentials: 'same-origin'
        });
        if (resp.ok) {
            const data = await resp.json();
            return data.token;
        }
    } catch (err) {
        console.error('Failed to fetch CSRF token:', err);
    }
    return null;
}

// Get or fetch CSRF token (checks cookie first, then fetches if needed)
async function ensureCsrfToken() {
    let token = getCsrfTokenFromCookie();
    if (!token) {
        token = await fetchCsrfToken();
    }
    return token;
}

// Enhanced fetch with automatic CSRF token inclusion
async function safeFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    
    // Only include CSRF token for state-changing methods
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const token = await ensureCsrfToken();
        if (token) {
            options.headers = options.headers || {};
            options.headers['X-CSRF-Token'] = token;
        }
    }
    
    // Ensure credentials are included
    if (!options.credentials) {
        options.credentials = 'same-origin';
    }
    
    return fetch(url, options);
}

// Initialize CSRF token on page load
document.addEventListener('DOMContentLoaded', async () => {
    await ensureCsrfToken();
});
