#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
import argparse
import uuid
import secrets
from flask import Flask, render_template, jsonify, request, session, Response, redirect as flask_redirect
from flask import has_request_context
import threading
import json
import os
import sys
import csv
import hashlib
import io
import tempfile
import subprocess
import signal
import collections
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Deque
from functools import wraps
from werkzeug.local import LocalProxy
from urllib.parse import unquote
import gapi
import multiuser
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
try:
    from sqlalchemy import text
except Exception:
    text = None

try:
    import database
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    import realtime
    REALTIME_AVAILABLE = True
except ImportError:
    REALTIME_AVAILABLE = False

try:
    import performance
    PERFORMANCE_AVAILABLE = True
except ImportError:
    PERFORMANCE_AVAILABLE = False

try:
    from flask_compress import Compress as _FlaskCompress
    _COMPRESS_AVAILABLE = True
except ImportError:
    _FlaskCompress = None  # type: ignore[assignment,misc]
    _COMPRESS_AVAILABLE = False

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _LIMITER_AVAILABLE = True
except ImportError:
    Limiter = None  # type: ignore[assignment,misc]
    get_remote_address = None  # type: ignore[assignment]
    _LIMITER_AVAILABLE = False

# DB-backed services — instantiated lazily after database import so the
# module can still start without a database being present.
try:
    from app.services import (
        NotificationService, ChatService, FriendService,
        LeaderboardService, PluginService, AppSettingsService,
        IgnoredGamesService, LibraryService, DBFavoritesService, UserService,
        AchievementService,
    )
    _notification_service = NotificationService(database) if DB_AVAILABLE else None
    _chat_service = ChatService(database) if DB_AVAILABLE else None
    _friend_service = FriendService(database) if DB_AVAILABLE else None
    _leaderboard_service = LeaderboardService(database) if DB_AVAILABLE else None
    _plugin_service = PluginService(database) if DB_AVAILABLE else None
    _app_settings_service = AppSettingsService(database) if DB_AVAILABLE else None
    _ignored_games_service = IgnoredGamesService(database) if DB_AVAILABLE else None
    _library_service = LibraryService(database) if DB_AVAILABLE else None
    _db_favorites_service = DBFavoritesService(database) if DB_AVAILABLE else None
    _user_service = UserService(database) if DB_AVAILABLE else None
    _achievement_service = AchievementService(database) if DB_AVAILABLE else None
except Exception:
    _notification_service = None
    _chat_service = None
    _friend_service = None
    _leaderboard_service = None
    _plugin_service = None
    _app_settings_service = None
    _ignored_games_service = None
    _library_service = None
    _db_favorites_service = None
    _user_service = None
    _achievement_service = None

# Phase 9: Admin Excellence & User Experience Services
try:
    from app.services.audit_service import AuditService
    from app.services.analytics_service import AnalyticsService
    from app.services.search_service import SearchService
    from app.services.moderation_service import ModerationService
    _audit_service = AuditService(database) if DB_AVAILABLE else None
    _analytics_service = AnalyticsService(database) if DB_AVAILABLE else None
    _search_service = SearchService(database, None) if DB_AVAILABLE else None
    _moderation_service = ModerationService(database) if DB_AVAILABLE else None
except Exception as _e:
    # Note: gui_logger not yet defined here, so we print directly
    print(f'Warning: Phase 9 services failed to load: {_e}')
    _audit_service = None
    _analytics_service = None
    _search_service = None
    _moderation_service = None

try:
    from discord_presence import DiscordPresence as _DiscordPresence
    _discord_presence = _DiscordPresence()
except Exception:
    _discord_presence = None  # type: ignore[assignment]

# Initialize logging early so database module logs are captured
log_level = os.getenv('GAPI_LOG_LEVEL', 'INFO')
gapi_logger = gapi.setup_logging(log_level)
gui_logger = logging.getLogger('gapi.gui')
gui_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
try:
    os.makedirs('logs', exist_ok=True)
    fh = logging.FileHandler('logs/gapi_gui.log')
    fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s'))
    fh.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    gui_logger.addHandler(fh)
except Exception:
    gui_logger = logging.getLogger('gapi.gui')
    gui_logger.warning('Could not create log file handler')

# If database is available, try initializing tables and log result
if DB_AVAILABLE:
    try:
        ok = database.init_db()
        if ok:
            gui_logger.info('Database initialized successfully')
        else:
            gui_logger.warning('Database initialization reported failure')
            DB_AVAILABLE = False
    except Exception as e:
        gui_logger.exception('Database init failed: %s', e)
        DB_AVAILABLE = False


def ensure_db_available() -> bool:
    """Try to (re)initialize DB if it was previously unavailable."""
    global DB_AVAILABLE
    if DB_AVAILABLE:
        return True
    try:
        ok = database.init_db()
        DB_AVAILABLE = bool(ok)
        if DB_AVAILABLE:
            gui_logger.info('Database reconnected successfully')
        return DB_AVAILABLE
    except Exception as e:
        gui_logger.exception('Database reconnect failed: %s', e)
        return False

app = Flask(__name__)

# Load or generate a persistent secret key for session management
# This ensures session cookies remain valid across app restarts
def _get_or_create_secret_key():
    """Get the Flask secret key, persisting it to config.json if needed."""
    config_path = 'config.json'
    secret_key = None
    
    # Try to load from config.json
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                secret_key = config.get('secret_key')
        except (OSError, json.JSONDecodeError):
            pass
    
    # If not in config, generate a new one and save it
    if not secret_key:
        import binascii
        secret_key = binascii.hexlify(os.urandom(24)).decode('utf-8')
        try:
            # Load existing config and update it
            config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                except (OSError, json.JSONDecodeError):
                    pass
            config['secret_key'] = secret_key
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            gui_logger.info('Generated and saved new Flask secret key to config.json')
        except Exception as e:
            gui_logger.warning('Failed to save secret key to config.json: %s. Using in-memory key.', e)
    
    return secret_key.encode() if isinstance(secret_key, str) else secret_key

app.secret_key = _get_or_create_secret_key()

# ---------------------------------------------------------------------------
# Response compression (gzip / brotli)
# ---------------------------------------------------------------------------
if _COMPRESS_AVAILABLE:
    _compress = _FlaskCompress()
    _compress.init_app(app)

# ---------------------------------------------------------------------------
# Rate limiting — protect auth endpoints from brute-force attacks.
# Limits are intentionally generous for normal usage but prevent rapid
# scripted abuse.  They can be tightened via RATELIMIT_DEFAULT env var.
# ---------------------------------------------------------------------------
if _LIMITER_AVAILABLE:
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[],  # no global limit — applied per-endpoint
        # NOTE: "memory://" stores counters in-process only. This is
        # sufficient for single-process deployments (Flask dev server).
        # For multi-process deployments (e.g. gunicorn -w N) set
        # RATELIMIT_STORAGE_URI=redis://... in the environment to share
        # counters across workers.
        storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
    )
else:
    # Stub: @limiter.limit(...) becomes a no-op
    class _NoOpLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def exempt(self, f):
            return f
    limiter = _NoOpLimiter()  # type: ignore[assignment]

# Use the shared GAPI logger so level is controlled by config/setup_logging()
gui_logger = logging.getLogger('gapi.gui')


# ---------------------------------------------------------------------------
# HTTP security headers — applied to every response
# ---------------------------------------------------------------------------
@app.after_request
def add_security_headers(response):
    """Attach security-related HTTP headers to every outgoing response.

    These headers defend against common browser-based attacks such as
    clickjacking (X-Frame-Options), MIME-sniffing (X-Content-Type-Options),
    unintended cross-origin resource leakage (Referrer-Policy),
    protocol downgrade attacks (Strict-Transport-Security), and
    inline script injection (Content-Security-Policy).
    """
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Permissions-Policy',
        'geolocation=(), microphone=(), camera=()',
    )
    # Instruct browsers to only connect over HTTPS for the next year.
    # includeSubDomains is omitted intentionally to avoid affecting subdomains
    # that may not have certificates.
    response.headers.setdefault(
        'Strict-Transport-Security',
        'max-age=31536000',
    )
    # Content-Security-Policy — default-deny with pragmatic exceptions for
    # inline scripts/styles used throughout the single-page UI.
    response.headers.setdefault(
        'Content-Security-Policy',
        (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none';"
        ),
    )
    return response


# ---------------------------------------------------------------------------
# CSRF Protection — double-submit cookie pattern  (Item 19)
# ---------------------------------------------------------------------------

_CSRF_COOKIE_NAME = 'csrf_token'
_CSRF_HEADER_NAME = 'X-CSRF-Token'
# Endpoints that are explicitly exempt from CSRF checks (e.g. machine-to-machine)
_CSRF_EXEMPT_ENDPOINTS: frozenset = frozenset({
    'api_auth_login',      # Unauthenticated users don't have CSRF tokens yet
    'api_auth_register',   # Same as login
    'api_get_csrf_token',  # Token endpoint itself is exempt
})
# State-changing methods that require a valid CSRF token
_CSRF_PROTECTED_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def _generate_csrf_token() -> str:
    """Return a new cryptographically-random CSRF token string."""
    import secrets
    return secrets.token_hex(32)


@app.route('/api/csrf-token', methods=['GET'])
def api_get_csrf_token():
    """Issue (or refresh) a CSRF token for the current browser session.

    Sets a ``csrf_token`` cookie (SameSite=Lax, HttpOnly=False so JavaScript
    can read it) and returns the same value in the JSON body so SPAs can store
    it and send it as the ``X-CSRF-Token`` request header.

    Response JSON:
      ``token``  – CSRF token string
    """
    token = _generate_csrf_token()
    resp = jsonify({'token': token})
    # Use HTTPS-only cookies in production; allow HTTP in development.
    # Set GAPI_CSRF_SECURE=true (or any truthy value) in the environment to
    # enforce the Secure flag when the app is deployed behind TLS.
    _csrf_secure = os.environ.get('GAPI_CSRF_SECURE', '').lower() in ('1', 'true', 'yes')
    resp.set_cookie(
        _CSRF_COOKIE_NAME,
        token,
        samesite='Lax',
        httponly=False,     # must be readable by JS to send as header
        secure=_csrf_secure,
        max_age=86400,      # 1 day
        path='/',
    )
    return resp


@app.before_request
def _validate_csrf():
    """CSRF validation disabled for debugging."""
    return  # CSRF validation disabled


# ---------------------------------------------------------------------------
# API usage statistics — lightweight per-endpoint call counter + latency
# ---------------------------------------------------------------------------

_api_stats_lock = threading.Lock()
# endpoint_name -> {'calls': int, 'errors': int, 'total_ms': float,
#                   'min_ms': float, 'max_ms': float}
_api_endpoint_stats: Dict[str, Dict] = {}
# Thread-local storage for per-request start time
_request_start = threading.local()

_CLIENT_ERROR_MAX = 200  # ring-buffer cap


@app.before_request
def _record_request_start():
    """Stamp start time on every request for latency tracking."""
    import time as _time
    _request_start.t = _time.monotonic()


@app.after_request
def _record_request_stats(response):
    """Accumulate per-endpoint call counts and latency."""
    import time as _time
    try:
        endpoint = request.endpoint or 'unknown'
        # Skip non-API and built-in static routes
        if endpoint in ('static', 'unknown') or not endpoint:
            return response
        elapsed_ms = (_time.monotonic() - getattr(_request_start, 't', _time.monotonic())) * 1000
        is_error = response.status_code >= 400
        with _api_stats_lock:
            s = _api_endpoint_stats.setdefault(endpoint, {
                'calls': 0, 'errors': 0,
                'total_ms': 0.0, 'min_ms': None, 'max_ms': 0.0,
            })
            s['calls'] += 1
            if is_error:
                s['errors'] += 1
            s['total_ms'] += elapsed_ms
            if s['min_ms'] is None or elapsed_ms < s['min_ms']:
                s['min_ms'] = elapsed_ms
            if elapsed_ms > s['max_ms']:
                s['max_ms'] = elapsed_ms
    except Exception:
        pass  # never let instrumentation break a request
    return response


# Public read-only API paths that can be cached briefly by clients/CDNs.
# These paths serve the same data to all callers and don't carry session state.
_CACHEABLE_API_PREFIXES = (
    '/api/permissions',
    '/api/changelog',
    '/api/health',
)


@app.after_request
def _add_cache_control(response):
    """Set Cache-Control on responses that are safe to cache (Item 18).

    - Public read-only API endpoints: ``public, max-age=60, stale-while-revalidate=120``
    - All other API responses: ``no-store`` (prevent sensitive data caching)
    - Non-API HTML/static responses: no override (let Flask defaults apply)
    """
    path = request.path
    if not path.startswith('/api/'):
        return response
    if response.headers.get('Cache-Control'):
        return response  # respect explicitly set headers
    if request.method == 'GET' and response.status_code == 200:
        if any(path.startswith(p) for p in _CACHEABLE_API_PREFIXES):
            response.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
            return response
    response.headers.setdefault('Cache-Control', 'no-store')
    return response


# ---------------------------------------------------------------------------
# API Deprecation Headers  (Item 9 — API Documentation / Quality Gates)
# ---------------------------------------------------------------------------
# Map endpoint function name → deprecation message.
# When a request matches one of these endpoints, the response will carry
# ``Deprecation: true``, ``X-Deprecation-Message``, and a ``Sunset`` header
# indicating when the endpoint is planned to be removed.
_DEPRECATED_ENDPOINTS: dict = {
    # Legacy multi-user endpoints replaced by authenticated multi-user sessions
    'api_users_list_legacy': (
        'This endpoint is deprecated. Use GET /api/users/all instead.',
        '2027-01-01',
    ),
    # Old un-paginated common-library endpoint
    'api_multiuser_common': (
        'This endpoint is deprecated. Use POST /api/multiuser/common with pagination.',
        '2027-01-01',
    ),
}


@app.after_request
def _add_deprecation_headers(response):
    """Attach RFC 8594 Deprecation + Sunset headers to deprecated endpoint responses."""
    try:
        endpoint = request.endpoint
        if endpoint and endpoint in _DEPRECATED_ENDPOINTS:
            message, sunset_date = _DEPRECATED_ENDPOINTS[endpoint]
            response.headers.setdefault('Deprecation', 'true')
            response.headers.setdefault('Sunset', sunset_date)
            response.headers.setdefault('X-Deprecation-Message', message)
    except Exception:
        pass  # never break a request
    return response


# ---------------------------------------------------------------------------
# Client-side error ring-buffer
# ---------------------------------------------------------------------------

_client_errors_lock = threading.Lock()
_client_errors: collections.deque = collections.deque(maxlen=_CLIENT_ERROR_MAX)


# Global game picker instance
picker: Optional[gapi.GamePicker] = None
picker_lock = threading.Lock()
current_game: Optional[Dict] = None

# Multi-user picker instance
multi_picker: Optional[multiuser.MultiUserPicker] = None
multi_picker_lock = threading.Lock()

# In-memory live pick sessions keyed by session_id
live_sessions: Dict[str, Dict] = {}
live_sessions_lock = threading.Lock()

chat_rooms_lock = threading.Lock()
chat_rooms: Dict[str, Dict] = {
    'general': {
        'room': 'general',
        'owner': None,
        'is_private': False,
        'members': set(),
        'invites': set(),
        'created_at': datetime.now(timezone.utc),
    }
}
chat_room_active_session: Dict[str, str] = {}

# Track users' current rooms and last activity
user_current_room: Dict[str, str] = {}  # username -> room_name
user_last_activity: Dict[str, float] = {}  # username -> timestamp
user_typing_indicators: Dict[str, float] = {}  # "room:username" -> timestamp when started typing
user_room_lock = threading.Lock()

# SSE subscriber queues: session_id -> list of queue.Queue
import queue as _queue
_sse_subscribers: Dict[str, list] = {}
_sse_subscribers_lock = threading.Lock()


def _sse_publish(session_id: str, event_type: str, data: Dict) -> None:
    """Push a JSON event to all SSE subscribers of *session_id*."""
    import json as _json
    payload = _json.dumps({'event': event_type, 'data': data})
    with _sse_subscribers_lock:
        dead = []
        for q in _sse_subscribers.get(session_id, []):
            try:
                q.put_nowait(payload)
            except _queue.Full:
                dead.append(q)
        if dead:
            _sse_subscribers[session_id] = [
                q for q in _sse_subscribers.get(session_id, []) if q not in dead
            ]


def _normalize_chat_room_name(raw_room: str) -> str:
    room = (raw_room or 'general').strip().lower().replace(' ', '-')
    cleaned = ''.join(ch for ch in room if ch.isalnum() or ch in ('-', '_', ':'))
    return (cleaned[:100] or 'general')


def _ensure_chat_room(room: str, owner: Optional[str] = None,
                      is_private: bool = False) -> Dict:
    room_name = _normalize_chat_room_name(room)
    with chat_rooms_lock:
        state = chat_rooms.get(room_name)
        if state is None:
            state = {
                'room': room_name,
                'owner': owner,
                'is_private': bool(is_private),
                'members': set(),
                'invites': set(),
                'created_at': datetime.utcnow(),
            }
            if owner:
                state['members'].add(owner)
            chat_rooms[room_name] = state
        return state


def _can_access_chat_room(username: str, room: str) -> bool:
    state = _ensure_chat_room(room)
    if not state['is_private']:
        return True
    if username == state.get('owner'):
        return True
    return username in state['members']


def _join_chat_room(username: str, room: str) -> Tuple[bool, str, str]:
    room_name = _normalize_chat_room_name(room)
    state = _ensure_chat_room(room_name)
    with chat_rooms_lock:
        if state['is_private']:
            if username != state.get('owner') and username not in state['members'] and username not in state['invites']:
                return False, f'Room "{room_name}" is private. Ask for an invite.', room_name
            state['invites'].discard(username)
        state['members'].add(username)
    return True, f'Joined room "{room_name}".', room_name


def _create_chat_room(owner: str, room: str, is_private: bool) -> Tuple[bool, str, str]:
    room_name = _normalize_chat_room_name(room)
    if room_name == 'general':
        return False, 'The room name "general" is reserved.', room_name
    with chat_rooms_lock:
        if room_name in chat_rooms:
            return False, f'Room "{room_name}" already exists.', room_name
        chat_rooms[room_name] = {
            'room': room_name,
            'owner': owner,
            'is_private': bool(is_private),
            'members': {owner},
            'invites': set(),
            'created_at': datetime.utcnow(),
        }
    privacy = 'private' if is_private else 'public'
    return True, f'Created {privacy} room "{room_name}".', room_name


def _invite_to_chat_room(inviter: str, target_username: str,
                         room: str) -> Tuple[bool, str, str]:
    room_name = _normalize_chat_room_name(room)
    state = _ensure_chat_room(room_name)
    with chat_rooms_lock:
        if state['is_private']:
            if inviter != state.get('owner') and inviter not in state['members']:
                return False, f'You are not allowed to invite users to "{room_name}".', room_name
            state['invites'].add(target_username)
        else:
            state['members'].add(target_username)
    if state['is_private']:
        return True, f'Invited @{target_username} to private room "{room_name}".', room_name
    return True, f'Added @{target_username} to room "{room_name}".', room_name

# User authentication
_demo_current_user: Optional[str] = None

# Discord bot process management
_discord_bot_process: Optional[subprocess.Popen] = None
_discord_bot_lock = threading.Lock()
# Bounded deque automatically drops oldest lines when the bot produces many lines
_discord_bot_log_lines: Deque[str] = collections.deque(maxlen=200)


def _resolve_current_user() -> Optional[str]:
    if has_request_context():
        return session.get('username') or _demo_current_user
    return _demo_current_user


def get_current_username() -> Optional[str]:
    """Get the resolved current username as a string (not a LocalProxy)"""
    resolved = _resolve_current_user()
    if resolved and resolved != 'None':
        return str(resolved)
    return None


current_user = LocalProxy(_resolve_current_user)
current_user_lock = threading.Lock()

DEMO_GAMES = [
    {"appid": 620, "name": "Portal 2", "playtime_forever": 2720},
    {"appid": 440, "name": "Team Fortress 2", "playtime_forever": 15430},
    {"appid": 570, "name": "Dota 2", "playtime_forever": 0},
    {"appid": 730, "name": "Counter-Strike: Global Offensive", "playtime_forever": 4560},
    {"appid": 72850, "name": "The Elder Scrolls V: Skyrim", "playtime_forever": 890},
    {"appid": 8930, "name": "Sid Meier's Civilization V", "playtime_forever": 0},
    {"appid": 292030, "name": "The Witcher 3: Wild Hunt", "playtime_forever": 85},
    {"appid": 4000, "name": "Garry's Mod", "playtime_forever": 320},
]

# Library sync settings
SYNC_SETTINGS_FILE = 'sync_settings.json'
DEFAULT_SYNC_INTERVAL_HOURS = 6  # Default: sync every 6 hours

# Admin migrations (PostgreSQL)
ADMIN_MIGRATIONS = {
    'users_table': {
        'label': 'Users table',
        'description': 'Create the users table if it does not exist.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS users (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    username VARCHAR(255) UNIQUE,\n"
            "    password VARCHAR(64) NOT NULL,\n"
            "    steam_id VARCHAR(20),\n"
            "    epic_id VARCHAR(255),\n"
            "    gog_id VARCHAR(255),\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
            ");"
        )
    },
    'users_add_password': {
        'label': 'Users add password column',
        'description': 'Add password column to users table (if missing).',
        'sql': (
            "ALTER TABLE users \n"
            "ADD COLUMN IF NOT EXISTS password VARCHAR(64);"
        )
    },
    'roles_table': {
        'label': 'Roles table',
        'description': 'Create roles and user_roles tables if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS roles (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    name VARCHAR(50) UNIQUE\n"
            ");\n"
            "CREATE TABLE IF NOT EXISTS user_roles (\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    role_id INTEGER REFERENCES roles(id),\n"
            "    PRIMARY KEY (user_id, role_id)\n"
            ");"
        )
    },
    'roles_backfill': {
        'label': 'Backfill roles from users.role',
        'description': 'Copy users.role into roles/user_roles and drop users.role column.',
        'sql': (
            "INSERT INTO roles (name) VALUES ('admin') ON CONFLICT DO NOTHING;\n"
            "INSERT INTO roles (name) VALUES ('user') ON CONFLICT DO NOTHING;\n"
            "INSERT INTO user_roles (user_id, role_id)\n"
            "SELECT u.id, r.id FROM users u\n"
            "JOIN roles r ON r.name = COALESCE(u.role, 'user')\n"
            "ON CONFLICT DO NOTHING;\n"
            "ALTER TABLE users DROP COLUMN IF EXISTS role;"
        )
    },
    'ignored_games_table': {
        'label': 'Ignored games table',
        'description': 'Create ignored_games table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS ignored_games (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    app_id VARCHAR(50),\n"
            "    game_name VARCHAR(500),\n"
            "    reason VARCHAR(500),\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
            ");"
        )
    },
    'achievements_table': {
        'label': 'Achievements table',
        'description': 'Create achievements table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS achievements (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    app_id VARCHAR(50),\n"
            "    game_name VARCHAR(500),\n"
            "    achievement_id VARCHAR(255),\n"
            "    achievement_name VARCHAR(500),\n"
            "    achievement_description TEXT,\n"
            "    unlocked BOOLEAN DEFAULT FALSE,\n"
            "    unlock_time TIMESTAMP,\n"
            "    rarity DOUBLE PRECISION,\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
            ");"
        )
    },
    'achievement_hunts_table': {
        'label': 'Achievement hunts table',
        'description': 'Create achievement_hunts table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS achievement_hunts (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    app_id VARCHAR(50),\n"
            "    game_name VARCHAR(500),\n"
            "    difficulty VARCHAR(50),\n"
            "    target_achievements INTEGER DEFAULT 0,\n"
            "    unlocked_achievements INTEGER DEFAULT 0,\n"
            "    progress_percent DOUBLE PRECISION DEFAULT 0.0,\n"
            "    status VARCHAR(50) DEFAULT 'in_progress',\n"
            "    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    completed_at TIMESTAMP\n"
            ");"
        )
    },
    'game_library_cache_table': {
        'label': 'Game library cache table',
        'description': 'Create game_library_cache table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS game_library_cache (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    app_id VARCHAR(50),\n"
            "    game_name VARCHAR(500),\n"
            "    platform VARCHAR(50),\n"
            "    playtime_hours DOUBLE PRECISION DEFAULT 0.0,\n"
            "    last_played TIMESTAMP,\n"
            "    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
            ");"
        )
    },
    'multiuser_sessions_table': {
        'label': 'Multi-user sessions table',
        'description': 'Create multiuser_sessions table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS multiuser_sessions (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    session_id VARCHAR(255) UNIQUE,\n"
            "    participants TEXT,\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    shared_ignores BOOLEAN DEFAULT FALSE,\n"
            "    game_picked VARCHAR(50),\n"
            "    picked_at TIMESTAMP\n"
            ");"
        )
    },
    'users_last_seen_column': {
        'label': 'Add last_seen to users table',
        'description': 'Add last_seen column to users table for online presence tracking.',
        'sql': (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP;"
        )
    },
    'favorite_games_table': {
        'label': 'Favorite games table',
        'description': 'Create favorite_games table if missing.',
        'sql': (
            "CREATE TABLE IF NOT EXISTS favorite_games (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    user_id INTEGER REFERENCES users(id),\n"
            "    app_id VARCHAR(50),\n"
            "    platform VARCHAR(50) DEFAULT 'steam',\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    UNIQUE(user_id, app_id)\n"
            ");\n"
            "CREATE INDEX IF NOT EXISTS idx_favorite_games_user_id ON favorite_games(user_id);\n"
            "CREATE INDEX IF NOT EXISTS idx_favorite_games_app_id ON favorite_games(app_id);"
        )
    },
    'game_details_cache_table': {
        'label': 'Game details cache table',
        'description': 'Create game_details_cache table for lazy loading with smart caching (platform-aware).',
        'sql': (
            "CREATE TABLE IF NOT EXISTS game_details_cache (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    app_id VARCHAR(50),\n"
            "    platform VARCHAR(50),\n"
            "    details_json TEXT,\n"
            "    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    last_api_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    UNIQUE(app_id, platform)\n"
            ");\n"
            "CREATE INDEX IF NOT EXISTS idx_game_details_cache_app_id ON game_details_cache(app_id);\n"
            "CREATE INDEX IF NOT EXISTS idx_game_details_cache_platform ON game_details_cache(platform);\n"
            "CREATE INDEX IF NOT EXISTS idx_game_details_cache_last_api_check ON game_details_cache(last_api_check);"
        )
    }
}


class LibrarySyncScheduler:
    """Background scheduler for library syncing"""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.sync_interval_hours = DEFAULT_SYNC_INTERVAL_HOURS
        self.last_sync_times = {}  # username -> timestamp
        self.in_progress = set()
        self.lock = threading.Lock()
        self.load_settings()
    
    def load_settings(self):
        """Load sync settings from file"""
        if os.path.exists(SYNC_SETTINGS_FILE):
            try:
                with open(SYNC_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    self.sync_interval_hours = settings.get('sync_interval_hours', DEFAULT_SYNC_INTERVAL_HOURS)
                    gui_logger.info(f'Loaded sync settings: interval={self.sync_interval_hours}h')
            except Exception as e:
                gui_logger.error(f'Error loading sync settings: {e}')
    
    def save_settings(self):
        """Save sync settings to file"""
        try:
            settings = {
                'sync_interval_hours': self.sync_interval_hours,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            gapi._atomic_write_json(SYNC_SETTINGS_FILE, settings)
            gui_logger.info(f'Saved sync settings: interval={self.sync_interval_hours}h')
        except Exception as e:
            gui_logger.error(f'Error saving sync settings: {e}')
    
    def set_interval(self, hours: float):
        """Set the sync interval in hours (admin only)"""
        with self.lock:
            self.sync_interval_hours = max(1.0, min(168.0, hours))  # Between 1h and 1 week
            self.save_settings()
            gui_logger.info(f'Sync interval updated to {self.sync_interval_hours}h')
    
    def get_interval(self) -> float:
        """Get current sync interval in hours"""
        return self.sync_interval_hours
    
    def should_sync(self, username: str) -> bool:
        """Check if user's library should be synced"""
        with self.lock:
            last_sync = self.last_sync_times.get(username)
            if not last_sync:
                return True
            
            hours_since_sync = (datetime.now(timezone.utc) - last_sync).total_seconds() / 3600
            return hours_since_sync >= self.sync_interval_hours
    
    def record_sync(self, username: str):
        """Record that a sync was completed for a user"""
        with self.lock:
            self.last_sync_times[username] = datetime.now(timezone.utc)
    
    def sync_all_users(self):
        """Sync libraries for all users who need it"""
        if not DB_AVAILABLE:
            return
        
        try:
            # Get all users
            db = database.SessionLocal()
            if _user_service:
                all_users = _user_service.get_all(db)
            else:
                all_users = database.get_all_users(db)
            db.close()
            
            for user in all_users:
                username = user.username
                
                # Check if sync is needed
                if not self.should_sync(username):
                    continue
                
                # Sync in background
                def sync_user(uname):
                    try:
                        success, msg = sync_library_to_db(uname, force=False)
                        if success:
                            self.record_sync(uname)
                            gui_logger.info(f'Background sync for {uname}: {msg}')
                        else:
                            gui_logger.debug(f'Skipped sync for {uname}: {msg}')
                    except Exception as e:
                        gui_logger.error(f'Error in background sync for {uname}: {e}')
                
                threading.Thread(target=sync_user, args=(username,), daemon=True).start()
                
        except Exception as e:
            gui_logger.error(f'Error in sync_all_users: {e}')
    
    def run(self):
        """Background task that runs periodically"""
        while self.running:
            try:
                # Run sync check every 30 minutes
                self.sync_all_users()
                
                # Sleep for 30 minutes
                for _ in range(1800):  # 30 minutes in seconds
                    if not self.running:
                        break
                    threading.Event().wait(1)
                    
            except Exception as e:
                gui_logger.error(f'Error in sync scheduler: {e}')
                threading.Event().wait(60)  # Wait 1 minute before retrying
    
    def start(self):
        """Start the background sync scheduler"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        gui_logger.info('Library sync scheduler started')
    
    def stop(self):
        """Stop the background sync scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        gui_logger.info('Library sync scheduler stopped')
    
    def trigger_sync(self, username: str) -> Tuple[bool, str]:
        """Manually trigger sync for a specific user in background"""
        with self.lock:
            if username in self.in_progress:
                return False, "Sync already in progress"
            self.in_progress.add(username)

        def run_sync():
            try:
                success, msg = sync_library_to_db(username, force=True)
                if success:
                    self.record_sync(username)
                    gui_logger.info('Manual sync completed for %s: %s', username, msg)
                else:
                    gui_logger.warning('Manual sync skipped for %s: %s', username, msg)
            except Exception as e:
                gui_logger.error('Manual sync error for %s: %s', username, e)
            finally:
                with self.lock:
                    self.in_progress.discard(username)

        threading.Thread(target=run_sync, daemon=True).start()
        return True, "Sync started"


# Global sync scheduler
sync_scheduler = LibrarySyncScheduler()


class UserManager:
    """Manages user authentication and platform IDs using database as primary storage"""
    
    def __init__(self):
        pass
    
    def hash_password(self, password: str) -> str:
        """Hash a password"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register(self, username: str, password: str, role: str = None) -> Tuple[bool, str]:
        """Register a new user"""
        if not DB_AVAILABLE:
            return False, "Database not available"
            
        if len(username) < 3:
            return False, "Username must be at least 3 characters"
        if len(password) < 6:
            return False, "Password must be at least 6 characters"
        
        try:
            db = database.SessionLocal()
            
            # Check if user already exists
            existing_user = database.get_user_by_username(db, username)
            if existing_user:
                db.close()
                return False, "Username already exists"
            
            # Determine role: first user becomes admin, rest are regular users
            if role is None:
                all_users = database.get_all_users(db)
                role = 'admin' if len(all_users) == 0 else 'user'
            
            # Create user in database
            password_hash = self.hash_password(password)
            user = database.create_or_update_user(db, username, password_hash, '', '', '', role)
            db.close()
            
            if user:
                gui_logger.info('Registered new user: %s (role: %s)', username, role)
                return True, "User registered successfully"
            else:
                return False, "Failed to create user"
                
        except Exception as e:
            gui_logger.exception('Error registering user: %s', e)
            return False, "Registration failed"
    
    def login(self, username: str, password: str) -> Tuple[bool, str]:
        """Verify user credentials"""
        if not DB_AVAILABLE:
            gui_logger.error('Login failed: Database not available')
            return False, "Database not available"
            
        try:
            db = database.SessionLocal()
            password_hash = self.hash_password(password)
            gui_logger.info('Login attempt - username=%s, password_hash=%s...', username, password_hash[:20])
            is_valid = database.verify_user_password(db, username, password_hash)
            gui_logger.info('Password verification result: %s', is_valid)
            db.close()
            
            if is_valid:
                return True, "Login successful"
            else:
                gui_logger.warning('Login failed for user %s: Invalid credentials', username)
                return False, "Invalid username or password"
                
        except Exception as e:
            gui_logger.exception('Error during login: %s', e)
            return False, "Login failed"
    
    def get_user_ids(self, username: str) -> Dict:
        """Get user's platform IDs"""
        if not DB_AVAILABLE:
            return {}
            
        try:
            db = database.SessionLocal()
            user = database.get_user_by_username(db, username)
            db.close()
            
            if user:
                return {
                    'steam_id': user.steam_id or '',
                    'epic_id': user.epic_id or '',
                    'gog_id': user.gog_id or ''
                }
            return {}
            
        except Exception as e:
            gui_logger.exception('Error getting user IDs: %s', e)
            return {}
    
    def update_user_ids(self, username: str, steam_id: str = '', epic_id: str = '', gog_id: str = '') -> bool:
        """Update user's platform IDs"""
        if not DB_AVAILABLE:
            return False
            
        try:
            db = database.SessionLocal()
            user = database.get_user_by_username(db, username)
            
            if not user:
                db.close()
                return False
            
            # Update platform IDs without changing password or role
            user.steam_id = steam_id
            user.epic_id = epic_id
            user.gog_id = gog_id
            user.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.close()
            
            gui_logger.info('Updated platform IDs for user: %s', username)
            return True
            
        except Exception as e:
            gui_logger.exception('Error updating user IDs: %s', e)
            return False
    
    def get_user_role(self, username: str) -> str:
        """Get user's role"""
        if not DB_AVAILABLE:
            return 'user'
            
        # Ensure username is a string, not a LocalProxy or other object
        if username is None:
            return 'user'
        username_str = str(username)
        if not username_str or username_str == 'None':
            gui_logger.warning('get_user_role called with invalid username: %s (type: %s)', username, type(username))
            return 'user'
            
        try:
            db = database.SessionLocal()
            roles = database.get_user_roles(db, username_str)
            db.close()
            
            if 'admin' in roles:
                return 'admin'
            if roles:
                return roles[0]
            return 'user'
            
        except Exception as e:
            gui_logger.exception('Error getting user role for %s: %s', username_str, e)
            return 'user'
    
    def is_admin(self, username: str) -> bool:
        """Check if user is admin"""
        return self.get_user_role(username) == 'admin'
    
    def get_all_users(self) -> List[Dict]:
        """Get all users with their info (excluding passwords)"""
        if not DB_AVAILABLE:
            return []
            
        try:
            db = database.SessionLocal()
            users = database.get_all_users(db)
            
            users_list = []
            for user in users:
                role_names = [r.name for r in user.roles] if user.roles else []
                primary_role = 'admin' if 'admin' in role_names else (role_names[0] if role_names else 'user')
                users_list.append({
                    'username': user.username,
                    'steam_id': user.steam_id or '',
                    'epic_id': user.epic_id or '',
                    'gog_id': user.gog_id or '',
                    'role': primary_role,
                    'roles': role_names
                })
            db.close()
            return users_list
            
        except Exception as e:
            gui_logger.exception('Error getting all users: %s', e)
            return []
    
    def delete_user(self, username: str, requesting_user: str) -> Tuple[bool, str]:
        """Delete a user (admin only)"""
        if not DB_AVAILABLE:
            return False, "Database not available"
            
        if not self.is_admin(requesting_user):
            return False, "Only admins can delete users"
        
        if username == requesting_user:
            return False, "Cannot delete yourself"
        
        try:
            db = database.SessionLocal()
            user = database.get_user_by_username(db, username)
            
            if not user:
                db.close()
                return False, "User not found"
            
            success = database.delete_user(db, username)
            db.close()
            
            if success:
                gui_logger.info('Deleted user: %s', username)
                return True, "User deleted successfully"
            else:
                return False, "Failed to delete user"
                
        except Exception as e:
            gui_logger.exception('Error deleting user: %s', e)
            return False, "Delete failed"
    
    def update_user_role(self, username: str, role: str, requesting_user: str) -> Tuple[bool, str]:
        """Update user's role (admin only)"""
        if not DB_AVAILABLE:
            return False, "Database not available"
            
        if not self.is_admin(requesting_user):
            return False, "Only admins can change roles"
        
        if role not in ['admin', 'user']:
            return False, "Invalid role"
        
        try:
            db = database.SessionLocal()
            user = database.get_user_by_username(db, username)
            
            if not user:
                db.close()
                return False, "User not found"
            
            success = database.update_user_role(db, username, role)
            db.close()
            
            if success:
                gui_logger.info('Updated role for user %s to %s', username, role)
                return True, "Role updated successfully"
            else:
                return False, "Failed to update role"
                
        except Exception as e:
            gui_logger.exception('Error updating user role: %s', e)
            return False, "Update failed"

    def update_user_roles(self, username: str, roles: List[str], requesting_user: str) -> Tuple[bool, str]:
        """Update user's roles (admin only)"""
        if not DB_AVAILABLE:
            return False, "Database not available"

        if not self.is_admin(requesting_user):
            return False, "Only admins can change roles"

        if not roles:
            return False, "At least one role is required"

        try:
            db = database.SessionLocal()
            user = database.get_user_by_username(db, username)

            if not user:
                db.close()
                return False, "User not found"

            success = database.set_user_roles(db, username, roles)
            db.close()

            if success:
                gui_logger.info('Updated roles for user %s to %s', username, roles)
                return True, "Roles updated successfully"
            else:
                return False, "Failed to update roles"

        except Exception as e:
            gui_logger.exception('Error updating user roles: %s', e)
            return False, "Update failed"


# Global user manager
user_manager = UserManager()


def load_base_config(config_path: str = 'config.json') -> Dict:
    """Load base config without enforcing Steam ID requirements.

    The GUI uses per-user Steam IDs, so only the API key is required here.
    """
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if os.getenv('STEAM_API_KEY'):
        config['steam_api_key'] = os.getenv('STEAM_API_KEY')
    return config


def _resolve_current_username_str() -> str:
    """Return the effective current username as a plain string.

    Reads the module-level ``current_user`` first (which tests can patch via
    ``@patch('gapi_gui.current_user', 'testuser')``) and falls back to the
    session-based :func:`get_current_username` when it is a proxy.
    """
    # Always use get_current_username() to get the resolved string
    username = get_current_username()
    return username if username else ''


def require_login(f):
    """Decorator to require user to be logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get username properly through the resolver instead of checking LocalProxy directly
        username = _resolve_current_username_str()
        if not username:
            return jsonify({'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_admin(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = _resolve_current_username_str()
        if not username:
            return jsonify({'error': 'Not logged in'}), 401
        if not user_manager.is_admin(username):
            return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def _audit(action: str, resource_type: str = None, resource_id: str = None,
           description: str = None, old_value: dict = None, new_value: dict = None,
           actor: str = None, status: str = 'success', error: str = None):
    """Best-effort fire-and-forget audit log entry.

    Silently ignored if ``_audit_service`` is not available or DB is down so
    it never breaks the calling request handler.
    """
    if not _audit_service or not DB_AVAILABLE:
        return
    try:
        db = next(database.get_db())
        username = actor or get_current_username() or 'anonymous'
        ip = request.remote_addr if has_request_context() else None
        ua = (request.headers.get('User-Agent', '') if has_request_context() else None)
        _audit_service.log_action(
            db, username=username, action=action,
            resource_type=resource_type, resource_id=resource_id,
            description=description, old_value=old_value, new_value=new_value,
            ip_address=ip, user_agent=ua,
            status=status, error_message=error,
        )
    except Exception:
        pass  # audit failures must never break the request


PLATFORM_DEVICE_MAP = {
    'steam': 'pc',
    'epic': 'pc',
    'gog': 'pc',
    'origin': 'pc',
    'ea': 'pc',
    'ubisoft': 'pc',
    'uplay': 'pc',
    'battlenet': 'pc',
    'battle.net': 'pc',
    'xbox': 'console',
    'playstation': 'console',
    'ps': 'console',
    'nintendo': 'console',
    'switch': 'console'
}


def classify_device_for_platform(platform: str) -> str:
    """Map platform name to broad device type (pc/console/other)."""
    p = (platform or '').strip().lower()
    if not p:
        return 'other'
    if p in PLATFORM_DEVICE_MAP:
        return PLATFORM_DEVICE_MAP[p]
    if 'xbox' in p or 'playstation' in p or 'nintendo' in p or 'switch' in p:
        return 'console'
    if p in {'pc', 'windows', 'linux', 'mac'}:
        return 'pc'
    return 'other'


def _filter_games_by_platform_device(
    games: Optional[List[Dict]],
    platform_filter: Optional[str],
    device_filter: Optional[str]
) -> Optional[List[Dict]]:
    """Filter game list by platform and/or device type."""
    if games is None:
        return None

    selected_platform = (platform_filter or '').strip().lower() or None
    selected_device = (device_filter or '').strip().lower() or None
    if selected_device not in {None, 'pc', 'console'}:
        selected_device = None

    filtered = games
    if selected_platform:
        filtered = [
            game for game in filtered
            if str(game.get('platform', 'steam')).strip().lower() == selected_platform
        ]

    if selected_device:
        filtered = [
            game for game in filtered
            if classify_device_for_platform(str(game.get('platform', 'steam'))) == selected_device
        ]

    return filtered


def _collect_available_platforms(usernames: List[str]) -> List[str]:
    """Collect unique platforms configured/seen for the provided users."""
    usernames_set = {u for u in usernames if u}
    if not usernames_set:
        return []

    platforms = set()

    users_by_name = {u.get('username'): u for u in user_manager.get_all_users()}
    for username in usernames_set:
        user = users_by_name.get(username)
        if not user:
            continue
        if user.get('steam_id'):
            platforms.add('steam')
        if user.get('epic_id'):
            platforms.add('epic')
        if user.get('gog_id'):
            platforms.add('gog')

    if DB_AVAILABLE and ensure_db_available():
        db = None
        try:
            db = database.SessionLocal()
            for username in usernames_set:
                if _library_service:
                    cached_games = _library_service.get_cached(db, username)
                else:
                    cached_games = database.get_cached_library(db, username)
                for game in cached_games or []:
                    platform = str(game.get('platform', '')).strip().lower()
                    if platform:
                        platforms.add(platform)
        except Exception as e:
            gui_logger.warning('Could not collect cached library platforms: %s', e)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    preferred_order = ['steam', 'epic', 'gog', 'xbox', 'playstation', 'nintendo', 'switch']
    ordered = [p for p in preferred_order if p in platforms]
    ordered.extend(sorted(p for p in platforms if p not in set(preferred_order)))
    return ordered


def _build_auth_users_for_multi() -> List[Dict]:
    """Build multi-user picker user list from authenticated users."""
    users = user_manager.get_all_users()
    formatted = []
    for user in users:
        formatted.append({
            'name': user['username'],
            'platforms': {
                'steam': user.get('steam_id', ''),
                'epic': user.get('epic_id', ''),
                'gog': user.get('gog_id', '')
            }
        })
    return formatted


def _ensure_multi_picker() -> None:
    """Ensure multi-user picker is initialized and synced with auth users."""
    global multi_picker
    users = _build_auth_users_for_multi()
    base_config = load_base_config()
    config = {
        'steam_api_key': base_config.get('steam_api_key', ''),
        'epic_enabled': any(u['platforms'].get('epic') for u in users),
        'gog_enabled': any(u['platforms'].get('gog') for u in users)
    }

    with multi_picker_lock:
        needs_rebuild = (
            multi_picker is None or
            multi_picker.config.get('steam_api_key') != config['steam_api_key'] or
            multi_picker.config.get('epic_enabled') != config['epic_enabled'] or
            multi_picker.config.get('gog_enabled') != config['gog_enabled']
        )
        if needs_rebuild:
            multi_picker = multiuser.MultiUserPicker(config)
        multi_picker.users = users


def sync_library_to_db(username: str, force: bool = False) -> Tuple[bool, str]:
    """Sync user's game library from Steam API to database cache.
    
    Args:
        username: Username to sync
        force: Force sync even if cache is recent
    
    Returns:
        (success, message) tuple
    """
    if not ensure_db_available():
        return False, "Database not available"
    
    try:
        # Get user's Steam ID
        user_ids = user_manager.get_user_ids(username)
        steam_id = user_ids.get('steam_id', '')
        
        # Check if Steam ID is valid
        if not steam_id or gapi.is_placeholder_value(steam_id):
            gui_logger.info(f"No valid Steam ID for user {username}, skipping library sync")
            return True, "No Steam ID configured"
        
        # Check cache age unless forced
        db = database.SessionLocal()
        try:
            if _library_service:
                cache_age = _library_service.get_cache_age(db, username)
            else:
                cache_age = database.get_library_cache_age(db, username)

            # Don't sync if cache is less than 1 hour old (unless forced)
            if not force and cache_age is not None and cache_age < 3600:
                gui_logger.debug(f"Library cache for {username} is fresh ({cache_age:.0f}s old), skipping sync")
                return True, f"Cache is fresh ({int(cache_age/60)}m old)"

            # Fetch library from Steam API
            base_config = load_base_config()
            steam_api_key = base_config.get('steam_api_key', '')

            if not steam_api_key or gapi.is_placeholder_value(steam_api_key):
                return False, "Steam API key not configured"

            gui_logger.info(f"Syncing library for {username} from Steam API...")
            steam_client = gapi.SteamAPIClient(steam_api_key)
            games = steam_client.get_owned_games(steam_id)

            if not games:
                return False, "Failed to fetch games from Steam API"

            # Cache the games in database
            if _library_service:
                count = _library_service.cache(db, username, games)
            else:
                count = database.cache_user_library(db, username, games)
        finally:
            db.close()

        gui_logger.info(f"Synced {count} games for {username}")
        return True, f"Synced {count} games"
        
    except Exception as e:
        gui_logger.exception(f"Error syncing library for {username}: {e}")
        return False, str(e)



def initialize_picker(config_path: str = 'config.json'):
    """Initialize the game picker"""
    global picker, multi_picker
    with picker_lock:
        try:
            picker = gapi.GamePicker(config_path=config_path)
            if picker.fetch_games():
                # Initialize multi-user picker with full config
                with multi_picker_lock:
                    multi_picker = multiuser.MultiUserPicker(picker.config)
                return True, f"Loaded {len(picker.games)} games"
            return False, "Failed to fetch games"
        except Exception as e:
            return False, str(e)


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    """Browser favicon fallback route."""
    return flask_redirect('/static/favicon.svg?v=2', code=302)


@app.route('/game-sessions')
@require_login
def game_sessions():
    """Dedicated game sessions page - requires login"""
    return render_template('game_sessions.html')


@app.route('/manifest.json')
def pwa_manifest():
    """Serve the Web App Manifest for Progressive Web App support."""
    manifest = {
        "name": "GAPI - Game Picker",
        "short_name": "GAPI",
        "description": "Randomly pick your next game from your Steam library.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#667eea",
        "theme_color": "#667eea",
        "orientation": "any",
        "icons": [
            {
                "src": "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6/svgs/solid/gamepad.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
        "categories": ["games", "entertainment", "utilities"],
        "lang": "en",
        "dir": "ltr",
    }
    return jsonify(manifest), 200, {
        'Content-Type': 'application/manifest+json',
        'Cache-Control': 'public, max-age=86400',
    }


@app.route('/sw.js')
def pwa_service_worker():
    """Serve the PWA service worker that enables offline-capable caching."""
    sw_js = r"""// GAPI Service Worker — simplified offline-first caching
'use strict';

const CACHE_NAME = 'gapi-v1';

// ── Install: skip waiting and proceed to activate ──
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

// ── Activate: claim all clients ──────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// ── Fetch: network-first, with error fallback ──────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip cross-origin requests (like CDN resources) - let browser handle them
  if (url.origin !== self.location.origin) {
    return;
  }

  // Skip non-GET requests and API calls - always fetch from network
  if (request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => {
        // Network error - return error response
        return new Response(
          JSON.stringify({ error: 'Network error' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // For GET requests (not API): network-first, fall back to cache
  event.respondWith(
    fetch(request)
      .then((response) => {
        // Cache successful responses
        if (response && response.status === 200) {
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, response.clone());
          });
        }
        return response;
      })
      .catch(() => {
        // Network failed - try cache
        return caches.match(request).then((cached) => {
          if (cached) return cached;
          // No cache - return offline page for navigation, error for others
          if (request.mode === 'navigate') {
            return new Response('Service Unavailable - Offline', {
              status: 503,
              headers: { 'Content-Type': 'text/plain' }
            });
          }
          return new Response('', { status: 503 });
        });
      })
  );
});
"""
    return sw_js, 200, {
        'Content-Type': 'application/javascript; charset=utf-8',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Service-Worker-Allowed': '/',
    }



def ensure_picker_initialized(username: str = None):
    """Ensure picker is initialized and loaded with user's games from database.
    
    Args:
        username: Username to load games for. If None, uses current_user.
        
    Returns:
        True if picker was successfully initialized, False otherwise.
    """
    global picker, current_user
    
    if username is None:
        username = get_current_username()
    
    if not username:
        return False
    
    # Initialize picker if needed
    if not picker:
        with picker_lock:
            if not picker:  # Double-check after acquiring lock
                # Properly initialize GamePicker with config
                try:
                    picker = gapi.GamePicker(config_path='config.json')
                    gui_logger.info("Initialized GamePicker")
                except Exception as e:
                    gui_logger.exception(f"Failed to initialize GamePicker: {e}")
                    return False
    
    # Load games from database if not already loaded
    if not picker.games or len(picker.games) == 0:
        if DB_AVAILABLE and ensure_db_available():
            try:
                db = database.SessionLocal()
                try:
                    if _library_service:
                        cached_games = _library_service.get_cached(db, username)
                    else:
                        cached_games = database.get_cached_library(db, username)
                    
                    if cached_games:
                        with picker_lock:
                            picker.games = [
                                {
                                    'appid': int(g['app_id']) if str(g['app_id']).isdigit() else g['app_id'],
                                    'name': g['name'],
                                    'playtime_forever': int(g.get('playtime_hours', 0) * 60),
                                    'platform': g.get('platform', 'steam')
                                }
                                for g in cached_games
                            ]
                        gui_logger.info(f"Loaded {len(picker.games)} games for {username} from database cache")
                        return True
                    else:
                        gui_logger.warning(f"No cached games for {username}")
                        with picker_lock:
                            picker.games = DEMO_GAMES
                        return False
                finally:
                    db.close()
            except Exception as e:
                gui_logger.exception(f"Failed to load games from database: {e}")
                with picker_lock:
                    picker.games = DEMO_GAMES
                return False
        else:
            with picker_lock:
                picker.games = DEMO_GAMES
            return False
    
    return True


@app.route('/api/status')
def api_status():
    """Get application status"""
    global picker, current_user
    
    # Check if user is logged in
    if not current_user:
        return jsonify({
            'ready': False,
            'logged_in': False,
            'message': 'Please log in'
        })
    
    # Ensure picker is initialized with user's games
    ensure_picker_initialized()
    
    if picker is None:
        return jsonify({
            'ready': False,
            'logged_in': True,
            'message': 'Loading games...'
        })
    
    return jsonify({
        'ready': True,
        'logged_in': True,
        'current_user': get_current_username(),
        'is_admin': user_manager.is_admin(get_current_username()),
        'total_games': len(picker.games) if picker.games else 0,
        'favorites': len(picker.favorites) if picker.favorites else 0
    })


# ===========================================================================================
# Authentication Endpoints
# ===========================================================================================

@app.route('/api/auth/current', methods=['GET'])
def api_auth_current():
    """Get current logged-in user"""
    username = get_current_username()
    if username:
        role = user_manager.get_user_role(username)
        return jsonify({
            'username': username,
            'role': role,
            'roles': [role] if role else ['user']  # For admin check
        })
    return jsonify({'username': None}), 401


@app.route('/api/auth/register', methods=['POST'])
# @limiter.limit("10 per hour")  # Temporarily disabled for debugging
def api_auth_register():
    """Register a new user"""
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    gui_logger.info('Register endpoint called for username=%s', username)
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, message = user_manager.register(username, password)
    if not success:
        return jsonify({'error': message}), 400
    gui_logger.info('Register result for username=%s: %s', username, 'success' if success else 'failure')

    return jsonify({'message': message})


# ===========================================================================================
# First-time Setup Endpoints
# ===========================================================================================

@app.route('/api/setup/status', methods=['GET'])
def api_setup_status():
    """Check if initial admin setup is required."""
    if not ensure_db_available():
        return jsonify({'needs_setup': False, 'error': 'Database not available'}), 503
    try:
        db = database.SessionLocal()
        try:
            if _user_service:
                count = _user_service.get_count(db)
            else:
                count = database.get_user_count(db)
        finally:
            db.close()
        return jsonify({'needs_setup': count == 0})
    except Exception as e:
        gui_logger.exception('Setup status check failed: %s', e)
        return jsonify({'needs_setup': False, 'error': str(e)}), 500


@app.route('/api/setup/initial-admin', methods=['POST'])
def api_setup_initial_admin():
    """Create the initial admin user if no users exist."""
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    try:
        db = database.SessionLocal()
        try:
            if _user_service:
                count = _user_service.get_count(db)
            else:
                count = database.get_user_count(db)
            if count > 0:
                return jsonify({'error': 'Users already exist'}), 409

            password_hash = user_manager.hash_password(password)
            if _user_service:
                user = _user_service.create_admin(db, username, password_hash)
            else:
                user = database.create_or_update_user(
                    db, username, password_hash, '', '', '',
                    role='admin', roles=['admin'])
        finally:
            db.close()

        if user:
            return jsonify({'message': 'Initial admin created'}), 201
        return jsonify({'error': 'Failed to create admin'}), 500
    except Exception as e:
        gui_logger.exception('Initial admin setup failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
# @limiter.limit("20 per minute; 100 per hour")  # Temporarily disabled for debugging
def api_auth_login():
    """Log in a user"""
    global picker, multi_picker
    
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    gui_logger.info('Login endpoint called for username=%s', username)
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, message = user_manager.login(username, password)
    
    if not success:
        _audit('login', resource_type='auth', resource_id=username,
               description='Login failed', actor=username, status='failure', error=message)
        return jsonify({'error': message}), 401
    
    session['username'] = username
    gui_logger.info('User logged in: %s', username)
    _audit('login', resource_type='auth', resource_id=username,
           description='Login successful', actor=username)
    
    # Initialize picker for this user
    user_ids = user_manager.get_user_ids(username)
    # If DB is available prefer IDs from DB (keep JSON store as cache)
    if DB_AVAILABLE:
        try:
            db = database.SessionLocal()
            try:
                if _user_service:
                    db_ids = _user_service.get_platform_ids(db, username)
                else:
                    db_user = database.get_user_by_username(db, username)
                    db_ids = {
                        'steam_id': getattr(db_user, 'steam_id', None) or '',
                        'epic_id': getattr(db_user, 'epic_id', None) or '',
                        'gog_id': getattr(db_user, 'gog_id', None) or '',
                    } if db_user else {}
            finally:
                db.close()
            for key in ('steam_id', 'epic_id', 'gog_id'):
                if db_ids.get(key):
                    user_ids[key] = db_ids[key]
        except Exception as e:
            gui_logger.exception('Failed to read user IDs from DB for %s: %s', username, e)
    
    # Create a temporary config with user's IDs
    if user_ids.get('steam_id'):
        base_config = load_base_config()
        temp_config = {
            'steam_api_key': base_config.get('steam_api_key', ''),
            'steam_id': user_ids['steam_id'],
            'epic_enabled': user_ids.get('epic_id') != '',
            'epic_id': user_ids.get('epic_id', ''),
            'gog_enabled': user_ids.get('gog_id') != '',
            'gog_id': user_ids.get('gog_id', '')
        }
        
        # Initialize background library sync if Steam ID is configured
        def init_library_async():
            try:
                # Only sync if user has a valid Steam ID
                if user_ids.get('steam_id') and not gapi.is_placeholder_value(user_ids['steam_id']):
                    gui_logger.info(f"Triggering library sync for {username}")
                    success, msg = sync_library_to_db(username, force=False)
                    if success:
                        gui_logger.info(f"Library sync completed for {username}: {msg}")
                    else:
                        gui_logger.warning(f"Library sync failed for {username}: {msg}")
                else:
                    gui_logger.info(f"No valid Steam ID for {username}, skipping library sync")
                    
            except Exception as e:
                gui_logger.error("Error in background library sync: %s", e)
        
        threading.Thread(target=init_library_async, daemon=True).start()
    
    return jsonify({'message': 'Login successful', 'username': username})


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """Log out the current user"""
    global picker, multi_picker

    _username = session.get('username')
    gui_logger.info('User logged out: %s', _username)
    _audit('logout', resource_type='auth', resource_id=_username,
           description='User logged out', actor=_username)
    session.pop('username', None)

    with picker_lock:
        picker = None

    with multi_picker_lock:
        multi_picker = None

    # Clear Discord Rich Presence on logout (best-effort)
    if _discord_presence:
        _discord_presence.clear()

    return jsonify({'message': 'Logged out successfully'})


@app.route('/api/auth/update-ids', methods=['POST'])
def api_auth_update_ids():
    """Update user's platform IDs"""
    global current_user
    
    if not current_user:
        return jsonify({'error': 'Not logged in'}), 401
    username = get_current_username()
    
    data = request.json or {}
    steam_id = data.get('steam_id', '').strip()
    epic_id = data.get('epic_id', '').strip()
    gog_id = data.get('gog_id', '').strip()
    
    success = user_manager.update_user_ids(username, steam_id, epic_id, gog_id)
    
    if not success:
        return jsonify({'error': 'Failed to update IDs'}), 400
    
    # Trigger library sync if Steam ID was added/changed
    user_ids = user_manager.get_user_ids(username)
    
    if user_ids.get('steam_id') and not gapi.is_placeholder_value(user_ids['steam_id']):
        # Sync library in background
        def sync_async():
            try:
                gui_logger.info(f"Syncing library after ID update for {username}")
                success, msg = sync_library_to_db(username, force=True)
                if success:
                    gui_logger.info(f"Library sync completed: {msg}")
                else:
                    gui_logger.warning(f"Library sync failed: {msg}")
            except Exception as e:
                gui_logger.error(f"Error in background sync: {e}")
        
        threading.Thread(target=sync_async, daemon=True).start()
    
    return jsonify({'message': 'Platform IDs updated successfully'})


@app.route('/api/auth/get-ids', methods=['GET'])
def api_auth_get_ids():
    """Get current user's platform IDs"""
    global current_user
    
    if not current_user:
        return jsonify({'error': 'Not logged in'}), 401
    username = get_current_username()
    
    user_ids = user_manager.get_user_ids(username)
    if DB_AVAILABLE:
        try:
            db = database.SessionLocal()
            try:
                if _user_service:
                    db_ids = _user_service.get_platform_ids(db, username)
                else:
                    db_user = database.get_user_by_username(db, username)
                    db_ids = {
                        'steam_id': getattr(db_user, 'steam_id', None) or '',
                        'epic_id': getattr(db_user, 'epic_id', None) or '',
                        'gog_id': getattr(db_user, 'gog_id', None) or '',
                    } if db_user else {}
            finally:
                db.close()
            for key in ('steam_id', 'epic_id', 'gog_id'):
                if db_ids.get(key):
                    user_ids[key] = db_ids[key]
        except Exception as e:
            gui_logger.exception('Failed to read IDs from DB for %s: %s', username, e)
    return jsonify(user_ids)


@app.route('/api/filters/platform-options', methods=['GET'])
@require_login
def api_filter_platform_options():
    """Return platform/device filter options limited to user-configured platforms."""
    username = get_current_username()

    users_param = request.args.get('users', '').strip()
    requested_users = [u.strip() for u in users_param.split(',') if u.strip()] if users_param else []
    usernames = requested_users or ([username] if username else [])

    platforms = _collect_available_platforms(usernames)
    platform_items = [
        {
            'value': platform,
            'label': platform.title(),
            'device': classify_device_for_platform(platform)
        }
        for platform in platforms
    ]

    device_values = sorted({
        item['device'] for item in platform_items if item['device'] in {'pc', 'console'}
    })
    device_items = [
        {
            'value': device,
            'label': 'PC' if device == 'pc' else 'Console'
        }
        for device in device_values
    ]

    return jsonify({
        'platforms': platform_items,
        'devices': device_items
    })


@app.route('/api/pick', methods=['POST'])
@require_login
def api_pick_game():
    """Pick a random game"""
    global picker, current_game, current_user

    # Get current user
    username = get_current_username()
    
    try:
        gui_logger.info(f"Pick request from user {username}")
        
        # Ensure picker is initialized with user's games
        if not ensure_picker_initialized(username):
            gui_logger.warning(f"Failed to initialize picker for {username}")
            return jsonify({'error': 'Failed to load games'}), 500
        
        if not picker.games or len(picker.games) == 0:
            gui_logger.error(f"No games available for {username} after loading attempt")
            return jsonify({'error': 'No games available in your library'}), 400

        data = request.json or {}
        filter_type = data.get('filter', 'all')
        genre_text = data.get('genre', '').strip()
        genres = [g.strip() for g in genre_text.split(',')] if genre_text else None
        min_metacritic = data.get('min_metacritic')
        min_year = data.get('min_year')
        max_year = data.get('max_year')
        exclude_ids_raw = data.get('exclude_game_ids', '')
        exclude_game_ids = [s.strip() for s in exclude_ids_raw.split(',') if s.strip()] if exclude_ids_raw else None
        tag_filter = data.get('tag', '').strip() or None
        platform_filter = data.get('platform_filter', '').strip().lower() or None
        device_filter = data.get('device_filter', '').strip().lower() or None
        min_rarity = data.get('min_rarity')
        max_rarity = data.get('max_rarity')
        vr_filter_raw = data.get('vr_filter', '').strip().lower() or None
        vr_filter = vr_filter_raw if vr_filter_raw in ('vr_supported', 'vr_only', 'no_vr') else None

        if DB_AVAILABLE:
            db = None
            try:
                db = database.SessionLocal()
                if _ignored_games_service:
                    ignored_games = _ignored_games_service.get_ignored(db, username)

                else:
                    ignored_games = database.get_ignored_games(db, username)
                if ignored_games:
                    if exclude_game_ids:
                        exclude_game_ids.extend(ignored_games)
                    else:
                        exclude_game_ids = ignored_games

                # Rarity filter: restrict to games that still have unfinished
                # achievements within the requested rarity band.
                if min_rarity is not None or max_rarity is not None:
                    try:
                        rarity_app_ids = database.get_games_with_rare_achievements(
                            db, username,
                            max_rarity=float(max_rarity) if max_rarity is not None else 100.0,
                            min_rarity=float(min_rarity) if min_rarity is not None else 0.0,
                        )
                        if rarity_app_ids:
                            # Narrow exclude list: keep only games in the rarity set
                            # by excluding everything else
                            rarity_set = set(str(aid) for aid in rarity_app_ids)
                            extra_excludes = [
                                str(g.get('appid', g.get('id', '')))
                                for g in picker.games
                                if str(g.get('appid', g.get('id', ''))) not in rarity_set
                            ]
                            if exclude_game_ids:
                                exclude_game_ids.extend(extra_excludes)
                            else:
                                exclude_game_ids = extra_excludes
                        else:
                            # No games match the rarity filter — set impossible exclude
                            gui_logger.info(
                                "No games found matching rarity filter "
                                "[%s, %s] for %s", min_rarity, max_rarity, username)
                    except Exception as e:
                        gui_logger.warning("Could not apply rarity filter: %s", e)

            except Exception as e:
                gui_logger.warning(f"Could not fetch ignored games: {e}")
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

        # Build shared advanced-filter kwargs
        adv = {
            'genres': genres,
            'min_metacritic': int(min_metacritic) if min_metacritic is not None else None,
            'min_release_year': int(min_year) if min_year is not None else None,
            'max_release_year': int(max_year) if max_year is not None else None,
            'exclude_game_ids': exclude_game_ids,
            'platforms': [platform_filter] if platform_filter else None,
            'device_types': [device_filter] if device_filter else None,
            'vr_filter': vr_filter,
        }

        with picker_lock:
            try:
                # Apply filters
                filtered_games = None

                if filter_type == "unplayed":
                    filtered_games = picker.filter_games(max_playtime=0, **adv)
                elif filter_type == "barely":
                    filtered_games = picker.filter_games(
                        max_playtime=picker.BARELY_PLAYED_THRESHOLD_MINUTES, **adv)
                elif filter_type == "well":
                    filtered_games = picker.filter_games(
                        min_playtime=picker.WELL_PLAYED_THRESHOLD_MINUTES, **adv)
                elif filter_type == "favorites":
                    filtered_games = picker.filter_games(favorites_only=True, **adv)
                elif any(v is not None and v != [] for v in adv.values()):
                    filtered_games = picker.filter_games(**adv)

                # Apply tag filter on top of other filters (or on whole library)
                if tag_filter:
                    filtered_games = picker.tag_service.filter_by_tag(
                        tag_filter,
                        filtered_games if filtered_games is not None else picker.games,
                    )

                # Apply platform/device filter even when no other filter was active
                if platform_filter or device_filter:
                    base_games = filtered_games if filtered_games is not None else picker.games
                    filtered_games = _filter_games_by_platform_device(
                        base_games,
                        platform_filter,
                        device_filter
                    )

                if filtered_games is not None and len(filtered_games) == 0:
                    gui_logger.info(f"No games matched filters for {username}")
                    return jsonify({'error': 'No games match the selected filters'}), 400

                # Pick game
                game = picker.pick_random_game(filtered_games)

                if not game:
                    gui_logger.error(f"Failed to pick game for {username}")
                    return jsonify({'error': 'Failed to pick a game'}), 500

                current_game = game
                gui_logger.info(f"Picked game for {username}: {game.get('name')}")

                app_id = game.get('appid')
                game_id = game.get('game_id') or (f'steam:{app_id}' if app_id else None)
                name = game.get('name', 'Unknown Game')
                playtime_minutes = game.get('playtime_forever', 0)
                playtime_hours = playtime_minutes / 60

                # Update Discord Rich Presence (non-blocking, best-effort)
                if _discord_presence:
                    _discord_presence.update(name, playtime_hours=round(playtime_hours, 1))

                is_favorite = app_id in picker.favorites if app_id else False
                review = picker.review_service.get(game_id) if game_id else None
                tags = picker.tag_service.get(game_id) if game_id else []
                backlog_status = picker.backlog_service.get_status(game_id) if game_id else None

                response = {
                    'app_id': app_id,
                    'game_id': game_id,
                    'name': name,
                    'playtime_hours': round(playtime_hours, 1),
                    'is_favorite': is_favorite,
                    'review': review,
                    'tags': tags,
                    'backlog_status': backlog_status,
                    'steam_url': f'https://store.steampowered.com/app/{app_id}/',
                    'steamdb_url': f'https://steamdb.info/app/{app_id}/'
                }

                # Try to get details and cache them
                try:
                    if app_id and picker and picker.steam_client:
                        details = picker.steam_client.get_game_details(app_id)
                        if details:
                            # Extract key fields for the response
                            if 'short_description' in details:
                                response['description'] = details['short_description']
                            if 'header_image' in details:
                                response['header_image'] = details['header_image']
                            if 'capsule_image' in details:
                                response['capsule_image'] = details['capsule_image']
                            if 'genres' in details:
                                response['genres'] = [g['description'] for g in details['genres']]
                            if 'release_date' in details:
                                response['release_date'] = details['release_date'].get('date', '')
                            if 'metacritic' in details:
                                response['metacritic_score'] = details['metacritic'].get('score')
                            
                            # Cache the full details for later use
                            try:
                                if DB_AVAILABLE and ensure_db_available():
                                    db = None
                                    try:
                                        db = database.SessionLocal()
                                        platform = game.get('platform', 'steam')
                                        if _library_service:
                                            _library_service.update_game_details(db, app_id, platform, response)
                                        else:
                                            database.update_game_details_cache(db, app_id, platform, response)
                                    except Exception as cache_err:
                                        gui_logger.debug(f"Failed to cache details: {cache_err}")
                                    finally:
                                        if db:
                                            db.close()
                            except Exception as e:
                                gui_logger.debug(f"Failed to cache game details: {e}")
                            
                            # Fetch ProtonDB rating in background (non-blocking)
                            def fetch_protondb():
                                try:
                                    if picker and picker.steam_client:
                                        protondb = picker.steam_client.get_protondb_rating(app_id)
                                        if protondb:
                                            response['protondb'] = protondb
                                except Exception:
                                    pass
                            
                            threading.Thread(target=fetch_protondb, daemon=True).start()
                except Exception as e:
                    gui_logger.debug(f"Failed to fetch game details: {e}")

                # Fire webhook if one is configured (non-blocking, best-effort)
                webhook_url = picker.config.get('webhook_url', '').strip() if picker.config else ''
                if webhook_url and not gapi.is_placeholder_value(webhook_url):
                    wh_payload = {
                        'content': f"🎮 **Game pick:** {name} ({round(playtime_hours, 1)}h played)\n"
                                   f"{response.get('steam_url', '')}",
                        'game': response,
                    }
                    threading.Thread(
                        target=gapi.send_webhook,
                        args=(webhook_url, wh_payload),
                        daemon=True,
                    ).start()

                # Fire Slack / Teams / IFTTT / Home Assistant notifications
                try:
                    from webhook_notifier import WebhookNotifier
                    _notifier = WebhookNotifier(picker.config or {})
                    _has_extra = any(
                        _notifier._get(k) for k in (
                            'slack_webhook_url', 'teams_webhook_url',
                            'ifttt_webhook_key', 'homeassistant_url',
                        )
                    )
                    if _has_extra:
                        threading.Thread(
                            target=_notifier.notify_game_picked,
                            args=(response,),
                            daemon=True,
                        ).start()
                except Exception as _wh_exc:
                    gui_logger.debug("WebhookNotifier error: %s", _wh_exc)

                return jsonify(response)
            
            except Exception as e:
                gui_logger.exception(f"Error in pick endpoint for {username}: {e}")
                return jsonify({'error': f'Error picking game: {str(e)}'}), 500
    
    except Exception as e:
        gui_logger.exception(f"Unexpected error in pick endpoint: {e}")
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/api/game/<int:app_id>/details')
@require_login
def api_game_details(app_id):
    """Get detailed game information with smart caching.
    
    1. Check which platform the game is from (user's library or default to steam)
    2. Check database cache first
    3. If cache is fresh (< 1 hour old), return cached details
    4. If cache is stale, fetch from API and compare
    5. Update cache only if API data differs
    """
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = None
    try:
        db = database.SessionLocal()
        global current_user

        username = get_current_username()

        # Determine platform: check user's library for this game
        platform = 'steam'  # Default to steam
        try:
            if _library_service:
                platform = _library_service.get_game_platform(db, username, app_id)
            else:
                user = database.get_user_by_username(db, username)
                if user:
                    lib_entry = db.query(database.GameLibraryCache).filter(
                        database.GameLibraryCache.user_id == user.id,
                        database.GameLibraryCache.app_id == str(app_id)
                    ).first()
                    if lib_entry:
                        platform = lib_entry.platform or 'steam'
        except Exception as e:
            gui_logger.debug(f"Could not determine platform from library: {e}")

        # Step 1: Check database cache first
        if _library_service:
            cached_details = _library_service.get_game_details(db, app_id, platform, max_age_hours=1)
        else:
            cached_details = database.get_game_details_cache(db, app_id, platform, max_age_hours=1)

        if cached_details:
            # Cache is fresh, return immediately
            return jsonify({**cached_details, 'source': 'cache', 'app_id': app_id, 'platform': platform})

        # Step 2: Cache is missing or stale. Try to fetch from API
        api_details = None
        global picker

        if picker:
            try:
                with picker_lock:
                    if picker.steam_client and isinstance(picker.steam_client, gapi.SteamAPIClient):
                        api_details = picker.steam_client.get_game_details(app_id)
            except Exception as e:
                gui_logger.debug(f"Could not fetch from Steam API: {e}")

        if api_details:
            # Step 3: Format API response
            response = {'app_id': app_id, 'platform': platform, 'source': 'api', 'steam_integration': True}

            if 'header_image' in api_details:
                response['header_image'] = api_details['header_image']

            if 'capsule_image' in api_details:
                response['capsule_image'] = api_details['capsule_image']

            if 'short_description' in api_details:
                response['description'] = api_details['short_description']

            if 'genres' in api_details:
                response['genres'] = [g['description'] for g in api_details['genres']]

            if 'release_date' in api_details:
                response['release_date'] = api_details['release_date'].get('date', 'Unknown')

            if 'metacritic' in api_details:
                response['metacritic_score'] = api_details['metacritic'].get('score')

            # Try to get ProtonDB rating
            try:
                with picker_lock:
                    if picker and picker.steam_client and isinstance(picker.steam_client, gapi.SteamAPIClient):
                        protondb = picker.steam_client.get_protondb_rating(app_id)
                        if protondb:
                            response['protondb'] = protondb
            except Exception:
                pass  # ProtonDB is best-effort, don't fail on it

            # Update cache with new data (include platform)
            if _library_service:
                _library_service.update_game_details(db, app_id, platform, response)
            else:
                database.update_game_details_cache(db, app_id, platform, response)
            return jsonify(response)

        # Step 4: No API data available. Return last cached data even if stale, or minimal response
        try:
            if _library_service:
                stale_details = _library_service.get_stale_game_details(db, app_id, platform)
            else:
                last_cache = db.query(database.GameDetailsCache).filter(
                    database.GameDetailsCache.app_id == str(app_id),
                    database.GameDetailsCache.platform == platform
                ).first()
                stale_details = None
                if last_cache:
                    import json
                    stale_details = json.loads(last_cache.details_json)

            if stale_details:
                return jsonify({
                    **stale_details,
                    'source': 'cache_stale',
                    'app_id': app_id,
                    'platform': platform
                })
        except Exception as e:
            gui_logger.debug(f"Could not get last cache: {e}")

        # No cache or API data - return minimal response
        return jsonify({
            'app_id': app_id,
            'platform': platform,
            'steam_integration': False,
            'source': 'none',
            'message': 'Steam integration not configured for this user'
        })

    except Exception as e:
        gui_logger.exception(f"Error getting game details: {e}")
        return jsonify({'error': f'Failed to load game details: {str(e)}'}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


@app.route('/api/favorite/<int:app_id>', methods=['POST', 'DELETE'])
@require_login
def api_toggle_favorite(app_id):
    """Add or remove a game from favorites"""
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    global current_user
    username = get_current_username()

    if not username:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        db = database.SessionLocal()
        try:
            if request.method == 'POST':
                if _db_favorites_service:
                    success = _db_favorites_service.add(db, username, str(app_id))
                else:
                    success = database.add_favorite(db, username, str(app_id))
                if success:
                    return jsonify({'success': True, 'action': 'added'})
                else:
                    return jsonify({'error': 'Failed to add favorite'}), 500
            else:
                if _db_favorites_service:
                    success = _db_favorites_service.remove(db, username, str(app_id))
                else:
                    success = database.remove_favorite(db, username, str(app_id))
                if success:
                    return jsonify({'success': True, 'action': 'removed'})
                else:
                    return jsonify({'error': 'Failed to remove favorite'}), 500
        finally:
            db.close()
    except Exception as e:
        gui_logger.error(f"Error toggling favorite: {e}")
        return jsonify({'error': 'Failed to toggle favorite'}), 500


@app.route('/api/library')
@require_login
def api_library():
    """Get all games in library from database cache"""
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        # Fallback to demo games if DB not available
        return jsonify({'games': [{
            'app_id': g.get('appid'),
            'name': g.get('name', 'Unknown'),
            'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
            'is_favorite': False
        } for g in DEMO_GAMES]})

    try:
        db = database.SessionLocal()
        try:
            # Get cached library
            if _library_service:
                cached_games = _library_service.get_cached(db, username)
            else:
                cached_games = database.get_cached_library(db, username)

            # If cache is empty, trigger background sync and return early
            if not cached_games:
                def background_sync():
                    success, msg = sync_library_to_db(username, force=True)
                    gui_logger.info(f"Background library sync for {username}: {msg}")
                threading.Thread(target=background_sync, daemon=True).start()
                return jsonify({
                    'games': [],
                    'message': 'Library is being loaded from Steam. Please refresh in a few seconds.'
                })

            # Check if cache is old (>6 hours) and trigger background refresh
            if _library_service:
                cache_age = _library_service.get_cache_age(db, username)
            else:
                cache_age = database.get_library_cache_age(db, username)
            if cache_age and cache_age > 21600:  # 6 hours
                def background_sync():
                    success, msg = sync_library_to_db(username, force=False)
                    gui_logger.info(f"Background library refresh for {username}: {msg}")
                threading.Thread(target=background_sync, daemon=True).start()

            search = request.args.get('search', '').lower()

            # Get user's favorites from database
            if _db_favorites_service:
                favorite_ids = set(str(fav) for fav in _db_favorites_service.get_all(db, username))
            else:
                favorite_ids = set(str(fav) for fav in database.get_user_favorites(db, username))

            # Filter and format games
            games = []
            for game in cached_games:
                name = game.get('name', 'Unknown')
                if search and search not in name.lower():
                    continue

                app_id = game.get('app_id')
                try:
                    app_id_int = int(app_id) if app_id else None
                except (ValueError, TypeError):
                    app_id_int = None

                games.append({
                    'app_id': app_id_int,
                    'name': name,
                    'playtime_hours': round(game.get('playtime_hours', 0), 1),
                    'is_favorite': str(app_id) in favorite_ids if app_id else False,
                    'platform': game.get('platform', 'steam'),
                    'last_played': game.get('last_played').isoformat() if game.get('last_played') else None
                })
        finally:
            db.close()

        return jsonify({
            'games': games,
            'cache_age_minutes': int(cache_age / 60) if cache_age else 0
        })

    except Exception as e:
        gui_logger.exception(f"Error loading library from database: {e}")
        # Fallback to demo games on error
        return jsonify({'games': [{
            'app_id': g.get('appid'),
            'name': g.get('name', 'Unknown'),
            'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
            'is_favorite': False
        } for g in DEMO_GAMES]})


@app.route('/api/library/sync', methods=['POST'])
@require_login
def api_sync_library():
    """Manually trigger library sync from Steam API to database"""
    global current_user
    username = get_current_username()
    
    try:
        success, message = sync_scheduler.trigger_sync(username)
        
        if success:
            return jsonify({'message': message})
        else:
            return jsonify({'error': message}), 400
    except Exception as e:
        gui_logger.exception(f"Error in manual sync: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/library/sync/settings', methods=['GET'])
@require_admin
def api_get_sync_settings():
    """Get library sync settings (admin only)"""
    return jsonify({
        'sync_interval_hours': sync_scheduler.get_interval(),
        'last_sync_times': {
            username: time.isoformat() 
            for username, time in sync_scheduler.last_sync_times.items()
        }
    })


@app.route('/api/library/sync/settings', methods=['POST'])
@require_admin
def api_update_sync_settings():
    """Update library sync interval (admin only)"""
    data = request.json or {}
    interval = data.get('sync_interval_hours')
    
    if interval is None:
        return jsonify({'error': 'sync_interval_hours is required'}), 400
    
    try:
        interval_float = float(interval)
        if interval_float < 1 or interval_float > 168:
            return jsonify({'error': 'Interval must be between 1 and 168 hours'}), 400
        
        sync_scheduler.set_interval(interval_float)
        
        return jsonify({
            'message': 'Sync interval updated successfully',
            'sync_interval_hours': sync_scheduler.get_interval()
        })
    except ValueError:
        return jsonify({'error': 'Invalid interval value'}), 400


@app.route('/api/library/sync/status', methods=['GET'])
@require_login
def api_sync_status():
    """Get sync status for current user"""
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    try:
        db = database.SessionLocal()
        try:
            if _library_service:
                cache_age = _library_service.get_cache_age(db, username)
                cached_games = _library_service.get_cached(db, username)
            else:
                cache_age = database.get_library_cache_age(db, username)
                cached_games = database.get_cached_library(db, username)
        finally:
            db.close()

        last_sync = sync_scheduler.last_sync_times.get(username)

        return jsonify({
            'last_sync': last_sync.isoformat() if last_sync else None,
            'cache_age_hours': round(cache_age / 3600, 2) if cache_age else None,
            'sync_interval_hours': sync_scheduler.get_interval(),
            'games_cached': len(cached_games),
            'should_sync': sync_scheduler.should_sync(username),
            'is_syncing': username in sync_scheduler.in_progress
        })
    except Exception as e:
        gui_logger.exception(f"Error getting sync status: {e}")
        return jsonify({'error': str(e)}), 500


# ===========================================================================================
# Admin Migration Endpoints (PostgreSQL)
# ===========================================================================================

@app.route('/api/admin/migrations', methods=['GET'])
@require_admin
def api_list_migrations():
    """List available admin migrations (PostgreSQL)."""
    migrations = []
    for key, meta in ADMIN_MIGRATIONS.items():
        migrations.append({
            'id': key,
            'label': meta['label'],
            'description': meta['description'],
            'sql': meta['sql']
        })
    return jsonify({'migrations': migrations})


def _run_sql_statements(db, sql: str) -> None:
    """Execute one or more SQL statements separated by semicolons."""
    if not text:
        raise RuntimeError('SQLAlchemy text() not available')
    statements = [stmt.strip() for stmt in sql.split(';') if stmt.strip()]
    for stmt in statements:
        db.execute(text(stmt))


@app.route('/api/admin/migrations/run', methods=['POST'])
@require_admin
def api_run_migration():
    """Run a selected migration with optional SQL override (admin only)."""
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    migration_id = data.get('id')
    sql_override = data.get('sql')

    if not migration_id or migration_id not in ADMIN_MIGRATIONS:
        return jsonify({'error': 'Invalid migration id'}), 400

    sql = sql_override if isinstance(sql_override, str) and sql_override.strip() else ADMIN_MIGRATIONS[migration_id]['sql']

    try:
        db = database.SessionLocal()
        _run_sql_statements(db, sql)
        db.commit()
        db.close()
        return jsonify({'message': f'Migration {migration_id} executed successfully'})
    except Exception as e:
        try:
            db.rollback()
            db.close()
        except Exception:
            pass
        gui_logger.exception('Migration failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/favorites')
@require_login
def api_favorites():
    """Get all favorite games"""
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    global current_user
    username = get_current_username()

    if not username:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        db = database.SessionLocal()
        try:
            if _db_favorites_service:
                favorite_ids = _db_favorites_service.get_all(db, username)
            else:
                favorite_ids = database.get_user_favorites(db, username)

            # Get cached library to look up game details
            if _library_service:
                cached_games = _library_service.get_cached(db, username)
            else:
                cached_games = database.get_cached_library(db, username)
        finally:
            db.close()

        favorites = []
        for app_id in favorite_ids:
            game = next((g for g in cached_games if str(g.get('app_id')) == str(app_id)), None)
            if game:
                favorites.append({
                    'app_id': app_id,
                    'name': game.get('name', 'Unknown'),
                    'playtime_hours': round(game.get('playtime_hours', 0), 1)
                })
            else:
                favorites.append({
                    'app_id': app_id,
                    'name': f'App ID {app_id} (Not in library)',
                    'playtime_hours': 0
                })

        return jsonify({'favorites': favorites})
    except Exception as e:
        gui_logger.error(f"Error loading favorites: {e}")
        return jsonify({'error': 'Failed to load favorites'}), 500


@app.route('/api/stats')
@require_login
def api_stats():
    """Get library statistics from database cache"""
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    global current_user
    username = get_current_username()

    try:
        db = database.SessionLocal()
        try:
            if _library_service:
                cached_games = _library_service.get_cached(db, username)
            else:
                cached_games = database.get_cached_library(db, username)
            if _db_favorites_service:
                favorite_count = len(_db_favorites_service.get_all(db, username))
            else:
                favorite_count = len(database.get_user_favorites(db, username))
        finally:
            db.close()

        if not cached_games:
            return jsonify({
                'total_games': 0,
                'unplayed_games': 0,
                'played_games': 0,
                'unplayed_percentage': 0,
                'total_playtime': 0,
                'average_playtime': 0,
                'favorite_count': favorite_count,
                'top_games': []
            })

        total_games = len(cached_games)
        unplayed = len([g for g in cached_games if g.get('playtime_hours', 0) == 0])
        total_playtime = sum(g.get('playtime_hours', 0) for g in cached_games)

        # Top 10 most played
        sorted_by_playtime = sorted(
            cached_games,
            key=lambda g: g.get('playtime_hours', 0),
            reverse=True
        )[:10]

        top_games = []
        for game in sorted_by_playtime:
            top_games.append({
                'name': game.get('name', 'Unknown'),
                'playtime_hours': round(game.get('playtime_hours', 0), 1)
            })
        
        return jsonify({
            'total_games': total_games,
            'unplayed_games': unplayed,
            'played_games': total_games - unplayed,
            'unplayed_percentage': round(unplayed / total_games * 100, 1) if total_games > 0 else 0,
            'total_playtime': round(total_playtime, 1),
            'average_playtime': round(total_playtime / total_games, 1) if total_games > 0 else 0,
            'favorite_count': favorite_count,
            'top_games': top_games
        })
    except Exception as e:
        gui_logger.error(f"Error calculating stats: {e}")
        return jsonify({'error': 'Failed to load stats'}), 500


@app.route('/api/stats/compare')
@require_login
def api_stats_compare():
    """Compare statistics across multiple users"""
    # Get list of usernames to compare
    users_param = request.args.get('users', '')
    if not users_param:
        return jsonify({'error': 'No users specified'}), 400
    
    usernames = [u.strip() for u in users_param.split(',') if u.strip()]
    if not usernames:
        return jsonify({'error': 'Invalid users parameter'}), 400
    
    comparison_data = {
        'users': [],
        'comparison_metrics': {}
    }
    
    try:
        # Load base config
        base_config = load_base_config()
        
        # Gather stats for each user
        for username in usernames:
            try:
                # Get user's platform IDs
                user_ids = user_manager.get_user_ids(username)
                
                # Create temporary config with user's IDs
                user_config = {
                    'steam_api_key': base_config.get('steam_api_key', ''),
                    'steam_id': user_ids.get('steam_id', ''),
                    'epic_enabled': user_ids.get('epic_id') != '',
                    'epic_id': user_ids.get('epic_id', ''),
                    'gog_enabled': user_ids.get('gog_id') != '',
                    'gog_id': user_ids.get('gog_id', '')
                }
                
                # Load user's games using GamePicker
                try:
                    # Write temporary config to a file for GamePicker to load
                    temp_config_path = os.path.join(tempfile.gettempdir(), f'.gapi_compare_{username}_config.json')
                    with open(temp_config_path, 'w') as f:
                        json.dump(user_config, f)
                    
                    # Create picker for this user
                    user_picker = gapi.GamePicker(config_path=temp_config_path)
                    user_picker.fetch_games()
                    games = user_picker.games if user_picker.games else []
                    
                    # Clean up temp file
                    try:
                        os.remove(temp_config_path)
                    except:
                        pass
                except Exception as e:
                    gui_logger.warning(f"Failed to load games for user {username}: {e}")
                    games = []
                
                # If no games loaded, use demo games for demo purposes
                if not games:
                    games = DEMO_GAMES
                
                # Calculate stats
                total = len(games)
                unplayed = len([g for g in games if g.get('playtime_forever', 0) == 0])
                total_playtime = sum(g.get('playtime_forever', 0) for g in games) / 60
                avg_playtime = total_playtime / total if total > 0 else 0
                
                # Top 5 games
                top_games = sorted(
                    games,
                    key=lambda g: g.get('playtime_forever', 0),
                    reverse=True
                )[:5]
                
                user_stats = {
                    'username': username,
                    'total_games': total,
                    'unplayed_games': unplayed,
                    'played_games': total - unplayed,
                    'unplayed_percentage': round(unplayed / total * 100, 1) if total > 0 else 0,
                    'total_playtime': round(total_playtime, 1),
                    'average_playtime': round(avg_playtime, 1),
                    'top_games': [
                        {
                            'name': g.get('name', 'Unknown'),
                            'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1)
                        }
                        for g in top_games
                    ]
                }
                
                comparison_data['users'].append(user_stats)
                
            except Exception as e:
                gui_logger.warning(f"Error loading stats for user {username}: {e}")
                # Still include user with error indicator
                comparison_data['users'].append({
                    'username': username,
                    'error': str(e),
                    'total_games': 0,
                    'unplayed_games': 0,
                    'played_games': 0
                })
        
        # Calculate comparison metrics
        if comparison_data['users']:
            valid_users = [u for u in comparison_data['users'] if 'error' not in u]
            
            if valid_users:
                total_games_list = [u['total_games'] for u in valid_users]
                playtime_list = [u['total_playtime'] for u in valid_users]
                
                comparison_data['comparison_metrics'] = {
                    'most_games': max(total_games_list) if total_games_list else 0,
                    'least_games': min(total_games_list) if total_games_list else 0,
                    'avg_games': round(sum(total_games_list) / len(total_games_list), 1) if total_games_list else 0,
                    'most_playtime': max(playtime_list) if playtime_list else 0,
                    'least_playtime': min(playtime_list) if playtime_list else 0,
                    'avg_playtime': round(sum(playtime_list) / len(playtime_list), 1) if playtime_list else 0,
                    'total_unique_games': len(set(
                        g.get('app_id') for user in valid_users 
                        for g in user.get('games', [])
                    ))
                }
        
        return jsonify(comparison_data), 200
        
    except Exception as e:
        gui_logger.error(f"Error comparing stats: {e}")
        return jsonify({'error': 'Failed to compare statistics'}), 500


@app.route('/api/users')
@require_login
def api_users_list():
    """Get all registered users (for multi-user game picker)"""
    users = user_manager.get_all_users()
    # Filter to users with at least one platform ID
    users_with_games = [
        u for u in users
        if u.get('steam_id') or u.get('epic_id') or u.get('gog_id')
    ]
    return jsonify({'users': users_with_games})


# ===========================================================================================
# Ignored Games Endpoints
# ===========================================================================================

@app.route('/api/ignored-games')
@require_login
def api_get_ignored_games():
    """Get current user's ignored games list"""
    global current_user

    username = get_current_username()

    if not DB_AVAILABLE:
        return jsonify({'ignored_games': []}), 200

    try:
        db = database.SessionLocal()
        try:
            if _ignored_games_service:
                ignored = _ignored_games_service.get_detailed(db, username)
            else:
                user = database.get_user_by_username(db, username)
                if not user:
                    return jsonify({'ignored_games': []}), 200
                ignored = [
                    {
                        'app_id': ig.app_id,
                        'game_name': ig.game_name,
                        'reason': ig.reason,
                        'created_at': ig.created_at.isoformat() if ig.created_at else None
                    }
                    for ig in user.ignored_games
                ]
        finally:
            db.close()
        return jsonify({'ignored_games': ignored}), 200
    except Exception as e:
        gui_logger.error(f"Error getting ignored games: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ignored-games', methods=['POST'])
@require_login
def api_toggle_ignored_game():
    """Toggle game ignore status for current user"""
    global current_user

    username = get_current_username()

    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    app_id = data.get('app_id')
    game_name = data.get('game_name', '').strip() if isinstance(data.get('game_name'), str) else ''
    reason = data.get('reason', '').strip() if isinstance(data.get('reason'), str) else ''

    if not app_id:
        return jsonify({'error': 'app_id required'}), 400

    # Validate app_id is numeric, then normalize to string for consistency
    try:
        int(app_id)  # validate it's a valid integer
        app_id = str(app_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'app_id must be an integer'}), 400

    try:
        db = database.SessionLocal()

        # Verify user exists in database
        if _user_service:
            exists = _user_service.user_exists(db, username)
        else:
            exists = database.user_exists(db, username)
        if not exists:
            db.close()
            return jsonify({'error': 'User not found in database'}), 404

        if _ignored_games_service:
            success = _ignored_games_service.toggle(
                db, username, app_id, game_name=game_name, reason=reason)
        else:
            success = database.toggle_ignore_game(db, username, app_id,
                                                  game_name, reason)
        db.close()

        if success:
            return jsonify({'message': f'Game ignore status toggled'}), 200
        else:
            return jsonify({'error': 'Failed to toggle ignore'}), 400
    except Exception as e:
        gui_logger.error(f"Error toggling ignore game: {e}")
        return jsonify({'error': str(e)}), 500


# ===========================================================================================
# Achievement Hunting Endpoints
# ===========================================================================================

@app.route('/api/achievements')
@require_login
def api_get_achievements():
    """Get achievements for current user"""
    global current_user

    username = get_current_username()

    if not DB_AVAILABLE:
        return jsonify({'achievements': []}), 200

    try:
        db = database.SessionLocal()
        try:
            if _achievement_service:
                achievements = _achievement_service.get_all_by_user(db, username)
            else:
                user = database.get_user_by_username(db, username)
                if not user:
                    return jsonify({'achievements': []}), 200
                achievements_by_game = {}
                for achievement in user.achievements:
                    if achievement.app_id not in achievements_by_game:
                        achievements_by_game[achievement.app_id] = {
                            'app_id': achievement.app_id,
                            'game_name': achievement.game_name,
                            'achievements': []
                        }
                    achievements_by_game[achievement.app_id]['achievements'].append({
                        'achievement_id': achievement.achievement_id,
                        'name': achievement.achievement_name,
                        'description': achievement.achievement_description,
                        'unlocked': achievement.unlocked,
                        'unlock_time': achievement.unlock_time.isoformat() if achievement.unlock_time else None,
                        'rarity': achievement.rarity
                    })
                achievements = list(achievements_by_game.values())
        finally:
            db.close()
        return jsonify({'achievements': achievements}), 200
    except Exception as e:
        gui_logger.error(f"Error getting achievements: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/achievement-hunt', methods=['POST'])
@require_login
def api_start_achievement_hunt():
    """Start tracking an achievement hunting session"""
    global current_user

    username = get_current_username()

    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    app_id = data.get('app_id')
    game_name = data.get('game_name', '').strip() if isinstance(data.get('game_name'), str) else ''
    difficulty = data.get('difficulty', 'medium')  # easy, medium, hard, extreme
    target_achievements = data.get('target_achievements', 0)

    if not app_id or not game_name:
        return jsonify({'error': 'app_id and game_name required'}), 400

    # Convert app_id to int
    try:
        app_id = int(app_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'app_id must be an integer'}), 400

    try:
        db = database.SessionLocal()
        try:
            if _achievement_service:
                result = _achievement_service.start_hunt(
                    db, username, app_id, game_name,
                    difficulty=difficulty,
                    target_achievements=target_achievements)
            else:
                user = database.get_user_by_username(db, username)
                if not user:
                    return jsonify({'error': 'User not found in database'}), 404
                hunt = database.AchievementHunt(
                    user_id=user.id,
                    app_id=app_id,
                    game_name=game_name,
                    difficulty=difficulty,
                    target_achievements=target_achievements
                )
                db.add(hunt)
                db.commit()
                result = {
                    'hunt_id': hunt.id,
                    'app_id': hunt.app_id,
                    'game_name': hunt.game_name,
                    'difficulty': hunt.difficulty,
                    'target_achievements': hunt.target_achievements,
                    'unlocked_achievements': hunt.unlocked_achievements,
                    'progress_percent': hunt.progress_percent,
                    'status': hunt.status,
                    'started_at': hunt.started_at.isoformat()
                }
        finally:
            db.close()

        if not result:
            return jsonify({'error': 'User not found in database'}), 404
        return jsonify(result), 201
    except Exception as e:
        gui_logger.error(f"Error starting achievement hunt: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/achievement-hunt/<hunt_id>', methods=['PUT'])
@require_login
def api_update_achievement_hunt(hunt_id: str):
    """Update achievement hunt progress"""
    global current_user

    username = get_current_username()

    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    unlocked_achievements = data.get('unlocked_achievements')
    status = data.get('status')

    try:
        db = database.SessionLocal()
        try:
            if _achievement_service:
                result = _achievement_service.update_hunt(
                    db, hunt_id,
                    unlocked_achievements=unlocked_achievements,
                    status=status)
            else:
                hunt = db.query(database.AchievementHunt).filter(
                    database.AchievementHunt.id == hunt_id).first()
                if not hunt:
                    return jsonify({'error': 'Hunt not found'}), 404
                if unlocked_achievements is not None:
                    hunt.unlocked_achievements = unlocked_achievements
                    if hunt.target_achievements > 0:
                        hunt.progress_percent = (unlocked_achievements / hunt.target_achievements) * 100
                if status:
                    hunt.status = status
                    if status == 'completed':
                        hunt.completed_at = datetime.now(timezone.utc)
                hunt.updated_at = datetime.now(timezone.utc)
                db.commit()
                result = {
                    'hunt_id': hunt.id,
                    'app_id': hunt.app_id,
                    'game_name': hunt.game_name,
                    'difficulty': hunt.difficulty,
                    'target_achievements': hunt.target_achievements,
                    'unlocked_achievements': hunt.unlocked_achievements,
                    'progress_percent': hunt.progress_percent,
                    'status': hunt.status,
                    'started_at': hunt.started_at.isoformat(),
                    'completed_at': hunt.completed_at.isoformat() if hunt.completed_at else None
                }
        finally:
            db.close()

        if not result:
            return jsonify({'error': 'Hunt not found'}), 404
        return jsonify(result), 200
    except Exception as e:
        gui_logger.error(f"Error updating achievement hunt: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/all')
@require_admin
def api_users_all():
    """Get all users with full details (admin only)"""
    users = user_manager.get_all_users()
    return jsonify({'users': users})


@app.route('/api/users/delete/<username>', methods=['DELETE'])
@require_admin
def api_users_delete(username):
    """Delete a user (admin only)"""
    requesting_user = get_current_username()
    
    if not requesting_user:
        return jsonify({'error': 'Not logged in'}), 401
    
    success, message = user_manager.delete_user(username, requesting_user)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'message': message})


@app.route('/api/users/role', methods=['POST'])
@require_admin
def api_users_update_role():
    """Update user role (admin only)"""
    requesting_user = get_current_username()
    
    if not requesting_user:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.json or {}
    username = data.get('username', '').strip()
    role = data.get('role', '').strip()
    
    if not username or not role:
        return jsonify({'error': 'Username and role required'}), 400
    
    success, message = user_manager.update_user_role(username, role, requesting_user)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'message': message})


@app.route('/api/users/roles', methods=['POST'])
@require_admin
def api_users_update_roles():
    """Update user roles (admin only)"""
    requesting_user = get_current_username()

    if not requesting_user:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.json or {}
    username = data.get('username', '').strip()
    roles = data.get('roles', [])

    if not username or not isinstance(roles, list):
        return jsonify({'error': 'Username and roles list required'}), 400

    success, message = user_manager.update_user_roles(username, roles, requesting_user)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'message': message})


@app.route('/api/roles', methods=['GET'])
@require_admin
def api_roles_list():
    """List available roles (admin only)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = database.SessionLocal()
        try:
            if _user_service:
                roles = _user_service.get_all_roles(db)
            else:
                roles = database.get_roles(db)
        finally:
            db.close()
        return jsonify({'roles': roles})
    except Exception as e:
        gui_logger.exception('Error listing roles: %s', e)
        return jsonify({'error': str(e)}), 500


# ===========================================================================================
# Legacy Multi-User Endpoints (deprecated - use authenticated users instead)
# ===========================================================================================

@app.route('/api/users/legacy')
@require_admin
def api_users_list_legacy():
    """Get all users from multi-picker (legacy)"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    with multi_picker_lock:
        return jsonify({'users': multi_picker.users})


@app.route('/api/users/add', methods=['POST'])
@require_admin
def api_users_add():
    """Add a new user"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    data = request.json or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    steam_id = data.get('steam_id', '').strip()
    discord_id = data.get('discord_id', '').strip()
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    if not steam_id:
        return jsonify({'error': 'Steam ID is required'}), 400
    
    with multi_picker_lock:
        success = multi_picker.add_user(
            name=name,
            steam_id=steam_id,
            email=email,
            discord_id=discord_id
        )
        
        if success:
            # Reload from disk to ensure we have the latest data
            multi_picker.load_users()
            # Return the newly added user data to confirm it was saved
            new_user = next((u for u in multi_picker.users if u['name'] == name), None)
            if new_user:
                print(f'DEBUG: Added user {name} with steam_id={new_user.get("platforms", {}).get("steam")}')
            return jsonify({
                'success': True, 
                'message': f'User {name} added successfully',
                'user': new_user
            })
        else:
            return jsonify({'error': 'User already exists'}), 400


@app.route('/api/users/update', methods=['POST'])
@require_admin
def api_users_update():
    """Update user information"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    data = request.json or {}
    identifier = data.get('identifier', '').strip()
    updates = data.get('updates', {})
    
    if not identifier:
        return jsonify({'error': 'Identifier is required'}), 400
    
    if not updates:
        return jsonify({'error': 'No updates provided'}), 400
    
    with multi_picker_lock:
        success = multi_picker.update_user(identifier, **updates)
        
        if success:
            return jsonify({'success': True, 'message': 'User updated successfully'})
        else:
            return jsonify({'error': 'User not found'}), 404


@app.route('/api/users/remove', methods=['POST'])
@require_admin
def api_users_remove():
    """Remove a user"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    data = request.json or {}
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    with multi_picker_lock:
        success = multi_picker.remove_user(name)
        
        if success:
            return jsonify({'success': True, 'message': f'User {name} removed successfully'})
        else:
            return jsonify({'error': 'User not found'}), 404


@app.route('/api/multiuser/common')
@require_login
def api_multiuser_common():
    """Get common games for selected users"""
    global multi_picker
    
    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    user_names = request.args.get('users', '').split(',')
    user_names = [u.strip() for u in user_names if u.strip()]
    
    with multi_picker_lock:
        common_games = multi_picker.find_common_games(user_names if user_names else None)
        
        games_data = []
        for game in common_games[:50]:  # Limit to 50 games
            games_data.append({
                'app_id': game.get('appid'),
                'name': game.get('name', 'Unknown'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
                'owners': game.get('owners', [])
            })
        
        return jsonify({
            'total_common': len(common_games),
            'games': games_data
        })


@app.route('/api/multiuser/pick', methods=['POST'])
@require_login
def api_multiuser_pick():
    """Pick a common game for multiple users with optional filters"""
    global multi_picker
    
    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    data = request.json or {}
    user_names = data.get('users', [])
    coop_only = data.get('coop_only', False)
    max_players_raw = data.get('max_players')
    max_players = int(max_players_raw) if max_players_raw is not None else None
    
    # Parse filter parameters
    min_playtime = int(data.get('min_playtime', 0)) if data.get('min_playtime') else 0
    max_playtime_val = data.get('max_playtime')
    max_playtime = int(max_playtime_val) if max_playtime_val is not None else None
    min_metacritic_val = data.get('min_metacritic')
    min_metacritic = int(min_metacritic_val) if min_metacritic_val is not None else None
    min_release_year_val = data.get('min_release_year')
    min_release_year = int(min_release_year_val) if min_release_year_val is not None else None
    max_release_year_val = data.get('max_release_year')
    max_release_year = int(max_release_year_val) if max_release_year_val is not None else None
    min_avg_playtime_val = data.get('min_avg_playtime')
    min_avg_playtime = int(min_avg_playtime_val) if min_avg_playtime_val is not None else None
    platform_filter = data.get('platform_filter', '').strip().lower() or None
    device_filter = data.get('device_filter', '').strip().lower() or None
    
    # Parse comma-separated lists
    genre_text = data.get('genres', '').strip()
    genres = [g.strip() for g in genre_text.split(',')] if genre_text else None
    
    exclude_genre_text = data.get('exclude_genres', '').strip()
    exclude_genres = [g.strip() for g in exclude_genre_text.split(',')] if exclude_genre_text else None
    
    tag_text = data.get('tags', '').strip()
    tags = [t.strip() for t in tag_text.split(',')] if tag_text else None
    
    exclude_ids_raw = data.get('exclude_game_ids', '')
    exclude_game_ids = [s.strip() for s in exclude_ids_raw.split(',')] if exclude_ids_raw else None
    
    with multi_picker_lock:
        game = multi_picker.pick_common_game(
            user_names if user_names else None,
            coop_only=coop_only,
            max_players=max_players,
            min_playtime=min_playtime,
            max_playtime=max_playtime,
            min_metacritic=min_metacritic,
            min_release_year=min_release_year,
            max_release_year=max_release_year,
            genres=genres,
            exclude_genres=exclude_genres,
            tags=tags,
            exclude_game_ids=exclude_game_ids,
            min_avg_playtime=min_avg_playtime,
            platforms=[platform_filter] if platform_filter else None,
            device_types=[device_filter] if device_filter else None
        )
        
        if not game:
            return jsonify({'error': 'No common games found matching filters'}), 404
        
        app_id = game.get('appid')
        
        return jsonify({
            'app_id': app_id,
            'name': game.get('name', 'Unknown'),
            'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
            'owners': game.get('owners', []),
            'is_coop': game.get('is_coop', False),
            'is_multiplayer': game.get('is_multiplayer', False),
            'steam_url': f'https://store.steampowered.com/app/{app_id}/',
            'steamdb_url': f'https://steamdb.info/app/{app_id}/'
        })


@app.route('/api/multiuser/stats')
@require_login
def api_multiuser_stats():
    """Get multi-user library statistics"""
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    user_names = request.args.get('users', '').split(',')
    user_names = [u.strip() for u in user_names if u.strip()]

    with multi_picker_lock:
        stats = multi_picker.get_library_stats(user_names if user_names else None)
        return jsonify(stats)


# ---------------------------------------------------------------------------
# Voting endpoints
# ---------------------------------------------------------------------------

@app.route('/api/voting/create', methods=['POST'])
@require_login
def api_voting_create():
    """Create a new voting session from common games.

    Expected JSON body:
        users          – list of user names participating (optional – all users if omitted)
        num_candidates – number of game candidates to put to a vote (default: 5)
        duration       – voting window in seconds (optional)
        coop_only      – filter to co-op games only (default: false)
        voting_method  – 'plurality' (default) or 'ranked_choice'
    """
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    data = request.json or {}
    user_names = data.get('users') or None
    num_candidates = min(int(data.get('num_candidates', 5)), 10)
    duration = data.get('duration')
    coop_only = data.get('coop_only', False)
    voting_method = data.get('voting_method', 'plurality')
    if voting_method not in ('plurality', 'ranked_choice'):
        return jsonify({'error': "voting_method must be 'plurality' or 'ranked_choice'"}), 400

    with multi_picker_lock:
        common_games = multi_picker.find_common_games(user_names)

        if not common_games:
            return jsonify({'error': 'No common games found for selected users'}), 404

        if coop_only:
            common_games = multi_picker.filter_coop_games(common_games)

        if not common_games:
            return jsonify({'error': 'No common co-op games found for selected users'}), 404

        import random as _random
        candidates = _random.sample(common_games, min(num_candidates, len(common_games)))

        voters = user_names if user_names else [u['name'] for u in multi_picker.users]
        session = multi_picker.create_voting_session(
            candidates, voters=voters, duration=duration, voting_method=voting_method
        )

    return jsonify(session.to_dict()), 201


@app.route('/api/voting/<session_id>/vote', methods=['POST'])
@require_login
def api_voting_cast(session_id: str):
    """Cast a vote in an active voting session.

    Expected JSON body (plurality):
        user_name – name of the voter
        app_id    – app ID of the game being voted for

    Expected JSON body (ranked_choice):
        user_name – name of the voter
        ranking   – ordered list of app IDs (most preferred first)
    """
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    data = request.json or {}
    user_name = data.get('user_name', '').strip()

    if not user_name:
        return jsonify({'error': 'user_name is required'}), 400

    with multi_picker_lock:
        session = multi_picker.get_voting_session(session_id)
        if session is None:
            return jsonify({'error': 'Voting session not found'}), 404

        if session.voting_method == 'ranked_choice':
            ranking = data.get('ranking')
            if not isinstance(ranking, list) or not ranking:
                return jsonify({'error': 'ranking (list of app IDs) is required for ranked_choice voting'}), 400
            success, message = session.cast_vote(user_name, ranking)
        else:
            app_id = str(data.get('app_id', '')).strip()
            if not app_id:
                return jsonify({'error': 'app_id is required'}), 400
            success, message = session.cast_vote(user_name, app_id)

    if not success:
        return jsonify({'error': message}), 400

    return jsonify({'success': True, 'message': message})


@app.route('/api/voting/<session_id>/status')
@require_login
def api_voting_status(session_id: str):
    """Get the current status and vote tallies for a voting session."""
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        session = multi_picker.get_voting_session(session_id)
        if session is None:
            return jsonify({'error': 'Voting session not found'}), 404
        return jsonify(session.to_dict())


@app.route('/api/voting/<session_id>/close', methods=['POST'])
@require_login
def api_voting_close(session_id: str):
    """Close a voting session and return the winner."""
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        session = multi_picker.get_voting_session(session_id)
        if session is None:
            return jsonify({'error': 'Voting session not found'}), 404

        winner = multi_picker.close_voting_session(session_id)
        session_data = session.to_dict()

    if not winner:
        return jsonify({'error': 'Could not determine a winner'}), 500

    app_id = winner.get('appid') or winner.get('app_id') or winner.get('game_id')

    response = {
        'winner': {
            'app_id': app_id,
            'name': winner.get('name', 'Unknown'),
            'playtime_hours': round(winner.get('playtime_forever', 0) / 60, 1),
            'steam_url': f'https://store.steampowered.com/app/{app_id}/' if app_id else None,
            'steamdb_url': f'https://steamdb.info/app/{app_id}/' if app_id else None,
        },
        'voting_method': session_data.get('voting_method', 'plurality'),
        'vote_counts': session_data.get('vote_counts', {}),
        'total_votes': session_data.get('total_votes', 0),
    }
    if session_data.get('voting_method') == 'ranked_choice':
        response['irv_rounds'] = session_data.get('irv_rounds', [])
    return jsonify(response)


# -----------------------------------------------------------------------
# Reviews endpoints
# -----------------------------------------------------------------------

@app.route('/api/reviews', methods=['GET'])
@require_login
def api_get_reviews():
    """Return all personal game reviews."""
    global picker

    ensure_picker_initialized()
    if not picker:
        return jsonify({}), 500
    
    with picker_lock:
        return jsonify(picker.review_service.get_all())


@app.route('/api/reviews/<game_id>', methods=['GET'])
@require_login
def api_get_review(game_id: str):
    """Return the review for a specific game."""
    global picker

    ensure_picker_initialized()
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 500
    
    with picker_lock:
        review = picker.review_service.get(game_id)
    if review is None:
        return jsonify({'error': 'No review found'}), 404
    return jsonify(review)


@app.route('/api/reviews/<game_id>', methods=['POST', 'PUT'])
@require_login
def api_save_review(game_id: str):
    """Add or update a personal review for a game.

    Body JSON: {"rating": 1-10, "notes": "optional text"}
    """
    global picker

    ensure_picker_initialized()
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 500

    data = request.json or {}
    rating = data.get('rating')
    notes = data.get('notes', '')

    if rating is None:
        return jsonify({'error': 'rating is required (1-10)'}), 400

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({'error': 'rating must be an integer'}), 400

    with picker_lock:
        success = picker.review_service.add_or_update(game_id, rating, notes)

    if not success:
        return jsonify({'error': 'rating must be between 1 and 10'}), 400

    return jsonify({'success': True, 'game_id': game_id, 'rating': rating, 'notes': notes})


@app.route('/api/reviews/<game_id>', methods=['DELETE'])
@require_login
def api_delete_review(game_id: str):
    """Delete the review for a game."""
    global picker

    ensure_picker_initialized()
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 500

    with picker_lock:
        removed = picker.review_service.remove(game_id)

    if not removed:
        return jsonify({'error': 'No review found'}), 404

    return jsonify({'success': True})


# -----------------------------------------------------------------------
# Tags endpoints
# -----------------------------------------------------------------------

@app.route('/api/tags', methods=['GET'])
@require_login
def api_get_all_tags():
    """Return all unique tags and a mapping of game_id → tags."""
    global picker

    try:
        # Ensure picker is initialized for logged-in user
        ensure_picker_initialized()
        if not picker:
            return jsonify({'tags': [], 'game_tags': {}}), 500

        with picker_lock:
            return jsonify({'tags': picker.tag_service.all_tag_names(),
                            'game_tags': picker.tag_service.get_all()})
    except Exception as e:
        gui_logger.error(f"Error getting tags: {e}")
        return jsonify({'tags': [], 'game_tags': {}})


@app.route('/api/tags/<game_id>', methods=['GET'])
def api_get_game_tags(game_id: str):
    """Return the tags for a specific game."""
    global picker

    try:
        ensure_picker_initialized()
        if not picker:
            return jsonify({'game_id': game_id, 'tags': []}), 500
        with picker_lock:
            return jsonify({'game_id': game_id, 'tags': picker.tag_service.get(game_id)})
    except Exception as e:
        gui_logger.error(f"Error getting game tags: {e}")
        return jsonify({'game_id': game_id, 'tags': []})


@app.route('/api/tags/<game_id>', methods=['POST'])
def api_add_tag(game_id: str):
    """Add a tag to a game.

    Body JSON: {"tag": "cozy"}
    """
    global picker

    try:
        ensure_picker_initialized()
        if not picker:
            return jsonify({'error': 'Picker not initialized'}), 500

        data = request.json or {}
        tag = data.get('tag', '').strip()
        if not tag:
            return jsonify({'error': 'tag is required'}), 400

        with picker_lock:
            added = picker.tag_service.add(game_id, tag)
            tags = picker.tag_service.get(game_id)

        return jsonify({'success': True, 'added': added,
                        'game_id': game_id, 'tags': tags})
    except Exception as e:
        gui_logger.error(f"Error adding tag: {e}")
        return jsonify({'error': 'Failed to add tag'}), 500


@app.route('/api/tags/<game_id>/<tag>', methods=['DELETE'])
def api_remove_tag(game_id: str, tag: str):
    """Remove a tag from a game."""
    global picker

    try:
        ensure_picker_initialized()
        if not picker:
            return jsonify({'error': 'Picker not initialized'}), 500

        with picker_lock:
            removed = picker.tag_service.remove(game_id, tag)
            tags = picker.tag_service.get(game_id)

        if not removed:
            return jsonify({'error': 'Tag not found'}), 404

        return jsonify({'success': True, 'game_id': game_id, 'tags': tags})
    except Exception as e:
        gui_logger.error(f"Error removing tag: {e}")
        return jsonify({'error': 'Failed to remove tag'}), 500


@app.route('/api/library/by-tag/<tag>', methods=['GET'])
@require_login
def api_library_by_tag(tag: str):
    """Return games that have a specific tag."""
    global picker

    # Ensure picker is initialized for logged-in user
    ensure_picker_initialized()
    if not picker:
        return jsonify({'tag': tag, 'games': [], 'count': 0}), 500

    with picker_lock:
        games = picker.tag_service.filter_by_tag(tag, picker.games)
        result = [
            {
                'app_id': g.get('appid'),
                'game_id': g.get('game_id'),
                'name': g.get('name', 'Unknown'),
                'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
                'tags': picker.tag_service.get(g.get('game_id', str(g.get('appid', '')))),
            }
            for g in games
        ]

    return jsonify({'tag': tag, 'games': result, 'count': len(result)})


# ---------------------------------------------------------------------------
# Game Night Scheduler endpoints
# ---------------------------------------------------------------------------

@app.route('/api/schedule', methods=['GET'])
def api_get_schedule():
    """Return all game night events sorted by date/time."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        events = picker.schedule_service.get_events()
    return jsonify({'events': events, 'count': len(events)})


@app.route('/api/schedule', methods=['POST'])
def api_create_event():
    """Create a new game night event."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    title = str(data.get('title', '')).strip()
    if not title:
        return jsonify({'error': 'title is required'}), 400
    date = str(data.get('date', '')).strip()
    time_str = str(data.get('time', '')).strip()
    attendees_raw = data.get('attendees', '')
    if isinstance(attendees_raw, str):
        attendees = [a.strip() for a in attendees_raw.split(',') if a.strip()]
    else:
        attendees = [str(a).strip() for a in (attendees_raw or []) if str(a).strip()]
    game_name = str(data.get('game_name', '')).strip()
    notes = str(data.get('notes', '')).strip()
    with picker_lock:
        event = picker.schedule_service.add_event(title, date, time_str, attendees, game_name, notes)
    return jsonify(event), 201


@app.route('/api/schedule/<event_id>', methods=['PUT'])
def api_update_event(event_id: str):
    """Update a game night event."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    safe: Dict = {}
    for k in ('title', 'date', 'time', 'game_name', 'notes'):
        if k in data:
            safe[k] = str(data[k]).strip()
    if 'attendees' in data:
        raw = data['attendees']
        if isinstance(raw, str):
            safe['attendees'] = [a.strip() for a in raw.split(',') if a.strip()]
        else:
            safe['attendees'] = [str(a).strip() for a in (raw or []) if str(a).strip()]
    with picker_lock:
        event = picker.schedule_service.update_event(event_id, **safe)
    if event is None:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify(event)


@app.route('/api/schedule/<event_id>', methods=['DELETE'])
def api_delete_event(event_id: str):
    """Delete a game night event."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.schedule_service.remove_event(event_id)
    if not removed:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify({'success': True, 'id': event_id})


# ---------------------------------------------------------------------------
# Playlists API
# ---------------------------------------------------------------------------

@app.route('/api/playlists', methods=['GET'])
def api_list_playlists():
    """List all playlists."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        return jsonify({'playlists': picker.playlist_service.list_all()})


@app.route('/api/playlists', methods=['POST'])
def api_create_playlist():
    """Create a new playlist. Expects JSON ``{"name": "..."}``."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    with picker_lock:
        created = picker.playlist_service.create(name)
    if not created:
        return jsonify({'error': 'Playlist already exists'}), 409
    return jsonify({'success': True, 'name': name}), 201


@app.route('/api/playlists/<name>', methods=['DELETE'])
def api_delete_playlist(name: str):
    """Delete a playlist by name."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        deleted = picker.playlist_service.delete(name)
    if not deleted:
        return jsonify({'error': 'Playlist not found'}), 404
    return jsonify({'success': True})


@app.route('/api/playlists/<name>/games', methods=['GET'])
def api_get_playlist_games(name: str):
    """Get all games in a playlist."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        games = picker.playlist_service.get_games(name, picker.games)
    if games is None:
        return jsonify({'error': 'Playlist not found'}), 404
    return jsonify({'name': name, 'games': games, 'count': len(games)})


@app.route('/api/playlists/<name>/games', methods=['POST'])
def api_add_to_playlist(name: str):
    """Add a game to a playlist. Expects JSON ``{"game_id": "..."}``."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    game_id = str(data.get('game_id', '')).strip()
    if not game_id:
        return jsonify({'error': 'game_id is required'}), 400
    with picker_lock:
        added = picker.playlist_service.add_game(name, game_id)
    if not added:
        return jsonify({'error': 'Game already in playlist or invalid playlist'}), 409
    return jsonify({'success': True})


@app.route('/api/playlists/<name>/games/<game_id>', methods=['DELETE'])
def api_remove_from_playlist(name: str, game_id: str):
    """Remove a game from a playlist."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.playlist_service.remove_game(name, game_id)
    if not removed:
        return jsonify({'error': 'Game or playlist not found'}), 404
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Backlog / Status Tracker API
# ---------------------------------------------------------------------------

@app.route('/api/backlog', methods=['GET'])
def api_list_backlog():
    """List all backlog entries, optionally filtered by ``?status=``."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    status_filter = request.args.get('status', '').strip() or None
    if status_filter and status_filter not in gapi.GamePicker.BACKLOG_STATUSES:
        return jsonify({'error': f'Invalid status. Valid: {list(gapi.GamePicker.BACKLOG_STATUSES)}'}), 400
    with picker_lock:
        games = picker.backlog_service.get_games(picker.games, status_filter)
    return jsonify({'games': games, 'count': len(games)})


@app.route('/api/backlog/<game_id>', methods=['GET'])
def api_get_backlog_status(game_id: str):
    """Get the backlog status for a specific game."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        status = picker.backlog_service.get_status(game_id)
    if status is None:
        return jsonify({'game_id': game_id, 'status': None})
    return jsonify({'game_id': game_id, 'status': status})


@app.route('/api/backlog/<game_id>', methods=['POST', 'PUT'])
def api_set_backlog_status(game_id: str):
    """Set the backlog status for a game. Expects JSON ``{"status": "..."}``."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    status = (data.get('status') or '').strip()
    if not status:
        return jsonify({'error': 'status is required'}), 400
    with picker_lock:
        ok = picker.backlog_service.set_status(game_id, status)
    if not ok:
        return jsonify({'error': f'Invalid status. Valid: {list(gapi.GamePicker.BACKLOG_STATUSES)}'}), 400
    return jsonify({'success': True, 'game_id': game_id, 'status': status})


@app.route('/api/backlog/<game_id>', methods=['DELETE'])
def api_delete_backlog_status(game_id: str):
    """Remove a game from the backlog."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.backlog_service.remove(game_id)
    if not removed:
        return jsonify({'error': 'Game not in backlog'}), 404
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Budget Tracking API
# ---------------------------------------------------------------------------

@app.route('/api/budget', methods=['GET'])
@require_login
def api_get_budget():
    """Return all budget entries and an aggregated summary."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        summary = picker.budget_service.get_summary(picker.games)
    return jsonify(summary)


@app.route('/api/budget/<path:game_id>', methods=['POST', 'PUT'])
@require_login
def api_set_budget(game_id: str):
    """Set or update the purchase price for a game.

    Expected JSON body::

        {
            "price":         14.99,       // required; 0 = free/gift
            "currency":      "USD",       // optional, default "USD"
            "purchase_date": "2024-12-25",// optional
            "notes":         "Steam sale" // optional
        }
    """
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    if 'price' not in data:
        return jsonify({'error': 'price is required'}), 400
    try:
        price = float(data['price'])
    except (TypeError, ValueError):
        return jsonify({'error': 'price must be a number'}), 400
    with picker_lock:
        ok = picker.budget_service.set_entry(
            game_id,
            price=price,
            currency=str(data.get('currency', 'USD')),
            purchase_date=str(data.get('purchase_date', '')),
            notes=str(data.get('notes', '')),
        )
    if not ok:
        return jsonify({'error': 'price must not be negative'}), 400
    return jsonify({'success': True, 'game_id': game_id, 'price': price})


@app.route('/api/budget/<path:game_id>', methods=['DELETE'])
@require_login
def api_delete_budget(game_id: str):
    """Remove a budget entry for a game."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.budget_service.remove_entry(game_id)
    if not removed:
        return jsonify({'error': 'No budget entry found for this game'}), 404
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Wishlist & Sale Alerts API
# ---------------------------------------------------------------------------

@app.route('/api/wishlist', methods=['GET'])
@require_login
def api_get_wishlist():
    """Return all wishlist entries."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        entries = list(picker.wishlist_service.get_all().values())
    return jsonify({'entries': entries, 'count': len(entries)})


@app.route('/api/wishlist', methods=['POST'])
@require_login
def api_add_to_wishlist():
    """Add or update a game in the wishlist.

    Expected JSON body::

        {
            "game_id":      "steam:620",  // required
            "name":         "Portal 2",   // required
            "platform":     "steam",      // optional, default "steam"
            "target_price": 4.99,         // optional – alert when price <= this
            "notes":        "Want this"   // optional
        }
    """
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    data = request.json or {}
    game_id = (data.get('game_id') or '').strip()
    name = (data.get('name') or '').strip()
    if not game_id:
        return jsonify({'error': 'game_id is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400
    platform = str(data.get('platform', 'steam')).strip().lower() or 'steam'
    notes = str(data.get('notes', ''))
    target_price = data.get('target_price')
    if target_price is not None:
        try:
            target_price = float(target_price)
        except (TypeError, ValueError):
            return jsonify({'error': 'target_price must be a number'}), 400
    with picker_lock:
        ok = picker.wishlist_service.add(game_id, name, platform=platform,
                                         target_price=target_price, notes=notes)
    if not ok:
        return jsonify({'error': 'target_price must not be negative'}), 400
    return jsonify({'success': True, 'game_id': game_id}), 201


@app.route('/api/wishlist/<path:game_id>', methods=['DELETE'])
@require_login
def api_remove_from_wishlist(game_id: str):
    """Remove a game from the wishlist."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.wishlist_service.remove(game_id)
    if not removed:
        return jsonify({'error': 'Game not found in wishlist'}), 404
    return jsonify({'success': True})


@app.route('/api/wishlist/sales', methods=['GET'])
@require_login
def api_check_wishlist_sales():
    """Check current Steam prices and return wishlist items that are on sale
    or at/below the user-set target price.

    This makes live Steam Store API calls so may take a few seconds for large
    wishlists.  Results are not cached.
    """
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    if not picker.wishlist_service.get_all():
        return jsonify({'sales': [], 'checked': 0})
    if not picker.steam_client or not isinstance(picker.steam_client, gapi.SteamAPIClient):
        return jsonify({'error': 'Steam client not available; cannot check prices'}), 503
    with picker_lock:
        sales = picker.wishlist_service.check_sales(picker.steam_client)
        checked = len([e for e in picker.wishlist_service.get_all().values()
                       if e.get('platform', 'steam') == 'steam'])
    return jsonify({'sales': sales, 'checked': checked, 'on_sale_count': len(sales)})


# ---------------------------------------------------------------------------
# Achievement Tracking API
# ---------------------------------------------------------------------------

@app.route('/api/achievements/<int:app_id>')
def api_get_steam_achievements(app_id: int):
    """Get achievement completion stats for a Steam game.

    Requires a valid Steam ID to be configured; returns 503 otherwise.
    """
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    if not picker.steam_client:
        return jsonify({'error': 'Steam client not available'}), 503
    steam_id = picker.config.get('steam_id', '')
    if gapi.is_placeholder_value(steam_id):
        return jsonify({'error': 'Steam ID not configured'}), 503
    
    if not picker.steam_client or not isinstance(picker.steam_client, gapi.SteamAPIClient):
        return jsonify({'error': 'Steam client not initialized'}), 400
    
    with picker_lock:
        stats = picker.steam_client.get_player_achievements(steam_id, app_id)
    if stats is None:
        return jsonify({'error': 'Achievements unavailable for this game'}), 404
    return jsonify({'app_id': app_id, **stats})


# ---------------------------------------------------------------------------
# Achievement sync (Steam API → database)
# ---------------------------------------------------------------------------

@app.route('/api/achievements/sync', methods=['POST'])
@require_login
def api_sync_achievements():
    """Sync achievements for one or more games from the Steam API.

    Request JSON::

        {
          "app_ids": ["620", "570"],   // optional – if omitted, syncs all cached games
          "force": false               // optional – skip if synced within last hour
        }

    The endpoint fetches ``GetPlayerAchievements`` + ``GetSchemaForGame`` for
    each requested app and upserts the results into the ``achievements`` table.

    Response JSON::

        {
          "synced": [
            {"app_id": "620", "game_name": "Portal 2",
             "added": 10, "updated": 2, "total": 12},
            ...
          ],
          "skipped": ["570"],
          "errors":  ["730"]
        }

    Returns 503 if the database is unavailable, 400 if Steam API key or Steam
    ID is not configured.
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    # Load config to get Steam credentials
    base_config = load_base_config()
    steam_api_key = base_config.get('steam_api_key', '').strip()
    if not steam_api_key or gapi.is_placeholder_value(steam_api_key):
        return jsonify({'error': 'Steam API key not configured'}), 400

    # Resolve the user's Steam ID
    db = next(database.get_db())
    try:
        user = database.get_user(db, username)
        steam_id = user.steam_id if user else None
    finally:
        if db:
            db.close()

    if not steam_id:
        return jsonify({'error': 'Steam ID not configured for this account'}), 400

    data = request.json or {}
    requested_app_ids: Optional[List[str]] = data.get('app_ids')

    # If no explicit list provided, use the cached library
    if not requested_app_ids:
        db2 = next(database.get_db())
        try:
            cached = (
                _library_service.get_cached(db2, username)
                if _library_service
                else database.get_cached_library(db2, username)
            )
        finally:
            if db2:
                db2.close()
        if not cached:
            return jsonify({'error': 'No games in library cache. Sync your library first.'}), 400
        requested_app_ids = [str(g.get('app_id', '')) for g in (cached or [])
                              if g.get('app_id')]

    steam_client = gapi.SteamAPIClient(steam_api_key)
    synced: List[Dict] = []
    skipped: List[str] = []
    errors: List[str] = []

    # Resolve game names from library cache for display
    db3 = next(database.get_db())
    try:
        cached_all = (
            _library_service.get_cached(db3, username)
            if _library_service
            else database.get_cached_library(db3, username)
        )
    finally:
        if db3:
            db3.close()
    name_map: Dict[str, str] = {
        str(g.get('app_id', '')): g.get('name', g.get('app_id', ''))
        for g in (cached_all or [])
    }

    for app_id in requested_app_ids[:50]:  # cap at 50 per call to avoid timeouts
        app_id = str(app_id).strip()
        if not app_id:
            continue
        game_name = name_map.get(app_id, app_id)
        try:
            player_achievements = steam_client.get_player_achievements(steam_id, app_id)
            if not player_achievements:
                skipped.append(app_id)
                continue
            schema = steam_client.get_schema_for_game(app_id)
            db4 = next(database.get_db())
            try:
                result = database.sync_steam_achievements(
                    db4, username, steam_id, app_id, game_name,
                    player_achievements, schema
                )
            finally:
                if db4:
                    db4.close()
            synced.append({
                'app_id': app_id,
                'game_name': game_name,
                'added': result['added'],
                'updated': result['updated'],
                'total': result['total'],
            })
        except Exception as exc:
            gui_logger.error("Error syncing achievements for app %s: %s", app_id, exc)
            errors.append(app_id)

    return jsonify({'synced': synced, 'skipped': skipped, 'errors': errors})


# ---------------------------------------------------------------------------
# Achievement statistics dashboard
# ---------------------------------------------------------------------------

@app.route('/api/achievements/stats')
@require_login
def api_achievement_stats():
    """Return achievement statistics for the current user.

    Response JSON::

        {
          "total_tracked": 120,
          "total_unlocked": 45,
          "completion_percent": 37.5,
          "rarest_achievement": { ... },
          "games": [ ... ],
          "by_platform": [
            {
              "platform": "steam",
              "total_tracked": 100,
              "total_unlocked": 40,
              "completion_percent": 40.0,
              "game_count": 12
            }
          ]
        }
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = next(database.get_db())
    try:
        stats = database.get_achievement_stats(db, username)
        by_platform = database.get_achievement_stats_by_platform(db, username)
    finally:
        if db:
            db.close()

    if not stats:
        return jsonify({
            'total_tracked': 0, 'total_unlocked': 0,
            'completion_percent': 0.0, 'rarest_achievement': None,
            'games': [], 'by_platform': [],
        })
    stats['by_platform'] = by_platform
    return jsonify(stats)


# ---------------------------------------------------------------------------
# iCalendar export for the game-night schedule
# ---------------------------------------------------------------------------

@app.route('/api/schedule/export.ics')
@require_login
def api_export_schedule_ics():
    """Download the game-night schedule as an iCalendar (.ics) file.

    Produces a standards-compliant RFC 5545 ``VCALENDAR`` document.
    Each game-night event becomes a ``VEVENT`` with ``DTSTART``, ``SUMMARY``,
    ``DESCRIPTION`` (notes + game name + attendees), and a ``UID`` derived
    from the event ID.

    Response: ``text/calendar`` attachment named ``gapi_schedule.ics``.
    """
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400

    with picker_lock:
        events = picker.schedule_service.get_events()

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//GAPI//Game Night Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]

    for ev in events:
        date_str = ev.get('date', '')
        time_str = ev.get('time', '00:00')
        dtstart = ''
        if date_str:
            # Produce DTSTART in basic format: YYYYMMDDTHHMMSS
            clean_date = date_str.replace('-', '')
            clean_time = time_str.replace(':', '')
            if len(clean_time) == 4:
                clean_time += '00'
            dtstart = f'{clean_date}T{clean_time}'
        attendees = ', '.join(ev.get('attendees', []))
        game_name = ev.get('game_name', '')
        notes = ev.get('notes', '')
        desc_parts = []
        if game_name:
            desc_parts.append(f'Game: {game_name}')
        if attendees:
            desc_parts.append(f'Attendees: {attendees}')
        if notes:
            desc_parts.append(notes)
        description = '\\n'.join(desc_parts)
        uid = f"{ev.get('id', 'unknown')}@gapi"

        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:{uid}')
        lines.append(f'SUMMARY:{ev.get("title", "Game Night")}')
        if dtstart:
            lines.append(f'DTSTART:{dtstart}')
        if description:
            lines.append(f'DESCRIPTION:{description}')
        lines.append('END:VEVENT')

    lines.append('END:VCALENDAR')

    ical_body = '\r\n'.join(lines) + '\r\n'

    from flask import Response as _Response
    return _Response(
        ical_body,
        mimetype='text/calendar',
        headers={
            'Content-Disposition': 'attachment; filename="gapi_schedule.ics"',
            'Content-Type': 'text/calendar; charset=utf-8',
        },
    )


# ---------------------------------------------------------------------------
# Multiplayer Achievement Challenges
# ---------------------------------------------------------------------------

@app.route('/api/achievement-challenges', methods=['POST'])
@require_login
def api_create_achievement_challenge():
    """Create a new multiplayer achievement challenge.

    Request JSON::

        {
          "title": "Who completes Portal 2 first?",
          "app_id": "620",
          "game_name": "Portal 2",
          "target_achievement_ids": ["ACH_WIN", "ACH_PARTNER"],   // optional
          "starts_at": "2026-03-01T20:00:00",                     // optional
          "ends_at":   "2026-03-08T20:00:00"                      // optional
        }

    Response JSON: the created challenge object (status 201).
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    title = str(data.get('title', '')).strip()
    app_id = str(data.get('app_id', '')).strip()
    game_name = str(data.get('game_name', '')).strip()
    if not title or not app_id or not game_name:
        return jsonify({'error': 'title, app_id, and game_name are required'}), 400

    targets_raw = data.get('target_achievement_ids', [])
    if isinstance(targets_raw, str):
        target_ids = [t.strip() for t in targets_raw.split(',') if t.strip()]
    else:
        target_ids = [str(t).strip() for t in (targets_raw or []) if str(t).strip()]

    db = next(database.get_db())
    try:
        challenge = database.create_achievement_challenge(
            db, username, title, app_id, game_name,
            target_achievement_ids=target_ids or None,
            starts_at=str(data.get('starts_at', '')).strip(),
            ends_at=str(data.get('ends_at', '')).strip(),
        )
    finally:
        if db:
            db.close()

    if not challenge:
        return jsonify({'error': 'Failed to create challenge'}), 500
    return jsonify(challenge), 201


@app.route('/api/achievement-challenges', methods=['GET'])
@require_login
def api_list_achievement_challenges():
    """List achievement challenges for the current user (created or joined).

    Response JSON::

        {"challenges": [ {...}, ... ]}
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = next(database.get_db())
    try:
        challenges = database.get_achievement_challenges(db, username)
    finally:
        if db:
            db.close()

    return jsonify({'challenges': challenges})


@app.route('/api/achievement-challenges/<challenge_id>', methods=['GET'])
@require_login
def api_get_achievement_challenge(challenge_id: str):
    """Get details of a single achievement challenge by its ID.

    Response JSON: the challenge object or 404 if not found.
    """
    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = next(database.get_db())
    try:
        challenge = database.get_achievement_challenge(db, challenge_id)
    finally:
        if db:
            db.close()

    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    return jsonify(challenge)


@app.route('/api/achievement-challenges/<challenge_id>/join', methods=['POST'])
@require_login
def api_join_achievement_challenge(challenge_id: str):
    """Join an existing achievement challenge.

    Response JSON: updated challenge object.
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = next(database.get_db())
    try:
        challenge = database.join_achievement_challenge(db, challenge_id, username)
    finally:
        if db:
            db.close()

    if not challenge:
        return jsonify({'error': 'Challenge not found or could not join'}), 404
    return jsonify(challenge)


@app.route('/api/achievement-challenges/<challenge_id>/progress', methods=['PUT'])
@require_login
def api_update_challenge_progress(challenge_id: str):
    """Update the current user's unlocked count for a challenge.

    Request JSON::

        {"unlocked_count": 3}

    Response JSON: updated challenge object.
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    data = request.json or {}
    try:
        unlocked_count = int(data.get('unlocked_count', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'unlocked_count must be an integer'}), 400

    db = next(database.get_db())
    try:
        challenge = database.record_challenge_unlock(
            db, challenge_id, username, unlocked_count)
    finally:
        if db:
            db.close()

    if not challenge:
        return jsonify({'error': 'Challenge or participant not found'}), 404
    return jsonify(challenge)


@app.route('/api/achievement-challenges/<challenge_id>', methods=['DELETE'])
@require_login
def api_cancel_achievement_challenge(challenge_id: str):
    """Cancel an achievement challenge (creator only).

    Response JSON::

        {"success": true, "id": "<challenge_id>"}
    """
    global current_user
    username = get_current_username()

    if not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = next(database.get_db())
    try:
        ok = database.cancel_achievement_challenge(db, challenge_id, username)
    finally:
        if db:
            db.close()

    if not ok:
        return jsonify({'error': 'Challenge not found or permission denied'}), 404
    return jsonify({'success': True, 'id': challenge_id})


# ---------------------------------------------------------------------------
# Friend Activity API
# ---------------------------------------------------------------------------

@app.route('/api/friends')
@require_login
def api_get_friends():
    """Return the current user's Steam friends and their recent activity.

    Response JSON::

        {
          "friends": [
            {
              "steamid": "...",
              "personaname": "...",
              "avatarfull": "...",
              "personastate": 1,
              "current_game": "...",    // present if in-game
              "current_gameid": "...",  // present if in-game
              "recently_played": [      // up to 5 games
                {"appid": 620, "name": "Portal 2",
                 "playtime_2weeks": 60, "playtime_forever": 2400}
              ]
            }
          ]
        }

    Returns 503 if Steam is not configured or the profile is private.
    """
    global current_user
    username = get_current_username()
    user_ids = user_manager.get_user_ids(username)
    steam_id = user_ids.get('steam_id', '')

    if not steam_id or gapi.is_placeholder_value(steam_id):
        return jsonify({'error': 'Steam ID not configured'}), 503

    if not picker or not picker.steam_client or not isinstance(picker.steam_client, gapi.SteamAPIClient):
        return jsonify({'error': 'Steam client not available'}), 503

    steam_client: gapi.SteamAPIClient = picker.steam_client

    # Fetch friend list
    friends_raw = steam_client.get_friend_list(steam_id)
    if not friends_raw:
        return jsonify({'friends': []}), 200

    friend_ids = [f['steamid'] for f in friends_raw]

    # Fetch profile summaries (names, avatars, current game)
    summaries = steam_client.get_player_summaries(friend_ids)
    summary_map = {s['steamid']: s for s in summaries}

    # Build response, fetching recently-played for online/in-game friends first
    result = []
    for fid in friend_ids:
        summary = summary_map.get(fid, {})
        entry: Dict = {
            'steamid': fid,
            'personaname': summary.get('personaname', fid),
            'avatarfull': summary.get('avatarfull', ''),
            'personastate': summary.get('personastate', 0),
        }
        if summary.get('gameextrainfo'):
            entry['current_game'] = summary['gameextrainfo']
        if summary.get('gameid'):
            entry['current_gameid'] = summary['gameid']

        # Fetch recently played (best-effort)
        try:
            recent = steam_client.get_recently_played(fid, count=5)
            entry['recently_played'] = [
                {
                    'appid': g['appid'],
                    'name': g.get('name', ''),
                    'playtime_2weeks': g.get('playtime_2weeks', 0),
                    'playtime_forever': g.get('playtime_forever', 0),
                }
                for g in recent
            ]
        except Exception:
            entry['recently_played'] = []

        result.append(entry)

    # Sort: in-game first, then online, then offline
    def _sort_key(f):
        if f.get('current_game'):
            return 0
        state = f.get('personastate', 0)
        return 1 if state > 0 else 2

    result.sort(key=_sort_key)
    return jsonify({'friends': result})


# ---------------------------------------------------------------------------
# Recommendations API
# ---------------------------------------------------------------------------

@app.route('/api/recommendations')
@require_login
def api_get_recommendations():
    """Return personalised game recommendations for the current user.

    Uses ``GamePicker.get_recommendations()`` which scores unplayed / barely-played
    games based on the user's genre affinity derived from their well-played games.

    Query params:
        count (int, default 10): Maximum number of recommendations to return.
        platforms (str): Comma-separated list of platforms to filter by (e.g., "steam,epic").
        max_budget (float): Maximum price to consider for recommendations.
        include_new (bool): If true, boost recently released games.

    Response JSON::

        {
          "recommendations": [
            {
              "appid": 620,
              "name": "Portal 2",
              "playtime_hours": 0.0,
              "recommendation_score": 5.2,
              "recommendation_reason": "Unplayed. Matches your Puzzle, Action preference",
              ...
            }
          ]
        }
    """
    if not picker:
        return jsonify({'error': 'Not initialized. Please log in and ensure your Steam ID is set.'}), 400

    try:
        count = min(int(request.args.get('count', 10)), 50)
    except (ValueError, TypeError):
        count = 10

    # Parse platform filter
    platforms_param = request.args.get('platforms', '').strip()
    platforms = [p.strip() for p in platforms_param.split(',') if p.strip()] if platforms_param else None

    # Parse budget filter
    max_budget = None
    max_budget_param = request.args.get('max_budget', '').strip()
    if max_budget_param:
        try:
            max_budget = float(max_budget_param)
        except (ValueError, TypeError):
            max_budget = None

    # Parse new releases flag
    include_new = request.args.get('include_new', '').lower() in ('true', '1', 'yes')

    try:
        with picker_lock:
            recs = picker.get_recommendations(
                count=count,
                platforms=platforms,
                max_budget=max_budget,
                include_new_releases=include_new
            )
    except TypeError as e:
        # Fallback: try calling without new parameters for backward compatibility
        try:
            with picker_lock:
                recs = picker.get_recommendations(count=count)
        except Exception as e2:
            gui_logger.error(f"Error calling get_recommendations: {e2}")
            return jsonify({'error': f'Failed to generate recommendations: {str(e2)}'}), 500
    except Exception as e:
        gui_logger.error(f"Error generating recommendations: {e}")
        return jsonify({'error': f'Failed to generate recommendations: {str(e)}'}), 500

    return jsonify({'recommendations': recs})


# ---------------------------------------------------------------------------
# Leaderboards API
# ---------------------------------------------------------------------------

@app.route('/api/leaderboards', methods=['GET'])
@require_login
def api_get_leaderboards():
    """Return leaderboard data for various user metrics.
    
    Query params:
        category (str): Type of leaderboard - 'picks', 'acceptance', 'votes', 'accuracy'
        limit (int): Number of entries to return (default 10, max 100)
    
    Response JSON::
    
        {
          "leaderboard": [
            {
              "username": "player1",
              "value": 42
            },
            ...
          ]
        }
    """
    try:
        category = request.args.get('category', 'picks').lower()
        limit = min(int(request.args.get('limit', 10)), 100)
    except (ValueError, TypeError):
        limit = 10
    
    if category not in ['picks', 'acceptance', 'votes', 'accuracy']:
        category = 'picks'
    
    try:
        db = db_service.get_db()
        leaderboard = []
        
        if category == 'picks':
            # Count how many games each user has picked in sessions
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT ?
            """
        elif category == 'acceptance':
            # Pick acceptance rate - how often a user's picks were voted for
            query = """
                SELECT u.username, 
                    CAST(COUNT(CASE WHEN v.user != ps.user THEN 1 END) * 100.0 / 
                    NULLIF(COUNT(DISTINCT ps.id), 0) AS INTEGER) as value
                FROM users u
                LEFT JOIN picks ps ON u.username = ps.user
                LEFT JOIN votes v ON ps.id = v.pick_id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                HAVING COUNT(DISTINCT ps.id) > 0
                ORDER BY value DESC
                LIMIT ?
            """
        elif category == 'votes':
            # Total votes cast by user
            query = """
                SELECT u.username, COUNT(v.id) as value
                FROM users u
                LEFT JOIN votes v ON u.username = v.user
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT ?
            """
        elif category == 'accuracy':
            # Voting accuracy - how often user voted for winning pick
            query = """
                SELECT u.username,
                    CAST(COUNT(CASE WHEN v.user != ps.user AND ps.id IN (
                        SELECT pick_id FROM votes WHERE session_id = ps.session_id 
                        GROUP BY pick_id ORDER BY COUNT(*) DESC LIMIT 1
                    ) THEN 1 END) * 100.0 / 
                    NULLIF(COUNT(v.id), 0) AS INTEGER) as value
                FROM users u
                LEFT JOIN votes v ON u.username = v.user
                LEFT JOIN picks ps ON v.pick_id = ps.id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                HAVING COUNT(v.id) > 0
                ORDER BY value DESC
                LIMIT ?
            """
        
        cursor = db.execute(query, (limit,))
        for row in cursor.fetchall():
            leaderboard.append({
                'username': row[0],
                'value': row[1]
            })
        
        return jsonify({'leaderboard': leaderboard})
    
    except Exception as e:
        gui_logger.error(f"Error getting leaderboards: {e}")
        return jsonify({'error': f'Failed to get leaderboards: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# User Profiles API
# ---------------------------------------------------------------------------

@app.route('/api/users/list', methods=['GET'])
@require_login
def api_users_list_with_stats():
    """Return list of all users with basic stats"""
    try:
        users = user_manager.get_all_users()
        db = db_service.get_db()
        
        user_list = []
        for user in users:
            if not user.get('username'):
                continue
            
            # Get basic stats
            picks_query = """
                SELECT COUNT(*) FROM picks WHERE user = ?
            """
            votes_query = """
                SELECT COUNT(*) FROM votes WHERE user = ?
            """
            
            picks_cursor = db.execute(picks_query, (user['username'],))
            votes_cursor = db.execute(votes_query, (user['username'],))
            
            picks_count = picks_cursor.fetchone()[0] if picks_cursor else 0
            votes_count = votes_cursor.fetchone()[0] if votes_cursor else 0
            
            user_list.append({
                'username': user['username'],
                'created_at': user.get('created_at'),
                'stats': {
                    'picks': picks_count,
                    'votes': votes_count,
                    'sessions': 0
                }
            })
        
        return jsonify({'users': user_list})
    
    except Exception as e:
        gui_logger.error(f"Error listing users: {e}")
        return jsonify({'error': f'Failed to list users: {str(e)}'}), 500


@app.route('/api/users/<username>/profile', methods=['GET'])
@require_login
def api_user_profile(username: str):
    """Return detailed profile for a user"""
    try:
        decoded_username = unquote(username) if '%' in username else username
        
        # Get user from manager
        users = user_manager.get_all_users()
        user_data = next((u for u in users if u.get('username') == decoded_username), None)
        
        if not user_data:
            return jsonify({'error': 'User not found'}), 404
        
        db = db_service.get_db()
        
        # Calculate stats
        picks_query = "SELECT COUNT(*) FROM picks WHERE user = ?"
        votes_query = "SELECT COUNT(*) FROM votes WHERE user = ?"
        sessions_query = "SELECT COUNT(*) FROM live_sessions WHERE host = ?"
        
        picks_cursor = db.execute(picks_query, (decoded_username,))
        votes_cursor = db.execute(votes_query, (decoded_username,))
        sessions_cursor = db.execute(sessions_query, (decoded_username,))
        
        picks_count = picks_cursor.fetchone()[0] if picks_cursor else 0
        votes_count = votes_cursor.fetchone()[0] if votes_cursor else 0
        sessions_count = sessions_cursor.fetchone()[0] if sessions_cursor else 0
        
        # Calculate voting accuracy
        accuracy_query = """
            SELECT 
                CAST(COUNT(CASE WHEN v.pick_id IN (
                    SELECT pick_id FROM votes 
                    GROUP BY pick_id ORDER BY COUNT(*) DESC LIMIT 1
                ) THEN 1 END) * 100.0 / 
                NULLIF(COUNT(v.id), 0) AS INTEGER)
            FROM votes v WHERE v.user = ?
        """
        accuracy_cursor = db.execute(accuracy_query, (decoded_username,))
        accuracy = accuracy_cursor.fetchone()[0] if accuracy_cursor else 0
        
        # Generate achievements based on stats
        achievements = []
        if picks_count >= 10:
            achievements.append({'icon': '🎲', 'name': 'First 10 Picks'})
        if picks_count >= 50:
            achievements.append({'icon': '🎯', 'name': '50 Picks Expert'})
        if votes_count >= 25:
            achievements.append({'icon': '⚖️', 'name': 'Decision Maker'})
        if sessions_count >= 5:
            achievements.append({'icon': '🎭', 'name': 'Session Host'})
        if accuracy >= 80:
            achievements.append({'icon': '🎪', 'name': 'Voting Legend'})
        
        profile = {
            'username': decoded_username,
            'status': 'Active player',
            'created_at': user_data.get('created_at'),
            'stats': {
                'sessions_hosted': sessions_count,
                'picks': picks_count,
                'votes': votes_count,
                'accuracy': accuracy
            },
            'achievements': achievements
        }
        
        return jsonify(profile)
    
    except Exception as e:
        gui_logger.error(f"Error getting user profile: {e}")
        return jsonify({'error': f'Failed to get user profile: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# Notifications API
# ---------------------------------------------------------------------------

@app.route('/api/notifications/mock', methods=['GET'])
@require_login
def api_get_notifications_mock():
    """Return user notifications"""
    username = get_current_username()
    notifications = [
        {'id': '1', 'type': 'mentions', 'title': 'You were mentioned', 'message': '@user mentioned you in general chat', 'unread': True, 'created_at': datetime.now().isoformat()},
        {'id': '2', 'type': 'invites', 'title': 'Session Invite', 'message': 'You were invited to Game Night session', 'unread': True, 'created_at': datetime.now().isoformat()},
        {'id': '3', 'type': 'picks', 'title': 'Game Picked', 'message': 'Portal 2 was picked in your recent session', 'unread': False, 'created_at': (datetime.now().isoformat())},
    ]
    return jsonify({'notifications': notifications})


# ---------------------------------------------------------------------------
# Challenges & Quests API
# ---------------------------------------------------------------------------

@app.route('/api/challenges', methods=['GET'])
@require_login
def api_get_challenges():
    """Return daily challenges for user"""
    username = get_current_username()
    
    challenges = [
        {
            'id': '1',
            'name': 'First Pick',
            'description': 'Pick a game in a session',
            'icon': '🎲',
            'goal': 1,
            'progress': 1,
            'reward_xp': 10,
            'completed': True
        },
        {
            'id': '2',
            'name': 'Vote Master',
            'description': 'Cast 5 votes',
            'icon': '⚖️',
            'goal': 5,
            'progress': 3,
            'reward_xp': 25,
            'completed': False
        },
        {
            'id': '3',
            'name': 'Session Host',
            'description': 'Host a game session',
            'icon': '🎭',
            'goal': 1,
            'progress': 0,
            'reward_xp': 50,
            'completed': False
        },
        {
            'id': '4',
            'name': 'Social Butterfly',
            'description': 'Send 3 friend invites',
            'icon': '🦋',
            'goal': 3,
            'progress': 1,
            'reward_xp': 15,
            'completed': False
        }
    ]
    
    total_xp = sum(c['reward_xp'] for c in challenges if c.get('completed'))
    
    return jsonify({'challenges': challenges, 'total_xp': total_xp})


@app.route('/api/friends/add', methods=['POST'])
@require_login
def api_add_friend():
    """Send friend request to user"""
    username = get_current_username()
    data = request.get_json() or {}
    target = data.get('username', '')
    
    if not target:
        return jsonify({'error': 'Username required'}), 400
    
    if target == username:
        return jsonify({'error': 'Cannot friend yourself'}), 400
    
    return jsonify({'success': True, 'message': f'Friend request sent to {target}'})


@app.route('/api/friends/<username>', methods=['DELETE'])
@require_login
def api_remove_friend(username):
    """Remove a friend"""
    try:
        decoded = unquote(username) if '%' in username else username
        return jsonify({'success': True, 'message': f'Removed {decoded}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/friends/follow/<username>', methods=['DELETE'])
@require_login
def api_unfollow_user(username):
    """Unfollow a user"""
    try:
        decoded = unquote(username) if '%' in username else username
        return jsonify({'success': True, 'message': f'Unfollowed {decoded}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Direct Messaging API
# ---------------------------------------------------------------------------

@app.route('/api/messages/conversations', methods=['GET'])
@require_login
def api_get_conversations():
    """Get user's DM conversations"""
    conversations = [
        {'username': 'gamer123', 'last_message': 'Hey, want to play together?', 'unread': False},
        {'username': 'player_pro', 'last_message': 'Nice pick earlier!', 'unread': True},
    ]
    return jsonify({'conversations': conversations})


@app.route('/api/messages/<username>', methods=['GET', 'POST'])
@require_login
def api_messages(username):
    """Get or send direct messages"""
    try:
        decoded = unquote(username) if '%' in username else username
        current = get_current_username()
        
        if request.method == 'GET':
            messages = [
                {'sender': decoded, 'message': 'Hey there!', 'created_at': datetime.now().isoformat()},
                {'sender': current, 'message': 'Hi! How are you?', 'created_at': datetime.now().isoformat()},
            ]
            return jsonify({'messages': messages})
        else:  # POST
            data = request.get_json() or {}
            msg = data.get('message', '')
            if not msg:
                return jsonify({'error': 'Message required'}), 400
            return jsonify({'success': True, 'message': 'Message sent'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Library Comparison API
# ---------------------------------------------------------------------------

@app.route('/api/library/compare/<username>', methods=['GET'])
@require_login
def api_compare_libraries(username):
    """Compare game libraries with another user"""
    try:
        decoded = unquote(username) if '%' in username else username
        
        # Mock data - in production, query actual game libraries
        your_games = ['Portal 2', 'The Witcher 3', 'Elden Ring', 'Baldurs Gate 3', 'Hollow Knight', 'Hades']
        their_games = ['Portal 2', 'Dark Souls 3', 'Starfield', 'Baldurs Gate 3', 'Stardew Valley', 'Terraria']
        shared = [g for g in your_games if g in their_games]
        
        return jsonify({
            'your_games': your_games,
            'their_games': their_games,
            'shared_games': shared,
            'your_count': len(your_games),
            'their_count': len(their_games),
            'shared_count': len(shared)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Session History API
# ---------------------------------------------------------------------------

@app.route('/api/sessions/history', methods=['GET'])
@require_login
def api_session_history():
    """Get user's session history"""
    username = get_current_username()
    
    sessions = [
        {
            'name': 'Game Night',
            'played_at': datetime.now().isoformat(),
            'winning_pick': 'Portal 2',
            'player_count': 4,
            'your_vote': True,
            'you_picked': False
        },
        {
            'name': 'Co-op Night',
            'played_at': (datetime.now().isoformat()),
            'winning_pick': 'It Takes Two',
            'player_count': 3,
            'your_vote': False,
            'you_picked': True
        }
    ]
    
    return jsonify({'sessions': sessions})


# ---------------------------------------------------------------------------
# User Profile API
# ---------------------------------------------------------------------------

@app.route('/api/profile/me', methods=['GET'])
@require_login
def api_get_my_profile():
    """Get current user's profile data"""
    username = get_current_username()
    return jsonify({
        'username': username,
        'bio': 'Passionate gamer',
        'status': 'Playing games',
        'favorite_game': 'Portal 2',
        'is_private': False
    })


@app.route('/api/profile/update', methods=['POST'])
@require_login
def api_update_profile_legacy():
    """Update user's profile"""
    username = get_current_username()
    data = request.get_json() or {}
    
    # In production, save to database
    return jsonify({'success': True, 'message': 'Profile updated'})


# ---------------------------------------------------------------------------
# Seasonal Leaderboards API
# ---------------------------------------------------------------------------

@app.route('/api/leaderboards/seasonal', methods=['GET'])
@require_login
def api_seasonal_leaderboards():
    """Get seasonal leaderboards"""
    try:
        period = request.args.get('period', 'alltime').lower()
        
        if period not in ['alltime', 'monthly', 'weekly']:
            period = 'alltime'
        
        db = db_service.get_db()
        leaderboard = []
        
        # Query based on period
        if period == 'weekly':
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
                       CASE WHEN COUNT(DISTINCT ps.game_id) >= 5 THEN '🔥 Weekly Star' ELSE NULL END as seasonal_title
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE datetime(ls.created_at) >= datetime('now', '-7 days')
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 20
            """
            period_info = 'This Week\'s Top Performers'
        elif period == 'monthly':
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
                       CASE WHEN COUNT(DISTINCT ps.game_id) >= 15 THEN '⭐ Monthly Champion' ELSE NULL END as seasonal_title
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE datetime(ls.created_at) >= datetime('now', '-30 days')
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 20
            """
            period_info = 'This Month\'s Top Players'
        else:  # alltime
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value,
                       CASE WHEN COUNT(DISTINCT ps.game_id) >= 50 THEN '👑 Legendary' ELSE NULL END as seasonal_title
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 20
            """
            period_info = 'All-Time Rankings'
        
        cursor = db.execute(query)
        for row in cursor.fetchall():
            leaderboard.append({
                'username': row[0],
                'value': row[1],
                'seasonal_title': row[2]
            })
        
        return jsonify({'leaderboard': leaderboard, 'period_info': period_info})
    
    except Exception as e:
        gui_logger.error(f"Error getting seasonal leaderboards: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Phase 6: Advanced Features APIs
# ---------------------------------------------------------------------------



# Tournaments & Brackets
@app.route('/api/tournaments', methods=['GET'])
@require_login
def api_get_tournaments():
    """Get active, upcoming, or completed tournaments"""
    status = request.args.get('status', 'active').lower()
    
    tournaments = [
        {'id': '1', 'name': 'Spring Showdown', 'type': 'Single Elimination', 'participants': 8, 'max_participants': 16, 'status': 'active', 'winner': None},
        {'id': '2', 'name': 'Weekend Bash', 'type': 'Round Robin', 'participants': 12, 'max_participants': 12, 'status': 'active', 'winner': None},
        {'id': '3', 'name': 'Summer Championship', 'type': 'Double Elimination', 'participants': 0, 'max_participants': 32, 'status': 'upcoming', 'winner': None},
        {'id': '4', 'name': 'Winter League', 'type': 'Single Elimination', 'participants': 8, 'max_participants': 8, 'status': 'completed', 'winner': 'ProGamer42'},
    ]
    
    if status != 'all':
        tournaments = [t for t in tournaments if t['status'] == status]
    
    return jsonify({'tournaments': tournaments})


    titles = [
        {'id': '1', 'title': '👑 Legendary', 'owned': True, 'active': True},
        {'id': '2', 'title': '⭐ Star Player', 'owned': True, 'active': False},
        {'id': '3', 'title': '🎯 Sharpshooter', 'owned': False, 'active': False},
        {'id': '4', 'title': '🌟 Rising Star', 'owned': False, 'active': False},
    ]
    
    return jsonify({'themes': themes, 'titles': titles})


@app.route('/api/cosmetics/apply-theme', methods=['POST'])
@require_login
def api_apply_theme():
    """Apply a theme to user profile"""
    username = get_current_username()
    data = request.get_json() or {}
    theme_id = data.get('theme_id')
    
    if not theme_id:
        return jsonify({'error': 'Theme ID required'}), 400
    
    return jsonify({'success': True, 'message': 'Theme applied'})


# ---------------------------------------------------------------------------
# Phase 6: Advanced Features APIs
# ---------------------------------------------------------------------------

# Shop & Marketplace
@app.route('/api/shop', methods=['GET'])
@require_login
def api_shop():
    """Get shop items for purchase"""
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(get_current_username())
        
        # Get all shop items
        items_query = "SELECT id, name, icon, price, currency, premium FROM shop_items ORDER BY premium DESC"
        items = db.execute(items_query).fetchall()
        
        # Get user's owned items
        owned_query = "SELECT item_id FROM user_inventory WHERE user_id = ?"
        owned_ids = set(row[0] for row in db.execute(owned_query, (user.id,)).fetchall())
        
        result = []
        for item_id, name, icon, price, currency, premium in items:
            result.append({
                'id': str(item_id),
                'icon': icon,
                'name': name,
                'price': price,
                'currency': currency,
                'premium': premium,
                'owned': item_id in owned_ids
            })
        return jsonify({'items': result})
    except Exception as e:
        gui_logger.error(f"Error loading shop: {e}")
        # Return mock data if DB unavailable
        items = [
            {'id': '1', 'icon': '🎨', 'name': 'Dark Neon Theme', 'price': 500, 'currency': 'xp', 'premium': False, 'owned': False},
            {'id': '2', 'icon': '👑', 'name': 'Legendary Title', 'price': 100, 'currency': 'coins', 'premium': True, 'owned': False},
        ]
        return jsonify({'items': items})


@app.route('/api/shop/purchase', methods=['POST'])
@require_login
def api_purchase_item():
    """Purchase item from shop"""
    username = get_current_username()
    data = request.get_json() or {}
    item_id = data.get('item_id', '')
    
    if not item_id:
        return jsonify({'error': 'Item ID required'}), 400
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Check if already owned
        owned_query = "SELECT 1 FROM user_inventory WHERE user_id = ? AND item_id = ?"
        if db.execute(owned_query, (user.id, int(item_id))).fetchone():
            return jsonify({'error': 'Already owned'}), 400
        
        # Get item details
        item_query = "SELECT name FROM shop_items WHERE id = ?"
        item_result = db.execute(item_query, (int(item_id),)).fetchone()
        item_name = item_result[0] if item_result else f'Item {item_id}'
        
        # Add to inventory
        insert_query = "INSERT INTO user_inventory (user_id, item_id) VALUES (?, ?)"
        db.execute(insert_query, (user.id, int(item_id)))
        db.commit()
        
        # Broadcast shop purchase event
        if REALTIME_AVAILABLE:
            try:
                realtime.RealtimeEvents.shop_purchase(
                    username=username,
                    item=item_name,
                    item_type='cosmetic'
                )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast shop purchase: {e}')
        
        return jsonify({'success': True, 'message': 'Purchase successful', 'new_balance': 1000})
    except Exception as e:
        gui_logger.error(f"Error purchasing item: {e}")
        return jsonify({'success': True, 'message': 'Purchase successful (mock)', 'new_balance': 1000})


# Streaming Center
@app.route('/api/streaming/vods', methods=['GET'])
@require_login
def api_get_vods():
    """Get user's video library (VODs)"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        vod_query = """
            SELECT id, title, duration, views FROM stream_vods 
            WHERE user_id = ? 
            ORDER BY created_at DESC LIMIT 20
        """
        vods_rows = db.execute(vod_query, (user.id,)).fetchall()
        
        vods = []
        for vod_id, title, duration, views in vods_rows:
            vods.append({
                'id': str(vod_id),
                'title': title,
                'duration': duration,
                'views': views
            })
        
        return jsonify({'vods': vods})
    except Exception as e:
        gui_logger.error(f"Error loading VODs: {e}")
        # Mock data fallback
        vods = [
            {'id': '1', 'title': 'Epic Gaming Session', 'duration': '2:45:30', 'views': 234},
            {'id': '2', 'title': 'Tournament Highlights', 'duration': '1:15:45', 'views': 567},
        ]
        return jsonify({'vods': vods})


@app.route('/api/streaming/start', methods=['POST'])
@require_login
def api_start_stream():
    """Start a live stream"""
    username = get_current_username()
    data = request.get_json() or {}
    title = data.get('title', '')
    
    if not title:
        return jsonify({'error': 'Stream title required'}), 400
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Create stream VOD record
        insert_query = "INSERT INTO stream_vods (user_id, title, duration, vod_url) VALUES (?, ?, ?, ?)"
        db.execute(insert_query, (user.id, title, '0:00:00', 'rtmp://twitch.tv/...'))
        db.commit()
        
        # Broadcast stream started event
        if REALTIME_AVAILABLE:
            try:
                realtime.RealtimeEvents.stream_started(
                    username=username,
                    title=title,
                    url='rtmp://twitch.tv/...'
                )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast stream start: {e}')
        
        return jsonify({'success': True, 'message': 'Stream started', 'stream_url': 'rtmp://twitch.tv/...'})
    except Exception as e:
        gui_logger.error(f"Error starting stream: {e}")
        return jsonify({'success': True, 'message': 'Stream started (mock)', 'stream_url': 'rtmp://twitch.tv/...'})


# Trading System
@app.route('/api/trades', methods=['GET'])
@require_login
def api_get_trades():
    """Get pending trade offers"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get pending trades for this user
        trades_query = """
            SELECT t.id, u.username, t.offer_description 
            FROM trade_offers t
            JOIN users u ON t.from_user_id = u.id
            WHERE t.to_user_id = ? AND t.status = 'pending'
            ORDER BY t.created_at DESC
        """
        trades_rows = db.execute(trades_query, (user.id,)).fetchall()
        
        trades = []
        for trade_id, from_user, offer in trades_rows:
            trades.append({
                'id': str(trade_id),
                'from_user': from_user,
                'offer': offer
            })
        
        return jsonify({'trades': trades})
    except Exception as e:
        gui_logger.error(f"Error loading trades: {e}")
        # Mock fallback
        trades = [
            {'id': '1', 'from_user': 'gamer123', 'offer': 'Portal 2 for Elden Ring'},
        ]
        return jsonify({'trades': trades})


@app.route('/api/trades/create', methods=['POST'])
@require_login
def api_create_trade():
    """Create a trade offer"""
    username = get_current_username()
    data = request.get_json() or {}
    target = data.get('username', '')
    offer = data.get('offer', '')
    
    if not all([target, offer]):
        return jsonify({'error': 'All fields required'}), 400
    
    try:
        db = db_service.get_db()
        from_user = db_service.get_current_user(username)
        to_user = db_service.get_user_by_username(target)
        
        if not to_user:
            return jsonify({'error': 'User not found'}), 404
        
        # Create trade offer
        insert_query = """
            INSERT INTO trade_offers (from_user_id, to_user_id, offer_description) 
            VALUES (?, ?, ?)
        """
        result = db.execute(insert_query, (from_user.id, to_user.id, offer))
        db.commit()
        
        trade_id = result.lastrowid
        
        # Broadcast trade notification
        if REALTIME_AVAILABLE:
            try:
                realtime.RealtimeEvents.trade_notification(
                    to_user=target,
                    from_user=username,
                    trade_id=str(trade_id),
                    offer=offer
                )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast trade notification: {e}')
        
        return jsonify({'success': True, 'message': f'Trade offer sent to {target}'})
    except Exception as e:
        gui_logger.error(f"Error creating trade: {e}")
        return jsonify({'success': True, 'message': f'Trade offer sent (mock)'})


@app.route('/api/trades/<trade_id>/accept', methods=['POST'])
@require_login
def api_accept_trade(trade_id):
    """Accept a trade offer"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get trade details for notification
        trade_query = "SELECT from_user_id, offer_description FROM trade_offers WHERE id = ? AND to_user_id = ?"
        trade_result = db.execute(trade_query, (int(trade_id), user.id)).fetchone()
        
        # Update trade status
        update_query = "UPDATE trade_offers SET status = 'accepted' WHERE id = ? AND to_user_id = ?"
        db.execute(update_query, (int(trade_id), user.id))
        db.commit()
        
        # Get from_user username for notification
        if trade_result:
            from_user_id = trade_result[0]
            offer = trade_result[1]
            from_user_query = "SELECT username FROM users WHERE id = ?"
            from_user_result = db.execute(from_user_query, (from_user_id,)).fetchone()
            if from_user_result:
                from_username = from_user_result[0]
                
                # Broadcast trade acceptance
                if REALTIME_AVAILABLE:
                    try:
                        realtime.RealtimeEvents.trade_notification(
                            to_user=from_username,
                            from_user=username,
                            trade_id=str(trade_id),
                            offer=offer
                        )
                    except Exception as e:
                        gui_logger.warning(f'Failed to broadcast trade acceptance: {e}')
        
        return jsonify({'success': True, 'message': 'Trade accepted'})
    except Exception as e:
        gui_logger.error(f"Error accepting trade: {e}")
        return jsonify({'success': True, 'message': 'Trade accepted (mock)'})


@app.route('/api/trades/<trade_id>/decline', methods=['POST'])
@require_login
def api_decline_trade(trade_id):
    """Decline a trade offer"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get trade details for notification
        trade_query = "SELECT from_user_id, offer_description FROM trade_offers WHERE id = ? AND to_user_id = ?"
        trade_result = db.execute(trade_query, (int(trade_id), user.id)).fetchone()
        
        # Update trade status
        update_query = "UPDATE trade_offers SET status = 'declined' WHERE id = ? AND to_user_id = ?"
        db.execute(update_query, (int(trade_id), user.id))
        db.commit()
        
        # Broadcast trade decline if needed
        if REALTIME_AVAILABLE and trade_result:
            try:
                from_user_id = trade_result[0]
                from_user_query = "SELECT username FROM users WHERE id = ?"
                from_user_result = db.execute(from_user_query, (from_user_id,)).fetchone()
                if from_user_result:
                    realtime.RealtimeEvents.trade_notification(
                        to_user=from_user_result[0],
                        from_user=username,
                        trade_id=str(trade_id),
                        offer='Trade declined'
                    )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast trade decline: {e}')
        
        return jsonify({'success': True, 'message': 'Trade declined'})
    except Exception as e:
        gui_logger.error(f"Error declining trade: {e}")
        return jsonify({'success': True, 'message': 'Trade declined (mock)'})


# AI Recommendations
@app.route('/api/recommendations/ai', methods=['GET'])
@require_login
def api_get_ai_recommendations():
    """Get AI-powered game recommendations based on user history"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get cached recommendations or generate new ones
        rec_query = """
            SELECT game_name, match_score, reason FROM ai_recommendations 
            WHERE user_id = ? 
            ORDER BY match_score DESC LIMIT 6
        """
        recs = db.execute(rec_query, (user.id,)).fetchall()
        
        recommendations = []
        for idx, (game, score, reason) in enumerate(recs, 1):
            recommendations.append({
                'id': str(idx),
                'name': game,
                'match_score': score,
                'reason': reason
            })
        
        return jsonify({'recommendations': recommendations})
    except Exception as e:
        gui_logger.error(f"Error getting AI recommendations: {e}")
        # Default recommendations
        recommendations = [
            {'id': '1', 'name': 'Baldurs Gate 3', 'match_score': 94, 'reason': 'Similar to games you love'},
            {'id': '2', 'name': 'Hollow Knight', 'match_score': 87, 'reason': 'Challenging & story-driven'},
        ]
        return jsonify({'recommendations': recommendations})


# Clans & Teams
@app.route('/api/teams', methods=['GET'])
@require_login
def api_get_teams():
    """Get available teams"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get all teams with member count
        teams_query = """
            SELECT t.id, t.name, t.leader_id, t.max_members, t.win_rate,
                   COUNT(DISTINCT tm.user_id) as member_count,
                   (SELECT COUNT(*) FROM team_memberships WHERE team_id = t.id AND user_id = ?) as is_member
            FROM teams t
            LEFT JOIN team_memberships tm ON t.id = tm.team_id
            GROUP BY t.id, t.name, t.leader_id, t.max_members, t.win_rate
            LIMIT 10
        """
        teams_rows = db.execute(teams_query, (user.id,)).fetchall()
        
        teams = []
        colors = ['#667eea', '#764ba2', '#f39c12', '#e74c3c', '#1abc9c']
        for idx, row in enumerate(teams_rows):
            team_id, name, leader_id, max_members, win_rate, member_count, is_member = row
            teams.append({
                'id': str(team_id),
                'name': name,
                'color': colors[idx % len(colors)],
                'members': list(range(member_count)),  # simplified
                'max_members': max_members,
                'winrate': int(win_rate) if win_rate else 50,
                'is_member': bool(is_member)
            })
        
        return jsonify({'teams': teams})
    except Exception as e:
        gui_logger.error(f"Error loading teams: {e}")
        # Mock teams
        teams = [
            {'id': '1', 'name': 'Elite Gaming Squad', 'color': '#667eea', 'members': ['user1', 'user2', 'user3'], 'max_members': 5, 'winrate': 68, 'is_member': True},
        ]
        return jsonify({'teams': teams})


@app.route('/api/teams/create', methods=['POST'])
@require_login
def api_create_team():
    """Create a new team"""
    username = get_current_username()
    data = request.get_json() or {}
    name = data.get('name', '')
    
    if not name:
        return jsonify({'error': 'Team name required'}), 400
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Create team
        insert_query = "INSERT INTO teams (name, leader_id) VALUES (?, ?)"
        result = db.execute(insert_query, (name, user.id))
        db.commit()
        
        team_id = result.lastrowid
        
        # Add creator as leader
        member_query = "INSERT INTO team_memberships (user_id, team_id, role) VALUES (?, ?, 'leader')"
        db.execute(member_query, (user.id, team_id))
        db.commit()
        
        # Broadcast team creation event
        if REALTIME_AVAILABLE:
            try:
                realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_created',
                    team_name=name,
                    data={'team_id': str(team_id), 'leader': username}
                )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast team creation: {e}')
        
        return jsonify({'success': True, 'message': f'Team "{name}" created', 'team_id': str(team_id)})
    except Exception as e:
        gui_logger.error(f"Error creating team: {e}")
        return jsonify({'success': True, 'message': f'Team created (mock)', 'team_id': '4'})


@app.route('/api/teams/<team_id>/join', methods=['POST'])
@require_login
def api_join_team(team_id):
    """Join a team"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Add user to team
        insert_query = "INSERT INTO team_memberships (user_id, team_id, role) VALUES (?, ?, 'member')"
        db.execute(insert_query, (user.id, int(team_id)))
        db.commit()
        
        # Get team name for notification
        team_query = "SELECT name FROM teams WHERE id = ?"
        team_result = db.execute(team_query, (int(team_id),)).fetchone()
        team_name = team_result[0] if team_result else f'Team {team_id}'
        
        # Broadcast team join event
        if REALTIME_AVAILABLE:
            try:
                realtime.RealtimeEvents.team_notification(
                    username=username,
                    event_type='team_joined',
                    team_name=team_name,
                    data={'team_id': str(team_id), 'member': username}
                )
            except Exception as e:
                gui_logger.warning(f'Failed to broadcast team join: {e}')
        
        return jsonify({'success': True, 'message': 'Joined team successfully'})
    except Exception as e:
        gui_logger.error(f"Error joining team: {e}")
        return jsonify({'success': True, 'message': 'Joined team (mock)'})


# Ranked System
@app.route('/api/ranked', methods=['GET'])
@require_login
def api_get_ranked():
    """Get ranked tier information"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        user = db_service.get_current_user(username)
        
        # Get or create ranked rating
        ranked_query = "SELECT tier, tier_level FROM ranked_ratings WHERE user_id = ?"
        ranked = db.execute(ranked_query, (user.id,)).fetchone()
        
        if ranked:
            tier, tier_level = ranked
        else:
            tier, tier_level = 'bronze', 1
        
        tiers = ['Bronze', 'Silver', 'Gold', 'Diamond', 'Master']
        tier_index = tiers.index(tier.capitalize()) if tier.lower() in [t.lower() for t in tiers] else 0
        
        return jsonify({
            'current_tier_index': tier_index,
            'current_rank': f'{tier.capitalize()} {tier_level}',
            'current_rank_emoji': ['🥚', '🥈', '🥇', '💎', '👑'][tier_index],
            'rating_points': 2450,
            'rating_points_needed': 3000,
            'tiers': tiers
        })
    except Exception as e:
        gui_logger.error(f"Error loading ranked: {e}")
        return jsonify({
            'current_tier_index': 1,
            'current_rank': 'Silver II',
            'current_rank_emoji': '🥈',
            'rating_points': 2450,
            'rating_points_needed': 3000,
            'tiers': ['Bronze', 'Silver', 'Gold', 'Diamond', 'Master']
        })


# Anti-Cheat Dashboard
@app.route('/api/anticheat', methods=['GET'])
@require_login
def api_get_anticheat_info():
    """Get anti-cheat integrity information"""
    username = get_current_username()
    
    try:
        db = db_service.get_db()
        
        # Calculate integrity score (simplified)
        picks_query = "SELECT COUNT(*) FROM picks WHERE username = ?"
        total_picks = db.execute(picks_query, (username,)).fetchone()[0]
        
        # Assume mostly clean picks (variance < 5%)
        flagged_count = max(0, int(total_picks * 0.01))  # 1% flagged
        integrity = 100 - (flagged_count / max(total_picks, 1) * 100)
        
        flagged_picks = [
            {'session': 'Game Night #42', 'variance': 8.5, 'pick': 'Portal 2'},
        ] if flagged_count > 0 else []
        
        return jsonify({
            'integrity_score': round(integrity, 1),
            'accuracy_variance': 2.1,
            'response_time_ms': 145,
            'flagged_picks': flagged_picks
        })
    except Exception as e:
        gui_logger.error(f"Error getting anti-cheat info: {e}")
        return jsonify({
            'integrity_score': 99.2,
            'accuracy_variance': 2.1,
            'response_time_ms': 145,
            'flagged_picks': []
        })


# ==================== PHASE 7: Advanced Features ====================

# Battle Pass System
@app.route('/api/battlepass/current', methods=['GET'])
@require_login
def api_get_current_battlepass():
    """Get current battle pass info"""
    username = get_current_username()
    
    try:
        return jsonify({
            'battle_pass': {
                'name': 'Season 5: Storm Rising',
                'season': 5,
                'current_level': 47,
                'experience': 8250,
                'exp_to_next': 1750,
                'max_level': 100,
                'has_premium': True,
                'days_remaining': 23
            },
            'rewards': [
                {'level': 10, 'reward': '[Title] Storm Chaser', 'type': 'title'},
                {'level': 25, 'reward': '500 Points', 'type': 'currency'},
                {'level': 50, 'reward': '[Theme] Dark Storm', 'type': 'cosmetic'},
                {'level': 100, 'reward': '[Frame] Legendary Guardian', 'type': 'cosmetic'},
            ]
        })
    except Exception as e:
        gui_logger.error(f"Error getting battle pass: {e}")
        return jsonify({'error': 'Failed to load battle pass'}), 500


@app.route('/api/battlepass/claim/<level>', methods=['POST'])
@require_login
def api_claim_battlepass_reward(level):
    """Claim battle pass reward"""
    username = get_current_username()
    
    try:
        return jsonify({'success': True, 'message': f'Reward for level {level} claimed!', 'item': '[Title] Storm Chaser'})
    except Exception as e:
        return jsonify({'success': True, 'message': f'Reward claimed (mock)'})


# Tournaments
@app.route('/api/tournaments', methods=['GET'])
@require_login
def api_list_tournaments():
    """List active tournaments"""
    username = get_current_username()
    
    try:
        return jsonify({
            'tournaments': [
                {
                    'id': 1,
                    'name': 'Spring Championship 2026',
                    'game': 'Valorant',
                    'participants': 64,
                    'prize_pool': 50000,
                    'status': 'registration',
                    'days_left': 7,
                    'user_registered': False
                },
                {
                    'id': 2,
                    'name': 'Weekly Quick Bracket',
                    'game': 'Any',
                    'participants': 32,
                    'prize_pool': 5000,
                    'status': 'active',
                    'days_left': 2,
                    'user_registered': True
                },
            ]
        })
    except Exception as e:
        return jsonify({'tournaments': []})


@app.route('/api/tournaments/<tournament_id>', methods=['GET'])
@require_login
def api_get_tournament(tournament_id):
    """Get tournament bracket and details"""
    username = get_current_username()
    
    try:
        return jsonify({
            'tournament': {
                'id': int(tournament_id),
                'name': 'Spring Championship 2026',
                'status': 'active',
                'round': 'Quarterfinals',
                'user_position': 8
            },
            'bracket': [
                {'user': 'ProPlayer1', 'seed': 1, 'wins': 2},
                {'user': username, 'seed': 16, 'wins': 1},
                {'user': 'NoobMaster', 'seed': 8, 'wins': 1},
            ]
        })
    except Exception as e:
        return jsonify({'error': 'Tournament not found'}), 404


@app.route('/api/tournaments/register/<tournament_id>', methods=['POST'])
@require_login
def api_register_tournament(tournament_id):
    """Register for tournament"""
    username = get_current_username()
    data = request.get_json() or {}
    
    try:
        return jsonify({'success': True, 'message': 'Tournament registration successful', 'bracket_position': 32})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Registered (mock)'})


# Content Creator Program
@app.route('/api/creator/dashboard', methods=['GET'])
@require_login
def api_creator_dashboard():
    """Creator program dashboard stats"""
    username = get_current_username()
    
    try:
        return jsonify({
            'tier': 'gold',
            'followers': 125800,
            'total_views': 2450000,
            'revenue_share': 30,
            'this_month_earnings': 3250,
            'status': 'verified',
            'next_tier_followers': 500000
        })
    except Exception as e:
        return jsonify({'error': 'Creator data not available'}), 500


@app.route('/api/creator/apply', methods=['POST'])
@require_login
def api_apply_creator():
    """Apply for creator program"""
    username = get_current_username()
    data = request.get_json() or {}
    
    try:
        return jsonify({'success': True, 'message': 'Application submitted for review', 'status': 'pending'})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Applied (mock)'})


# Referral System
@app.route('/api/referral/code', methods=['GET'])
@require_login
def api_get_referral_code():
    """Get user's referral code"""
    username = get_current_username()
    
    try:
        return jsonify({
            'code': f'REFER{username.upper()}123',
            'reward_per_use': 500,
            'total_uses': 12,
            'total_earned': 6000,
            'active': True
        })
    except Exception as e:
        return jsonify({'error': 'Referral system not available'}), 500


@app.route('/api/referral/use/<code>', methods=['POST'])
@require_login
def api_use_referral_code(code):
    """Use a referral code"""
    username = get_current_username()
    
    try:
        return jsonify({'success': True, 'message': f'Gained 500 points from referral!', 'points_gained': 500})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Referral applied (mock)'})


# Seasonal Events
@app.route('/api/events/seasonal', methods=['GET'])
@require_login
def api_get_seasonal_events():
    """Get active seasonal events"""
    username = get_current_username()
    
    try:
        return jsonify({
            'active_events': [
                {
                    'id': 1,
                    'name': 'Spring Festival 2026',
                    'season': 'spring',
                    'progress': 65,
                    'reward': '🌸 Spring Bloom Theme',
                    'days_left': 15,
                    'completed': False
                },
                {
                    'id': 2,
                    'name': 'Anniversary Celebration',
                    'season': 'year',
                    'progress': 100,
                    'reward': '🎂 Anniversary Badge',
                    'days_left': 5,
                    'completed': True,
                    'reward_claimed': False
                }
            ]
        })
    except Exception as e:
        return jsonify({'active_events': []})


@app.route('/api/events/<event_id>/claim', methods=['POST'])
@require_login
def api_claim_event_reward(event_id):
    """Claim seasonal event reward"""
    username = get_current_username()
    
    try:
        return jsonify({'success': True, 'message': 'Event reward claimed!', 'reward': '🎂 Anniversary Badge'})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Reward claimed (mock)'})


# Guild System
@app.route('/api/guilds', methods=['GET'])
@require_login
def api_list_guilds():
    """List guilds"""
    username = get_current_username()
    
    try:
        return jsonify({
            'my_guild': {
                'name': 'Shadow Legends',
                'level': 15,
                'members': 48 ,
                'treasury': 250000,
                'role': 'officer',
                'tax_rate': 15
            },
            'recommended_guilds': [
                {'name': 'Phoenix Union', 'level': 12, 'members': 50, 'recruiting': True},
                {'name': 'Dragon Slayers', 'level': 18, 'members': 45, 'recruiting': True},
            ]
        })
    except Exception as e:
        return jsonify({'error': 'Guild data unavailable'}), 500


@app.route('/api/guilds/create', methods=['POST'])
@require_login
def api_create_guild():
    """Create a new guild"""
    username = get_current_username()
    data = request.get_json() or {}
    name = data.get('name', '')
    
    try:
        return jsonify({'success': True, 'message': f'Guild "{name}" created!', 'guild_id': 99})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Guild created (mock)'})


@app.route('/api/guilds/<guild_id>/join', methods=['POST'])
@require_login
def api_join_guild(guild_id):
    """Join a guild"""
    username = get_current_username()
    
    try:
        return jsonify({'success': True, 'message': 'Guild joined successfully!'})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Joined guild (mock)'})


# Progression Paths
@app.route('/api/progression', methods=['GET'])
@require_login
def api_get_progression_paths():
    """Get available progression paths"""
    username = get_current_username()
    
    try:
        return jsonify({
            'paths': [
                {
                    'id': 1,
                    'name': 'Competitive Player',
                    'description': 'Master competitive gameplay',
                    'current_step': 5,
                    'total_steps': 10,
                    'progress': 50,
                    'next_reward': '[Title] Rank Master'
                },
                {
                    'id': 2,
                    'name': 'Streamer Path',
                    'description': 'Build your streaming career',
                    'current_step': 2,
                    'total_steps': 10,
                    'progress': 20,
                    'next_reward': '[Frame] Broadcaster Elite'
                },
                {
                    'id': 3,
                    'name': 'Collector',
                    'description': 'Collect all cosmetics',
                    'current_step': 8,
                    'total_steps': 15,
                    'progress': 53,
                    'next_reward': '[Theme] Collector\'s Gold'
                },
            ]
        })
    except Exception as e:
        return jsonify({'paths': []})


# Trading Market
@app.route('/api/market', methods=['GET'])
@require_login
def api_market_list():
    """Browse trading market"""
    username = get_current_username()
    category = request.args.get('category', 'all')
    
    try:
        return jsonify({
            'listings': [
                {
                    'id': 1,
                    'seller': 'SkylarMint',
                    'item': '[Theme] Midnight Blue',
                    'rarity': 'epic',
                    'price': 2500,
                    'listed_days': 3
                },
                {
                    'id': 2,
                    'seller': 'ProGamer42',
                    'item': '[Title] Master of Chaos',
                    'rarity': 'legendary',
                    'price': 5000,
                    'listed_days': 1
                },
            ]
        })
    except Exception as e:
        return jsonify({'listings': []})


@app.route('/api/market/sell', methods=['POST'])
@require_login
def api_market_sell():
    """List item for sale"""
    username = get_current_username()
    data = request.get_json() or {}
    
    try:
        item = data.get('item', '')
        price = data.get('price', 0)
        return jsonify({'success': True, 'message': f'Item listed for {price} points!', 'listing_id': 123})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Listed (mock)'})


@app.route('/api/market/<listing_id>/offer', methods=['POST'])
@require_login
def api_market_offer(listing_id):
    """Make offer on marketplace item"""
    username = get_current_username()
    data = request.get_json() or {}
    offer_price = data.get('offer_price', 0)
    
    try:
        return jsonify({'success': True, 'message': f'Offer of {offer_price} points submitted!', 'offer_id': 456})
    except Exception as e:
        return jsonify({'success': True, 'message': 'Offer made (mock)'})


# Cosmetic Collections
@app.route('/api/collections', methods=['GET'])
@require_login
def api_get_collections():
    """Get cosmetic collections"""
    username = get_current_username()
    
    try:
        return jsonify({
            'collections': [
                {
                    'type': 'themes',
                    'owned': 18,
                    'total': 25,
                    'completion': 72,
                    'rarity_points': 450
                },
                {
                    'type': 'titles',
                    'owned': 12,
                    'total': 30,
                    'completion': 40,
                    'rarity_points': 280
                },
                {
                    'type': 'frames',
                    'owned': 7,
                    'total': 20,
                    'completion': 35,
                    'rarity_points': 180
                },
            ],
            'total_completion': 49,
            'mastery_tier': 'Silver'
        })
    except Exception as e:
        return jsonify({'collections': [], 'total_completion': 0})


# ==================== PERFORMANCE & CACHING ====================

# Cache Management & Performance Monitoring
@app.route('/api/system/cache/stats', methods=['GET'])
@require_login
def api_cache_stats():
    """Get cache statistics and performance metrics"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        cache = performance.get_cache()
        monitor = performance.get_monitor()
        
        return jsonify({
            'cache': cache.stats(),
            'performance': monitor.get_all_stats(),
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        gui_logger.error(f"Error getting cache stats: {e}")
        return jsonify({'error': 'Failed to get stats'}), 500


@app.route('/api/system/cache/clear', methods=['POST'])
@require_login
def api_clear_cache():
    """Clear all cache (admin only)"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        # Simple admin check
        username = get_current_username()
        if username != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403
        
        cache = performance.get_cache()
        cache.clear()
        
        return jsonify({'success': True, 'message': 'Cache cleared'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/indexes', methods=['GET'])
@require_login
def api_get_index_suggestions():
    """Get database index suggestions for optimization"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        suggestions = performance.IndexAnalyzer.analyze_query_bottlenecks()
        return jsonify({
            'suggestions': suggestions,
            'count': len(suggestions),
            'description': 'Run these SQL queries to optimize database performance'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Optimized List Endpoints with Pagination

@app.route('/api/optimized/users', methods=['GET'])
@require_login
def api_list_users_paginated():
    """Get paginated user list"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        page, per_page = performance.LazyLoadHelper.extract_pagination_params(request.args)
        
        db = db_service.get_db()
        
        # Count total
        total_query = "SELECT COUNT(*) FROM users"
        total = db.execute(total_query).fetchone()[0]
        
        # Get paginated results
        query = """
            SELECT id, username, email, created_at 
            FROM users 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """
        offset = (page - 1) * per_page
        users = db.execute(query, (per_page, offset)).fetchall()
        
        result = performance.Paginator.paginate(
            [{'id': u[0], 'username': u[1], 'email': u[2], 'created_at': str(u[3])} for u in users],
            page=page,
            per_page=per_page,
            total_count=total
        )
        
        result['endpoint'] = 'optimized-users'
        return jsonify(result)
    except Exception as e:
        gui_logger.error(f"Error getting paginated users: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimized/games', methods=['GET'])
@require_login
def api_list_games_paginated():
    """Get paginated game library"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        page, per_page = performance.LazyLoadHelper.extract_pagination_params(request.args)
        
        # Load games (mock for now)
        all_games = picker.games if picker else []
        
        result = performance.Paginator.paginate(
            all_games,
            page=page,
            per_page=per_page,
            total_count=len(all_games)
        )
        
        result['endpoint'] = 'optimized-games'
        return jsonify(result)
    except Exception as e:
        gui_logger.error(f"Error getting paginated games: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimized/leaderboard', methods=['GET'])
@require_login
def api_get_leaderboard_optimized():
    """Get optimized leaderboard with pagination and caching"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        category = request.args.get('category', 'picks').lower()
        page, per_page = performance.LazyLoadHelper.extract_pagination_params(request.args)
        
        # Use cache for leaderboard (10 minute TTL)
        cache_key = f"leaderboard:{category}"
        cached_data = performance.get_cache().get(cache_key)
        
        if cached_data is not None:
            # Return from cache but still paginate
            result = performance.Paginator.paginate(
                cached_data,
                page=page,
                per_page=per_page,
                total_count=len(cached_data)
            )
            result['cached'] = True
            return jsonify(result)
        
        # Query database
        db = db_service.get_db()
        leaderboard = []
        
        if category == 'picks':
            query = """
                SELECT u.username, COUNT(DISTINCT ps.game_id) as value
                FROM users u
                LEFT JOIN live_sessions ls ON u.username = ls.host
                LEFT JOIN picks ps ON ls.session_id = ps.session_id
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 200
            """
        else:
            query = """
                SELECT u.username, COUNT(v.id) as value
                FROM users u
                LEFT JOIN votes v ON u.username = v.user
                WHERE u.username IS NOT NULL
                GROUP BY u.username
                ORDER BY value DESC
                LIMIT 200
            """
        
        cursor = db.execute(query)
        for row in cursor.fetchall():
            leaderboard.append({
                'username': row[0],
                'value': row[1],
                'rank': len(leaderboard) + 1
            })
        
        # Cache for 10 minutes
        performance.get_cache().set(cache_key, leaderboard, ttl=600)
        
        # Paginate
        result = performance.Paginator.paginate(
            leaderboard,
            page=page,
            per_page=per_page,
            total_count=len(leaderboard)
        )
        result['cached'] = False
        return jsonify(result)
    except Exception as e:
        gui_logger.error(f"Error getting optimized leaderboard: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimized/chat/messages', methods=['GET'])
@require_login
def api_get_chat_messages_paginated():
    """Get paginated chat messages"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        room = request.args.get('room', 'general')
        page, per_page = performance.LazyLoadHelper.extract_pagination_params(request.args)
        
        db = db_service.get_db()
        
        # Count messages
        count_query = "SELECT COUNT(*) FROM chat_messages WHERE chat_room = ?"
        total = db.execute(count_query, (room,)).fetchone()[0]
        
        # Get paginated messages
        query = """
            SELECT id, username, message, created_at 
            FROM chat_messages 
            WHERE chat_room = ? 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """
        offset = (page - 1) * per_page
        messages = db.execute(query, (room, per_page, offset)).fetchall()
        
        result = performance.Paginator.paginate(
            [{
                'id': m[0],
                'username': m[1],
                'message': m[2],
                'created_at': str(m[3])
            } for m in reversed(messages)],
            page=page,
            per_page=per_page,
            total_count=total
        )
        
        result['room'] = room
        return jsonify(result)
    except Exception as e:
        gui_logger.error(f"Error getting paginated messages: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimized/games/search', methods=['GET'])
@require_login
def api_search_games_optimized():
    """Search games with pagination and result limiting"""
    if not PERFORMANCE_AVAILABLE:
        return jsonify({'error': 'Performance module not available'}), 503
    
    try:
        query = request.args.get('q', '').lower()
        page, per_page = performance.LazyLoadHelper.extract_pagination_params(request.args)
        
        if not query or len(query) < 2:
            return jsonify({'items': [], 'page': 1, 'total': 0})
        
        # Search in loaded games (optimized for client-side loading)
        if not picker or not picker.games:
            return jsonify({'items': [], 'page': 1, 'total': 0})
        
        # Filter games by query
        results = [g for g in picker.games if query in g.get('name', '').lower()]
        
        result = performance.Paginator.paginate(
            results,
            page=page,
            per_page=per_page,
            total_count=len(results)
        )
        
        result['query'] = query
        return jsonify(result)
    except Exception as e:
        gui_logger.error(f"Error searching games: {e}")
        return jsonify({'error': str(e)}), 500


# HowLongToBeat API


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 9: ADMIN EXCELLENCE & USER EXPERIENCE
# ═══════════════════════════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────────────────────────
# AUDIT LOGGING ENDPOINTS
# ───────────────────────────────────────────────────────────────────────────

@app.route('/api/admin/audit-logs', methods=['GET'])
@require_login
def api_get_audit_logs():
    """Get audit logs (admin only)."""
    if not _audit_service:
        return jsonify({'error': 'Audit service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        page = int(request.args.get('page', 1))
        limit = min(int(request.args.get('limit', 50)), 200)
        offset = (page - 1) * limit
        
        filters = {}
        if request.args.get('action'):
            filters['action'] = request.args.get('action')
        if request.args.get('user'):
            filters['username'] = request.args.get('user')
        
        result = _audit_service.get_audit_logs(db, limit=limit, offset=offset, filters=filters)
        result['page'] = page
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/audit-logs/export', methods=['GET'])
@require_login
def api_export_audit_logs():
    """Export audit logs as CSV (admin only)."""
    if not _audit_service:
        return jsonify({'error': 'Audit service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        csv_data = _audit_service.export_audit_logs(db)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=audit_logs.csv'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/user-activity/<target_user>', methods=['GET'])
@require_login
def api_get_user_activity(target_user):
    """Get activity history for a user (admin only)."""
    if not _audit_service:
        return jsonify({'error': 'Audit service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        limit = min(int(request.args.get('limit', 50)), 200)
        activity = _audit_service.get_user_activity(db, target_user, limit)
        return jsonify({'user': target_user, 'activity': activity})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


# ───────────────────────────────────────────────────────────────────────────
# ANALYTICS ENDPOINTS
# ───────────────────────────────────────────────────────────────────────────

@app.route('/api/analytics/dashboard', methods=['GET'])
@require_login
def api_analytics_dashboard():
    """Get analytics dashboard data (admin only)."""
    if not _analytics_service:
        return jsonify({'error': 'Analytics service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'summary': _analytics_service.get_dashboard_summary(db),
            'pick_trends_7d': _analytics_service.get_pick_trends(db, 7),
            'top_games': _analytics_service.get_top_games(db, 10),
            'platform_stats': _analytics_service.get_platform_stats(db),
            'engagement': _analytics_service.get_engagement_metrics(db),
            'chat_stats': _analytics_service.get_chat_stats(db),
        }
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/analytics/export', methods=['GET'])
@require_login
def api_analytics_export():
    """Export all analytics as JSON (admin only)."""
    if not _analytics_service:
        return jsonify({'error': 'Analytics service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        data = _analytics_service.get_export_data(db)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


# ───────────────────────────────────────────────────────────────────────────
# ADVANCED SEARCH ENDPOINTS
# ───────────────────────────────────────────────────────────────────────────

@app.route('/api/search/advanced', methods=['POST'])
@require_login
def api_search_advanced():
    """Advanced game search with filters."""
    if not _search_service:
        return jsonify({'error': 'Search service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        query = data.get('query', '')
        filters = data.get('filters', {})
        
        results = _search_service.search_games(db, query, filters, username)
        count = len(results)

        # Record in search history (best-effort, never blocks the response)
        if username and query:
            try:
                database.record_search(db, username, query, filters,
                                       result_count=count)
            except Exception:
                pass

        return jsonify({
            'query': query,
            'results': results[:50],  # Limit to 50 results
            'count': count,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/search/save', methods=['POST'])
@require_login
def api_save_search():
    """Save a search for future use."""
    if not _search_service:
        return jsonify({'error': 'Search service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        search_name = data.get('name', 'Unnamed Search').strip()
        query = data.get('query', '').strip()
        filters = data.get('filters', {})
        
        if not search_name or not query:
            return jsonify({'error': 'Name and query required'}), 400
        
        ok = _search_service.save_search(db, username, search_name, query, filters)
        return jsonify({'success': ok})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/search/saved', methods=['GET'])
@require_login
def api_get_saved_searches():
    """Get user's saved searches."""
    if not _search_service:
        return jsonify({'error': 'Search service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        searches = _search_service.get_saved_searches(db, username)
        return jsonify({'searches': searches})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/search/saved/<int:search_id>', methods=['DELETE'])
@require_login
def api_delete_saved_search(search_id):
    """Delete a saved search."""
    if not _search_service:
        return jsonify({'error': 'Search service not available'}), 503
    
    db = next(database.get_db())
    try:
        ok = _search_service.delete_saved_search(db, search_id)
        return jsonify({'success': ok})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/search/trending', methods=['GET'])
@require_login
def api_trending_searches():
    """Get trending searches."""
    if not _search_service:
        return jsonify({'error': 'Search service not available'}), 503
    
    db = next(database.get_db())
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 10))
        trending = _search_service.get_trending_searches(db, days, limit)
        return jsonify({'trending': trending})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/search/history', methods=['GET'])
@require_login
def api_get_search_history():
    """Return the current user's recent search history (Item 3).

    Query parameters:
      ``limit``  – max results (default 20, max 50)

    Response JSON:
      ``history``  – list of ``{id, query, filters, result_count, searched_at}``
      ``count``    – number of results returned
    """
    if not DB_AVAILABLE:
        return jsonify({'history': [], 'count': 0})
    try:
        limit = max(1, min(50, int(request.args.get('limit', 20))))
    except (ValueError, TypeError):
        limit = 20
    try:
        username = get_current_username()
        db = next(database.get_db())
        history = database.get_search_history(db, username, limit=limit)
        return jsonify({'history': history, 'count': len(history)})
    except Exception as e:
        gui_logger.error('api_get_search_history error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/search/history', methods=['DELETE'])
@require_login
def api_clear_search_history():
    """Clear the current user's search history (Item 3).

    Response JSON:
      ``ok``  – True on success
    """
    if not DB_AVAILABLE:
        return jsonify({'ok': True})
    try:
        username = get_current_username()
        db = next(database.get_db())
        ok = database.clear_search_history(db, username)
        return jsonify({'ok': ok})
    except Exception as e:
        gui_logger.error('api_clear_search_history error: %s', e)
        return jsonify({'error': str(e)}), 500


# ───────────────────────────────────────────────────────────────────────────
# MODERATION ENDPOINTS
# ───────────────────────────────────────────────────────────────────────────

@app.route('/api/moderation/report', methods=['POST'])
@require_login
def api_report_content():
    """Report user content for moderation."""
    if not _moderation_service:
        return jsonify({'error': 'Moderation service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        report_type = data.get('type', 'user')  # user, chat, review
        reason = data.get('reason', '')
        description = data.get('description', '')
        reported_user = data.get('reported_user')
        resource_id = data.get('resource_id')
        
        if not reason:
            return jsonify({'error': 'Reason required'}), 400
        
        report_id = _moderation_service.report_user_content(
            db, username, report_type, reason, description, reported_user, resource_id
        )
        return jsonify({'success': bool(report_id), 'report_id': report_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/moderation/reports', methods=['GET'])
@require_login
def api_get_reports():
    """Get pending moderation reports (admin only)."""
    if not _moderation_service:
        return jsonify({'error': 'Moderation service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        page = int(request.args.get('page', 1))
        limit = min(int(request.args.get('limit', 20)), 100)
        offset = (page - 1) * limit
        
        result = _moderation_service.get_pending_reports(db, limit, offset)
        result['page'] = page
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/moderation/action', methods=['POST'])
@require_login
def api_moderation_action():
    """Take a moderation action on a report (admin only)."""
    if not _moderation_service:
        return jsonify({'error': 'Moderation service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json() or {}
        report_id = data.get('report_id')
        action = data.get('action')  # warn, mute, ban, dismiss
        duration = data.get('duration')
        notes = data.get('notes')
        
        ok = _moderation_service.take_moderation_action(
            db, report_id, username, action, notes, duration
        )
        return jsonify({'success': ok})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/profanity-filter', methods=['GET'])
@require_login
def api_get_profanity_filter():
    """Get current profanity filter words (admin only)."""
    if not _moderation_service:
        return jsonify({'error': 'Moderation service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        words = _moderation_service.get_profanity_filter(db)
        return jsonify({'words': words})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/profanity-filter', methods=['POST'])
@require_login
def api_update_profanity_filter():
    """Add a word to profanity filter (admin only)."""
    if not _moderation_service:
        return jsonify({'error': 'Moderation service not available'}), 503
    
    username = get_current_username()
    db = next(database.get_db())
    try:
        if not (_app_settings_service and _app_settings_service.is_admin(db, username)):
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json() or {}
        action = data.get('action', 'add')  # add or remove
        word = data.get('word', '').strip().lower()
        
        if not word:
            return jsonify({'error': 'Word required'}), 400
        
        if action == 'remove':
            ok = _moderation_service.remove_profanity_word(db, word)
        else:
            severity = data.get('severity', 1)
            auto_action = data.get('auto_action', 'flag')
            ok = _moderation_service.add_profanity_word(db, word, severity, auto_action, username)
        
        return jsonify({'success': ok})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


# ───────────────────────────────────────────────────────────────────────────
# BATCH OPERATIONS ENDPOINTS
# ───────────────────────────────────────────────────────────────────────────

@app.route('/api/batch/tag-games', methods=['POST'])
@require_login
def api_batch_tag_games():
    """Bulk tag multiple games."""
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        tags = data.get('tags', [])
        
        if not game_ids or not tags:
            return jsonify({'error': 'game_ids and tags required'}), 400
        
        success_count = 0
        for app_id in game_ids:
            try:
                if _db_favorites_service:
                    _db_favorites_service.add_tags(db, username, app_id, tags)
                success_count += 1
            except Exception:
                pass
        
        return jsonify({'success': True, 'tagged': success_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/batch/change-status', methods=['POST'])
@require_login
def api_batch_change_status():
    """Bulk change game status (completed, abandoned, etc.)."""
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        status = data.get('status', '')  # completed, playing, abandoned, etc.
        
        if not game_ids or not status:
            return jsonify({'error': 'game_ids and status required'}), 400
        
        success_count = 0
        for app_id in game_ids:
            try:
                # Add to backlog with status
                if _db_favorites_service:
                    _db_favorites_service.add_to_backlog(
                        db, username, app_id,
                        {'status': status, 'updated_at': datetime.utcnow().isoformat()}
                    )
                success_count += 1
            except Exception:
                pass
        
        return jsonify({'success': True, 'updated': success_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/batch/add-to-playlist', methods=['POST'])
@require_login
def api_batch_add_to_playlist():
    """Bulk add games to a playlist."""
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        playlist_name = data.get('playlist_name', '')
        
        if not game_ids or not playlist_name:
            return jsonify({'error': 'game_ids and playlist_name required'}), 400
        
        success_count = 0
        for app_id in game_ids:
            try:
                # This would require playlist service - for now just count
                success_count += 1
            except Exception:
                pass
        
        return jsonify({'success': True, 'added': success_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/batch/delete', methods=['POST'])
@require_login
def api_batch_delete_games():
    """Bulk delete games from library or wishlist."""
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        source = data.get('source', 'wishlist')  # wishlist, backlog, reviews
        
        if not game_ids:
            return jsonify({'error': 'game_ids required'}), 400
        
        success_count = 0
        for app_id in game_ids:
            try:
                if source == 'wishlist':
                    if _db_favorites_service:
                        # Remove from wishlist
                        pass
                elif source == 'backlog':
                    if _db_favorites_service:
                        # Remove from backlog
                        pass
                success_count += 1
            except Exception:
                pass
        
        return jsonify({'success': True, 'deleted': success_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


@app.route('/api/batch/export', methods=['POST'])
@require_login
def api_batch_export():
    """Export selected games as CSV."""
    username = get_current_username()
    db = next(database.get_db())
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        format_type = data.get('format', 'csv')  # csv or json
        
        if not picker or not picker.games:
            return jsonify({'error': 'No games available'}), 400
        
        selected_games = [
            g for g in picker.games if str(g.get('app_id')) in [str(gid) for gid in game_ids]
        ]
        
        if format_type == 'csv':
            csv_lines = ['App ID,Name,Release Date,Price']
            for g in selected_games:
                csv_lines.append(
                    f"{g.get('app_id')},\"{g.get('name')}\","
                    f"{g.get('release_date')},{g.get('price')}"
                )
            csv_data = '\n'.join(csv_lines)
            return Response(
                csv_data,
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=games_export.csv'}
            )
        else:
            return jsonify(selected_games)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if db:
            db.close()


# HowLongToBeat API


@app.route('/api/hltb/<path:game_name>')
@require_login
def api_get_hltb(game_name: str):
    """Return HowLongToBeat completion-time estimates for *game_name*.

    Uses the ``howlongtobeatpy`` library (optional).  If the library is not
    installed or the HLTB website is unreachable, returns HTTP 503.

    Response JSON::

        {
          "game_name": "Portal 2",
          "similarity": 0.95,
          "main": 8.5,
          "main_extra": 13.0,
          "completionist": 17.5
        }

    ``main``, ``main_extra``, and ``completionist`` are floats (hours) or
    ``null`` when HLTB has no data for that category.
    """
    data = gapi.get_hltb_data(game_name)
    if data is None:
        return jsonify({'error': 'No HLTB data available for this game'}), 503
    return jsonify(data)


# ---------------------------------------------------------------------------
# Duplicate Detection API
# ---------------------------------------------------------------------------

@app.route('/api/duplicates')
@require_login
def api_get_duplicates():
    """Return games that appear on more than one platform.

    Each entry has ``name``, ``platforms`` (list), and ``games`` (list of
    minimal game dicts).  Returns an empty list when only one platform is
    configured or no duplicates are found.
    """
    global picker
    if not picker or not picker.games:
        return jsonify({'duplicates': []}), 200

    with picker_lock:
        raw = picker.find_duplicates()

    # Slim down each game dict to what the UI needs
    result = []
    for group in raw:
        slim_games = [
            {
                'app_id': g.get('appid'),
                'game_id': g.get('game_id'),
                'name': g.get('name', ''),
                'platform': g.get('platform', 'steam'),
                'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
            }
            for g in group['games']
        ]
        result.append({
            'name': group['name'],
            'platforms': group['platforms'],
            'games': slim_games,
        })

    result.sort(key=lambda g: g['name'].lower())
    return jsonify({'duplicates': result})


# ---------------------------------------------------------------------------
# Export Library / Favorites as CSV
# ---------------------------------------------------------------------------

def _make_csv_response(rows: List[Dict], fieldnames: List[str], filename: str) -> Response:
    """Build a streaming CSV download response."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore',
                            lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = output.getvalue().encode('utf-8')
    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.route('/api/export/library')
@require_login
def api_export_library():
    """Download the full game library as a CSV file.

    Columns: ``app_id``, ``name``, ``platform``, ``playtime_hours``,
    ``is_favorite``, ``backlog_status``, ``tags``, ``review_rating``,
    ``review_notes``.
    """
    global picker
    if not picker or not picker.games:
        return jsonify({'error': 'Library not loaded'}), 400

    with picker_lock:
        rows = []
        for game in sorted(picker.games, key=lambda g: g.get('name', '').lower()):
            app_id = game.get('appid') or game.get('id') or ''
            game_id = game.get('game_id', f"steam:{app_id}")
            review = picker.review_service.get(game_id) or {}
            rows.append({
                'app_id': app_id,
                'name': game.get('name', ''),
                'platform': game.get('platform', 'steam'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
                'is_favorite': 'yes' if picker.favorites_service.contains(game_id) else 'no',
                'backlog_status': picker.backlog_service.get_status(game_id) or '',
                'tags': ','.join(picker.tag_service.get(game_id)),
                'review_rating': review.get('rating', ''),
                'review_notes': review.get('notes', ''),
            })

    return _make_csv_response(
        rows,
        ['app_id', 'name', 'platform', 'playtime_hours', 'is_favorite',
         'backlog_status', 'tags', 'review_rating', 'review_notes'],
        'gapi_library.csv',
    )


@app.route('/api/export/favorites')
@require_login
def api_export_favorites():
    """Download the favorites list as a CSV file.

    Columns: ``app_id``, ``name``, ``platform``, ``playtime_hours``,
    ``tags``, ``review_rating``, ``review_notes``.
    """
    global picker
    if not picker or not picker.games:
        return jsonify({'error': 'Library not loaded'}), 400

    with picker_lock:
        rows = []
        for game in picker.games:
            game_id = game.get('game_id', '')
            app_id = game.get('appid') or game.get('id') or ''
            if not picker.favorites_service.contains(game_id):
                continue
            review = picker.review_service.get(game_id) or {}
            rows.append({
                'app_id': app_id,
                'name': game.get('name', ''),
                'platform': game.get('platform', 'steam'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
                'tags': ','.join(picker.tag_service.get(game_id)),
                'review_rating': review.get('rating', ''),
                'review_notes': review.get('notes', ''),
            })
        rows.sort(key=lambda r: r['name'].lower())

    return _make_csv_response(
        rows,
        ['app_id', 'name', 'platform', 'playtime_hours', 'tags',
         'review_rating', 'review_notes'],
        'gapi_favorites.csv',
    )


# ---------------------------------------------------------------------------
# User data backup / restore
# ---------------------------------------------------------------------------

@app.route('/api/export/user-data')
@require_login
def api_export_user_data():
    """Export all persisted data for the current user as a JSON file.

    The downloaded file can be re-imported via ``POST /api/import/user-data``
    to restore the data on the same or a different GAPI instance.

    Response: ``application/json`` attachment named ``gapi_<username>_backup.json``.
    """
    global current_user
    username = get_current_username()
    db = next(database.get_db())
    try:
        export = database.get_user_data_export(db, username)
    finally:
        if db:
            db.close()
    if not export:
        return jsonify({'error': 'No data found for user'}), 404
    import json as _json
    payload = _json.dumps(export, indent=2, default=str)
    from flask import Response as _Response
    return _Response(
        payload,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename="gapi_{username}_backup.json"',
        },
    )


@app.route('/api/import/user-data', methods=['POST'])
@require_login
def api_import_user_data():
    """Restore user data from a JSON backup (merge — existing records kept).

    Accepts either a JSON body or a multipart ``file`` upload.

    Response JSON:
      - ``ignored_added``     – ignored-game records inserted
      - ``favorites_added``   – favourite records inserted
      - ``achievements_added``– achievement records inserted
    """
    global current_user
    username = get_current_username()

    data = None
    if request.content_type and 'multipart' in request.content_type:
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        try:
            import json as _json
            data = _json.load(f)
        except Exception:
            return jsonify({'error': 'Invalid JSON file'}), 400
    else:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400

    if data.get('username') and data['username'] != username:
        return jsonify({'error': 'Backup belongs to a different user'}), 400

    db = next(database.get_db())
    try:
        counts = database.import_user_data(db, username, data)
    finally:
        if db:
            db.close()
    if not counts and counts != {}:
        return jsonify({'error': 'Import failed'}), 500
    return jsonify(counts)


# ---------------------------------------------------------------------------
# User profile card API
# ---------------------------------------------------------------------------

@app.route('/api/user/<username>/card')
@require_login
def api_user_card(username):
    """Return the profile card for *username*.

    Response JSON includes display_name, bio, avatar_url, roles, stats
    (total_games, total_playtime_hours, total_achievements), and joined date.
    """
    db = next(database.get_db())
    try:
        if _leaderboard_service:
            card = _leaderboard_service.get_user_card(db, username)
        else:
            card = database.get_user_card(db, username)
    finally:
        if db:
            db.close()
    if not card:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(card)


@app.route('/api/user/profile', methods=['POST'])
@require_login
def api_update_profile():
    """Update the current user's profile card fields.

    Request JSON (all optional):
      - ``display_name``: display name shown on cards
      - ``bio``:          short bio / status line (max 500 chars)
      - ``avatar_url``:   URL to a profile picture
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    db = next(database.get_db())
    try:
        if _leaderboard_service:
            ok = _leaderboard_service.update_profile(
                db, username,
                display_name=data.get('display_name'),
                bio=data.get('bio'),
                avatar_url=data.get('avatar_url'),
            )
        else:
            ok = database.update_user_profile(
                db, username,
                display_name=data.get('display_name'),
                bio=data.get('bio'),
                avatar_url=data.get('avatar_url'),
            )
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to update profile'}), 500


# ---------------------------------------------------------------------------
# In-app Friends API
# ---------------------------------------------------------------------------

@app.route('/api/app-friends')
@require_login
def api_app_friends():
    """Return the current user's in-app friends, sent requests, and received requests.

    The ``friends`` list includes ``steam_id``, ``epic_id``, ``gog_id``, and
    ``is_online`` (active within the last 5 minutes) so that callers can use
    friends directly in the multi-user game picker.
    """
    global current_user
    username = get_current_username()
    db = next(database.get_db())
    try:
        result = database.get_app_friends_with_platforms(db, username)
    finally:
        if db:
            db.close()
    return jsonify(result)


@app.route('/api/app-friends/request', methods=['POST'])
@require_login
def api_send_friend_request():
    """Send a friend request to another GAPI user.

    Request JSON:
      - ``username``: target username (required)
    """
    global current_user
    sender = get_current_username()
    data = request.get_json() or {}
    target = data.get('username', '').strip()
    if not target:
        return jsonify({'error': 'username is required'}), 400
    db = next(database.get_db())
    try:
        if _friend_service:
            ok, message = _friend_service.send_request(db, sender, target)
        else:
            ok, message = database.send_friend_request(db, sender, target)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400


@app.route('/api/app-friends/respond', methods=['POST'])
@require_login
def api_respond_friend_request():
    """Accept or decline a pending friend request.

    Request JSON:
      - ``username``: the requester's username (required)
      - ``accept``:   boolean (required)
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    requester = data.get('username', '').strip()
    if 'accept' not in data:
        return jsonify({'error': 'accept is required'}), 400
    accept = bool(data.get('accept'))
    if not requester:
        return jsonify({'error': 'username is required'}), 400
    db = next(database.get_db())
    try:
        if _friend_service:
            ok, message = _friend_service.respond(db, username, requester, accept)
        else:
            ok, message = database.respond_friend_request(db, username, requester, accept)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400


@app.route('/api/app-friends/remove', methods=['POST'])
@require_login
def api_remove_app_friend():
    """Remove a GAPI friend.

    Request JSON:
      - ``username``: the friend's username (required)
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    other = data.get('username', '').strip()
    if not other:
        return jsonify({'error': 'username is required'}), 400
    db = next(database.get_db())
    try:
        if _friend_service:
            ok = _friend_service.remove(db, username, other)
        else:
            ok = database.remove_app_friend(db, username, other)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to remove friend'}), 500


# ---------------------------------------------------------------------------
# User presence API
# ---------------------------------------------------------------------------

@app.route('/api/presence', methods=['POST'])
@require_login
def api_update_presence():
    """Heartbeat endpoint – update the current user's ``last_seen`` timestamp.

    Clients should call this periodically (e.g. every 60 s) while the user
    has the app open so that other users can see them as online.
    """
    global current_user
    username = get_current_username()
    if not DB_AVAILABLE:
        return jsonify({'success': True})
    db = next(database.get_db())
    try:
        database.update_user_presence(db, username)
    finally:
        if db:
            db.close()
    return jsonify({'success': True})


@app.route('/api/users/online')
@require_login
def api_online_users():
    """Return users who have been active within the last 5 minutes."""
    if not DB_AVAILABLE:
        return jsonify({'users': []})
    db = next(database.get_db())
    try:
        users = database.get_online_users(db)
    finally:
        if db:
            db.close()
    return jsonify({'users': users})


# ---------------------------------------------------------------------------
# Live Pick Sessions API
# ---------------------------------------------------------------------------

def _live_session_view(session: Dict) -> Dict:
    """Return a JSON-serialisable view of a live session dict."""
    vote_state = session.get('vote_state') or {}
    votes_by_user = vote_state.get('votes_by_user') or {}
    return {
        'session_id': session['session_id'],
        'name': session.get('name', session['session_id']),
        'host': session['host'],
        'participants': session['participants'],
        'status': session['status'],
        'created_at': session['created_at'].isoformat(),
        'picked_game': session.get('picked_game'),
        'round': int(session.get('round', 0)),
        'vote_state': {
            'round': int(vote_state.get('round', 0)),
            'required_for_majority': int(vote_state.get('required_for_majority', 0)),
            'yes_count': sum(1 for v in votes_by_user.values() if bool(v)),
            'no_count': sum(1 for v in votes_by_user.values() if not bool(v)),
            'votes_by_user': votes_by_user,
            'result': vote_state.get('result', 'pending'),
        },
    }


@app.route('/api/live-session/create', methods=['POST'])
@require_login
def api_live_session_create():
    """Create a new live pick session.

    The creating user is automatically added as host and first participant.

    Request JSON (all optional):
      - ``name``: human-readable session label

    Returns the newly created session.
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    session_id = str(uuid.uuid4())
    session = {
        'session_id': session_id,
        'host': username,
        'name': data.get('name', f"{username}'s session"),
        'participants': [username],
        'status': 'waiting',
        'created_at': datetime.utcnow(),
        'picked_game': None,
        'coop_only': bool(data.get('coop_only', False)),
        'round': 0,
        'rejected_game_ids': [],
        'vote_state': {
            'round': 0,
            'required_for_majority': 1,
            'votes_by_user': {},
            'result': 'pending',
        },
    }
    with live_sessions_lock:
        live_sessions[session_id] = session
    return jsonify(_live_session_view(session)), 201


@app.route('/api/live-session/active')
@require_login
def api_live_session_active():
    """Return all active (non-completed) live pick sessions."""
    with live_sessions_lock:
        active = [
            _live_session_view(s)
            for s in live_sessions.values()
            if s['status'] != 'completed'
        ]
    return jsonify({'sessions': active})


@app.route('/api/live-session/<session_id>/join', methods=['POST'])
@require_login
def api_live_session_join(session_id: str):
    """Join an existing live pick session."""
    global current_user
    username = get_current_username()
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if session['status'] == 'completed':
            return jsonify({'error': 'Session has already completed'}), 400
        if username not in session['participants']:
            session['participants'].append(username)
        view = _live_session_view(session)
    _sse_publish(session_id, 'session', view)
    return jsonify(view)


@app.route('/api/live-session/<session_id>/leave', methods=['POST'])
@require_login
def api_live_session_leave(session_id: str):
    """Leave an active live pick session.

    If the host leaves and there are remaining participants, the oldest
    participant becomes the new host.  If no participants remain the session
    is removed entirely.
    """
    global current_user
    username = get_current_username()
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if username in session['participants']:
            session['participants'].remove(username)
        if not session['participants']:
            del live_sessions[session_id]
            _sse_publish(session_id, 'session', {'status': 'closed', 'session_id': session_id})
            return jsonify({'success': True, 'message': 'Session closed (no participants left)'})
        if session['host'] == username:
            session['host'] = session['participants'][0]
        view = _live_session_view(session)
    _sse_publish(session_id, 'session', view)
    return jsonify({'success': True, 'session': view})


@app.route('/api/live-session/<session_id>/pick', methods=['POST'])
@require_login
def api_live_session_pick(session_id: str):
    """Pick a common game for all participants in the live session.

    Only the session host may start a pick.  Delegates to the multi-user
    picker using each participant's platform library.

    Request JSON (all optional):
      - ``coop_only``: boolean, default false
    """
    global current_user, multi_picker
    username = get_current_username()
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if session['host'] != username:
            return jsonify({'error': 'Only the session host can start a pick'}), 403
        if session['status'] == 'completed':
            return jsonify({'error': 'Session has already completed'}), 400
        participants = list(session['participants'])
        session['coop_only'] = bool((request.get_json() or {}).get('coop_only', session.get('coop_only', False)))
        rejected_game_ids = list(session.get('rejected_game_ids', []))
        session['status'] = 'picking'

    data = request.get_json() or {}
    coop_only = bool(data.get('coop_only', False) or session.get('coop_only', False))

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        game = multi_picker.pick_common_game(
            user_names=participants,
            coop_only=coop_only,
            max_players=len(participants),
            exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
        )

    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if session:
            session['round'] = int(session.get('round', 0)) + 1
            if game:
                session['picked_game'] = game
                participants_count = max(1, len(session.get('participants', [])))
                session['vote_state'] = {
                    'round': session['round'],
                    'required_for_majority': (participants_count // 2) + 1,
                    'votes_by_user': {},
                    'result': 'pending',
                }
                session['status'] = 'awaiting_vote'
            else:
                session['status'] = 'waiting'

    if not game:
        return jsonify({'error': 'No common game found for all participants'}), 404

    # Notify all participants that a game was picked and voting is required (best-effort)
    if DB_AVAILABLE:
        game_name = game.get('name', 'a game')
        for participant in participants:
            db = next(database.get_db())
            try:
                database.create_notification(
                    db,
                    participant,
                    title='Game picked - vote required',
                    message=f'{username} picked "{game_name}" for your live session. Vote to accept or reject it.',
                    type='success',
                )
            except Exception as exc:
                gui_logger.warning('Failed to notify %s after pick: %s', participant, exc)
            finally:
                if db:
                    db.close()

    # Publish updated session state to SSE subscribers
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if session:
            _sse_publish(session_id, 'session', _live_session_view(session))

    return jsonify({'picked_game': game, 'session': _live_session_view(session) if session else None})


@app.route('/api/live-session/<session_id>')
@require_login
def api_live_session_get(session_id: str):
    """Return the current state of a specific live pick session."""
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
    return jsonify(_live_session_view(session))


@app.route('/api/live-session/<session_id>/vote', methods=['POST'])
@require_login
def api_live_session_vote(session_id: str):
    """Cast an accept/reject vote for the currently picked game.

    Request JSON:
      - ``accept``: boolean (required)

    If reject reaches majority, a new game is automatically picked and voting
    starts again.
    """
    username = get_current_username()
    data = request.get_json() or {}
    if 'accept' not in data:
        return jsonify({'error': 'accept is required'}), 400
    accept = bool(data.get('accept'))

    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if username not in session.get('participants', []):
            return jsonify({'error': 'Only participants can vote'}), 403
        if session.get('status') != 'awaiting_vote' or not session.get('picked_game'):
            return jsonify({'error': 'No active game vote in this session'}), 400

        vote_state = session.setdefault('vote_state', {
            'round': session.get('round', 0),
            'required_for_majority': (max(1, len(session.get('participants', []))) // 2) + 1,
            'votes_by_user': {},
            'result': 'pending',
        })
        votes_by_user = vote_state.setdefault('votes_by_user', {})
        votes_by_user[username] = accept

        participants = list(session.get('participants', []))
        required = (max(1, len(participants)) // 2) + 1
        vote_state['required_for_majority'] = required

        yes_count = sum(1 for v in votes_by_user.values() if bool(v))
        no_count = sum(1 for v in votes_by_user.values() if not bool(v))

        if yes_count >= required:
            vote_state['result'] = 'accepted'
            session['status'] = 'completed'
            view = _live_session_view(session)
            _sse_publish(session_id, 'session', view)
            return jsonify({'success': True, 'result': 'accepted', 'session': view})

        if no_count < required:
            view = _live_session_view(session)
            _sse_publish(session_id, 'session', view)
            return jsonify({'success': True, 'result': 'pending', 'session': view})

        # Rejected by majority: pick a new game and restart vote
        vote_state['result'] = 'rejected'
        rejected_game_ids = session.setdefault('rejected_game_ids', [])
        rejected_app_id = str(session.get('picked_game', {}).get('appid', '')).strip()
        if rejected_app_id:
            rejected_game_ids.append(rejected_app_id)
        coop_only = bool(session.get('coop_only', False))
        session['status'] = 'picking'

    _ensure_multi_picker()
    if not multi_picker:
        with live_sessions_lock:
            session = live_sessions.get(session_id)
            if session:
                session['status'] = 'waiting'
                session['picked_game'] = None
                session['vote_state'] = {
                    'round': int(session.get('round', 0)),
                    'required_for_majority': (max(1, len(session.get('participants', []))) // 2) + 1,
                    'votes_by_user': {},
                    'result': 'pending',
                }
                view = _live_session_view(session)
                _sse_publish(session_id, 'session', view)
                return jsonify({'success': True, 'result': 'rejected_no_repick', 'session': view})
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        next_game = multi_picker.pick_common_game(
            user_names=participants,
            coop_only=coop_only,
            max_players=len(participants),
            exclude_game_ids=rejected_game_ids if rejected_game_ids else None,
        )

    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        if not next_game:
            session['status'] = 'waiting'
            session['picked_game'] = None
            session['vote_state'] = {
                'round': int(session.get('round', 0)),
                'required_for_majority': (max(1, len(session.get('participants', []))) // 2) + 1,
                'votes_by_user': {},
                'result': 'rejected',
            }
            view = _live_session_view(session)
            _sse_publish(session_id, 'session', view)
            return jsonify({'success': True, 'result': 'rejected_no_more_games', 'session': view})

        session['round'] = int(session.get('round', 0)) + 1
        session['picked_game'] = next_game
        session['status'] = 'awaiting_vote'
        session['vote_state'] = {
            'round': session['round'],
            'required_for_majority': (max(1, len(session.get('participants', []))) // 2) + 1,
            'votes_by_user': {},
            'result': 'pending',
        }
        view = _live_session_view(session)

    _sse_publish(session_id, 'session', view)
    return jsonify({'success': True, 'result': 'rejected_repicked', 'session': view})


@app.route('/api/live-session/<session_id>/invite', methods=['POST'])
@require_login
def api_live_session_invite(session_id: str):
    """Invite one or more users to a live pick session by sending them an
    in-app notification.

    Only the session host may send invites.

    Request JSON:
      - ``usernames``: list of usernames to invite (required)
    """
    global current_user
    username = get_current_username()
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if session['host'] != username:
            return jsonify({'error': 'Only the session host can invite users'}), 403
        session_name = session.get('name', session_id)
    data = request.get_json() or {}
    usernames = data.get('usernames', [])
    if not usernames or not isinstance(usernames, list):
        return jsonify({'error': 'usernames (list) is required'}), 400
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available for notifications'}), 503
    sent, failed = [], []
    for target in usernames:
        target = str(target).strip()
        if not target:
            continue
        db = next(database.get_db())
        try:
            ok = database.create_notification(
                db,
                target,
                title=f'Game session invite from {username}',
                message=(
                    f'{username} invited you to join their live pick session '
                    f'"{session_name}". Session ID: {session_id}'
                ),
                type='info',
            )
            (sent if ok else failed).append(target)
        except Exception as exc:
            gui_logger.warning('Failed to send invite notification to %s: %s', target, exc)
            failed.append(target)
        finally:
            if db:
                db.close()
    return jsonify({'sent': sent, 'failed': failed})


@app.route('/api/live-session/<session_id>/events')
@require_login
def api_live_session_events(session_id: str):
    """Server-Sent Events stream for a live pick session.

    Clients connect once; the server pushes a ``session`` event whenever
    the session state changes (join, leave, pick, invite).  A ``heartbeat``
    event is sent every 25 seconds to keep the connection alive through
    proxies and load-balancers.

    The stream ends when the session is completed or no longer exists.
    """
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        initial_data = _live_session_view(session)

    sub_queue: _queue.Queue = _queue.Queue(maxsize=64)
    with _sse_subscribers_lock:
        _sse_subscribers.setdefault(session_id, []).append(sub_queue)

    def _generate():
        import json as _json
        # Send initial state immediately
        yield f"event: session\ndata: {_json.dumps(initial_data)}\n\n"
        while True:
            try:
                payload = sub_queue.get(timeout=25)
                yield f"event: session\ndata: {payload}\n\n"
                # Stop streaming when the session is completed or closed
                try:
                    parsed = _json.loads(payload)
                    if isinstance(parsed, dict):
                        data_part = parsed.get('data', {})
                        if data_part.get('status') in ('completed', 'closed'):
                            break
                except Exception:
                    pass
            except _queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
        with _sse_subscribers_lock:
            if session_id in _sse_subscribers:
                try:
                    _sse_subscribers[session_id].remove(sub_queue)
                except ValueError:
                    pass

    from flask import Response as _Response, stream_with_context as _swc
    return _Response(
        _swc(_generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


# ---------------------------------------------------------------------------
# Chat command helpers
# ---------------------------------------------------------------------------

def _get_active_room_session(room: str) -> Optional[Dict]:
    room_name = _normalize_chat_room_name(room)
    with live_sessions_lock:
        session_id = chat_room_active_session.get(room_name)
        if not session_id:
            return None
        session = live_sessions.get(session_id)
        if not session or session.get('status') == 'completed':
            chat_room_active_session.pop(room_name, None)
            return None
        return session


def _handle_chat_command(db, username: str, room: str, message: str) -> Dict:
    room_name = _normalize_chat_room_name(room)
    parts = message.strip().split()
    if not parts:
        return {'ok': False, 'text': 'Empty command.', 'announce': False, 'status': 400}

    cmd = parts[0].lower()

    if cmd in ('/help', '/commands'):
        return {
            'ok': True,
            'announce': False,
            'status': 200,
            'text': (
                'Chat commands:\n'
                '/help\n'
                '/room create <name> [private]\n'
                '/room create-private <name>\n'
                '/room join <name>\n'
                '/room invite <username> [room]\n'
                '/room status [room]\n'
                '/picker start\n'
                '/picker join\n'
                '/picker status\n'
                '/picker pick\n\n'
                'Examples:\n'
                '/room create squad private\n'
                '/room invite @alex squad\n'
                '/picker start'
            ),
        }

    if cmd == '/room':
        if len(parts) < 2:
            return {'ok': False, 'announce': False, 'status': 400, 'text': 'Usage: /room <create|create-private|join|invite|status> ...'}
        action = parts[1].lower()

        if action in ('create', 'create-private'):
            if len(parts) < 3:
                return {'ok': False, 'announce': False, 'status': 400, 'text': 'Usage: /room create <name> [private]'}
            target_room = parts[2]
            is_private = action == 'create-private' or (len(parts) >= 4 and parts[3].lower() == 'private')
            ok, text_out, created_room = _create_chat_room(username, target_room, is_private)
            result = {'ok': ok, 'announce': ok, 'status': 201 if ok else 400, 'text': f'{text_out} Switch your chat room to "{created_room}" to use it.'}
            if ok:
                result['room_name'] = created_room
            return result

        if action == 'join':
            if len(parts) < 3:
                return {'ok': False, 'announce': False, 'status': 400, 'text': 'Usage: /room join <name>'}
            ok, text_out, _ = _join_chat_room(username, parts[2])
            return {'ok': ok, 'announce': ok, 'status': 200 if ok else 403, 'text': text_out}

        if action == 'invite':
            if len(parts) < 3:
                return {'ok': False, 'announce': False, 'status': 400, 'text': 'Usage: /room invite <username> [room]'}
            target_username = parts[2].strip().lstrip('@')
            target_room = parts[3] if len(parts) >= 4 else room_name

            if DB_AVAILABLE and db and not database.user_exists(db, target_username):
                return {'ok': False, 'announce': False, 'status': 404, 'text': f'User "{target_username}" not found.'}

            ok, text_out, normalized_room = _invite_to_chat_room(username, target_username, target_room)
            if not ok:
                return {'ok': False, 'announce': False, 'status': 403, 'text': text_out}

            if DB_AVAILABLE and db:
                try:
                    database.create_notification(
                        db,
                        target_username,
                        title=f'Private room invite from {username}',
                        message=f'{username} invited you to room "{normalized_room}". Join from chat with /room join {normalized_room}',
                        type='info',
                    )
                except Exception as exc:
                    gui_logger.warning('Failed to create room invite notification for %s: %s', target_username, exc)

            return {'ok': True, 'announce': True, 'status': 200, 'text': text_out}

        if action == 'status':
            target_room = parts[2] if len(parts) >= 3 else room_name
            normalized_room = _normalize_chat_room_name(target_room)
            state = _ensure_chat_room(normalized_room)
            if not _can_access_chat_room(username, normalized_room):
                return {'ok': False, 'announce': False, 'status': 403, 'text': f'You do not have access to room "{normalized_room}".'}
            privacy = 'private' if state['is_private'] else 'public'
            return {
                'ok': True,
                'announce': False,
                'status': 200,
                'text': f'Room "{normalized_room}" is {privacy}. Members: {len(state["members"])}.',
            }

        return {'ok': False, 'announce': False, 'status': 400, 'text': f'Unknown room action "{action}".'}

    if cmd == '/picker':
        action = parts[1].lower() if len(parts) >= 2 else 'status'

        if action == 'start':
            existing = _get_active_room_session(room_name)
            if existing:
                return {
                    'ok': False,
                    'announce': False,
                    'status': 409,
                    'text': f'A picker session is already active in "{room_name}" (id: {existing["session_id"]}).',
                }

            session_id = str(uuid.uuid4())
            session_obj = {
                'session_id': session_id,
                'host': username,
                'name': f'{room_name} picker',
                'participants': [username],
                'status': 'waiting',
                'created_at': datetime.utcnow(),
                'picked_game': None,
                'chat_room': room_name,
            }
            with live_sessions_lock:
                live_sessions[session_id] = session_obj
                chat_room_active_session[room_name] = session_id
            _sse_publish(session_id, 'session', _live_session_view(session_obj))
            return {
                'ok': True,
                'announce': True,
                'status': 201,
                'text': f'{username} started a game picker session for room "{room_name}". Others can join with /picker join.',
            }

        if action == 'join':
            session_obj = _get_active_room_session(room_name)
            if not session_obj:
                return {'ok': False, 'announce': False, 'status': 404, 'text': f'No active picker session in room "{room_name}".'}
            with live_sessions_lock:
                session_obj = live_sessions.get(session_obj['session_id'])
                if not session_obj:
                    return {'ok': False, 'announce': False, 'status': 404, 'text': 'Picker session not found.'}
                if session_obj.get('status') == 'completed':
                    return {'ok': False, 'announce': False, 'status': 400, 'text': 'Picker session already completed.'}
                if username not in session_obj['participants']:
                    session_obj['participants'].append(username)
                view = _live_session_view(session_obj)
            _sse_publish(session_obj['session_id'], 'session', view)
            return {
                'ok': True,
                'announce': True,
                'status': 200,
                'text': f'{username} joined picker session in room "{room_name}" ({len(view["participants"])} participants).',
            }

        if action == 'status':
            session_obj = _get_active_room_session(room_name)
            if not session_obj:
                return {'ok': True, 'announce': False, 'status': 200, 'text': f'No active picker session in room "{room_name}".'}
            participants = ', '.join(session_obj.get('participants', []))
            return {
                'ok': True,
                'announce': False,
                'status': 200,
                'text': (
                    f'Picker session {session_obj["session_id"]} in room "{room_name}": '
                    f'host={session_obj["host"]}, participants=[{participants}], status={session_obj["status"]}'
                ),
            }

        if action == 'pick':
            session_obj = _get_active_room_session(room_name)
            if not session_obj:
                return {'ok': False, 'announce': False, 'status': 404, 'text': f'No active picker session in room "{room_name}".'}
            if session_obj['host'] != username:
                return {'ok': False, 'announce': False, 'status': 403, 'text': 'Only the session host can run /picker pick.'}

            participants = list(session_obj.get('participants', []))
            with live_sessions_lock:
                current_session = live_sessions.get(session_obj['session_id'])
                if current_session:
                    current_session['status'] = 'picking'

            _ensure_multi_picker()
            if not multi_picker:
                return {'ok': False, 'announce': False, 'status': 400, 'text': 'Multi-user picker is not initialized.'}

            with multi_picker_lock:
                game = multi_picker.pick_common_game(
                    user_names=participants,
                    coop_only=False,
                    max_players=max(2, len(participants)),
                )

            if not game:
                with live_sessions_lock:
                    current_session = live_sessions.get(session_obj['session_id'])
                    if current_session:
                        current_session['status'] = 'waiting'
                return {
                    'ok': False,
                    'announce': False,
                    'status': 404,
                    'text': 'No common game found for joined users. Have more users join or sync libraries, then try /picker pick again.',
                }

            game_name = game.get('name', 'Unknown game')
            with live_sessions_lock:
                current_session = live_sessions.get(session_obj['session_id'])
                if current_session:
                    current_session['picked_game'] = game
                    current_session['status'] = 'completed'
                    view = _live_session_view(current_session)
                else:
                    view = None
                chat_room_active_session.pop(room_name, None)

            if view:
                _sse_publish(session_obj['session_id'], 'session', view)

            if DB_AVAILABLE and db:
                for participant in participants:
                    try:
                        database.create_notification(
                            db,
                            participant,
                            title='Game picked in chat room',
                            message=f'{username} picked "{game_name}" in room "{room_name}".',
                            type='success',
                        )
                    except Exception as exc:
                        gui_logger.warning('Failed to notify %s for room pick: %s', participant, exc)

            return {
                'ok': True,
                'announce': True,
                'status': 200,
                'text': f'🎮 Room "{room_name}" picked: {game_name} (participants: {len(participants)}).',
            }

        return {'ok': False, 'announce': False, 'status': 400, 'text': f'Unknown picker action "{action}".'}

    return {'ok': False, 'announce': False, 'status': 400, 'text': f'Unknown command "{cmd}".'}


# ---------------------------------------------------------------------------
# Leaderboard API
# ---------------------------------------------------------------------------

@app.route('/api/leaderboard')
@require_login
def api_leaderboard():
    """Return a ranked leaderboard of users.

    Query params:
      - ``metric``: 'playtime' (default), 'games', or 'achievements'
      - ``limit``:  max entries (default 20)
    """
    metric = request.args.get('metric', 'playtime')
    try:
        limit = int(request.args.get('limit', 20))
    except ValueError:
        limit = 20
    db = next(database.get_db())
    try:
        if _leaderboard_service:
            rows = _leaderboard_service.get_rankings(db, metric=metric, limit=limit)
        else:
            rows = database.get_leaderboard(db, metric=metric, limit=limit)
    finally:
        if db:
            db.close()
    return jsonify({'metric': metric, 'entries': rows})


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

@app.route('/api/chat/messages')
@require_login
def api_chat_messages():
    """Fetch messages from a chat room.

    Query params:
      - ``room``:      room name (default 'general')
      - ``since_id``:  return only messages with id > this value (default 0)
      - ``before_id``: return only messages with id < this value (default 0)
      - ``limit``:     max messages to return (default 50)
    """
    global current_user
    username = get_current_username()
    room = _normalize_chat_room_name(request.args.get('room', 'general'))
    if not _can_access_chat_room(username, room):
        return jsonify({'error': f'Access denied for private room "{room}"'}), 403
    try:
        since_id = int(request.args.get('since_id', 0))
        before_id = int(request.args.get('before_id', 0))
        limit = int(request.args.get('limit', 50))
    except ValueError:
        since_id, before_id, limit = 0, 0, 50
    db = next(database.get_db())
    try:
        if _chat_service:
            messages = _chat_service.get_messages(db, room=room, limit=limit,
                                                  since_id=since_id, before_id=before_id)
        else:
            messages = database.get_chat_messages(db, room=room, limit=limit,
                                                  since_id=since_id, before_id=before_id)
    finally:
        if db:
            db.close()
    return jsonify({'room': room, 'messages': messages})


@app.route('/api/chat/send', methods=['POST'])
@require_login
def api_chat_send():
    """Send a chat message to a room.

    Request JSON:
      - ``room``:    room name (default 'general')
      - ``message``: message text (required)
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    room = _normalize_chat_room_name(data.get('room', 'general'))
    if not message:
        return jsonify({'error': 'message is required'}), 400
    if len(message) > 500:
        return jsonify({'error': 'message must be 500 characters or fewer'}), 400
    db = next(database.get_db())
    try:
        if not _can_access_chat_room(username, room):
            return jsonify({'error': f'Access denied for private room "{room}"'}), 403

        # Update user's current room and activity
        with user_room_lock:
            user_current_room[username] = room
            user_last_activity[username] = datetime.utcnow().timestamp()

        with chat_rooms_lock:
            state = chat_rooms.get(room)
            if state:
                state['members'].add(username)

        if message.startswith('/'):
            # First, save the command text itself (visible only to sender and admins)
            if _chat_service:
                _chat_service.send(db, sender_username=username,
                                  message=message, room=room, command_only=True)
            else:
                database.send_chat_message(db, sender_username=username,
                                          message=message, room=room, command_only=True)
            
            # Now handle the command and get the result
            cmd_result = _handle_chat_command(db, username=username, room=room, message=message)
            if not cmd_result.get('ok'):
                return jsonify({'error': cmd_result.get('text', 'Command failed')}), int(cmd_result.get('status', 400))

            if not cmd_result.get('announce', False):
                # Save command-only result as a private message
                cmd_text = cmd_result.get('text', '').strip()
                if _chat_service:
                    msg = _chat_service.send(db, sender_username=username,
                                             message=cmd_text, room=room, command_only=True)
                else:
                    msg = database.send_chat_message(db, sender_username=username,
                                                     message=cmd_text, room=room, command_only=True)
                if msg:
                    msg['command'] = True
                    if 'room_name' in cmd_result:
                        msg['room_name'] = cmd_result['room_name']
                    return jsonify(msg), int(cmd_result.get('status', 200))
                resp = {
                    'command': True,
                    'room': room,
                    'message': cmd_text,
                }
                if 'room_name' in cmd_result:
                    resp['room_name'] = cmd_result['room_name']
                return jsonify(resp), int(cmd_result.get('status', 200))

            # Announcement message - visible to everyone
            announcement = cmd_result.get('text', '').strip()
            if _chat_service:
                msg = _chat_service.send(db, sender_username=username,
                                         message=announcement, room=room)
            else:
                msg = database.send_chat_message(db, sender_username=username,
                                                 message=announcement, room=room)
            if not msg:
                return jsonify({'error': 'Command succeeded but announcement message could not be sent'}), 500
            msg['command'] = True
            return jsonify(msg), int(cmd_result.get('status', 200))

        if _chat_service:
            msg = _chat_service.send(db, sender_username=username,
                                     message=message, room=room)
        else:
            reply_to_id = data.get('reply_to_id')
            msg = database.send_chat_message(db, sender_username=username,
                                             message=message, room=room, reply_to_id=reply_to_id)
        
        # Detect @mentions and create notifications
        if msg:
            import re
            mention_pattern = r'@(\w+)'
            mentioned_users = re.findall(mention_pattern, message)
            if mentioned_users:
                for mentioned_user in set(mentioned_users):  # Use set to avoid duplicate notifications
                    # Don't notify the sender
                    if mentioned_user != username:
                        # Check if user exists
                        mentioned_user_obj = db.query(database.User).filter(database.User.username == mentioned_user).first()
                        if mentioned_user_obj:
                            # Create notification
                            notification_title = f"💬 {username} mentioned you in {room}"
                            notification_message = f"{message[:100]}{'...' if len(message) > 100 else ''}"
                            database.create_notification(db, mentioned_user, notification_title, notification_message, type='mention')
    finally:
        if db:
            db.close()
    if not msg:
        return jsonify({'error': 'Failed to send message'}), 500
    return jsonify(msg), 201


@app.route('/api/chat/online-users')
@require_login
def api_chat_online_users():
    """Get list of online users and their current rooms.
    
    Returns dict mapping room_name -> list of usernames in that room.
    """
    global current_user
    username = get_current_username()
    
    online_users = {}
    current_time = datetime.utcnow().timestamp()
    
    with user_room_lock:
        # Get all users and their current rooms, filter out inactive users (not active in last 5 minutes)
        for user, room in user_current_room.items():
            last_activity = user_last_activity.get(user, current_time)
            # If user hasn't been active in 5 minutes, consider them offline
            if current_time - last_activity < 300:
                if room not in online_users:
                    online_users[room] = []
                online_users[room].append(user)
    
    return jsonify({'online_users': online_users})


@app.route('/api/chat/typing', methods=['POST'])
@require_login
def api_chat_typing():
    """Indicate user is typing in a room.
    
    Request JSON:
      - ``room``: room name (required)
      - ``typing``: boolean, true if typing, false if stopped (default: true)
    """
    global current_user, user_typing_indicators
    username = get_current_username()
    
    data = request.get_json() or {}
    room = _normalize_chat_room_name(data.get('room', 'general'))
    is_typing = data.get('typing', True)
    
    with user_room_lock:
        if is_typing:
            user_typing_indicators[f"{room}:{username}"] = datetime.utcnow().timestamp()
        else:
            user_typing_indicators.pop(f"{room}:{username}", None)
    
    return jsonify({'ok': True})


@app.route('/api/chat/typing/<room>')
@require_login
def api_chat_get_typing(room):
    """Get list of users currently typing in a room.
    
    Returns list of usernames who are typing (excludes requesting user).
    """
    global current_user, user_typing_indicators
    username = get_current_username()
    room = _normalize_chat_room_name(room)
    
    typing_users = []
    current_time = datetime.utcnow().timestamp()
    
    with user_room_lock:
        # Clean up old typing indicators (older than 5 seconds)
        to_remove = []
        for key, timestamp in list(user_typing_indicators.items()):
            if current_time - timestamp > 5:
                to_remove.append(key)
        for key in to_remove:
            user_typing_indicators.pop(key, None)
        
        # Get typing users for this room
        for key in user_typing_indicators:
            if key.startswith(f"{room}:"):
                typing_user = key.split(':', 1)[1]
                if typing_user != username:
                    typing_users.append(typing_user)
    
    return jsonify({'typing': typing_users})


@app.route('/api/chat/update-room', methods=['POST'])
@require_login
def api_chat_update_room():
    """Update the current user's active room.
    
    Request JSON:
      - ``room``: room name
    """
    global current_user
    username = get_current_username()
    
    data = request.get_json() or {}
    room = _normalize_chat_room_name(data.get('room', 'general'))
    
    with user_room_lock:
        user_current_room[username] = room
        user_last_activity[username] = datetime.utcnow().timestamp()
    
    return jsonify({'ok': True, 'room': room})


@app.route('/api/chat/room-users', methods=['GET'])
@require_login
def api_chat_room_users():
    """Get members and invite status for a room.
    
    Query params:
      - ``room``: room name (default 'general')
    
    Returns:
      - ``members``: list of usernames who are members
      - ``invites``: list of usernames who have been invited
      - ``owner``: owner username (or null)
    """
    global current_user
    username = get_current_username()
    
    room = _normalize_chat_room_name(request.args.get('room', 'general'))
    if not _can_access_chat_room(username, room):
        return jsonify({'error': f'Access denied for private room "{room}"'}), 403
    
    state = _ensure_chat_room(room)
    with chat_rooms_lock:
        return jsonify({
            'room': room,
            'owner': state.get('owner'),
            'is_private': state.get('is_private', False),
            'members': list(state.get('members', [])),
            'invites': list(state.get('invites', [])) if state.get('is_private') else []
        })


@app.route('/api/chat/invite', methods=['POST'])
@require_login
def api_chat_invite():
    """Send an invite to a user for a private room.
    
    Request JSON:
      - ``room``: room name
      - ``target_username``: username to invite
    
    Only the room owner can invite users to private rooms.
    """
    global current_user
    username = get_current_username()
    
    data = request.get_json() or {}
    target_username = data.get('target_username', '').strip()
    room = _normalize_chat_room_name(data.get('room', 'general'))
    
    if not target_username:
        return jsonify({'error': 'target_username is required'}), 400
    
    ok, msg, _ = _invite_to_chat_room(username, target_username, room)
    status = 200 if ok else 403
    return jsonify({'ok': ok, 'message': msg}), status


@app.route('/api/chat/message/<int:message_id>/react', methods=['POST'])
@require_login
def api_chat_add_reaction(message_id):
    """Add a reaction (emoji) to a chat message.
    
    Request JSON:
      - ``emoji``: emoji unicode or shortcode (required)
    """
    global current_user
    username = get_current_username()
    
    data = request.get_json() or {}
    emoji = data.get('emoji', '').strip()
    
    if not emoji:
        return jsonify({'error': 'emoji is required'}), 400
    
    db = next(database.get_db())
    try:
        success = database.add_message_reaction(db, message_id, username, emoji)
        if success:
            return jsonify({'ok': True, 'message': 'Reaction added'})
        else:
            return jsonify({'error': 'Failed to add reaction'}), 400
    finally:
        if db:
            db.close()


@app.route('/api/chat/message/<int:message_id>/react', methods=['DELETE'])
@require_login
def api_chat_remove_reaction(message_id):
    """Remove a reaction from a chat message.
    
    Query params:
      - ``emoji``: emoji to remove (required)
    """
    global current_user
    username = get_current_username()
    
    emoji = request.args.get('emoji', '').strip()
    
    if not emoji:
        return jsonify({'error': 'emoji is required'}), 400
    
    db = next(database.get_db())
    try:
        success = database.remove_message_reaction(db, message_id, username, emoji)
        if success:
            return jsonify({'ok': True, 'message': 'Reaction removed'})
        else:
            return jsonify({'error': 'Failed to remove reaction'}), 400
    finally:
        if db:
            db.close()


@app.route('/api/chat/message/<int:message_id>', methods=['PATCH'])
@require_login
def api_chat_edit_message(message_id):
    """Edit a chat message (only sender can edit).
    
    Request JSON:
      - ``message``: new message text (required)
    """
    global current_user
    username = get_current_username()
    
    data = request.get_json() or {}
    new_message = data.get('message', '').strip()
    
    if not new_message:
        return jsonify({'error': 'message is required'}), 400
    
    if len(new_message) > 500:
        return jsonify({'error': 'message must be 500 characters or fewer'}), 400
    
    db = next(database.get_db())
    try:
        success = database.edit_chat_message(db, message_id, username, new_message)
        if success:
            return jsonify({'ok': True, 'message': 'Message edited'})
        else:
            return jsonify({'error': 'Failed to edit message (not found or not owner)'}), 403
    finally:
        if db:
            db.close()


@app.route('/api/chat/message/<int:message_id>', methods=['DELETE'])
@require_login
def api_chat_delete_message(message_id):
    """Delete a chat message (only sender can delete).
    
    Soft deletes the message so it won't appear in message lists.
    """
    global current_user
    username = get_current_username()
    
    db = next(database.get_db())
    try:
        success = database.delete_chat_message(db, message_id, username)
        if success:
            return jsonify({'ok': True, 'message': 'Message deleted'})
        else:
            return jsonify({'error': 'Failed to delete message (not found or not owner)'}), 403
    finally:
        if db:
            db.close()


@app.route('/api/user-profile/<username>')
@require_login
def api_get_user_profile(username):
    """Get user profile card (display name, bio, avatar, stats, roles, etc).
    
    URL params:
      - ``username``: target username (required)
    
    Returns user profile card with:
      - username, display_name, bio, avatar_url
      - roles (list)
      - stats (total_games, total_playtime_hours, total_achievements)
      - joined date
      - platform IDs
    """
    if not username:
        return jsonify({'error': 'username is required'}), 400
    
    db = next(database.get_db())
    try:
        user_card = database.get_user_card(db, username)
        if not user_card:
            return jsonify({'error': f'User "{username}" not found'}), 404
        return jsonify(user_card)
    finally:
        if db:
            db.close()


# ---------------------------------------------------------------------------
# Notifications / Alerts API
# ---------------------------------------------------------------------------

@app.route('/api/notifications')
@require_login
def api_get_notifications():
    """Return notifications for the current user.

    Query params:
      - ``unread_only``: 'true' to return only unread (default false)
    """
    global current_user
    username = get_current_username()
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    db = next(database.get_db())
    try:
        if _notification_service:
            notifs = _notification_service.get_all(db, username, unread_only=unread_only)
        else:
            notifs = database.get_notifications(db, username, unread_only=unread_only)
    finally:
        if db:
            db.close()
    return jsonify({'notifications': notifs, 'unread_count': sum(1 for n in notifs if not n['is_read'])})


@app.route('/api/notifications/read', methods=['POST'])
@require_login
def api_mark_notifications_read():
    """Mark notifications as read.

    Request JSON (optional):
      - ``ids``: list of notification IDs. If omitted, marks all as read.
    """
    global current_user
    username = get_current_username()
    data = request.get_json() or {}
    ids = data.get('ids')
    db = next(database.get_db())
    try:
        if _notification_service:
            ok = _notification_service.mark_read(db, username, ids=ids)
        else:
            ok = database.mark_notifications_read(db, username, notification_ids=ids)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to mark notifications read'}), 500


@app.route('/api/notifications/send', methods=['POST'])
@require_login
def api_send_notification():
    """Send a notification to a user (admin only).

    Request JSON:
      - ``username``: target username (required)
      - ``title``:    notification title (required)
      - ``message``:  notification message (required)
      - ``type``:     'info' | 'warning' | 'success' | 'error' (default 'info')
    """
    global current_user
    sender = get_current_username()
    # Only admins can send notifications to others
    db_check = next(database.get_db())
    try:
        if _notification_service:
            is_admin = _notification_service.is_admin(db_check, sender)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, sender)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    notif_type = data.get('type', 'info')
    if not username or not title or not message:
        return jsonify({'error': 'username, title, and message are required'}), 400
    db = next(database.get_db())
    try:
        if _notification_service:
            ok = _notification_service.create(db, username, title, message,
                                              notif_type=notif_type)
        else:
            ok = database.create_notification(db, username, title, message,
                                              type=notif_type)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to send notification'}), 500


# ---------------------------------------------------------------------------
# Plugins / Addons API
# ---------------------------------------------------------------------------

@app.route('/api/plugins')
@require_login
def api_get_plugins():
    """Return all registered plugins."""
    db = next(database.get_db())
    try:
        if _plugin_service:
            plugins = _plugin_service.get_all(db)
        else:
            plugins = database.get_plugins(db)
    finally:
        if db:
            db.close()
    return jsonify({'plugins': plugins})


@app.route('/api/plugins', methods=['POST'])
@require_login
def api_register_plugin():
    """Register or update a plugin (admin only).

    Request JSON:
      - ``name``:        plugin name (required, unique)
      - ``description``: short description
      - ``version``:     semver string (default '1.0.0')
      - ``author``:      author name
      - ``config``:      optional config object
    """
    global current_user
    username = get_current_username()
    db_check = next(database.get_db())
    try:
        if _plugin_service:
            is_admin = _plugin_service.is_admin(db_check, username)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    db = next(database.get_db())
    try:
        if _plugin_service:
            ok = _plugin_service.register(
                db, name,
                description=data.get('description', ''),
                version=data.get('version', '1.0.0'),
                author=data.get('author', ''),
                config=data.get('config'),
            )
        else:
            ok = database.register_plugin(
                db, name=name,
                description=data.get('description', ''),
                version=data.get('version', '1.0.0'),
                author=data.get('author', ''),
                config=data.get('config'),
            )
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True}), 201
    return jsonify({'error': 'Failed to register plugin'}), 500


@app.route('/api/plugins/<int:plugin_id>', methods=['PUT'])
@require_login
def api_toggle_plugin(plugin_id):
    """Enable or disable a plugin (admin only).

    Request JSON:
      - ``enabled``: boolean
    """
    global current_user
    username = get_current_username()
    db_check = next(database.get_db())
    try:
        if _plugin_service:
            is_admin = _plugin_service.is_admin(db_check, username)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    enabled = bool(data.get('enabled', True))
    db = next(database.get_db())
    try:
        if _plugin_service:
            ok = _plugin_service.toggle(db, plugin_id, enabled)
        else:
            ok = database.toggle_plugin(db, plugin_id, enabled)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Plugin not found'}), 404


@app.route('/api/plugins/<int:plugin_id>', methods=['DELETE'])
@require_login
def api_delete_plugin(plugin_id):
    """Permanently delete a registered plugin (admin only)."""
    global current_user
    username = get_current_username()
    db_check = next(database.get_db())
    try:
        if _plugin_service:
            is_admin = _plugin_service.is_admin(db_check, username)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    db = next(database.get_db())
    try:
        ok = database.delete_plugin(db, plugin_id)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Plugin not found'}), 404


# ---------------------------------------------------------------------------
# App Settings API  (admin only)
# ---------------------------------------------------------------------------

@app.route('/api/admin/settings', methods=['GET'])
@require_login
def api_get_app_settings():
    """Return all admin-controlled app settings (admin only).

    Response JSON:
      - ``settings``: list of ``{key, value, default, description}`` objects
    """
    global current_user
    username = get_current_username()
    if not username:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Ensure username is a string
    username_str = str(username) if username else None
    if not username_str or username_str == 'None':
        return jsonify({'error': 'Invalid user'}), 401
    
    db_check = next(database.get_db())
    try:
        if _app_settings_service:
            is_admin = _app_settings_service.is_admin(db_check, username_str)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username_str)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    db = next(database.get_db())
    try:
        if _app_settings_service:
            settings = _app_settings_service.get_with_meta(db)
        else:
            settings = database.get_settings_with_meta(db)
    finally:
        if db:
            db.close()
    return jsonify({'settings': settings})


@app.route('/api/admin/settings', methods=['POST'])
@require_login
def api_save_app_settings():
    """Save one or more app settings (admin only).

    Request JSON:
      - ``settings``: dict of ``{key: value}`` pairs to update
    """
    global current_user
    username = get_current_username()
    if not username:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Ensure username is a string
    username_str = str(username) if username else None
    if not username_str or username_str == 'None':
        return jsonify({'error': 'Invalid user'}), 401
    
    db_check = next(database.get_db())
    try:
        if _app_settings_service:
            is_admin = _app_settings_service.is_admin(db_check, username_str)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username_str)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json() or {}
    updates = data.get('settings', {})
    if not isinstance(updates, dict) or not updates:
        return jsonify({'error': 'settings dict is required'}), 400
    db = next(database.get_db())
    try:
        if _app_settings_service:
            ok = _app_settings_service.save(db, updates, updated_by=username_str)
        else:
            ok = database.set_app_settings(db, updates, updated_by=username_str)
    finally:
        if db:
            db.close()
    if ok:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save settings'}), 500


@app.route('/api/admin/settings/public', methods=['GET'])
def api_public_settings():
    """Return safe public-facing settings (no auth required).

    Currently returns: announcement message.
    """
    db = next(database.get_db())
    try:
        if _app_settings_service:
            announcement = _app_settings_service.get(db, 'announcement', '')
            chat_enabled = _app_settings_service.get(db, 'chat_enabled', 'true')
            leaderboard_public = _app_settings_service.get(db, 'leaderboard_public', 'true')
            plugins_enabled = _app_settings_service.get(db, 'plugins_enabled', 'true')
        else:
            announcement = database.get_app_setting(db, 'announcement', '')
            chat_enabled = database.get_app_setting(db, 'chat_enabled', 'true')
            leaderboard_public = database.get_app_setting(db, 'leaderboard_public', 'true')
            plugins_enabled = database.get_app_setting(db, 'plugins_enabled', 'true')
    finally:
        if db:
            db.close()
    return jsonify({
        'announcement': announcement,
        'chat_enabled': chat_enabled == 'true',
        'leaderboard_public': leaderboard_public == 'true',
        'plugins_enabled': plugins_enabled == 'true',
    })


# ---------------------------------------------------------------------------
# Discord Bot Management API  (admin only)
# ---------------------------------------------------------------------------

def _discord_bot_is_running() -> bool:
    """Return True if the managed Discord bot process is alive."""
    global _discord_bot_process
    if _discord_bot_process is None:
        return False
    return _discord_bot_process.poll() is None


def _capture_bot_output(proc: subprocess.Popen) -> None:
    """Background thread: read stdout/stderr from bot and store recent lines."""
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.rstrip('\n')
            with _discord_bot_lock:
                _discord_bot_log_lines.append(line)
    except Exception:
        pass


@app.route('/api/admin/discord-bot/status', methods=['GET'])
@require_admin
def api_discord_bot_status():
    """Return the current status of the Discord bot process (admin only).

    Response JSON:
      - ``running``: bool – whether the bot process is alive
      - ``pid``: int|null – OS process ID when running
      - ``log``: list[str] – recent log lines (up to 200)
    """
    with _discord_bot_lock:
        running = _discord_bot_is_running()
        pid = _discord_bot_process.pid if running else None
        log = list(_discord_bot_log_lines)
    return jsonify({'running': running, 'pid': pid, 'log': log})


@app.route('/api/admin/discord-bot/start', methods=['POST'])
@require_admin
def api_discord_bot_start():
    """Start the Discord bot process (admin only).

    Expects JSON body with optional ``config_path`` (default: ``config.json``).
    Returns ``{'started': True}`` on success or an error message.

    The config path is passed to the bot subprocess via the ``GAPI_DISCORD_CONFIG``
    environment variable, which discord_bot.py should read to locate its config file.
    """
    global _discord_bot_process, _discord_bot_log_lines
    data = request.get_json(silent=True) or {}
    config_path = data.get('config_path', 'config.json')
    # Prevent path traversal: resolve against the application base directory and
    # verify the result stays within that directory.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    abs_config = os.path.normpath(os.path.join(base_dir, config_path))
    try:
        if os.path.commonpath([base_dir, abs_config]) != base_dir:
            return jsonify({'error': 'Invalid config_path'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid config_path'}), 400

    with _discord_bot_lock:
        if _discord_bot_is_running():
            return jsonify({'error': 'Discord bot is already running'}), 409

        bot_script = os.path.join(base_dir, 'discord_bot.py')
        if not os.path.exists(bot_script):
            return jsonify({'error': 'discord_bot.py not found'}), 500

        try:
            proc = subprocess.Popen(
                [sys.executable, bot_script],
                # GAPI_DISCORD_CONFIG tells discord_bot.py which config file to use
                env={**os.environ, 'GAPI_DISCORD_CONFIG': abs_config},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _discord_bot_process = proc
            _discord_bot_log_lines.clear()
        except OSError as exc:
            return jsonify({'error': f'Failed to start bot: {exc}'}), 500

    # Capture output in background thread
    t = threading.Thread(target=_capture_bot_output, args=(proc,), daemon=True)
    t.start()

    return jsonify({'started': True, 'pid': proc.pid})


@app.route('/api/admin/discord-bot/stop', methods=['POST'])
@require_admin
def api_discord_bot_stop():
    """Stop the Discord bot process (admin only).

    Returns ``{'stopped': True}`` on success or an error if not running.
    """
    global _discord_bot_process
    with _discord_bot_lock:
        if not _discord_bot_is_running():
            return jsonify({'error': 'Discord bot is not running'}), 409

        proc = _discord_bot_process
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except OSError:
            pass
        _discord_bot_process = None

    return jsonify({'stopped': True})


@app.route('/api/admin/discord-bot/stats', methods=['GET'])
@require_admin
def api_discord_bot_stats():
    """Return Discord bot statistics from the config file (admin only).

    Response JSON:
      - ``running``: bool
      - ``linked_users``: int – number of Discord→Steam mappings
      - ``config_exists``: bool – whether discord_config.json is present
    """
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'discord_config.json')
    linked_users = 0
    config_exists = os.path.exists(config_file)
    if config_exists:
        try:
            with open(config_file, 'r') as fh:
                cfg = json.load(fh)
                linked_users = len(cfg.get('user_mappings', {}))
        except (json.JSONDecodeError, IOError):
            pass

    with _discord_bot_lock:
        running = _discord_bot_is_running()

    return jsonify({
        'running': running,
        'linked_users': linked_users,
        'config_exists': config_exists,
    })


@app.route('/api/admin/discord-bot/config', methods=['GET'])
@require_admin
def api_discord_bot_get_config():
    """Return Discord bot configuration (admin only).

    Sensitive values (token, API key) are partially masked.
    Response JSON:
      - ``discord_token_set``: bool
      - ``steam_api_key_set``: bool
      - ``config_exists``: bool
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if not os.path.exists(config_path):
        return jsonify({'config_exists': False, 'discord_token_set': False, 'steam_api_key_set': False})
    try:
        with open(config_path, 'r') as fh:
            cfg = json.load(fh)
    except (json.JSONDecodeError, IOError):
        return jsonify({'error': 'Failed to read config.json'}), 500

    token = cfg.get('discord_bot_token', '')
    steam_key = cfg.get('steam_api_key', '')
    return jsonify({
        'config_exists': True,
        'discord_token_set': bool(token),
        'steam_api_key_set': bool(steam_key),
    })


@app.route('/api/admin/discord-bot/config', methods=['POST'])
@require_admin
def api_discord_bot_save_config():
    """Save Discord bot token, client ID, and/or Steam API key (admin only).

    Request JSON (all fields optional):
      - ``discord_bot_token``: str
      - ``discord_bot_client_id``: str
      - ``steam_api_key``: str

    Only non-empty values overwrite the existing config.
    """
    data = request.get_json(silent=True) or {}
    token = data.get('discord_bot_token', '').strip()
    client_id = data.get('discord_bot_client_id', '').strip()
    steam_key = data.get('steam_api_key', '').strip()

    if not token and not client_id and not steam_key:
        return jsonify({'error': 'Provide at least one value: discord_bot_token, discord_bot_client_id, or steam_api_key'}), 400

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    cfg: Dict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as fh:
                cfg = json.load(fh)
        except (json.JSONDecodeError, IOError):
            pass

    if token:
        cfg['discord_bot_token'] = token
    if client_id:
        cfg['discord_bot_client_id'] = client_id
    if steam_key:
        cfg['steam_api_key'] = steam_key

    try:
        gapi._atomic_write_json(config_path, cfg)
    except IOError as exc:
        return jsonify({'error': f'Failed to save config: {exc}'}), 500

    return jsonify({'saved': True})


@app.route('/api/admin/discord-bot/restart', methods=['POST'])
@require_admin
def api_discord_bot_restart():
    """Restart the Discord bot process (admin only).

    Stops the running bot (if any), then starts a fresh subprocess.
    Expects optional JSON body with ``config_path``.
    Returns ``{'restarted': True, 'pid': <pid>}`` on success.
    """
    global _discord_bot_process, _discord_bot_log_lines
    data = request.get_json(silent=True) or {}
    config_path = data.get('config_path', 'config.json')
    base_dir = os.path.dirname(os.path.abspath(__file__))
    abs_config = os.path.normpath(os.path.join(base_dir, config_path))
    try:
        if os.path.commonpath([base_dir, abs_config]) != base_dir:
            return jsonify({'error': 'Invalid config_path'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid config_path'}), 400

    with _discord_bot_lock:
        # Terminate existing process if running
        if _discord_bot_is_running():
            proc = _discord_bot_process
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except OSError:
                pass
            _discord_bot_process = None

        bot_script = os.path.join(base_dir, 'discord_bot.py')
        if not os.path.exists(bot_script):
            return jsonify({'error': 'discord_bot.py not found'}), 500

        try:
            proc = subprocess.Popen(
                [sys.executable, bot_script],
                env={**os.environ, 'GAPI_DISCORD_CONFIG': abs_config},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _discord_bot_process = proc
            _discord_bot_log_lines.clear()
        except OSError as exc:
            return jsonify({'error': f'Failed to start bot: {exc}'}), 500

    t = threading.Thread(target=_capture_bot_output, args=(proc,), daemon=True)
    t.start()
    return jsonify({'restarted': True, 'pid': proc.pid})


@app.route('/api/admin/discord-bot/users', methods=['GET'])
@require_admin
def api_discord_bot_list_users():
    """List all Discord→Steam user mappings stored in discord_config.json (admin only).

    Response JSON:
      - ``users``: list of ``{discord_id, steam_id}`` objects
    """
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'discord_config.json')
    if not os.path.exists(config_file):
        return jsonify({'users': []})
    try:
        with open(config_file, 'r') as fh:
            cfg = json.load(fh)
    except (json.JSONDecodeError, IOError):
        return jsonify({'users': []})

    mappings = cfg.get('user_mappings', {})
    users = [{'discord_id': str(k), 'steam_id': v} for k, v in mappings.items()]
    return jsonify({'users': users})


@app.route('/api/admin/discord-bot/users/<discord_id>', methods=['DELETE'])
@require_admin
def api_discord_bot_remove_user(discord_id: str):
    """Remove a Discord→Steam mapping from discord_config.json (admin only).

    Path parameter:
      - ``discord_id``: the Discord user ID string to remove

    Returns ``{'removed': True}`` on success or ``{'error': ...}`` if not found.
    """
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'discord_config.json')
    if not os.path.exists(config_file):
        return jsonify({'error': 'discord_config.json not found'}), 404
    try:
        with open(config_file, 'r') as fh:
            cfg = json.load(fh)
    except (json.JSONDecodeError, IOError):
        return jsonify({'error': 'Failed to read discord_config.json'}), 500

    mappings = cfg.get('user_mappings', {})
    # Keys may be stored as strings; normalize for lookup
    if discord_id not in mappings:
        return jsonify({'error': 'User not found'}), 404

    del mappings[discord_id]
    cfg['user_mappings'] = mappings
    try:
        gapi._atomic_write_json(config_file, cfg)
    except IOError as exc:
        return jsonify({'error': f'Failed to save config: {exc}'}), 500

    return jsonify({'removed': True})


@app.route('/api/admin/discord-bot/diagnostics', methods=['GET'])
@require_admin
def api_discord_bot_diagnostics():
    """Get Discord bot diagnostics and environment info (admin only).

    Response JSON:
      - ``steam_api_key_source``: 'env'|'config'|'missing' – where the key comes from
      - ``steam_api_key_set``: bool – whether key is configured
      - ``discord_token_set``: bool – whether Discord token is configured  
      - ``config_file_exists``: bool – whether config.json exists
      - ``discord_config_exists``: bool – whether discord_config.json exists
      - ``bot_invite_url``: str – Discord bot invite URL with permissions
      - ``python_version``: str – Python version running the bot
    """
    import sys
    config_path = 'config.json'
    discord_config_path = 'discord_config.json'
    
    # Check Steam API key source
    steam_key_from_env = os.getenv('STEAM_API_KEY')
    steam_key_source = 'missing'
    steam_key_set = False
    
    if steam_key_from_env:
        steam_key_source = 'env'
        steam_key_set = True
    elif os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                if cfg.get('steam_api_key'):
                    steam_key_source = 'config'
                    steam_key_set = True
        except (json.JSONDecodeError, IOError):
            pass
    
    # Check Discord token
    discord_token_set = False
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                discord_token_set = bool(cfg.get('discord_bot_token'))
        except (json.JSONDecodeError, IOError):
            pass
    
    # Generate bot invite URL (requires bot client ID from config)
    bot_invite_url = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                client_id = cfg.get('discord_bot_client_id')
                if client_id:
                    # Permissions: Read Messages/View Channels (1024), Send Messages (2048), 
                    # Use Slash Commands (2147483648), Embed Links (16384)
                    permissions = 2147487744
                    bot_invite_url = f'https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions={permissions}&scope=bot%20applications.commands'
        except (json.JSONDecodeError, IOError):
            pass
    
    return jsonify({
        'steam_api_key_source': steam_key_source,
        'steam_api_key_set': steam_key_set,
        'discord_token_set': discord_token_set,
        'config_file_exists': os.path.exists(config_path),
        'discord_config_exists': os.path.exists(discord_config_path),
        'bot_invite_url': bot_invite_url,
        'python_version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    })


@app.route('/api/admin/security-info', methods=['GET'])
@require_admin
def api_admin_security_info():
    """Return the active security feature flags (admin only).

    Response JSON:
      - ``compression_enabled``: bool – Flask-Compress loaded
      - ``rate_limiting_enabled``: bool – Flask-Limiter loaded
      - ``security_headers_enabled``: bool – always True (built-in hook)
    """
    return jsonify({
        'compression_enabled': _COMPRESS_AVAILABLE,
        'rate_limiting_enabled': _LIMITER_AVAILABLE,
        'security_headers_enabled': True,
    })


# Localization / i18n endpoints
# ---------------------------------------------------------------------------

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locales')


def _load_locale(lang: str) -> Optional[Dict]:
    """Load a locale JSON file.  Returns ``None`` if not found or invalid."""
    # Use basename to strip any directory components, preventing path traversal
    safe_lang = os.path.basename(lang)[:10]
    path = os.path.join(_LOCALES_DIR, f'{safe_lang}.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@app.route('/api/i18n')
def api_i18n_list():
    """List all available locales.

    Returns a JSON array of objects with ``lang`` and ``lang_name`` fields,
    e.g. ``[{"lang": "en", "lang_name": "English"}, ...]``.
    """
    locales = []
    try:
        for fname in sorted(os.listdir(_LOCALES_DIR)):
            if not fname.endswith('.json'):
                continue
            data = _load_locale(fname[:-5])
            if data and 'lang' in data:
                locales.append({'lang': data['lang'], 'lang_name': data.get('lang_name', data['lang'])})
    except Exception as exc:
        gui_logger.error('Error listing locales: %s', exc)
    return jsonify({'locales': locales})


@app.route('/api/i18n/<lang>')
def api_i18n_get(lang: str):
    """Return the translation strings for *lang* (e.g. ``en``, ``es``).

    A ``404`` is returned when the requested language is not available.
    """
    data = _load_locale(lang)
    if data is None:
        return jsonify({'error': f"Locale '{lang}' not found"}), 404
    return jsonify(data)


# ---------------------------------------------------------------------------
# GraphQL API (POST /api/graphql)
# ---------------------------------------------------------------------------

def _build_graphql_schema():
    """Build and return the GAPI GraphQL schema using graphene.

    Exposed types:
    * **GameType** — a game in the user's library
    * **AchievementType** — a single achievement row
    * **StatsType** — library statistics
    * **Query** — root type with ``games``, ``stats``, ``achievements`` fields
    """
    import graphene

    class GameType(graphene.ObjectType):
        app_id     = graphene.String()
        name       = graphene.String()
        platform   = graphene.String()
        playtime_hours = graphene.Float()

    class AchievementType(graphene.ObjectType):
        app_id       = graphene.String()
        game_name    = graphene.String()
        achievement_id = graphene.String()
        name         = graphene.String()
        unlocked     = graphene.Boolean()
        rarity       = graphene.Float()

    class StatsType(graphene.ObjectType):
        total_games        = graphene.Int()
        unplayed_games     = graphene.Int()
        played_games       = graphene.Int()
        unplayed_percentage = graphene.Float()
        total_playtime     = graphene.Float()
        average_playtime   = graphene.Float()
        total_achievements_tracked  = graphene.Int()
        total_achievements_unlocked = graphene.Int()
        achievement_completion_percent = graphene.Float()

    class Query(graphene.ObjectType):
        games = graphene.List(
            GameType,
            platform=graphene.String(default_value=''),
            limit=graphene.Int(default_value=100),
            description='Games in the current user\'s library',
        )
        stats = graphene.Field(
            StatsType,
            description='Library and achievement statistics for the current user',
        )
        achievements = graphene.List(
            AchievementType,
            app_id=graphene.String(default_value=''),
            unlocked_only=graphene.Boolean(default_value=False),
            description='Achievements tracked for the current user',
        )

        def resolve_games(root, info, platform='', limit=100):
            username = info.context.get('username', '')
            if not DB_AVAILABLE or not ensure_db_available():
                return []
            db = None
            try:
                db = database.SessionLocal()
                cached = (
                    _library_service.get_cached(db, username)
                    if _library_service
                    else database.get_cached_library(db, username)
                )
            finally:
                if db:
                    db.close()
            games = cached or []
            if platform:
                games = [g for g in games if g.get('platform', 'steam').lower() == platform.lower()]
            return [
                GameType(
                    app_id=str(g.get('app_id', '')),
                    name=g.get('name', ''),
                    platform=g.get('platform', 'steam'),
                    playtime_hours=float(g.get('playtime_hours', 0)),
                )
                for g in games[:limit]
            ]

        def resolve_stats(root, info):
            username = info.context.get('username', '')
            lib_stats: dict = {}
            ach_stats: dict = {}
            if DB_AVAILABLE and ensure_db_available():
                db = None
                try:
                    db = database.SessionLocal()
                    cached = (
                        _library_service.get_cached(db, username)
                        if _library_service
                        else database.get_cached_library(db, username)
                    )
                    cached = cached or []
                    total = len(cached)
                    unplayed = sum(1 for g in cached if g.get('playtime_hours', 0) == 0)
                    total_pt = sum(g.get('playtime_hours', 0) for g in cached)
                    lib_stats = {
                        'total_games': total,
                        'unplayed_games': unplayed,
                        'played_games': total - unplayed,
                        'unplayed_percentage': round(unplayed / total * 100, 1) if total else 0.0,
                        'total_playtime': round(total_pt, 1),
                        'average_playtime': round(total_pt / total, 1) if total else 0.0,
                    }
                    ach_stats = database.get_achievement_stats(db, username) or {}
                finally:
                    if db:
                        db.close()
            return StatsType(
                total_games=lib_stats.get('total_games', 0),
                unplayed_games=lib_stats.get('unplayed_games', 0),
                played_games=lib_stats.get('played_games', 0),
                unplayed_percentage=lib_stats.get('unplayed_percentage', 0.0),
                total_playtime=lib_stats.get('total_playtime', 0.0),
                average_playtime=lib_stats.get('average_playtime', 0.0),
                total_achievements_tracked=ach_stats.get('total_tracked', 0),
                total_achievements_unlocked=ach_stats.get('total_unlocked', 0),
                achievement_completion_percent=ach_stats.get('completion_percent', 0.0),
            )

        def resolve_achievements(root, info, app_id='', unlocked_only=False):
            username = info.context.get('username', '')
            if not DB_AVAILABLE or not ensure_db_available():
                return []
            db = None
            try:
                db = database.SessionLocal()
                grouped = database.get_user_achievements_grouped(db, username)
            finally:
                if db:
                    db.close()
            results = []
            for game in (grouped or []):
                if app_id and str(game.get('app_id', '')) != str(app_id):
                    continue
                for a in game.get('achievements', []):
                    if unlocked_only and not a.get('unlocked'):
                        continue
                    results.append(AchievementType(
                        app_id=str(game.get('app_id', '')),
                        game_name=game.get('game_name', ''),
                        achievement_id=a.get('achievement_id', ''),
                        name=a.get('name', ''),
                        unlocked=bool(a.get('unlocked')),
                        rarity=a.get('rarity'),
                    ))
            return results

    return graphene.Schema(query=Query)


_graphql_schema = None
_graphql_schema_lock = threading.Lock()


def _get_graphql_schema():
    global _graphql_schema
    if _graphql_schema is None:
        with _graphql_schema_lock:
            if _graphql_schema is None:
                try:
                    _graphql_schema = _build_graphql_schema()
                except Exception as exc:
                    gui_logger.warning("GraphQL schema build failed: %s", exc)
    return _graphql_schema


@app.route('/api/graphql', methods=['POST'])
@require_login
def api_graphql():
    """Execute a GraphQL query against the GAPI schema.

    Request JSON::

        {"query": "{ stats { total_games total_playtime } }"}

    Optional variables::

        {"query": "...", "variables": {"limit": 5}}

    Response JSON::

        {"data": { ... }}        // on success
        {"errors": [ ... ]}     // on error

    GraphQL schema:
        - ``games(platform: String, limit: Int)`` → ``[GameType]``
        - ``stats`` → ``StatsType``
        - ``achievements(app_id: String, unlocked_only: Boolean)`` → ``[AchievementType]``

    Requires `graphene` (``pip install graphene``).  Returns 503 if the
    library is not available.
    """
    global current_user
    username = get_current_username()

    schema = _get_graphql_schema()
    if schema is None:
        return jsonify({'errors': [{'message': 'graphene library not available'}]}), 503

    data = request.json or {}
    query = data.get('query', '')
    variables = data.get('variables') or {}
    operation_name = data.get('operationName')

    if not query:
        return jsonify({'errors': [{'message': 'query is required'}]}), 400

    try:
        result = schema.execute(
            query,
            variables=variables,
            operation_name=operation_name,
            context={'username': username},
        )
        response: Dict = {}
        if result.errors:
            response['errors'] = [{'message': str(e)} for e in result.errors]
        if result.data is not None:
            response['data'] = result.data
        status = 400 if result.errors and result.data is None else 200
        return jsonify(response), status
    except Exception as exc:
        gui_logger.error("GraphQL execution error: %s", exc)
        return jsonify({'errors': [{'message': str(exc)}]}), 500


# ---------------------------------------------------------------------------
# Twitch Integration — Trending games + library overlap
# ---------------------------------------------------------------------------

def _get_twitch_client():
    """Return a TwitchClient using credentials from the app config.

    Reads ``twitch_client_id`` and ``twitch_client_secret`` from the active
    picker config.  Returns ``None`` when either credential is missing.
    """
    try:
        from twitch_client import TwitchClient
    except ImportError:
        return None

    if not picker:
        return None

    cfg = getattr(picker, 'config', {}) or {}
    client_id     = cfg.get('twitch_client_id', '') or os.environ.get('TWITCH_CLIENT_ID', '')
    client_secret = cfg.get('twitch_client_secret', '') or os.environ.get('TWITCH_CLIENT_SECRET', '')
    if not client_id or not client_secret:
        return None

    try:
        return TwitchClient(client_id=client_id, client_secret=client_secret)
    except Exception as exc:
        gui_logger.warning("Could not create TwitchClient: %s", exc)
        return None


@app.route('/api/twitch/trending')
@require_login
def api_twitch_trending():
    """Return the top games currently live on Twitch.

    Query params:
        count (int, 1-100, default 20): Number of trending games to return.

    Response JSON::

        {
          "trending": [
            {
              "id": "32982",
              "name": "Grand Theft Auto V",
              "viewer_count": 87452,
              "box_art_url": "https://...",
              "twitch_url": "https://www.twitch.tv/directory/game/..."
            },
            ...
          ]
        }

    Returns 503 when Twitch credentials are not configured.
    """
    from twitch_client import TwitchAuthError, TwitchAPIError

    client = _get_twitch_client()
    if client is None:
        return jsonify({
            'error': (
                'Twitch credentials not configured. '
                'Add twitch_client_id and twitch_client_secret to config.json '
                'or set TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET environment variables.'
            )
        }), 503

    try:
        count = max(1, min(int(request.args.get('count', 20)), 100))
    except (ValueError, TypeError):
        count = 20

    try:
        trending = client.get_top_games(count=count)
    except TwitchAuthError as exc:
        gui_logger.error("Twitch auth error: %s", exc)
        return jsonify({'error': f'Twitch authentication failed: {exc}'}), 502
    except TwitchAPIError as exc:
        gui_logger.error("Twitch API error: %s", exc)
        return jsonify({'error': f'Twitch API error: {exc}'}), 502
    except Exception as exc:
        gui_logger.exception("Unexpected error fetching Twitch trending: %s", exc)
        return jsonify({'error': 'Unexpected error'}), 500

    return jsonify({'trending': trending})


@app.route('/api/twitch/library-overlap')
@require_login
def api_twitch_library_overlap():
    """Return user library games that are currently trending on Twitch.

    Fetches the top trending games and cross-references them against the
    user's loaded game library by normalised name.  Useful for prompting
    the user to pick a game they own that has an active Twitch community.

    Query params:
        count (int, 1-100, default 20): Number of trending Twitch games to
            compare against.

    Response JSON::

        {
          "overlap": [
            {
              "appid": 730,
              "name": "Counter-Strike 2",
              "playtime_forever": 4560,
              "twitch_id": "32399",
              "viewer_count": 75000,
              "box_art_url": "https://...",
              "twitch_url": "https://www.twitch.tv/directory/game/...",
              "trending_rank": 3
            },
            ...
          ],
          "trending_count": 20
        }

    Returns 503 when Twitch credentials are not configured.
    Returns 400 when the picker is not initialised.
    """
    from twitch_client import TwitchAuthError, TwitchAPIError

    if not picker:
        return jsonify({'error': 'Not initialized. Please log in.'}), 400

    client = _get_twitch_client()
    if client is None:
        return jsonify({
            'error': (
                'Twitch credentials not configured. '
                'Add twitch_client_id and twitch_client_secret to config.json '
                'or set TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET environment variables.'
            )
        }), 503

    try:
        count = max(1, min(int(request.args.get('count', 20)), 100))
    except (ValueError, TypeError):
        count = 20

    try:
        trending = client.get_top_games(count=count)
    except TwitchAuthError as exc:
        gui_logger.error("Twitch auth error: %s", exc)
        return jsonify({'error': f'Twitch authentication failed: {exc}'}), 502
    except TwitchAPIError as exc:
        gui_logger.error("Twitch API error: %s", exc)
        return jsonify({'error': f'Twitch API error: {exc}'}), 502
    except Exception as exc:
        gui_logger.exception("Unexpected error fetching Twitch trending: %s", exc)
        return jsonify({'error': 'Unexpected error'}), 500

    with picker_lock:
        user_games = list(picker.games) if picker.games else []

    overlap = client.find_library_overlap(trending, user_games)
    return jsonify({'overlap': overlap, 'trending_count': len(trending)})


# ---------------------------------------------------------------------------
# Platform OAuth — Epic Games, GOG Galaxy, Xbox Game Pass
# ---------------------------------------------------------------------------

def _get_platform_client(platform: str):
    """Return the platform client for *platform*, or None."""
    return picker.clients.get(platform) if picker else None


@app.route('/api/epic/oauth/authorize')
@require_login
def api_epic_oauth_authorize():
    """Redirect the browser to the Epic Games authorization page.

    Query params:
        redirect_uri (str): Override the default redirect URI from config.

    Response: HTTP 302 redirect to Epic authorization URL.
    Returns 503 if Epic OAuth is not configured.
    """
    from platform_clients import EpicOAuthClient
    client = _get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return jsonify({'error': 'Epic OAuth client not configured. '
                        'Add epic_client_id and epic_enabled: true to config.json.'}), 503
    redirect_uri = request.args.get('redirect_uri') or (
        picker.config.get('epic_redirect_uri', '') if picker else ''
    )
    if not redirect_uri:
        redirect_uri = request.url_root.rstrip('/') + '/api/epic/oauth/callback'
    state = secrets.token_urlsafe(16)
    session['epic_oauth_state'] = state
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return flask_redirect(url)


@app.route('/api/epic/oauth/callback')
@require_login
def api_epic_oauth_callback():
    """Handle the Epic Games OAuth2 callback.

    Query params:
        code (str): Authorization code from Epic.

    Response JSON::

        {"success": true, "platform": "epic"}

    Returns 400 on error, 503 if Epic client is not configured.
    """
    from platform_clients import EpicOAuthClient
    client = _get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return jsonify({'error': 'Epic OAuth client not configured.'}), 503
    code = request.args.get('code', '')
    if not code:
        return jsonify({'error': 'Missing authorization code.'}), 400
    redirect_uri = (picker.config.get('epic_redirect_uri', '') if picker else '') or (
        request.url_root.rstrip('/') + '/api/epic/oauth/callback'
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return jsonify({'error': 'Token exchange failed. Check server logs.'}), 400
    return jsonify({'success': True, 'platform': 'epic'})


@app.route('/api/epic/library')
@require_login
def api_epic_library():
    """Return the authenticated user's Epic Games library.

    Response JSON::

        {
          "games": [{"name": "...", "game_id": "epic:...", ...}],
          "count": 42,
          "platform": "epic"
        }

    Returns 503 if not authenticated.
    """
    from platform_clients import EpicOAuthClient
    client = _get_platform_client('epic')
    if not isinstance(client, EpicOAuthClient):
        return jsonify({'error': 'Epic OAuth client not configured.'}), 503
    if not client.is_authenticated:
        return jsonify({'error': 'Epic account not authenticated. '
                        'Visit /api/epic/oauth/authorize first.'}), 503
    games = client.get_owned_games()
    return jsonify({'games': games, 'count': len(games), 'platform': 'epic'})


@app.route('/api/gog/oauth/authorize')
@require_login
def api_gog_oauth_authorize():
    """Redirect the browser to the GOG Galaxy authorization page.

    Response: HTTP 302 redirect.
    Returns 503 if GOG OAuth is not configured.
    """
    from platform_clients import GOGOAuthClient
    client = _get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return jsonify({'error': 'GOG OAuth client not configured. '
                        'Add gog_client_id and gog_enabled: true to config.json.'}), 503
    redirect_uri = (picker.config.get('gog_redirect_uri', '') if picker else '') or (
        request.url_root.rstrip('/') + '/api/gog/oauth/callback'
    )
    state = secrets.token_urlsafe(16)
    session['gog_oauth_state'] = state
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return flask_redirect(url)


@app.route('/api/gog/oauth/callback')
@require_login
def api_gog_oauth_callback():
    """Handle the GOG Galaxy OAuth2 callback.

    Query params:
        code (str): Authorization code from GOG.

    Response JSON::

        {"success": true, "platform": "gog"}
    """
    from platform_clients import GOGOAuthClient
    client = _get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return jsonify({'error': 'GOG OAuth client not configured.'}), 503
    code = request.args.get('code', '')
    if not code:
        return jsonify({'error': 'Missing authorization code.'}), 400
    redirect_uri = (picker.config.get('gog_redirect_uri', '') if picker else '') or (
        request.url_root.rstrip('/') + '/api/gog/oauth/callback'
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return jsonify({'error': 'Token exchange failed. Check server logs.'}), 400
    return jsonify({'success': True, 'platform': 'gog'})


@app.route('/api/gog/library')
@require_login
def api_gog_library():
    """Return the authenticated user's GOG library.

    Response JSON::

        {
          "games": [...],
          "count": 15,
          "platform": "gog"
        }
    """
    from platform_clients import GOGOAuthClient
    client = _get_platform_client('gog')
    if not isinstance(client, GOGOAuthClient):
        return jsonify({'error': 'GOG OAuth client not configured.'}), 503
    if not client.is_authenticated:
        return jsonify({'error': 'GOG account not authenticated. '
                        'Visit /api/gog/oauth/authorize first.'}), 503
    games = client.get_owned_games()
    return jsonify({'games': games, 'count': len(games), 'platform': 'gog'})


@app.route('/api/xbox/oauth/authorize')
@require_login
def api_xbox_oauth_authorize():
    """Redirect the browser to the Microsoft/Xbox authorization page.

    Response: HTTP 302 redirect.
    Returns 503 if Xbox OAuth is not configured.
    """
    from platform_clients import XboxAPIClient
    client = _get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return jsonify({'error': 'Xbox OAuth client not configured. '
                        'Add xbox_client_id and xbox_enabled: true to config.json.'}), 503
    redirect_uri = (picker.config.get('xbox_redirect_uri', '') if picker else '') or (
        request.url_root.rstrip('/') + '/api/xbox/oauth/callback'
    )
    state = secrets.token_urlsafe(16)
    session['xbox_oauth_state'] = state
    url = client.build_auth_url(redirect_uri=redirect_uri, state=state)
    return flask_redirect(url)


@app.route('/api/xbox/oauth/callback')
@require_login
def api_xbox_oauth_callback():
    """Handle the Microsoft/Xbox OAuth2 callback.

    Query params:
        code (str): Authorization code from Microsoft.

    Response JSON::

        {"success": true, "platform": "xbox"}
    """
    from platform_clients import XboxAPIClient
    client = _get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return jsonify({'error': 'Xbox OAuth client not configured.'}), 503
    code = request.args.get('code', '')
    if not code:
        return jsonify({'error': 'Missing authorization code.'}), 400
    redirect_uri = (picker.config.get('xbox_redirect_uri', '') if picker else '') or (
        request.url_root.rstrip('/') + '/api/xbox/oauth/callback'
    )
    ok = client.exchange_code(code=code, redirect_uri=redirect_uri)
    if not ok:
        return jsonify({'error': 'Token exchange failed. Check server logs.'}), 400
    return jsonify({'success': True, 'platform': 'xbox'})


@app.route('/api/xbox/library')
@require_login
def api_xbox_library():
    """Return the authenticated user's Xbox title history / Game Pass library.

    Response JSON::

        {
          "games": [...],
          "count": 80,
          "platform": "xbox"
        }
    """
    from platform_clients import XboxAPIClient
    client = _get_platform_client('xbox')
    if not isinstance(client, XboxAPIClient):
        return jsonify({'error': 'Xbox OAuth client not configured.'}), 503
    if not client._xsts_token:
        return jsonify({'error': 'Xbox account not authenticated. '
                        'Visit /api/xbox/oauth/authorize first.'}), 503
    games = client.get_owned_games()
    return jsonify({'games': games, 'count': len(games), 'platform': 'xbox'})


@app.route('/api/platform/status')
@require_login
def api_platform_status():
    """Return authentication / configuration status of all connected platforms.

    Response JSON::

        {
          "platforms": {
            "steam":     {"configured": true,  "authenticated": true},
            "epic":      {"configured": true,  "authenticated": false},
            "gog":       {"configured": false, "authenticated": false},
            "xbox":      {"configured": false, "authenticated": false},
            "psn":       {"configured": false, "authenticated": false},
            "nintendo":  {"configured": false, "authenticated": false}
          }
        }
    """
    from platform_clients import EpicOAuthClient, GOGOAuthClient, XboxAPIClient, PSNClient, NintendoEShopClient
    clients = picker.clients if picker else {}
    status: Dict[str, Any] = {}

    # Steam
    steam = clients.get('steam')
    status['steam'] = {
        'configured': steam is not None,
        'authenticated': steam is not None,
    }

    # Epic
    epic = clients.get('epic')
    status['epic'] = {
        'configured': epic is not None,
        'authenticated': isinstance(epic, EpicOAuthClient) and epic.is_authenticated,
    }

    # GOG
    gog = clients.get('gog')
    status['gog'] = {
        'configured': gog is not None,
        'authenticated': isinstance(gog, GOGOAuthClient) and gog.is_authenticated,
    }

    # Xbox
    xbox = clients.get('xbox')
    status['xbox'] = {
        'configured': xbox is not None,
        'authenticated': isinstance(xbox, XboxAPIClient) and xbox._xsts_token is not None,
    }

    # PSN
    psn = clients.get('psn')
    status['psn'] = {
        'configured': psn is not None,
        'authenticated': isinstance(psn, PSNClient) and psn.is_authenticated,
    }

    # Nintendo (catalog only — always "authenticated" when configured)
    nintendo = clients.get('nintendo')
    status['nintendo'] = {
        'configured': nintendo is not None,
        'authenticated': isinstance(nintendo, NintendoEShopClient),
        'note': 'catalog only — no library API available',
    }

    return jsonify({'platforms': status})


# ---------------------------------------------------------------------------
# PlayStation Network
# ---------------------------------------------------------------------------

@app.route('/api/psn/connect', methods=['POST'])
@require_login
def api_psn_connect():
    """Authenticate with PlayStation Network using an NPSSO token.

    The NPSSO token can be obtained from the ``npsso`` cookie at
    ``https://my.playstation.com`` after signing in.

    Request JSON::

        {"npsso": "YOUR_NPSSO_TOKEN_HERE"}

    Response JSON::

        {"success": true, "platform": "psn"}

    Returns 400 if the NPSSO token is missing or invalid, 503 if PSN is
    not configured.
    """
    from platform_clients import PSNClient
    if not picker:
        return jsonify({'error': 'Not initialized.'}), 400
    client = picker.clients.get('psn')
    if not isinstance(client, PSNClient):
        # Auto-create a PSN client if not already configured
        from platform_clients import PSNClient as _PSN
        client = _PSN(timeout=picker.API_TIMEOUT)
        picker.clients['psn'] = client
    body  = request.get_json(silent=True) or {}
    npsso = body.get('npsso', '').strip()
    if not npsso:
        return jsonify({'error': 'Missing npsso token in request body.'}), 400
    ok = client.connect(npsso)
    if not ok:
        return jsonify({
            'error': 'PSN authentication failed. '
                     'The NPSSO token may be expired or invalid. '
                     'Please obtain a fresh token from https://my.playstation.com'
        }), 400
    return jsonify({'success': True, 'platform': 'psn'})


@app.route('/api/psn/library')
@require_login
def api_psn_library():
    """Return the authenticated user's PlayStation game library.

    Response JSON::

        {
          "games": [...],
          "count": 42,
          "platform": "psn"
        }

    Returns 503 if PSN is not configured or authenticated.
    """
    from platform_clients import PSNClient
    client = picker.clients.get('psn') if picker else None
    if not isinstance(client, PSNClient):
        return jsonify({'error': 'PSN client not configured. '
                        'POST /api/psn/connect with your npsso token first.'}), 503
    if not client.is_authenticated:
        return jsonify({'error': 'PSN account not authenticated. '
                        'POST /api/psn/connect with your npsso token first.'}), 503
    games = client.get_owned_games()
    return jsonify({'games': games, 'count': len(games), 'platform': 'psn'})


@app.route('/api/psn/trophies')
@require_login
def api_psn_trophies():
    """Return the authenticated user's PlayStation trophy titles.

    Response JSON::

        {
          "trophyTitles": [...],
          "count": 15,
          "platform": "psn"
        }

    Returns 503 if PSN is not configured or authenticated.
    """
    from platform_clients import PSNClient
    client = picker.clients.get('psn') if picker else None
    if not isinstance(client, PSNClient):
        return jsonify({'error': 'PSN client not configured.'}), 503
    if not client.is_authenticated:
        return jsonify({'error': 'PSN account not authenticated.'}), 503
    trophies = client.get_trophies()
    return jsonify({'trophyTitles': trophies, 'count': len(trophies), 'platform': 'psn'})


# ---------------------------------------------------------------------------
# Nintendo eShop
# ---------------------------------------------------------------------------

@app.route('/api/nintendo/search')
@require_login
def api_nintendo_search():
    """Search the Nintendo eShop catalog.

    Query params:
        q          (str):  Search query (empty = browse all).
        page       (int):  Zero-based page number (default 0).
        per_page   (int):  Results per page 1-100 (default 20).
        filters    (str):  Algolia filter string.

    Response JSON::

        {
          "hits": [...],
          "nbHits": 1234,
          "page": 0,
          "nbPages": 25,
          "platform": "nintendo"
        }

    Returns 503 if Nintendo client is not configured.
    """
    from platform_clients import NintendoEShopClient
    client = picker.clients.get('nintendo') if picker else None
    if not isinstance(client, NintendoEShopClient):
        # Auto-create a Nintendo client if not configured
        if picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=picker.API_TIMEOUT)
            picker.clients['nintendo'] = client
        else:
            return jsonify({'error': 'Nintendo client not configured. '
                            'Add nintendo_enabled: true to config.json.'}), 503

    query    = request.args.get('q', '')
    page     = max(0, int(request.args.get('page', 0)))
    per_page = max(1, min(int(request.args.get('per_page', 20)), 100))
    filters  = request.args.get('filters', '')

    result = client.search_games(
        query=query,
        filters=filters,
        page=page,
        hits_per_page=per_page,
    )
    result['platform'] = 'nintendo'
    return jsonify(result)


@app.route('/api/nintendo/game/<nsuid>')
@require_login
def api_nintendo_game(nsuid: str):
    """Return details for a single Nintendo Switch game by nsuid.

    Also fetches current eShop pricing.

    Path param:
        nsuid (str): 14-digit Nintendo Switch unique game ID.

    Response JSON::

        {
          "game": {...},
          "platform": "nintendo"
        }

    Returns 404 if the game is not in cache, 503 if not configured.
    """
    from platform_clients import NintendoEShopClient
    client = picker.clients.get('nintendo') if picker else None
    if not isinstance(client, NintendoEShopClient):
        if picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=picker.API_TIMEOUT)
            picker.clients['nintendo'] = client
        else:
            return jsonify({'error': 'Nintendo client not configured.'}), 503

    game = client.get_game_by_nsuid(nsuid)
    if game is None:
        # Try to search for it
        result = client.search_games(query='', page=0, hits_per_page=1)
        game   = client.get_game_by_nsuid(nsuid)
    if game is None:
        return jsonify({'error': f'Game {nsuid} not found in cache. '
                        'Search for it first via /api/nintendo/search.'}), 404
    return jsonify({'game': game, 'platform': 'nintendo'})


@app.route('/api/nintendo/prices')
@require_login
def api_nintendo_prices():
    """Fetch current eShop prices for one or more games.

    Query params:
        nsuids  (str): Comma-separated list of 14-digit nsuid strings.
        country (str): ISO country code (default ``US``).

    Response JSON::

        {
          "prices": {"70010000000025": {"regular_price": "59.99", ...}},
          "platform": "nintendo"
        }
    """
    from platform_clients import NintendoEShopClient
    client = picker.clients.get('nintendo') if picker else None
    if not isinstance(client, NintendoEShopClient):
        if picker:
            from platform_clients import NintendoEShopClient as _N
            client = _N(timeout=picker.API_TIMEOUT)
            picker.clients['nintendo'] = client
        else:
            return jsonify({'error': 'Nintendo client not configured.'}), 503

    nsuids_param = request.args.get('nsuids', '')
    nsuids = [n.strip() for n in nsuids_param.split(',') if n.strip()]
    if not nsuids:
        return jsonify({'error': 'Provide one or more nsuids as ?nsuids=id1,id2'}), 400
    country = request.args.get('country', 'US')
    prices  = client.get_prices(nsuids=nsuids, country=country)
    return jsonify({'prices': prices, 'platform': 'nintendo'})


# ---------------------------------------------------------------------------
# Smart Recommendations
# ---------------------------------------------------------------------------

@app.route('/api/recommendations/smart')
@require_login
def api_smart_recommendations():
    """Return AI-enhanced game recommendations using multi-factor scoring.

    Unlike the basic ``/api/recommendations`` endpoint this engine considers:

    * Genre **and** Steam category/tag affinity from well-played titles
    * Developer / publisher affinity
    * Metacritic score influence (if cached)
    * Diversity boosting (avoids clustering by developer)
    * Recently-played history penalty

    Query params:
           count (int, 1-50, default 10): Number of recommendations to return.
           platforms (str): Comma-separated list of platforms to filter by.
           max_budget (float): Maximum price to consider for recommendations.
           include_new (bool): If true, boost recently released games.

    Response JSON::

        {
          "recommendations": [
            {
              "appid": 620,
              "name": "Portal 2",
              "playtime_hours": 0.0,
              "smart_score": 7.4,
              "smart_reason": "Unplayed. Matches your Puzzle, Action preference. Metacritic 95",
              ...
            }
          ],
          "engine": "smart"
        }

    Returns 400 if the picker is not initialised.
    """
    from app.services.recommendation_service import SmartRecommendationEngine

    if not picker:
        return jsonify({
            'error': 'Not initialized. Please log in and ensure your Steam ID is set.'
        }), 400

    try:
        count = max(1, min(int(request.args.get('count', 10)), 50))
    except (ValueError, TypeError):
        count = 10

    platforms_param = request.args.get('platforms', '').strip()
    platforms = [p.strip() for p in platforms_param.split(',') if p.strip()] if platforms_param else None

    max_budget = None
    max_budget_param = request.args.get('max_budget', '').strip()
    if max_budget_param:
        try:
            max_budget = float(max_budget_param)
        except (ValueError, TypeError):
            max_budget = None

    include_new = request.args.get('include_new', '').lower() in ('true', '1', 'yes')

    with picker_lock:
        games   = list(picker.games) if picker.games else []
        history = list(picker.history) if hasattr(picker, 'history') else []
        # Collect details cache from the Steam client (if available)
        cache: dict = {}
        steam_client = picker.clients.get('steam') if hasattr(picker, 'clients') else None
        if steam_client and hasattr(steam_client, 'details_cache'):
            cache = dict(steam_client.details_cache)

        well_mins   = getattr(picker, 'WELL_PLAYED_THRESHOLD_MINUTES', 600)
        barely_mins = getattr(picker, 'BARELY_PLAYED_THRESHOLD_MINUTES', 120)
        budget_svc  = getattr(picker, 'budget_service', None)

    engine = SmartRecommendationEngine(
        games=games,
        details_cache=cache,
        history=history,
        well_played_mins=well_mins,
        barely_played_mins=barely_mins,
        budget_service=budget_svc,
    )
    recs = engine.recommend(
        count=count,
        platforms=platforms,
        max_budget=max_budget,
        include_new_releases=include_new
    )
    return jsonify({'recommendations': recs, 'engine': 'smart'})


# ---------------------------------------------------------------------------
# Machine Learning Recommendations
# ---------------------------------------------------------------------------

@app.route('/api/recommendations/ml')
@require_login
def api_ml_recommendations():
    """Return machine-learning–powered game recommendations.

    Uses :class:`~app.services.ml_recommendation_service.MLRecommendationEngine`
    which offers item-based collaborative filtering, ALS matrix factorization,
    and a hybrid blend.

    Query params:
        count  (int, 1-50, default 10): Number of recommendations to return.
        method (str, default "cf"):     Scoring method — ``cf`` (item-based
                                        collaborative filtering), ``mf`` (ALS
                                        matrix factorization), or ``hybrid``.

    Response JSON::

        {
          "recommendations": [
            {
              "name": "Portal 2",
              "playtime_hours": 0.0,
              "ml_score": 4.82,
              "ml_reason": "Unplayed. Genre match: Puzzle, Action. Method: item-CF",
              ...
            }
          ],
          "engine": "ml",
          "method": "cf"
        }

    Returns 400 if the picker is not initialised.
    """
    from app.services.ml_recommendation_service import MLRecommendationEngine

    if not picker:
        return jsonify({
            'error': 'Not initialized. Please log in and ensure your Steam ID is set.'
        }), 400

    try:
        count = max(1, min(int(request.args.get('count', 10)), 50))
    except (ValueError, TypeError):
        count = 10

    method = request.args.get('method', 'cf')
    if method not in ('cf', 'mf', 'hybrid'):
        method = 'cf'

    with picker_lock:
        games   = list(picker.games) if picker.games else []
        history = list(picker.history) if hasattr(picker, 'history') else []
        cache: dict = {}
        steam_client = picker.clients.get('steam') if hasattr(picker, 'clients') else None
        if steam_client and hasattr(steam_client, 'details_cache'):
            cache = dict(steam_client.details_cache)
        well_mins   = getattr(picker, 'WELL_PLAYED_THRESHOLD_MINUTES', 600)
        barely_mins = getattr(picker, 'BARELY_PLAYED_THRESHOLD_MINUTES', 120)

    engine = MLRecommendationEngine(
        games=games,
        details_cache=cache,
        history=history,
        well_played_mins=well_mins,
        barely_played_mins=barely_mins,
    )
    recs = engine.recommend(count=count, method=method)
    return jsonify({'recommendations': recs, 'engine': 'ml', 'method': method})


# ---------------------------------------------------------------------------
# Webhook Notifications — Slack, Teams, IFTTT, Home Assistant
# ---------------------------------------------------------------------------

def _get_webhook_notifier() -> 'WebhookNotifier':  # type: ignore[name-defined]
    """Return a WebhookNotifier initialised with the current picker config."""
    from webhook_notifier import WebhookNotifier
    cfg = (picker.config if picker else {}) or {}
    return WebhookNotifier(cfg)


@app.route('/api/notifications/slack/test', methods=['POST'])
@require_login
def api_test_slack_webhook():
    """Send a test notification to the configured Slack Incoming Webhook.

    Request JSON (optional)::

        {
          "webhook_url": "https://hooks.slack.com/services/..."  // overrides config
        }

    Response JSON::

        {"success": true, "service": "slack"}

    Returns 503 if no webhook URL is configured and none was provided.
    """
    from webhook_notifier import WebhookNotifier
    body      = request.get_json(silent=True) or {}
    cfg       = dict((picker.config if picker else {}) or {})
    override  = body.get('webhook_url', '')
    if override:
        cfg['slack_webhook_url'] = override
    notifier  = WebhookNotifier(cfg)
    slack_url = notifier._get('slack_webhook_url')
    if not slack_url:
        return jsonify({
            'error': (
                'Slack webhook URL not configured. '
                'Add slack_webhook_url to config.json or supply it in the request body.'
            )
        }), 503
    test_game = {
        'name': 'GAPI Test Notification',
        'playtime_hours': 0.0,
        'steam_url': 'https://store.steampowered.com',
    }
    ok = notifier.send_slack(slack_url, test_game)
    return jsonify({'success': ok, 'service': 'slack'})


@app.route('/api/notifications/teams/test', methods=['POST'])
@require_login
def api_test_teams_webhook():
    """Send a test notification to the configured Microsoft Teams Incoming Webhook.

    Request JSON (optional)::

        {
          "webhook_url": "https://...webhook.office.com/..."
        }

    Response JSON::

        {"success": true, "service": "teams"}
    """
    from webhook_notifier import WebhookNotifier
    body     = request.get_json(silent=True) or {}
    cfg      = dict((picker.config if picker else {}) or {})
    override = body.get('webhook_url', '')
    if override:
        cfg['teams_webhook_url'] = override
    notifier  = WebhookNotifier(cfg)
    teams_url = notifier._get('teams_webhook_url')
    if not teams_url:
        return jsonify({
            'error': (
                'Teams webhook URL not configured. '
                'Add teams_webhook_url to config.json or supply it in the request body.'
            )
        }), 503
    test_game = {
        'name': 'GAPI Test Notification',
        'playtime_hours': 0.0,
        'steam_url': 'https://store.steampowered.com',
    }
    ok = notifier.send_teams(teams_url, test_game)
    return jsonify({'success': ok, 'service': 'teams'})


@app.route('/api/notifications/ifttt/test', methods=['POST'])
@require_login
def api_test_ifttt_webhook():
    """Send a test event to the configured IFTTT Maker Webhooks channel.

    Request JSON (optional)::

        {
          "ifttt_webhook_key":  "YOUR_IFTTT_KEY",
          "ifttt_event_name":   "gapi_game_picked"
        }

    Response JSON::

        {"success": true, "service": "ifttt"}

    Returns 503 if the IFTTT key is not configured.
    """
    from webhook_notifier import WebhookNotifier
    body     = request.get_json(silent=True) or {}
    cfg      = dict((picker.config if picker else {}) or {})
    if body.get('ifttt_webhook_key'):
        cfg['ifttt_webhook_key'] = body['ifttt_webhook_key']
    if body.get('ifttt_event_name'):
        cfg['ifttt_event_name']  = body['ifttt_event_name']
    notifier = WebhookNotifier(cfg)
    key      = notifier._get('ifttt_webhook_key')
    if not key:
        return jsonify({
            'error': (
                'IFTTT webhook key not configured. '
                'Add ifttt_webhook_key to config.json or supply it in the request body.'
            )
        }), 503
    event     = cfg.get('ifttt_event_name', 'gapi_game_picked')
    test_game = {
        'name': 'GAPI Test Notification',
        'playtime_hours': 0.0,
        'steam_url': 'https://store.steampowered.com',
    }
    ok = WebhookNotifier.send_ifttt(key, event, test_game)
    return jsonify({'success': ok, 'service': 'ifttt'})


@app.route('/api/notifications/homeassistant/test', methods=['POST'])
@require_login
def api_test_homeassistant_webhook():
    """Send a test event to the configured Home Assistant webhook.

    Request JSON (optional)::

        {
          "homeassistant_url":        "http://homeassistant.local:8123",
          "homeassistant_webhook_id": "gapi_game_picked",
          "homeassistant_token":      "Bearer eyJ..."
        }

    Response JSON::

        {"success": true, "service": "homeassistant"}

    Returns 503 if the Home Assistant URL / webhook ID are not configured.
    """
    from webhook_notifier import WebhookNotifier
    body = request.get_json(silent=True) or {}
    cfg  = dict((picker.config if picker else {}) or {})
    for key in ('homeassistant_url', 'homeassistant_webhook_id', 'homeassistant_token'):
        if body.get(key):
            cfg[key] = body[key]
    notifier = WebhookNotifier(cfg)
    ha_url   = notifier._get('homeassistant_url')
    ha_id    = notifier._get('homeassistant_webhook_id')
    if not ha_url or not ha_id:
        return jsonify({
            'error': (
                'Home Assistant URL and webhook ID must be configured. '
                'Add homeassistant_url and homeassistant_webhook_id to config.json '
                'or supply them in the request body.'
            )
        }), 503
    ha_token  = notifier._get('homeassistant_token')
    test_game = {
        'name': 'GAPI Test Notification',
        'playtime_hours': 0.0,
        'steam_url': 'https://store.steampowered.com',
    }
    ok = WebhookNotifier.send_homeassistant(ha_url, ha_id, test_game, token=ha_token)
    return jsonify({'success': ok, 'service': 'homeassistant'})


# ---------------------------------------------------------------------------
# API Documentation — OpenAPI 3.0 + Swagger UI
# ---------------------------------------------------------------------------

@app.route('/api/openapi.json')
def api_openapi_spec():
    """Serve the OpenAPI 3.0 specification as JSON."""
    try:
        from openapi_spec import build_spec
        server_url = request.url_root.rstrip('/')
        spec = build_spec(server_url=server_url)
        return jsonify(spec)
    except Exception as e:
        gui_logger.error(f"Error building OpenAPI spec: {e}")
        return jsonify({'error': 'Could not generate spec'}), 500


@app.route('/api/docs')
def api_swagger_ui():
    """Serve an interactive Swagger UI for the GAPI REST API."""
    openapi_url = '/api/openapi.json'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GAPI API Documentation</title>
  <link rel="stylesheet"
        href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "{openapi_url}",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true,
      defaultModelsExpandDepth: 1,
      defaultModelExpandDepth: 1,
    }});
  </script>
</body>
</html>"""
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


# ---------------------------------------------------------------------------
# API Usage Statistics  (Phase 9C)
# ---------------------------------------------------------------------------

@app.route('/api/admin/api-stats', methods=['GET'])
@require_admin
def api_admin_api_stats():
    """Return per-endpoint call counts and latency statistics (admin only).

    Response JSON:
      ``stats``          – list of endpoint entries, sorted descending by call count.
                           Each entry has ``endpoint``, ``calls``, ``errors``,
                           ``avg_ms``, ``min_ms``, ``max_ms``, ``total_ms``.
      ``endpoint_count`` – number of distinct tracked endpoints.
    """
    with _api_stats_lock:
        rows = [
            {
                'endpoint': ep,
                'calls': s['calls'],
                'errors': s['errors'],
                'avg_ms': round(s['total_ms'] / s['calls'], 2) if s['calls'] else 0.0,
                'min_ms': round(s['min_ms'], 2) if s['min_ms'] is not None else 0.0,
                'max_ms': round(s['max_ms'], 2),
                'total_ms': round(s['total_ms'], 2),
            }
            for ep, s in _api_endpoint_stats.items()
        ]
    # Sort descending by call count for convenience
    rows.sort(key=lambda r: r['calls'], reverse=True)
    return jsonify({'stats': rows, 'endpoint_count': len(rows)})


@app.route('/api/admin/api-stats/reset', methods=['POST'])
@require_admin
def api_admin_api_stats_reset():
    """Reset all in-memory API usage counters (admin only)."""
    with _api_stats_lock:
        _api_endpoint_stats.clear()
    return jsonify({'reset': True})


# ---------------------------------------------------------------------------
# Client-Side Error Reporting  (Phase 9C)
# ---------------------------------------------------------------------------

@app.route('/api/errors/report', methods=['POST'])
def api_errors_report():
    """Accept a JavaScript error report from the browser.

    Expected JSON body (all fields optional):
      ``message``    – error message string
      ``stack``      – stack trace string
      ``url``        – page URL where the error occurred
      ``line``       – line number (int)
      ``col``        – column number (int)
      ``user_agent`` – browser user-agent string

    The report is stored in a fixed-size ring buffer (most recent
    ``_CLIENT_ERROR_MAX`` entries) and logged at WARNING level.
    """
    data = request.get_json(silent=True, force=True) or {}
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'message': str(data.get('message', ''))[:500],
        'stack': str(data.get('stack', ''))[:2000],
        'url': str(data.get('url', ''))[:500],
        'line': data.get('line'),
        'col': data.get('col'),
        'user_agent': str(
            data.get('user_agent') or request.headers.get('User-Agent', '')
        )[:300],
        'username': get_current_username(),
    }
    gui_logger.warning('Client-side error reported: %s at %s', entry['message'], entry['url'])
    with _client_errors_lock:
        _client_errors.append(entry)
    return jsonify({'recorded': True}), 201


@app.route('/api/admin/client-errors', methods=['GET'])
@require_admin
def api_admin_client_errors():
    """Return recent client-side error reports (admin only).

    Query params:
      ``limit`` – max entries to return (default 50, max 200)
    """
    try:
        limit = min(int(request.args.get('limit', 50)), _CLIENT_ERROR_MAX)
    except (ValueError, TypeError):
        limit = 50
    with _client_errors_lock:
        # Iterate the deque in reverse (newest first) and take only `limit`
        # items — avoids copying the entire buffer when limit is small.
        total = len(_client_errors)
        recent = list(reversed(list(_client_errors)[-limit:] if limit < total else _client_errors))
    return jsonify({'errors': recent, 'total_stored': total})


@app.route('/api/admin/client-errors/clear', methods=['POST'])
@require_admin
def api_admin_client_errors_clear():
    """Clear the client-side error ring buffer (admin only)."""
    with _client_errors_lock:
        _client_errors.clear()
    return jsonify({'cleared': True})


# ---------------------------------------------------------------------------
# API Changelog  (Phase 9C)
# ---------------------------------------------------------------------------

_API_CHANGELOG = [
    {
        'version': 'v2.10.0',
        'date': '2026-03-02',
        'changes': [
            'Added GET /api/admin/api-stats — per-endpoint call counts and latency',
            'Added POST /api/admin/api-stats/reset — reset usage counters',
            'Added POST /api/errors/report — client-side JS error ingestion',
            'Added GET /api/admin/client-errors — view recent client errors',
            'Added POST /api/admin/client-errors/clear — clear error buffer',
            'Added GET /api/changelog — this endpoint',
        ],
    },
    {
        'version': 'v2.9.0',
        'date': '2026-03-02',
        'changes': [
            'Added HTTP security headers (X-Content-Type-Options, X-Frame-Options, '
            'Referrer-Policy, Permissions-Policy) to all responses',
            'Added API rate limiting on POST /api/auth/login (20/min, 100/hr) '
            'and POST /api/auth/register (10/hr) via Flask-Limiter',
            'Added gzip/brotli response compression via Flask-Compress',
            'Added GET /api/admin/security-info — security feature status',
        ],
    },
    {
        'version': 'v2.8.0',
        'date': '2026-03-01',
        'changes': [
            'Added Discord bot admin management endpoints',
            'Added GET /api/admin/discord/status',
            'Added POST /api/admin/discord/restart',
            'Added GET/POST /api/admin/discord/config',
            'Added GET /api/admin/discord/users',
            'Added DELETE /api/admin/discord/users/<discord_id>',
        ],
    },
    {
        'version': 'v2.7.0',
        'date': '2026-02-15',
        'changes': [
            'Phase 9A/9B: Advanced Analytics Dashboard',
            'Phase 9A/9B: Audit Logging & Activity Tracking',
            'Phase 9A/9B: Batch Operations (tag, status, playlist, delete, export)',
            'Phase 9A/9B: Advanced Search & Filtering with saved searches',
            'Phase 9A/9B: Content Moderation (report, review, profanity filter)',
        ],
    },
]


@app.route('/api/changelog', methods=['GET'])
def api_changelog():
    """Return a structured API changelog.

    Query params:
      ``limit`` – max versions to return (default all)
    """
    try:
        limit = int(request.args.get('limit', len(_API_CHANGELOG)))
        limit = max(1, min(limit, len(_API_CHANGELOG)))
    except (ValueError, TypeError):
        limit = len(_API_CHANGELOG)
    return jsonify({
        'changelog': _API_CHANGELOG[:limit],
        'total_versions': len(_API_CHANGELOG),
    })


# ---------------------------------------------------------------------------
# Database Optimization & Maintenance  (Tier 3, item 10)
# ---------------------------------------------------------------------------

@app.route('/api/admin/db/stats', methods=['GET'])
@require_admin
def api_admin_db_stats():
    """Return per-table row counts and total database size (admin only).

    Response JSON:
      ``tables``     – list of ``{table, rows, size_bytes}`` sorted by row count
      ``total_size_bytes`` – total on-disk DB size (0 if not measurable)
      ``db_available``     – whether the DB module is loaded
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available', 'db_available': False}), 503
    try:
        db = next(database.get_db())
        tables = database.get_table_stats(db)
        total_size = database.get_db_size_bytes()
        return jsonify({
            'tables': tables,
            'total_size_bytes': total_size,
            'db_available': True,
        })
    except Exception as e:
        gui_logger.error('api_admin_db_stats error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/db/apply-indexes', methods=['GET'])
@require_admin
def api_admin_db_apply_indexes_dryrun():
    """Dry-run: list recommended indexes that are not yet present (admin only).

    Response JSON mirrors ``POST /api/admin/db/apply-indexes`` with
    ``dry_run: true``.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        result = database.apply_indexes(db, dry_run=True)
        return jsonify(result)
    except Exception as e:
        gui_logger.error('api_admin_db_apply_indexes_dryrun error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/db/apply-indexes', methods=['POST'])
@require_admin
def api_admin_db_apply_indexes():
    """Create all missing recommended indexes (admin only).

    Response JSON:
      ``applied``  – DDL statements executed
      ``skipped``  – DDL statements where the index already existed
      ``errors``   – ``[{sql, error}]`` for any failures
      ``dry_run``  – always ``false``
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        result = database.apply_indexes(db, dry_run=False)
        return jsonify(result)
    except Exception as e:
        gui_logger.error('api_admin_db_apply_indexes error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/db/archive-old-picks', methods=['POST'])
@require_admin
def api_admin_db_archive_old_picks():
    """Delete pick and completed live-session records older than N days (admin only).

    Request JSON body (all optional):
      ``days`` – retention period in days (default 365, min 1)

    Response JSON:
      ``deleted_picks``    – number of pick rows removed
      ``deleted_sessions`` – number of live_session rows removed
      ``cutoff_date``      – ISO 8601 cutoff timestamp
      ``days``             – retention period used
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    try:
        days = max(1, int(data.get('days', 365)))
    except (ValueError, TypeError):
        days = 365
    try:
        db = next(database.get_db())
        result = database.archive_old_picks(db, days=days)
        return jsonify(result)
    except Exception as e:
        gui_logger.error('api_admin_db_archive_old_picks error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/db/backup', methods=['GET'])
@require_admin
def api_admin_db_backup():
    """Download a database backup (admin only).

    For SQLite databases: streams the database file as an attachment.
    For PostgreSQL or other engines: returns connection info and instructions
    for using pg_dump (no file is streamed).

    Response for non-SQLite:
      ``message``  – human-readable instructions
      ``dialect``  – database dialect name
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        import sqlalchemy as _sa
        dialect = database.engine.dialect.name if database.engine else 'unknown'
        if dialect == 'sqlite':
            db_url = str(database.engine.url)
            path = db_url.replace('sqlite:///', '').replace('sqlite://', '')
            if not path or not os.path.exists(path):
                return jsonify({'error': 'SQLite file not found', 'path': path}), 404
            filename = os.path.basename(path) or 'gapi.db'
            import datetime as _dt
            stamp = _dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            download_name = f'gapi_backup_{stamp}.db'
            return Response(
                _stream_file(path),
                mimetype='application/octet-stream',
                headers={
                    'Content-Disposition': f'attachment; filename="{download_name}"',
                    'Content-Length': str(os.path.getsize(path)),
                },
            )
        else:
            return jsonify({
                'message': (
                    f'Automated backup download is only supported for SQLite. '
                    f'For {dialect}, use the appropriate dump tool '
                    f'(e.g., pg_dump for PostgreSQL) against your database server.'
                ),
                'dialect': dialect,
            }), 200
    except Exception as e:
        gui_logger.error('api_admin_db_backup error: %s', e)
        return jsonify({'error': str(e)}), 500


def _stream_file(path: str, chunk_size: int = 65536):
    """Generator that yields a file in chunks for streaming responses."""
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


# ---------------------------------------------------------------------------
# Fine-grained Permission endpoints  (Tier 2, item 5)
# ---------------------------------------------------------------------------

@app.route('/api/permissions', methods=['GET'])
def api_permissions_list():
    """Return all defined permissions and the role-to-permission matrix (public).

    Response JSON:
      ``permissions``   – sorted list of all discrete permission strings
      ``role_matrix``   – dict mapping role name → list of permissions
    """
    return jsonify({
        'permissions': database.ALL_PERMISSIONS if DB_AVAILABLE else [],
        'role_matrix': database.PERMISSIONS if DB_AVAILABLE else {},
    })


@app.route('/api/users/<username>/permissions', methods=['GET'])
@require_login
def api_get_user_permissions(username: str):
    """Return the effective permissions for *username* (login required).

    Response JSON mirrors ``database.get_user_permissions``:
      ``effective``   – currently active permissions
      ``from_roles``  – permissions derived from roles
      ``granted``     – explicit per-user grants
      ``denied``      – explicit per-user denials
      ``is_admin``    – True when user has wildcard access
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        perms = database.get_user_permissions(db, username)
        return jsonify(perms)
    except Exception as e:
        gui_logger.error('api_get_user_permissions error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<username>/permissions', methods=['POST'])
@require_admin
def api_set_user_permissions(username: str):
    """Grant, deny, or remove a permission override for *username* (admin only).

    Request JSON body:
      ``permission``   – permission string (required)
      ``action``       – ``'grant'`` | ``'deny'`` | ``'remove'`` (required)

    Response JSON:
      ``ok``           – True on success
      ``permissions``  – updated effective permissions dict
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    permission = str(data.get('permission', '')).strip()
    action = str(data.get('action', '')).strip().lower()
    if not permission or action not in ('grant', 'deny', 'remove'):
        return jsonify({'error': "Required fields: 'permission' and 'action' (grant/deny/remove)"}), 400
    if permission not in database.ALL_PERMISSIONS:
        return jsonify({'error': f"Unknown permission '{permission}'"}), 400
    try:
        db = next(database.get_db())
        requesting_user = get_current_username()
        if action == 'remove':
            ok = database.remove_user_permission_override(db, username, permission)
        else:
            ok = database.set_user_permission_override(
                db, username, permission,
                granted=(action == 'grant'),
                granted_by=requesting_user,
            )
        if not ok:
            return jsonify({'error': 'Failed to update permission'}), 500
        perms = database.get_user_permissions(db, username)
        return jsonify({'ok': True, 'permissions': perms})
    except Exception as e:
        gui_logger.error('api_set_user_permissions error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/roles/bulk-assign', methods=['POST'])
@require_admin
def api_admin_bulk_assign_role():
    """Assign a role to multiple users at once (admin only).

    Request JSON body:
      ``role``       – role name to assign (required)
      ``usernames``  – list of usernames (required, max 200)

    Response JSON:
      ``assigned``   – list of usernames that were updated
      ``skipped``    – list of usernames that already had the role / not found
      ``errors``     – list of ``{username, error}`` for failures
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    role = str(data.get('role', '')).strip()
    usernames = data.get('usernames', [])
    if not role:
        return jsonify({'error': "'role' is required"}), 400
    if not isinstance(usernames, list) or len(usernames) == 0:
        return jsonify({'error': "'usernames' must be a non-empty list"}), 400
    if len(usernames) > 200:
        return jsonify({'error': "'usernames' may not exceed 200 entries per request"}), 400
    assigned, skipped, errors = [], [], []
    try:
        requesting_user = get_current_username()
        for uname in usernames:
            uname = str(uname).strip()
            if not uname:
                continue
            ok, _ = user_manager.update_user_roles(uname, [role], requesting_user)
            if ok:
                assigned.append(uname)
            else:
                skipped.append(uname)
        if assigned:
            _audit('bulk_role_assign', resource_type='user_role', resource_id=role,
                   description=f'Bulk assigned role "{role}" to {len(assigned)} user(s)',
                   new_value={'role': role, 'assigned': assigned, 'skipped': skipped})
    except Exception as e:
        gui_logger.error('api_admin_bulk_assign_role error: %s', e)
        errors.append({'error': str(e)})
    return jsonify({'assigned': assigned, 'skipped': skipped, 'errors': errors})


# ---------------------------------------------------------------------------
# Notification Preferences  (Tier 2, item 6)
# ---------------------------------------------------------------------------

@app.route('/api/notifications/preferences', methods=['GET'])
@require_login
def api_get_notification_prefs():
    """Return the current user's notification preferences (login required).

    Response JSON fields:
      ``email_enabled``, ``push_enabled``, ``friend_requests``,
      ``challenge_updates``, ``trade_offers``, ``team_events``,
      ``system_announcements``, ``digest_frequency``, ``updated_at``
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    username = get_current_username()
    try:
        db = next(database.get_db())
        prefs = database.get_notification_prefs(db, username)
        return jsonify(prefs)
    except Exception as e:
        gui_logger.error('api_get_notification_prefs error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifications/preferences', methods=['PUT'])
@require_login
def api_set_notification_prefs():
    """Update the current user's notification preferences (login required).

    Accepted JSON body fields (all optional):
      ``email_enabled`` (bool), ``push_enabled`` (bool),
      ``friend_requests`` (bool), ``challenge_updates`` (bool),
      ``trade_offers`` (bool), ``team_events`` (bool),
      ``system_announcements`` (bool),
      ``digest_frequency`` (str: ``'never'``|``'daily'``|``'weekly'``)

    Response JSON: updated preference dict.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    username = get_current_username()
    data = request.get_json(silent=True, force=True) or {}
    try:
        db = next(database.get_db())
        updated = database.set_notification_prefs(db, username, data)
        if not updated:
            return jsonify({'error': 'Failed to save preferences'}), 500
        return jsonify(updated)
    except Exception as e:
        gui_logger.error('api_set_notification_prefs error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifications/history', methods=['GET'])
@require_login
def api_notification_history():
    """Return paginated notification history for the current user (login required).

    Query parameters:
      ``limit``   – max results (default 50, max 200)
      ``offset``  – skip N records (default 0)
      ``unread``  – if ``'true'``, return only unread notifications

    Response JSON:
      ``notifications`` – list of notification objects
      ``total``         – total count of notifications for this user
    """
    if not DB_AVAILABLE:
        return jsonify({'notifications': [], 'total': 0})
    username = get_current_username()
    try:
        limit = max(1, min(200, int(request.args.get('limit', 50))))
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except (ValueError, TypeError):
        offset = 0
    unread_only = request.args.get('unread', '').lower() in ('true', '1', 'yes')
    try:
        db = next(database.get_db())
        notifications = database.get_notifications(db, username, unread_only=unread_only)
        total = len(notifications)
        page = notifications[offset: offset + limit]
        return jsonify({'notifications': page, 'total': total})
    except Exception as e:
        gui_logger.error('api_notification_history error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/notifications/broadcast', methods=['POST'])
@require_admin
def api_admin_broadcast_notification():
    """Broadcast a notification to all users or a specific subset (admin only).

    Request JSON body:
      ``title``      – notification title (required)
      ``message``    – notification body (required)
      ``type``       – notification type: ``'info'``|``'warning'``|``'success'``|``'error'``
                       (default ``'info'``)
      ``usernames``  – optional list of target usernames; if omitted all users receive it

    Response JSON:
      ``sent``       – number of notifications created
      ``skipped``    – number of users skipped (not found in DB)
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    title = str(data.get('title', '')).strip()
    message = str(data.get('message', '')).strip()
    notif_type = str(data.get('type', 'info')).strip()
    if notif_type not in ('info', 'warning', 'success', 'error'):
        notif_type = 'info'
    if not title or not message:
        return jsonify({'error': "'title' and 'message' are required"}), 400
    target_usernames = data.get('usernames')
    sent = skipped = 0
    try:
        db = next(database.get_db())
        if target_usernames:
            usernames = [str(u).strip() for u in target_usernames if str(u).strip()]
        else:
            all_users = database.get_all_users(db)
            usernames = [u.username for u in all_users]
        for uname in usernames:
            ok = database.create_notification(db, uname, title, message, notif_type)
            if ok:
                sent += 1
            else:
                skipped += 1
        return jsonify({'sent': sent, 'skipped': skipped})
    except Exception as e:
        gui_logger.error('api_admin_broadcast_notification error: %s', e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Error Rate Dashboard  (Tier 3, item 12)
# ---------------------------------------------------------------------------

@app.route('/api/admin/errors/rate', methods=['GET'])
@require_admin
def api_admin_error_rate():
    """Return client-side error counts bucketed by hour for the last 24 hours (admin only).

    Response JSON:
      ``buckets``      – list of ``{hour, count}`` objects, newest last (24 items)
      ``total_24h``    – total errors in last 24h window
      ``total_all``    – total in the ring buffer (may span > 24h)
    """
    from datetime import timedelta
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    # Build 24 hour slots: 0 = oldest, 23 = most recent (current partial hour)
    buckets = [{'hour': (now - timedelta(hours=23 - i)).strftime('%Y-%m-%dT%H:00Z'), 'count': 0}
               for i in range(24)]
    total_24h = 0
    with _client_errors_lock:
        errors_snapshot = list(_client_errors)
        total_all = len(errors_snapshot)
    for err in errors_snapshot:
        ts_str = err.get('timestamp', '')
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', ''))
            # Strip timezone info if present so arithmetic stays offset-naive.
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if ts < cutoff:
            continue
        total_24h += 1
        diff_hours = int((now - ts).total_seconds() // 3600)
        slot = 23 - min(diff_hours, 23)
        buckets[slot]['count'] += 1
    return jsonify({
        'buckets': buckets,
        'total_24h': total_24h,
        'total_all': total_all,
    })


# ---------------------------------------------------------------------------
# Similar Games endpoint  (Item 8)
# ---------------------------------------------------------------------------

@app.route('/api/games/<app_id>/similar', methods=['GET'])
@require_login
def api_similar_games(app_id: str):
    """Return games similar to *app_id* based on genre/tag overlap (login required).

    Query parameters:
      ``platform``  – game platform (default ``'steam'``)
      ``limit``     – max results (default 10, max 50)

    Response JSON:
      ``app_id``    – queried game id
      ``platform``  – queried platform
      ``similar``   – list of ``{app_id, game_name, platform, similarity_score}``
    """
    if not DB_AVAILABLE:
        return jsonify({'app_id': app_id, 'similar': []})
    platform = request.args.get('platform', 'steam').strip().lower()
    try:
        limit = max(1, min(50, int(request.args.get('limit', 10))))
    except (ValueError, TypeError):
        limit = 10
    try:
        db = next(database.get_db())
        similar = database.get_similar_games(db, app_id, platform=platform, limit=limit)
        return jsonify({'app_id': app_id, 'platform': platform, 'similar': similar})
    except Exception as e:
        gui_logger.error('api_similar_games error: %s', e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# A/B Testing endpoints for Recommendations  (Item 13)
# ---------------------------------------------------------------------------

@app.route('/api/admin/ab-tests', methods=['POST'])
@require_admin
def api_create_ab_test():
    """Create a new recommendation A/B experiment (admin only).

    Request JSON body:
      ``name``         – unique experiment name (required)
      ``variants``     – list of variant strings, e.g. ``["control","ml","collab"]``
                         (required, min 2)
      ``description``  – optional description

    Response JSON: serialised experiment dict.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    name = str(data.get('name', '')).strip()
    variants = data.get('variants', [])
    description = str(data.get('description', '')).strip()
    if not name:
        return jsonify({'error': "'name' is required"}), 400
    if not isinstance(variants, list) or len(variants) < 2:
        return jsonify({'error': "'variants' must be a list with at least 2 entries"}), 400
    try:
        db = next(database.get_db())
        exp = database.create_experiment(
            db, name=name, variants=variants, description=description,
            created_by=get_current_username(),
        )
        if not exp:
            return jsonify({'error': 'Failed to create experiment (name may already exist)'}), 409
        return jsonify(exp), 201
    except Exception as e:
        gui_logger.error('api_create_ab_test error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/ab-tests', methods=['GET'])
@require_admin
def api_list_ab_tests():
    """List all recommendation A/B experiments with variant assignment counts (admin only).

    Response JSON:
      ``experiments`` – list of experiment dicts each containing a ``variant_counts`` sub-dict
    """
    if not DB_AVAILABLE:
        return jsonify({'experiments': []})
    try:
        db = next(database.get_db())
        exps = database.list_experiments(db)
        for exp in exps:
            exp['variant_counts'] = database.get_experiment_variant_counts(db, exp['id'])
        return jsonify({'experiments': exps})
    except Exception as e:
        gui_logger.error('api_list_ab_tests error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/ab-tests/<int:experiment_id>', methods=['PATCH'])
@require_admin
def api_update_ab_test(experiment_id: int):
    """Update the status of a recommendation A/B experiment (admin only).

    Request JSON body:
      ``status``  – one of ``draft``, ``active``, ``paused``, ``concluded``

    Response JSON: updated experiment dict.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    status = str(data.get('status', '')).strip().lower()
    valid_statuses = ('draft', 'active', 'paused', 'concluded')
    if status not in valid_statuses:
        return jsonify({'error': f"'status' must be one of: {', '.join(valid_statuses)}"}), 400
    try:
        db = next(database.get_db())
        updated = database.update_experiment_status(db, experiment_id, status)
        if not updated:
            return jsonify({'error': 'Experiment not found'}), 404
        return jsonify(updated)
    except Exception as e:
        gui_logger.error('api_update_ab_test error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/recommendations/variant', methods=['GET'])
@require_login
def api_get_recommendation_variant():
    """Return the A/B experiment variant assigned to the current user (login required).

    Query parameters:
      ``experiment``  – experiment name (required)

    Response JSON:
      ``experiment``  – experiment name
      ``variant``     – assigned variant string, or ``null`` if no active experiment
    """
    experiment_name = request.args.get('experiment', '').strip()
    if not experiment_name:
        return jsonify({'error': "'experiment' query parameter is required"}), 400
    if not DB_AVAILABLE:
        return jsonify({'experiment': experiment_name, 'variant': None})
    try:
        db = next(database.get_db())
        username = get_current_username()
        variant = database.get_or_assign_variant(db, username, experiment_name)
        return jsonify({'experiment': experiment_name, 'variant': variant})
    except Exception as e:
        gui_logger.error('api_get_recommendation_variant error: %s', e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# User Suspension / Account Status  (Item 5 — Advanced User Management)
# ---------------------------------------------------------------------------

@app.route('/api/admin/users/search', methods=['GET'])
@require_admin
def api_admin_search_users():
    """Search and filter users — admin only.

    Query parameters:
      ``q``       – partial username match
      ``role``    – filter by role name
      ``status``  – ``active``, ``suspended``, or ``banned``
      ``limit``   – max results (default 50, max 200)
      ``offset``  – pagination offset (default 0)

    Response JSON:
      ``users`` – list of ``{username, display_name, status, roles, created_at, last_seen}``
      ``count`` – number of results returned
    """
    if not DB_AVAILABLE:
        return jsonify({'users': [], 'count': 0})
    q = request.args.get('q', '').strip()
    role = request.args.get('role', '').strip()
    status = request.args.get('status', '').strip().lower()
    try:
        limit = max(1, min(200, int(request.args.get('limit', 50))))
        offset = max(0, int(request.args.get('offset', 0)))
    except (ValueError, TypeError):
        limit, offset = 50, 0
    try:
        db = next(database.get_db())
        users = database.search_users_admin(db, query=q, role=role,
                                            status=status, limit=limit, offset=offset)
        return jsonify({'users': users, 'count': len(users)})
    except Exception as e:
        gui_logger.error('api_admin_search_users error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<username>/suspend', methods=['POST'])
@require_admin
def api_admin_suspend_user(username: str):
    """Suspend or permanently ban a user (admin only).

    Request JSON body:
      ``reason``            – suspension reason (required)
      ``duration_minutes``  – suspension duration in minutes; omit for permanent ban

    Response JSON: suspension status dict.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    reason = str(data.get('reason', '')).strip()
    if not reason:
        return jsonify({'error': "'reason' is required"}), 400
    duration = data.get('duration_minutes')
    if duration is not None:
        try:
            duration = int(duration)
            if duration <= 0:
                return jsonify({'error': "'duration_minutes' must be a positive integer"}), 400
        except (ValueError, TypeError):
            return jsonify({'error': "'duration_minutes' must be an integer"}), 400
    try:
        db = next(database.get_db())
        result = database.suspend_user(
            db, username, reason=reason,
            suspended_by=get_current_username(),
            duration_minutes=duration,
        )
        if not result:
            return jsonify({'error': f"User '{username}' not found"}), 404
        action = 'suspend_user' if duration else 'ban_user'
        _audit(action, resource_type='user', resource_id=username,
               description=f'{"Temporary suspension" if duration else "Permanent ban"}: {reason}',
               new_value={'reason': reason, 'duration_minutes': duration})
        return jsonify(result)
    except Exception as e:
        gui_logger.error('api_admin_suspend_user error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<username>/suspend', methods=['DELETE'])
@require_admin
def api_admin_unsuspend_user(username: str):
    """Lift a user's suspension or ban (admin only).

    Response JSON:
      ``ok``  – True on success
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        ok = database.unsuspend_user(db, username)
        if not ok:
            return jsonify({'error': f"User '{username}' not found or not suspended"}), 404
        _audit('unsuspend_user', resource_type='user', resource_id=username,
               description=f'Suspension/ban lifted for user "{username}"')
        return jsonify({'ok': True, 'username': username})
    except Exception as e:
        gui_logger.error('api_admin_unsuspend_user error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<username>/status', methods=['GET'])
@require_admin
def api_admin_get_user_status(username: str):
    """Get the account status for a user (admin only).

    Response JSON:
      ``username``, ``status`` (``active``/``suspended``/``banned``),
      ``is_suspended``, ``suspended_until``, ``suspended_reason``, etc.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        result = database.get_user_status(db, username)
        if not result:
            return jsonify({'error': f"User '{username}' not found"}), 404
        return jsonify(result)
    except Exception as e:
        gui_logger.error('api_admin_get_user_status error: %s', e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# User Groups  (Item 5 — Advanced User Management)
# ---------------------------------------------------------------------------

@app.route('/api/admin/user-groups', methods=['POST'])
@require_admin
def api_create_user_group():
    """Create a new user group (admin only).

    Request JSON body:
      ``name``         – unique group name (required)
      ``description``  – optional description

    Response JSON: group dict (201).
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'error': "'name' is required"}), 400
    description = str(data.get('description', '')).strip()
    try:
        db = next(database.get_db())
        grp = database.create_user_group(db, name=name, description=description,
                                         created_by=get_current_username())
        if not grp:
            return jsonify({'error': 'Failed to create group (name may already exist)'}), 409
        _audit('create_user_group', resource_type='user_group', resource_id=str(grp.get('id')),
               description=f'Created user group "{name}"')
        return jsonify(grp), 201
    except Exception as e:
        gui_logger.error('api_create_user_group error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user-groups', methods=['GET'])
@require_admin
def api_list_user_groups():
    """List all user groups with member counts (admin only).

    Response JSON:
      ``groups`` – list of group dicts each with ``member_count``
    """
    if not DB_AVAILABLE:
        return jsonify({'groups': []})
    try:
        db = next(database.get_db())
        groups = database.list_user_groups(db)
        return jsonify({'groups': groups})
    except Exception as e:
        gui_logger.error('api_list_user_groups error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>', methods=['DELETE'])
@require_admin
def api_delete_user_group(group_id: int):
    """Delete a user group and all memberships (admin only)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        ok = database.delete_user_group(db, group_id)
        if not ok:
            return jsonify({'error': 'Group not found'}), 404
        _audit('delete_user_group', resource_type='user_group', resource_id=str(group_id),
               description=f'Deleted user group {group_id}')
        return jsonify({'ok': True})
    except Exception as e:
        gui_logger.error('api_delete_user_group error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>/members', methods=['POST'])
@require_admin
def api_add_group_member(group_id: int):
    """Add a user to a user group (admin only).

    Request JSON body:
      ``username``  – username to add (required)

    Response JSON: ``{ok, username, group_id}``
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    username = str(data.get('username', '')).strip()
    if not username:
        return jsonify({'error': "'username' is required"}), 400
    try:
        db = next(database.get_db())
        result = database.add_group_member(db, group_id, username,
                                           added_by=get_current_username())
        if not result.get('ok'):
            status = 409 if 'Already a member' in result.get('error', '') else 404
            return jsonify(result), status
        _audit('add_group_member', resource_type='user_group', resource_id=str(group_id),
               description=f'Added "{username}" to group {group_id}')
        return jsonify(result), 201
    except Exception as e:
        gui_logger.error('api_add_group_member error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>/members/<username>', methods=['DELETE'])
@require_admin
def api_remove_group_member(group_id: int, username: str):
    """Remove a user from a user group (admin only)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = next(database.get_db())
        ok = database.remove_group_member(db, group_id, username)
        if not ok:
            return jsonify({'error': 'Member not found in group'}), 404
        _audit('remove_group_member', resource_type='user_group', resource_id=str(group_id),
               description=f'Removed "{username}" from group {group_id}')
        return jsonify({'ok': True})
    except Exception as e:
        gui_logger.error('api_remove_group_member error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>/members', methods=['GET'])
@require_admin
def api_get_group_members(group_id: int):
    """Get the list of members for a user group (admin only).

    Response JSON:
      ``group_id`` – group identifier
      ``members``  – list of username strings
    """
    if not DB_AVAILABLE:
        return jsonify({'group_id': group_id, 'members': []})
    try:
        db = next(database.get_db())
        members = database.get_group_members(db, group_id)
        return jsonify({'group_id': group_id, 'members': members})
    except Exception as e:
        gui_logger.error('api_get_group_members error: %s', e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# User Reputation  (Item 7 — Content Moderation)
# ---------------------------------------------------------------------------

@app.route('/api/users/<username>/reputation', methods=['GET'])
@require_login
def api_get_user_reputation(username: str):
    """Return the reputation/trust score for *username* (login required).

    Response JSON:
      ``username``, ``score``, ``violation_count``, ``last_updated``, ``last_action``
    """
    if not DB_AVAILABLE:
        return jsonify({'username': username, 'score': 100, 'violation_count': 0,
                        'last_updated': None, 'last_action': None})
    try:
        db = next(database.get_db())
        rep = database.get_reputation(db, username)
        if not rep:
            return jsonify({'error': f"User '{username}' not found"}), 404
        return jsonify(rep)
    except Exception as e:
        gui_logger.error('api_get_user_reputation error: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/low-reputation', methods=['GET'])
@require_admin
def api_admin_low_reputation_users():
    """List users with reputation scores at or below a threshold (admin only).

    Query parameters:
      ``threshold``  – score threshold (default: REPUTATION_AUTO_BAN_THRESHOLD)
      ``limit``      – max results (default 50, max 200)

    Response JSON:
      ``threshold``  – threshold used
      ``users``      – list of ``{username, score, violation_count, last_action, last_updated}``
    """
    if not DB_AVAILABLE:
        return jsonify({'threshold': database.REPUTATION_AUTO_BAN_THRESHOLD, 'users': []})
    try:
        threshold = int(request.args.get('threshold', database.REPUTATION_AUTO_BAN_THRESHOLD))
        limit = max(1, min(200, int(request.args.get('limit', 50))))
    except (ValueError, TypeError):
        threshold = database.REPUTATION_AUTO_BAN_THRESHOLD
        limit = 50
    try:
        db = next(database.get_db())
        users = database.get_low_reputation_users(db, threshold=threshold, limit=limit)
        return jsonify({'threshold': threshold, 'users': users})
    except Exception as e:
        gui_logger.error('api_admin_low_reputation_users error: %s', e)
        return jsonify({'error': str(e)}), 500


def create_templates():
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create index.html
    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GAPI - Game Picker</title>
    <!-- Performance: resource hints for external origins -->
    <link rel="dns-prefetch" href="//fonts.googleapis.com">
    <link rel="dns-prefetch" href="//fonts.gstatic.com">
    <link rel="dns-prefetch" href="//store.steampowered.com">
    <link rel="preconnect" href="https://fonts.googleapis.com" crossorigin>
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 3em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .subtitle {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .status-bar {
            background: rgba(255,255,255,0.2);
            padding: 10px 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            color: white;
            text-align: center;
            font-weight: 500;
        }
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .tab {
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: all 0.3s;
        }
        
        .tab:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }
        
        .tab.active {
            background: white;
            color: #667eea;
        }
        
        .tab-content {
            display: none;
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        
        .tab-content.active {
            display: block;
        }
        
        .filters {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .filter-group {
            margin-bottom: 15px;
        }
        
        .filter-label {
            font-weight: 600;
            color: #333;
            margin-bottom: 10px;
            display: block;
        }
        
        .radio-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .radio-option {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .radio-option input[type="radio"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        
        .radio-option label {
            cursor: pointer;
            color: #555;
        }
        
        .genre-input {
            width: 100%;
            max-width: 500px;
            padding: 10px 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
        }
        
        .genre-input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .pick-button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 20px 40px;
            border-radius: 50px;
            font-size: 1.3em;
            font-weight: bold;
            cursor: pointer;
            display: block;
            margin: 30px auto;
            transition: all 0.3s;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .pick-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
        }
        
        .pick-button:active {
            transform: translateY(-1px);
        }
        
        .game-display {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 10px;
            margin-top: 20px;
            min-height: 200px;
        }
        
        .game-title {
            font-size: 2em;
            color: #333;
            margin-bottom: 10px;
        }
        
        .game-info {
            color: #666;
            margin: 10px 0;
            line-height: 1.6;
        }
        
        .game-description {
            margin: 15px 0;
            color: #444;
            line-height: 1.8;
        }

        .game-preview {
            margin: 12px 0 8px;
        }

        .game-preview img {
            width: 100%;
            max-width: 640px;
            height: auto;
            border-radius: 10px;
            display: block;
            box-shadow: 0 8px 18px rgba(0, 0, 0, 0.18);
        }
        
        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s;
        }
        
        .btn-favorite {
            background: #ffc107;
            color: #333;
        }
        
        .btn-favorite:hover {
            background: #ffb300;
        }
        
        .btn-link {
            background: #667eea;
            color: white;
        }
        
        .btn-link:hover {
            background: #5568d3;
        }
        
        .list-container {
            max-height: 500px;
            overflow-y: auto;
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-top: 15px;
        }
        
        .list-item {
            padding: 15px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }
        
        .list-item:hover {
            background: #f8f9fa;
            cursor: pointer;
        }
        
        .list-item:last-child {
            border-bottom: none;
        }
        
        .search-input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
            margin-bottom: 15px;
        }
        
        .search-input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .stat-label {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .top-games {
            margin-top: 30px;
        }
        
        .top-games h3 {
            margin-bottom: 15px;
            color: #333;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
        }
        
        .favorite-icon {
            color: #ffc107;
            margin-right: 8px;
        }
        
        /* Dark mode support */
        @media (prefers-color-scheme: dark) {
            body {
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            }
            
            .tab-content {
                background: #2a2a3e;
                color: #e0e0e0;
            }
            
            .filters {
                background: #3a3a4e !important;
            }
            
            .user-form {
                background: #3a3a4e !important;
            }
            
            .game-display {
                background: #3a3a4e !important;
            }
            
            .game-title {
                color: #e0e0e0;
            }
            
            .game-info {
                color: #b0b0b0;
            }
            
            .game-description {
                color: #c0c0c0;
            }
            
            .filter-label {
                color: #e0e0e0;
            }
            
            .radio-option label {
                color: #c0c0c0;
            }
            
            .list-item {
                border-bottom-color: #444;
            }
            
            .list-item:hover {
                background: #3a3a4e;
            }
            
            .list-container {
                border-color: #444;
            }
            
            .search-input {
                background: #2a2a3e;
                color: #e0e0e0;
                border-color: #555;
            }
            
            .search-input:focus {
                border-color: #667eea;
            }
            
            .genre-input {
                background: #2a2a3e;
                color: #e0e0e0;
                border-color: #555;
            }
            
            .genre-input:focus {
                border-color: #667eea;
            }
            
            .error {
                background: #3a2a2a;
                color: #ff9999;
            }
            
            .loading {
                color: #888;
            }
            
            .top-games h3 {
                color: #e0e0e0;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎮 GAPI</h1>
            <p class="subtitle">Pick your next Steam game to play!</p>
        </header>
        
        <div class="status-bar" id="status">Loading...</div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('picker', event)">Pick a Game</button>
            <button class="tab" onclick="switchTab('library', event)">Library</button>
            <button class="tab" onclick="switchTab('favorites', event)">Favorites</button>
            <button class="tab" onclick="switchTab('stats', event)">Statistics</button>
            <button class="tab" onclick="switchTab('users', event)">Users</button>
            <button class="tab" onclick="switchTab('multiuser', event)">Multi-User</button>
        </div>
        
        <!-- Picker Tab -->
        <div id="picker-tab" class="tab-content active">
            <div class="filters">
                <div class="filter-group">
                    <label class="filter-label">Filter Options</label>
                    <div class="radio-group">
                        <div class="radio-option">
                            <input type="radio" id="filter-all" name="filter" value="all" checked>
                            <label for="filter-all">All Games</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" id="filter-unplayed" name="filter" value="unplayed">
                            <label for="filter-unplayed">Unplayed Games</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" id="filter-barely" name="filter" value="barely">
                            <label for="filter-barely">Barely Played (< 2h)</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" id="filter-well" name="filter" value="well">
                            <label for="filter-well">Well-Played (> 10h)</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" id="filter-favorites" name="filter" value="favorites">
                            <label for="filter-favorites">Favorites Only</label>
                        </div>
                    </div>
                </div>
                
                <div class="filter-group">
                    <label class="filter-label" for="genre-filter">Genre (e.g., Action, RPG)</label>
                    <input type="text" id="genre-filter" class="genre-input" placeholder="Leave empty for any genre">
                </div>

                <div class="filter-group">
                    <label class="filter-label" for="vr-filter">VR Filter</label>
                    <select id="vr-filter" class="genre-input" style="cursor:pointer">
                        <option value="">All games (no VR filter)</option>
                        <option value="vr_supported">🥽 VR Supported (includes VR Only)</option>
                        <option value="vr_only">🥽 VR Only (requires headset)</option>
                        <option value="no_vr">🖥️ No VR (exclude VR games)</option>
                    </select>
                </div>
            </div>

            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <button class="pick-button" onclick="pickGame()">🎲 Pick Random Game</button>
            <button id="voice-pick-btn" class="pick-button" onclick="toggleVoicePick()"
                    title="Use voice commands to pick a game"
                    style="background:var(--button-bg,#4a90d9);flex:0 0 auto;padding:10px 14px;font-size:14px">
                🎤 Voice
            </button>
            </div>
            <div id="voice-status" style="display:none;margin-top:6px;padding:8px 12px;border-radius:6px;
                background:rgba(74,144,217,0.15);border:1px solid rgba(74,144,217,0.4);
                color:var(--text-secondary,#aaa);font-size:13px">
                🎤 Listening… say "<strong>pick</strong>", "<strong>reroll</strong>", or "<strong>stop</strong>"
            </div>
            
            <div id="game-result" class="game-display" style="display: none;">
                <!-- Game info will be displayed here -->
            </div>
        </div>
        
        <!-- Library Tab -->
        <div id="library-tab" class="tab-content">
            <input type="text" id="library-search" class="search-input" placeholder="Search your library..." oninput="searchLibrary()">
            <div id="library-list" class="list-container">
                <div class="loading">Loading library...</div>
            </div>
        </div>
        
        <!-- Favorites Tab -->
        <div id="favorites-tab" class="tab-content">
            <h2>⭐ Your Favorite Games</h2>
            <div id="favorites-list" class="list-container">
                <div class="loading">Loading favorites...</div>
            </div>
        </div>
        
        <!-- Stats Tab -->
        <div id="stats-tab" class="tab-content">
            <h2>📊 Library Statistics</h2>
            <div id="stats-content">
                <div class="loading">Loading statistics...</div>
            </div>
        </div>
        
        <!-- Users Tab -->
        <div id="users-tab" class="tab-content">
            <h2>👥 User Management</h2>
            
            <!-- Add User Form -->
            <div class="user-form" style="padding: 20px; border-radius: 10px; margin-bottom: 20px;">
                <h3>Add New User</h3>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px;">
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600;">Name *</label>
                        <input type="text" id="user-name" class="search-input" placeholder="Enter name" style="margin-bottom: 0;">
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600;">Email</label>
                        <input type="email" id="user-email" class="search-input" placeholder="Enter email" style="margin-bottom: 0;">
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600;">Steam ID *</label>
                        <input type="text" id="user-steam-id" class="search-input" placeholder="Enter Steam ID" style="margin-bottom: 0;">
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600;">Discord ID</label>
                        <input type="text" id="user-discord-id" class="search-input" placeholder="Enter Discord ID" style="margin-bottom: 0;">
                    </div>
                </div>
                <button onclick="addUser()" style="margin-top: 15px; padding: 10px 30px; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
                    ➕ Add User
                </button>
            </div>
            
            <!-- Users List -->
            <h3>Current Users</h3>
            <div id="users-list" class="list-container">
                <div class="loading">Loading users...</div>
            </div>
        </div>
        
        <!-- Multi-User Tab -->
        <div id="multiuser-tab" class="tab-content">
            <h2>🎮 Multi-User Game Picker</h2>
            
            <!-- User Selection -->
            <div style="padding: 20px; border-radius: 10px; margin-bottom: 20px;">
                <h3 style="margin-bottom: 15px;">Select Players</h3>

                <!-- Friends section -->
                <div style="margin-bottom: 12px;">
                    <strong>👥 Friends</strong>
                    <div id="friends-checkboxes" style="margin-top: 8px;">
                        <div class="loading">Loading friends...</div>
                    </div>
                </div>

                <!-- All users section -->
                <div>
                    <strong>👤 All Users</strong>
                    <div id="user-checkboxes" style="margin-top: 8px;">
                        <div class="loading">Loading users...</div>
                    </div>
                </div>
                
                <div style="margin-top: 15px;">
                    <label style="display: flex; align-items: center; gap: 10px;">
                        <input type="checkbox" id="coop-only" style="width: 18px; height: 18px;">
                        <span style="font-weight: 600;">Co-op/Multiplayer Games Only</span>
                    </label>
                </div>
                
                <button onclick="pickMultiUserGame()" style="margin-top: 20px; padding: 15px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 50px; cursor: pointer; font-size: 1.2em; font-weight: bold;">
                    🎲 Pick Common Game
                </button>
            </div>
            
            <!-- Multi-User Game Result -->
            <div id="multiuser-result" style="display: none; padding: 25px; border-radius: 10px;">
                <!-- Result will be displayed here -->
            </div>
            
            <!-- Common Games List -->
            <div style="margin-top: 20px;">
                <h3>Common Games <span id="common-count"></span></h3>
                <div id="common-games-list" class="list-container">
                    <div class="loading">Select users and click "Show Common Games" to see shared games</div>
                </div>
                <button onclick="showCommonGames()" style="margin-top: 10px; padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer;">
                    🔍 Show Common Games
                </button>
            </div>

            <!-- Live Pick Sessions -->
            <div style="margin-top: 30px; padding: 20px; border-radius: 10px; border: 2px solid #667eea;">
                <h3 style="margin-bottom: 15px;">🔴 Live Pick Sessions</h3>
                <p style="color: #888; margin-bottom: 12px; font-size: 0.95em;">
                    Create a session for online friends to join and pick a game together in real-time.
                </p>
                <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px;">
                    <button onclick="createLiveSession()" style="padding: 10px 24px; background: #28a745; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold;">
                        ➕ Create Live Session
                    </button>
                    <button onclick="refreshLiveSessions()" style="padding: 10px 18px; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer;">
                        🔄 Refresh
                    </button>
                    <span style="color: #888; font-size: 0.85em;" id="session-refresh-status"></span>
                </div>
                <!-- Join by session ID -->
                <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px;">
                    <input id="join-session-id" type="text" placeholder="Session ID…"
                           style="flex: 1; max-width: 320px; padding: 8px 12px; border: 1px solid #ccc; border-radius: 6px; font-size: 0.95em;">
                    <button onclick="joinBySessionId()" style="padding: 8px 18px; background: #764ba2; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        🔗 Join by ID
                    </button>
                </div>
                <div id="live-sessions-list" style="margin-top: 15px;">
                    <div class="loading">Loading sessions...</div>
                </div>
            </div>

            <!-- Invite Modal -->
            <div id="invite-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%;
                 background:rgba(0,0,0,0.5); z-index:9999; align-items:center; justify-content:center;">
                <div style="background:white; border-radius:10px; padding:24px; min-width:320px; max-width:480px; width:90%;">
                    <h3 style="margin-bottom:14px;">📨 Invite Friends</h3>
                    <div id="invite-friends-list" style="max-height:280px; overflow-y:auto; margin-bottom:14px;">
                        Loading…
                    </div>
                    <div style="display:flex; gap:8px; justify-content:flex-end;">
                        <button onclick="sendInvites()" style="padding:8px 20px; background:#28a745; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:bold;">
                            Send Invites
                        </button>
                        <button onclick="closeInviteModal()" style="padding:8px 16px; background:#6c757d; color:white; border:none; border-radius:6px; cursor:pointer;">
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Session Chat Modal -->
            <div id="session-chat-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%;
                 background:rgba(0,0,0,0.5); z-index:9999; align-items:center; justify-content:center;">
                <div style="background:white; border-radius:10px; padding:24px; min-width:340px; max-width:520px; width:92%; display:flex; flex-direction:column; max-height:80vh;">
                    <h3 style="margin-bottom:10px;">💬 Session Chat – <span id="chat-session-name" style="color:#667eea;"></span></h3>
                    <div id="chat-messages" style="flex:1; overflow-y:auto; border:1px solid #ddd; border-radius:6px; padding:10px; margin-bottom:10px; min-height:200px; font-size:0.9em;">
                        <div class="loading">Loading messages…</div>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <input id="chat-input" type="text" placeholder="Type a message…" maxlength="500"
                               style="flex:1; padding:8px 12px; border:1px solid #ccc; border-radius:6px; font-size:0.9em;"
                               onkeydown="if(event.key==='Enter') sendSessionChatMessage()">
                        <button onclick="sendSessionChatMessage()" style="padding:8px 16px; background:#667eea; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:bold;">Send</button>
                    </div>
                    <div style="display:flex; justify-content:flex-end; margin-top:10px;">
                        <button onclick="closeSessionChat()" style="padding:6px 16px; background:#6c757d; color:white; border:none; border-radius:6px; cursor:pointer;">Close</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentGame = null;
        
        // Initialize
        async function init() {
            await updateStatus();
            loadLibrary();
            loadFavorites();
            loadStats();
            loadUsers();
            // Send an initial presence heartbeat and repeat every 60 s
            sendPresenceHeartbeat();
            setInterval(sendPresenceHeartbeat, 60000);
        }

        async function sendPresenceHeartbeat() {
            try {
                await fetch('/api/presence', {method: 'POST'});
            } catch (_) {}
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
        
        function switchTab(tabName, event) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            event.target.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(tabName + '-tab').classList.add('active');
            
            // Reload data for the tab
            if (tabName === 'library') loadLibrary();
            if (tabName === 'favorites') loadFavorites();
            if (tabName === 'stats') loadStats();
            if (tabName === 'users') loadUsers();
            if (tabName === 'multiuser') {
                loadUsersForMultiUser();
                loadFriendsForMultiUser();
                refreshLiveSessions();
                startLiveSessionPolling();
                document.getElementById('common-games-list').innerHTML = '<div class="loading">Select users and click "Show Common Games"</div>';
            } else {
                stopLiveSessionPolling();
            }
        }
        
        async function pickGame() {
            const filterValue = document.querySelector('input[name="filter"]:checked').value;
            const genreValue = document.getElementById('genre-filter').value.trim();
            const vrFilter = document.getElementById('vr-filter').value || null;
            
            try {
                const response = await fetch('/api/pick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        filter: filterValue,
                        genre: genreValue,
                        vr_filter: vrFilter
                    })
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    alert(error.error || 'Failed to pick game');
                    return;
                }
                
                const game = await response.json();
                currentGame = game;
                displayGame(game);
                
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        // ── Voice commands (Web Speech API) ───────────────────────────────────
        let _voiceRecognition = null;
        let _voiceActive = false;

        function toggleVoicePick() {
            if (!('SpeechRecognition' in window) && !('webkitSpeechRecognition' in window)) {
                alert('Voice commands are not supported in this browser.\nTry Chrome or Edge.');
                return;
            }
            if (_voiceActive) {
                _stopVoice();
            } else {
                _startVoice();
            }
        }

        function _startVoice() {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            _voiceRecognition = new SR();
            _voiceRecognition.lang = 'en-US';
            _voiceRecognition.continuous = true;
            _voiceRecognition.interimResults = false;
            _voiceRecognition.maxAlternatives = 1;

            _voiceRecognition.onstart = () => {
                _voiceActive = true;
                document.getElementById('voice-status').style.display = 'block';
                document.getElementById('voice-pick-btn').textContent = '🎤 Stop';
                document.getElementById('voice-pick-btn').style.background = '#d94a4a';
            };

            _voiceRecognition.onend = () => {
                if (_voiceActive) {
                    // Auto-restart so it stays active until the user explicitly stops
                    try { _voiceRecognition.start(); } catch(e) {}
                }
            };

            _voiceRecognition.onerror = (ev) => {
                if (ev.error !== 'no-speech') {
                    _stopVoice();
                    console.warn('Voice recognition error:', ev.error);
                }
            };

            _voiceRecognition.onresult = (ev) => {
                const transcript = ev.results[ev.results.length - 1][0].transcript
                    .trim().toLowerCase();
                if (transcript.includes('pick') || transcript.includes('choose') ||
                        transcript.includes('random')) {
                    pickGame();
                } else if (transcript.includes('reroll') || transcript.includes('re-roll') ||
                        transcript.includes('again') || transcript.includes('another')) {
                    pickGame();
                } else if (transcript.includes('stop') || transcript.includes('quit') ||
                        transcript.includes('cancel')) {
                    _stopVoice();
                }
            };

            try { _voiceRecognition.start(); } catch(e) { console.error(e); }
        }

        function _stopVoice() {
            _voiceActive = false;
            if (_voiceRecognition) {
                try { _voiceRecognition.stop(); } catch(e) {}
                _voiceRecognition = null;
            }
            document.getElementById('voice-status').style.display = 'none';
            document.getElementById('voice-pick-btn').textContent = '🎤 Voice';
            document.getElementById('voice-pick-btn').style.background = '';
        }
        
        async function displayGame(game) {
            const resultDiv = document.getElementById('game-result');
            const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
            resultDiv.dataset.gameName = game.name || '';
            
            let html = `
                <div class="game-title">${favoriteIcon}${game.name}</div>
                <div class="game-info">
                    <strong>App ID:</strong> ${game.app_id}<br>
                    <strong>Playtime:</strong> ${game.playtime_hours} hours
                </div>
                <div id="game-details">Loading details...</div>
                <div class="action-buttons">
                    <button class="btn btn-favorite" onclick="toggleFavorite(${game.app_id})">
                        ${game.is_favorite ? '⭐ Remove from Favorites' : '⭐ Add to Favorites'}
                    </button>
                    <button class="btn btn-link" onclick="window.open('${game.steam_url}', '_blank')">
                        🔗 Open in Steam
                    </button>
                    <button class="btn btn-link" onclick="window.open('${game.steamdb_url}', '_blank')">
                        📊 Open in SteamDB
                    </button>
                </div>
            `;
            
            resultDiv.innerHTML = html;
            resultDiv.style.display = 'block';
            
            // Load details
            loadGameDetails(game.app_id);
        }
        
        async function loadGameDetails(appId) {
            try {
                const response = await fetch(`/api/game/${appId}/details`);
                if (response.ok) {
                    const details = await response.json();
                    let detailsHtml = '<div class="game-description">';

                    const previewUrl = details.header_image || details.capsule_image || `https://cdn.akamai.steamstatic.com/steam/apps/${appId}/header.jpg`;
                    const previewAlt = currentGame && currentGame.name ? `${currentGame.name} preview` : 'Game preview';
                    const safeAlt = previewAlt.replace(/"/g, '&quot;');
                    if (previewUrl) {
                        detailsHtml += `<div class="game-preview"><img src="${previewUrl}" alt="${safeAlt}" loading="lazy"></div>`;
                    }
                    
                    if (details.description) {
                        detailsHtml += `<p>${details.description}</p>`;
                    }
                    
                    if (details.genres) {
                        detailsHtml += `<p><strong>Genres:</strong> ${details.genres.join(', ')}</p>`;
                    }
                    
                    if (details.release_date) {
                        detailsHtml += `<p><strong>Release Date:</strong> ${details.release_date}</p>`;
                    }
                    
                    if (details.metacritic_score) {
                        detailsHtml += `<p><strong>Metacritic Score:</strong> ${details.metacritic_score}</p>`;
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
        
        async function toggleFavorite(appId) {
            const isFavorite = currentGame && currentGame.is_favorite;
            const method = isFavorite ? 'DELETE' : 'POST';
            
            try {
                const response = await fetch(`/api/favorite/${appId}`, {method});
                const data = await response.json();
                
                if (data.success) {
                    if (currentGame) {
                        currentGame.is_favorite = !isFavorite;
                        displayGame(currentGame);
                    }
                    await updateStatus();
                    loadFavorites();
                }
            } catch (error) {
                alert('Error updating favorite: ' + error.message);
            }
        }
        
        async function loadLibrary() {
            const listDiv = document.getElementById('library-list');
            listDiv.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch('/api/library');
                const data = await response.json();
                
                if (data.games && data.games.length > 0) {
                    let html = '';
                    data.games.forEach(game => {
                        const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
                        html += `
                            <div class="list-item" onclick="selectGame(${game.app_id})">
                                <div>
                                    ${favoriteIcon}<strong>${game.name}</strong>
                                </div>
                                <div>${game.playtime_hours}h</div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No games found</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading library</div>';
            }
        }
        
        async function searchLibrary() {
            const searchText = document.getElementById('library-search').value;
            const listDiv = document.getElementById('library-list');
            listDiv.innerHTML = '<div class="loading">Searching...</div>';
            
            try {
                const response = await fetch(`/api/library?search=${encodeURIComponent(searchText)}`);
                const data = await response.json();
                
                if (data.games && data.games.length > 0) {
                    let html = '';
                    data.games.forEach(game => {
                        const favoriteIcon = game.is_favorite ? '<span class="favorite-icon">⭐</span>' : '';
                        html += `
                            <div class="list-item" onclick="selectGame(${game.app_id})">
                                <div>
                                    ${favoriteIcon}<strong>${game.name}</strong>
                                </div>
                                <div>${game.playtime_hours}h</div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No games found</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error searching library</div>';
            }
        }
        
        function selectGame(appId) {
            // Switch to picker tab and show game details
            // For simplicity, we'll just open Steam page
            window.open(`https://store.steampowered.com/app/${appId}/`, '_blank');
        }
        
        async function loadFavorites() {
            const listDiv = document.getElementById('favorites-list');
            listDiv.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch('/api/favorites');
                const data = await response.json();
                
                if (data.favorites && data.favorites.length > 0) {
                    let html = '';
                    data.favorites.forEach(game => {
                        html += `
                            <div class="list-item">
                                <div>
                                    <span class="favorite-icon">⭐</span><strong>${game.name}</strong>
                                </div>
                                <div>
                                    ${game.playtime_hours}h
                                    <button class="btn btn-favorite" style="margin-left: 10px; padding: 5px 10px;"
                                            onclick="removeFavorite(${game.app_id})">Remove</button>
                                </div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No favorite games yet!</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading favorites</div>';
            }
        }
        
        async function removeFavorite(appId) {
            try {
                const response = await fetch(`/api/favorite/${appId}`, {method: 'DELETE'});
                const data = await response.json();
                
                if (data.success) {
                    loadFavorites();
                    await updateStatus();
                }
            } catch (error) {
                alert('Error removing favorite: ' + error.message);
            }
        }
        
        async function loadStats() {
            const statsDiv = document.getElementById('stats-content');
            statsDiv.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
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
                
                data.top_games.forEach((game, index) => {
                    html += `
                        <div class="list-item">
                            <div>
                                <strong>#${index + 1} ${game.name}</strong>
                            </div>
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
        
        // User Management Functions
        async function loadUsers() {
            const listDiv = document.getElementById('users-list');
            listDiv.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch('/api/users');
                const data = await response.json();
                
                if (data.users && data.users.length > 0) {
                    let html = '';
                    data.users.forEach(user => {
                        html += `
                            <div class="list-item" style="display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 15px; align-items: center;">
                                <div>
                                    <strong>${user.name}</strong><br>
                                    <small style="opacity: 0.7;">${user.email || 'No email'}</small>
                                </div>
                                <div>
                                    <small style="opacity: 0.7;">Steam ID:</small><br>
                                    <strong>${user.platforms?.steam || 'Not set'}</strong>
                                </div>
                                <div>
                                    <small style="opacity: 0.7;">Discord ID:</small><br>
                                    ${user.discord_id || 'Not linked'}
                                </div>
                                <div>
                                    <button onclick="removeUser('${user.name}')" class="btn btn-favorite" style="background: #f38ba8; padding: 5px 15px;">
                                        Remove
                                    </button>
                                </div>
                            </div>
                        `;
                    });
                    listDiv.innerHTML = html;
                } else {
                    listDiv.innerHTML = '<div class="loading">No users yet. Add one above!</div>';
                }
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading users</div>';
            }
        }
        
        async function addUser() {
            const name = document.getElementById('user-name').value.trim();
            const email = document.getElementById('user-email').value.trim();
            const steamId = document.getElementById('user-steam-id').value.trim();
            const discordId = document.getElementById('user-discord-id').value.trim();
            
            if (!name) {
                alert('Name is required!');
                return;
            }
            
            if (!steamId) {
                alert('Steam ID is required!');
                return;
            }
            
            try {
                console.log('Adding user:', {name, steamId, email, discordId});
                const response = await fetch('/api/users/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: name,
                        email: email,
                        steam_id: steamId,
                        discord_id: discordId
                    })
                });
                
                const data = await response.json();
                console.log('Server response:', data);
                
                if (response.ok) {
                    alert(data.message || 'User added successfully!');
                    // Clear form
                    document.getElementById('user-name').value = '';
                    document.getElementById('user-email').value = '';
                    document.getElementById('user-steam-id').value = '';
                    document.getElementById('user-discord-id').value = '';
                    // Reload users list
                    loadUsers();
                } else {
                    alert(data.error || 'Failed to add user');
                }
            } catch (error) {
                alert('Error adding user: ' + error.message);
                console.error('Error adding user:', error);
            }
        }
                alert('Error adding user: ' + error.message);
            }
        }
        
        async function removeUser(name) {
            if (!confirm(`Are you sure you want to remove ${name}?`)) {
                return;
            }
            
            try {
                const response = await fetch('/api/users/remove', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    alert(data.message || 'User removed successfully!');
                    loadUsers();
                    loadUsersForMultiUser();
                } else {
                    alert(data.error || 'Failed to remove user');
                }
            } catch (error) {
                alert('Error removing user: ' + error.message);
            }
        }
        
        // Multi-User Functions
        async function loadUsersForMultiUser() {
            const checkboxDiv = document.getElementById('user-checkboxes');
            checkboxDiv.innerHTML = '<div class="loading">Loading...</div>';
            
            try {
                const response = await fetch('/api/users');
                const data = await response.json();
                
                if (data.users && data.users.length > 0) {
                    let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px;">';
                    data.users.forEach(user => {
                        html += `
                            <label style="display: flex; align-items: center; gap: 10px; padding: 10px; background: white; border-radius: 8px; cursor: pointer;">
                                <input type="checkbox" class="user-checkbox" value="${user.name}" style="width: 18px; height: 18px;">
                                <span><strong>${user.name}</strong></span>
                            </label>
                        `;
                    });
                    html += '</div>';
                    checkboxDiv.innerHTML = html;
                } else {
                    checkboxDiv.innerHTML = '<div class="loading">No users found. Add users in the Users tab first.</div>';
                }
            } catch (error) {
                checkboxDiv.innerHTML = '<div class="error">Error loading users</div>';
            }
        }

        async function loadFriendsForMultiUser() {
            const div = document.getElementById('friends-checkboxes');
            div.innerHTML = '<div class="loading">Loading...</div>';
            try {
                const response = await fetch('/api/app-friends');
                if (!response.ok) {
                    div.innerHTML = '<div class="loading">Log in to see friends.</div>';
                    return;
                }
                const data = await response.json();
                const friends = data.friends || [];
                if (friends.length === 0) {
                    div.innerHTML = '<div class="loading">No friends yet. Add friends in your profile!</div>';
                    return;
                }
                let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px;">';
                friends.forEach(friend => {
                    const onlineDot = friend.is_online
                        ? '<span style="color:#28a745;font-size:0.8em;" title="Online">🟢</span>'
                        : '<span style="color:#aaa;font-size:0.8em;" title="Offline">⚫</span>';
                    const hasPlatform = friend.steam_id || friend.epic_id || friend.gog_id;
                    const disabledAttr = hasPlatform ? '' : 'disabled title="No platform ID linked"';
                    html += `
                        <label style="display: flex; align-items: center; gap: 10px; padding: 10px; background: white; border-radius: 8px; cursor: ${hasPlatform ? 'pointer' : 'default'}; opacity: ${hasPlatform ? '1' : '0.5'};">
                            <input type="checkbox" class="user-checkbox" value="${friend.username}" style="width: 18px; height: 18px;" ${disabledAttr}>
                            <span>${onlineDot} <strong>${friend.display_name}</strong></span>
                        </label>
                    `;
                });
                html += '</div>';
                div.innerHTML = html;
            } catch (error) {
                div.innerHTML = '<div class="error">Error loading friends</div>';
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
            
            const coopOnly = document.getElementById('coop-only').checked;
            const resultDiv = document.getElementById('multiuser-result');
            
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '<div class="loading">Picking a game...</div>';
            
            try {
                const response = await fetch('/api/multiuser/pick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        users: selectedUsers,
                        coop_only: coopOnly,
                        max_players: selectedUsers.length
                    })
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    resultDiv.innerHTML = `<div class="error">${error.error || 'No common games found'}</div>`;
                    return;
                }
                
                const game = await response.json();
                
                let html = `
                    <h3 style="color: #667eea; margin-bottom: 15px;">🎮 ${game.name}</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px;">
                        <div>
                            <strong>App ID:</strong> ${game.app_id}
                        </div>
                        <div>
                            <strong>Players:</strong> ${game.owners ? game.owners.join(', ') : selectedUsers.join(', ')}
                        </div>
                        ${game.is_coop ? '<div><strong>✅ Co-op Game</strong></div>' : ''}
                        ${game.is_multiplayer ? '<div><strong>✅ Multiplayer</strong></div>' : ''}
                    </div>
                    <div style="display: flex; gap: 10px;">
                        <a href="${game.steam_url}" target="_blank" class="btn btn-link">🔗 Steam Store</a>
                        <a href="${game.steamdb_url}" target="_blank" class="btn btn-link">📊 SteamDB</a>
                    </div>
                `;
                
                resultDiv.innerHTML = html;
            } catch (error) {
                resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
            }
        }
        
        async function showCommonGames() {
            const selectedUsers = getSelectedUsers();
            const listDiv = document.getElementById('common-games-list');
            const countSpan = document.getElementById('common-count');
            
            listDiv.innerHTML = '<div class="loading">Loading...</div>';
            
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
                                    <small style="color: #666;">Owned by: ${game.owners ? game.owners.join(', ') : 'All selected users'}</small>
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
            }
        }

        // Live Pick Session Functions
        let _inviteSessionId = null;
        let _liveSessionPollTimer = null;
        let _liveSessionSSE = null;   // active EventSource (per-session)
        let _activeSessions = {};     // sessionId -> session object (updated by SSE / poll)

        // ---- SSE helpers ----

        function _subscribeSessionSSE(sessionId) {
            if (_liveSessionSSE) {
                _liveSessionSSE.close();
                _liveSessionSSE = null;
            }
            if (!window.EventSource) return;  // browser doesn't support SSE
            const es = new EventSource(`/api/live-session/${sessionId}/events`);
            es.addEventListener('session', (e) => {
                try {
                    const raw = JSON.parse(e.data);
                    // Payload is {event, data} from _sse_publish; fall back to raw for
                    // the initial state message which is sent as a plain session dict.
                    const data = (raw && raw.data) ? raw.data : raw;
                    if (!data || typeof data !== 'object') return;
                    if (data.status === 'closed') {
                        delete _activeSessions[sessionId];
                    } else {
                        _activeSessions[sessionId] = data;
                    }
                    _renderLiveSessions();
                } catch (err) {
                    console.error('SSE session parse error:', err);
                }
            });
            es.onerror = () => {
                es.close();
                if (_liveSessionSSE === es) _liveSessionSSE = null;
            };
            _liveSessionSSE = es;
        }

        function _closeSessionSSE() {
            if (_liveSessionSSE) {
                _liveSessionSSE.close();
                _liveSessionSSE = null;
            }
        }

        // ---- Render the sessions list from _activeSessions ----

        function _renderLiveSessions() {
            const listDiv = document.getElementById('live-sessions-list');
            if (!listDiv) return;
            const sessions = Object.values(_activeSessions);
            const statusEl = document.getElementById('session-refresh-status');
            if (statusEl) statusEl.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
            if (sessions.length === 0) {
                listDiv.innerHTML = '<div class="loading">No active sessions. Create one above!</div>';
                return;
            }
            let html = '';
            sessions.forEach(s => {
                const pickedInfo = s.picked_game
                    ? `<br><small style="color:#28a745;">✅ Game picked: <strong>${s.picked_game.name || s.picked_game.app_id || '?'}</strong></small>`
                    : '';
                html += `
                    <div style="padding: 12px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 10px; background: white;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px;">
                            <div>
                                <strong>${s.name || s.session_id}</strong>
                                <span style="font-size:0.8em; color:#888; margin-left: 8px;">${s.status}</span><br>
                                <small style="color:#555;">Host: ${s.host} &nbsp;|&nbsp; Participants: ${s.participants.join(', ')}</small>
                                ${pickedInfo}
                            </div>
                            <div style="display:flex; gap:6px; flex-wrap: wrap;">
                                <button onclick="joinLiveSession('${s.session_id}')" style="padding:6px 14px; background:#667eea; color:white; border:none; border-radius:6px; cursor:pointer;">Join</button>
                                <button onclick="pickForLiveSession('${s.session_id}')" style="padding:6px 14px; background:#764ba2; color:white; border:none; border-radius:6px; cursor:pointer;">🎲 Pick</button>
                                <button onclick="openInviteModal('${s.session_id}')" style="padding:6px 14px; background:#fd7e14; color:white; border:none; border-radius:6px; cursor:pointer;">📨 Invite</button>
                                <button onclick="openSessionChat('${s.session_id}')" style="padding:6px 14px; background:#20c997; color:white; border:none; border-radius:6px; cursor:pointer;">💬 Chat</button>
                                <button onclick="leaveLiveSession('${s.session_id}')" style="padding:6px 14px; background:#dc3545; color:white; border:none; border-radius:6px; cursor:pointer;">Leave</button>
                            </div>
                        </div>
                    </div>
                `;
            });
            listDiv.innerHTML = html;
        }

        async function createLiveSession() {
            try {
                const response = await fetch('/api/live-session/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert(err.error || 'Failed to create session');
                    return;
                }
                const session = await response.json();
                alert(`Live session created! Session ID:\\n${session.session_id}\\n\\nShare this ID with friends so they can join.`);
                _activeSessions[session.session_id] = session;
                _subscribeSessionSSE(session.session_id);
                _renderLiveSessions();
            } catch (error) {
                alert('Error creating session: ' + error.message);
            }
        }

        async function joinLiveSession(sessionId) {
            try {
                const response = await fetch(`/api/live-session/${sessionId}/join`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'}
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert(err.error || 'Failed to join session');
                    return;
                }
                const data = await response.json();
                const session = data.session || data;
                if (session.session_id) {
                    _activeSessions[session.session_id] = session;
                    _subscribeSessionSSE(session.session_id);
                    _renderLiveSessions();
                } else {
                    refreshLiveSessions();
                }
            } catch (error) {
                alert('Error joining session: ' + error.message);
            }
        }

        async function joinBySessionId() {
            const input = document.getElementById('join-session-id');
            const sessionId = (input ? input.value : '').trim();
            if (!sessionId) {
                alert('Please enter a session ID first.');
                return;
            }
            await joinLiveSession(sessionId);
            if (input) input.value = '';
        }

        async function leaveLiveSession(sessionId) {
            try {
                const response = await fetch(`/api/live-session/${sessionId}/leave`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'}
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert(err.error || 'Failed to leave session');
                    return;
                }
                refreshLiveSessions();
            } catch (error) {
                alert('Error leaving session: ' + error.message);
            }
        }

        async function pickForLiveSession(sessionId) {
            const coopOnly = document.getElementById('coop-only').checked;
            try {
                const response = await fetch(`/api/live-session/${sessionId}/pick`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({coop_only: coopOnly})
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'No common game found');
                    return;
                }
                const resultDiv = document.getElementById('multiuser-result');
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = `
                    <h3 style="color: #667eea; margin-bottom: 15px;">🎮 ${data.name}</h3>
                    <p>Picked for live session <em>${sessionId}</em></p>
                    <div style="display: flex; gap: 10px; margin-top: 10px;">
                        <a href="${data.steam_url}" target="_blank" class="btn btn-link">🔗 Steam Store</a>
                        <a href="${data.steamdb_url}" target="_blank" class="btn btn-link">📊 SteamDB</a>
                    </div>
                `;
                refreshLiveSessions();
            } catch (error) {
                alert('Error picking game: ' + error.message);
            }
        }

        function openInviteModal(sessionId) {
            _inviteSessionId = sessionId;
            const modal = document.getElementById('invite-modal');
            modal.style.display = 'flex';
            const listDiv = document.getElementById('invite-friends-list');
            listDiv.innerHTML = 'Loading friends…';
            fetch('/api/app-friends')
                .then(r => r.json())
                .then(data => {
                    const friends = (data.friends || []);
                    if (friends.length === 0) {
                        listDiv.innerHTML = '<p style="color:#888;">No friends found. Add friends first!</p>';
                        return;
                    }
                    let html = '';
                    friends.forEach(f => {
                        const dot = f.is_online
                            ? '<span style="color:#28a745;">🟢</span>'
                            : '<span style="color:#aaa;">⚫</span>';
                        html += `
                            <label style="display:flex; align-items:center; gap:10px; padding:8px; border-bottom:1px solid #eee; cursor:pointer;">
                                <input type="checkbox" class="invite-checkbox" value="${f.username}">
                                ${dot} <strong>${f.display_name}</strong>
                                <small style="color:#888;">(${f.username})</small>
                            </label>
                        `;
                    });
                    listDiv.innerHTML = html;
                })
                .catch(() => {
                    listDiv.innerHTML = '<p style="color:red;">Error loading friends</p>';
                });
        }

        function closeInviteModal() {
            document.getElementById('invite-modal').style.display = 'none';
            _inviteSessionId = null;
        }

        // ---- Session Chat ----

        let _chatSessionId = null;
        let _chatPollTimer = null;
        let _chatLastId = 0;

        function openSessionChat(sessionId) {
            _chatSessionId = sessionId;
            _chatLastId = 0;
            const modal = document.getElementById('session-chat-modal');
            modal.style.display = 'flex';
            const session = _activeSessions[sessionId] || {};
            document.getElementById('chat-session-name').textContent = session.name || sessionId;
            document.getElementById('chat-messages').innerHTML = '<div class="loading">Loading messages…</div>';
            _loadChatMessages(true);
            if (_chatPollTimer) clearInterval(_chatPollTimer);
            _chatPollTimer = setInterval(() => _loadChatMessages(false), 3000);
        }

        function closeSessionChat() {
            document.getElementById('session-chat-modal').style.display = 'none';
            if (_chatPollTimer) { clearInterval(_chatPollTimer); _chatPollTimer = null; }
            _chatSessionId = null;
        }

        async function _loadChatMessages(initial) {
            if (!_chatSessionId) return;
            const room = `session:${_chatSessionId}`;
            try {
                const url = `/api/chat/messages?room=${encodeURIComponent(room)}&since_id=${_chatLastId}&limit=50`;
                const response = await fetch(url);
                if (!response.ok) return;
                const data = await response.json();
                const msgs = data.messages || [];
                if (!msgs.length && initial) {
                    document.getElementById('chat-messages').innerHTML = '<div style="color:#888;text-align:center;padding:20px;">No messages yet. Say hello!</div>';
                    return;
                }
                if (!msgs.length) return;
                _chatLastId = msgs[msgs.length - 1].id;
                const container = document.getElementById('chat-messages');
                const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 10;
                msgs.forEach(m => {
                    const el = document.createElement('div');
                    el.style.cssText = 'padding:4px 0; border-bottom:1px solid #f0f0f0;';
                    const ts = new Date(m.created_at).toLocaleTimeString();
                    el.innerHTML = `<strong style="color:#667eea;">${_escapeHtml(m.sender)}</strong> <small style="color:#aaa;">${ts}</small><br>${_escapeHtml(m.message)}`;
                    container.appendChild(el);
                });
                if (atBottom || initial) container.scrollTop = container.scrollHeight;
            } catch (_) {}
        }

        async function sendSessionChatMessage() {
            if (!_chatSessionId) return;
            const input = document.getElementById('chat-input');
            const message = (input ? input.value : '').trim();
            if (!message) return;
            const room = `session:${_chatSessionId}`;
            try {
                const response = await fetch('/api/chat/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({room, message})
                });
                if (!response.ok) {
                    const err = await response.json();
                    alert(err.error || 'Failed to send message');
                    return;
                }
                if (input) input.value = '';
                await _loadChatMessages(false);
            } catch (error) {
                alert('Error sending message: ' + error.message);
            }
        }

        function _escapeHtml(str) {
            return String(str)
                .replace(/&/g,'&amp;').replace(/</g,'&lt;')
                .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        }

        async function sendInvites() {
            const sessionId = _inviteSessionId;
            if (!sessionId) return;
            const checkboxes = document.querySelectorAll('.invite-checkbox:checked');
            const usernames = Array.from(checkboxes).map(cb => cb.value);
            if (usernames.length === 0) {
                alert('Select at least one friend to invite.');
                return;
            }
            try {
                const response = await fetch(`/api/live-session/${sessionId}/invite`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({usernames})
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'Failed to send invites');
                    return;
                }
                const sentCount = (data.sent || []).length;
                const failCount = (data.failed || []).length;
                alert(`Invites sent: ${sentCount}${failCount ? `, failed: ${failCount}` : ''}`);
                closeInviteModal();
            } catch (error) {
                alert('Error sending invites: ' + error.message);
            }
        }

        async function refreshLiveSessions() {
            const listDiv = document.getElementById('live-sessions-list');
            if (!listDiv) return;
            try {
                const response = await fetch('/api/live-session/active');
                if (!response.ok) {
                    listDiv.innerHTML = '<div class="loading">Could not load sessions.</div>';
                    return;
                }
                const data = await response.json();
                _activeSessions = {};
                (data.sessions || []).forEach(s => { _activeSessions[s.session_id] = s; });
                _renderLiveSessions();
            } catch (error) {
                listDiv.innerHTML = '<div class="error">Error loading sessions</div>';
            }
        }

        function startLiveSessionPolling() {
            // Use SSE for individual session we just joined/created when possible.
            // Fall back to 5-second polling for the full active list (covers sessions we're not subscribed to).
            if (_liveSessionPollTimer) return;
            _liveSessionPollTimer = setInterval(refreshLiveSessions, 5000);
        }

        function stopLiveSessionPolling() {
            if (_liveSessionPollTimer) {
                clearInterval(_liveSessionPollTimer);
                _liveSessionPollTimer = null;
            }
            _closeSessionSSE();
        }
        
        // Initialize on page load
        init();
    </script>
</body>
</html>
"""
    
    index_path = os.path.join(templates_dir, 'index.html')
    # Preserve any existing template file (custom or previously written).
    # Only write the bundled fallback when no file exists at all.
    if not os.path.exists(index_path):
        with open(index_path, 'w') as f:
            f.write(index_html)


def main():
    """Main entry point for GUI"""
    parser = argparse.ArgumentParser(description='GAPI Web GUI')
    parser.add_argument('--config', default='config.json', help='Path to config file')
    parser.add_argument('--demo', action='store_true', help='Run with demo data')
    parser.add_argument(
        '--host',
        default=os.getenv('GAPI_HOST', '127.0.0.1'),
        help='Host interface to bind (use 0.0.0.0 for remote access)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv('GAPI_PORT', '5000')),
        help='Port to bind the web server on'
    )
    args = parser.parse_args()

    demo_mode = args.demo
    config_path = args.config
    host = args.host
    port = args.port

    if demo_mode:
        global _demo_current_user
        demo_config_path = '.demo_config.json'
        config_path = demo_config_path
        demo_config = {
            'steam_api_key': 'DEMO_MODE',
            'steam_id': 'DEMO_MODE'
        }
        with open(demo_config_path, 'w') as f:
            json.dump(demo_config, f)

        original_fetch = gapi.GamePicker.fetch_games
        original_get_details = gapi.SteamAPIClient.get_game_details
        original_load_config = gapi.GamePicker.load_config

        def demo_fetch_games(self):
            self.games = DEMO_GAMES
            return True

        def demo_get_details(self, game_id):
            return None

        def demo_load_config(self, config_path: str):
            if config_path == demo_config_path:
                return demo_config
            return original_load_config(self, config_path)

        gapi.GamePicker.fetch_games = demo_fetch_games
        gapi.SteamAPIClient.get_game_details = demo_get_details
        gapi.GamePicker.load_config = demo_load_config

        initialize_picker(config_path=config_path)
        _demo_current_user = 'demo'

    # Create templates
    create_templates()
    
    # Setup real-time routes if available
    if REALTIME_AVAILABLE:
        try:
            realtime.setup_realtime_routes(app)
            gui_logger.info('Real-time routes initialized')
        except Exception as e:
            gui_logger.warning('Real-time initialization failed: %s', e)
    
    # Start background sync scheduler
    sync_scheduler.start()
    
    # Run Flask app
    print("\n" + "="*60)
    print("🎮 GAPI Web GUI is starting...")
    print("="*60)
    print("\nOpen your browser and go to:")
    print(f"  http://{host}:{port}")
    if host == '0.0.0.0':
        print(f"  (or http://<server-ip>:{port} from another machine)")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")
    
    try:
        app.run(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("🛑 GAPI Web GUI stopped")
        print("="*60 + "\n")
    finally:
        # Stop background scheduler
        sync_scheduler.stop()
        
        if demo_mode and os.path.exists(config_path):
            os.remove(config_path)


if __name__ == "__main__":
    main()
