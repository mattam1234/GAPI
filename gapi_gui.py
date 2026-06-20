#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
import argparse
import uuid
import secrets
import random
from flask import Flask, render_template, jsonify, request, session, Response, redirect as flask_redirect
from flask import has_request_context
import threading
import json
import os
import sys
import csv
import io
import tempfile
import subprocess
import signal
import collections
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Deque, Any, Set
from functools import wraps
from werkzeug.local import LocalProxy
from urllib.parse import unquote, quote_plus
import gapi
import multiuser
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
DEFAULT_ENV_PATH = os.path.join(BASE_DIR, '.env')
try:
    from dotenv import load_dotenv
    load_dotenv(DEFAULT_ENV_PATH)
except Exception:
    pass
os.environ.setdefault('GAPI_CONFIG_PATH', DEFAULT_CONFIG_PATH)
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
    from app.repositories.backlog_repository import BacklogRepository as SharedBacklogRepository
    from app.services.backlog_service import BacklogService as SharedBacklogService
except Exception:
    SharedBacklogRepository = None  # type: ignore[assignment]
    SharedBacklogService = None  # type: ignore[assignment]

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

# Phase 10: Email notification service
try:
    from app.services.email_service import EmailService as _EmailService
    _email_service = _EmailService.from_env()
except Exception as _e:
    print(f'Warning: EmailService failed to load: {_e}')
    _email_service = None

# Phase 11: Web Push notification service
try:
    from app.services.push_notification_service import PushNotificationService as _PushNotificationService
    _push_service = _PushNotificationService.from_env()
except Exception as _e:
    print(f'Warning: PushNotificationService failed to load: {_e}')
    _push_service = None

try:
    from discord_presence import DiscordPresence as _DiscordPresence
    _discord_rpc = _DiscordPresence()
    PRESENCE_AVAILABLE = True
except Exception:
    _discord_rpc = None
    PRESENCE_AVAILABLE = False

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
    config_path = DEFAULT_CONFIG_PATH
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


# ---------------------------------------------------------------------------
# Per-user GamePicker instances
# ---------------------------------------------------------------------------
# The global ``picker`` is kept for backward-compat / demo mode.  All web
# route handlers should call ``ensure_picker_initialized(username)`` which
# returns the *caller's* private GamePicker instead of mutating the global.
# ---------------------------------------------------------------------------

# Global game picker instance (kept for backward-compat and demo mode only)
picker: Optional[gapi.GamePicker] = None
picker_lock = threading.Lock()
current_game: Optional[Dict] = None

# Per-user picker instances: username -> GamePicker
_pickers: Dict[str, gapi.GamePicker] = {}
_pickers_lock = threading.Lock()

# Directory that holds per-user sub-directories with JSON data files
_USER_DATA_DIR = 'user_data'
_SHARED_BACKLOGS_FILE = os.path.join(_USER_DATA_DIR, '.gapi_shared_backlogs.json')
_shared_backlog_service = None


def _get_shared_backlog_service():
    """Return the shared backlog collection service."""
    global _shared_backlog_service
    if _shared_backlog_service is not None:
        return _shared_backlog_service
    if SharedBacklogRepository is None or SharedBacklogService is None:
        raise RuntimeError('Backlog collections are unavailable')
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    _shared_backlog_service = SharedBacklogService(
        SharedBacklogRepository(_SHARED_BACKLOGS_FILE, backend='db')
    )
    return _shared_backlog_service


def _sanitize_username(username: str) -> str:
    """Return a filesystem-safe version of *username* for use as a directory name."""
    import re
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', username)
    return safe[:64] or 'user'

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
            "    discord_id VARCHAR(50),\n"
            "    epic_id VARCHAR(255),\n"
            "    gog_id VARCHAR(255),\n"
            "    email VARCHAR(255),\n"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
            "    last_seen TIMESTAMP,\n"
            "    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,\n"
            "    suspended_until TIMESTAMP,\n"
            "    suspended_reason VARCHAR(500),\n"
            "    suspended_by VARCHAR(255),\n"
            "    suspended_at TIMESTAMP\n"
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
    'users_add_email': {
        'label': 'Users add email column',
        'description': 'Add email column to users table (if missing).',
        'sql': (
            "ALTER TABLE users \n"
            "ADD COLUMN IF NOT EXISTS email VARCHAR(255);"
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
        return database.hash_password(password)
    
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
            user = database.create_or_update_user(db, username, password, '', '', '', role)
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
            gui_logger.info('Login attempt - username=%s', username)
            is_valid = database.verify_user_password(db, username, password)
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
                    'gog_id': user.gog_id or '',
                    'discord_id': user.discord_id or ''
                }
            return {}
            
        except Exception as e:
            gui_logger.exception('Error getting user IDs: %s', e)
            return {}
    
    def update_user_ids(self, username: str, steam_id: str = '', epic_id: str = '', gog_id: str = '',
                        discord_id: str = '') -> bool:
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
            if discord_id:
                user.discord_id = discord_id
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


def _resolve_repo_path(path: str) -> str:
    """Resolve application-local paths relative to the repository root."""
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def load_base_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict:
    """Load base config without enforcing Steam ID requirements.

    The GUI uses per-user Steam IDs, so only the API key is required here.
    """
    config_path = _resolve_repo_path(config_path)
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
    from werkzeug.local import LocalProxy as _LocalProxy
    # If current_user has been replaced with a plain value (e.g. in tests),
    # use it directly rather than going through the session-based resolver.
    if not isinstance(current_user, _LocalProxy):
        val = current_user
        if val and str(val) not in ('', 'None'):
            return str(val)
    username = get_current_username()
    return username if username else ''


def _is_valid_email_address(address: str) -> bool:
    """Return ``True`` if *address* is a plausible email address.

    Uses :func:`email.utils.parseaddr` for extraction, then checks for a
    non-empty local part, exactly one ``@``, and a domain with a dot.
    """
    import email.utils as _eu
    if not address or not isinstance(address, str):
        return False
    _, addr = _eu.parseaddr(address.strip())
    if not addr or addr.count('@') != 1:
        return False
    local, domain = addr.split('@', 1)
    return bool(local) and '.' in domain and not domain.startswith('.')


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


def _sync_user_achievements_from_cached_library(username: str) -> Dict[str, int]:
    """Best-effort achievements sync for all cached Steam games for one user."""
    result = {'synced': 0, 'skipped': 0, 'errors': 0}
    if not ensure_db_available():
        return result

    try:
        base_config = load_base_config()
        steam_api_key = str(base_config.get('steam_api_key', '')).strip()
        if not steam_api_key or gapi.is_placeholder_value(steam_api_key):
            gui_logger.info("Skipping auto achievement sync for %s: Steam API key missing", username)
            return result

        db = database.SessionLocal()
        try:
            user = database.get_user(db, username)
            steam_id = getattr(user, 'steam_id', '') if user else ''
            if not steam_id:
                gui_logger.info("Skipping auto achievement sync for %s: Steam ID missing", username)
                return result

            cached_games = (
                _library_service.get_cached(db, username)
                if _library_service
                else database.get_cached_library(db, username)
            ) or []
        finally:
            db.close()

        if not cached_games:
            return result

        steam_client = gapi.SteamAPIClient(steam_api_key)
        for game in cached_games:
            app_id = str(game.get('app_id', '')).strip()
            if not app_id.isdigit():
                result['skipped'] += 1
                continue

            game_name = str(game.get('name') or app_id).strip() or app_id
            try:
                player_achievements = steam_client.get_player_achievements_detailed(steam_id, app_id)
                if not player_achievements:
                    result['skipped'] += 1
                    continue

                schema = steam_client.get_schema_for_game(app_id)
                db_game = database.SessionLocal()
                try:
                    database.sync_steam_achievements(
                        db_game,
                        username,
                        steam_id,
                        app_id,
                        game_name,
                        player_achievements,
                        schema,
                    )
                finally:
                    db_game.close()
                result['synced'] += 1
            except Exception:
                gui_logger.exception(
                    "Auto achievement sync failed for %s app_id=%s",
                    username,
                    app_id,
                )
                result['errors'] += 1
    except Exception:
        gui_logger.exception("Auto achievement sync failed for user %s", username)
    return result


def _queue_library_achievement_sync(username: str) -> None:
    """Queue background achievement sync for the user's cached library."""
    def _run():
        stats = _sync_user_achievements_from_cached_library(username)
        gui_logger.info(
            "Auto achievement sync complete for %s: synced=%s skipped=%s errors=%s",
            username,
            stats.get('synced', 0),
            stats.get('skipped', 0),
            stats.get('errors', 0),
        )

    threading.Thread(target=_run, daemon=True).start()


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
        _queue_library_achievement_sync(username)
        return True, f"Synced {count} games and queued achievement sync"
        
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
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseClone);
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

// ── Push: receive a Web Push notification ─────────────────────────────────
self.addEventListener('push', (event) => {
  let data = { title: 'GAPI', body: 'You have a new notification.', url: '/', icon: '/static/icon-192.png', badge: '/static/badge-72.png' };
  if (event.data) {
    try { Object.assign(data, JSON.parse(event.data.text())); } catch (_) {}
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body:  data.body,
      icon:  data.icon  || '/static/icon-192.png',
      badge: data.badge || '/static/badge-72.png',
      data:  { url: data.url || '/' },
    })
  );
});

// ── Notification click: focus or open the target URL ─────────────────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
"""
    return sw_js, 200, {
        'Content-Type': 'application/javascript; charset=utf-8',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Service-Worker-Allowed': '/',
    }


def _invalidate_picker_for_user(username: str) -> None:
    """Evict the per-user picker from the cache so the next request reloads it.

    Call this after a library sync so the updated game list is picked up.
    """
    with _pickers_lock:
        _pickers.pop(username, None)


def ensure_picker_initialized(username: str = None) -> Optional[gapi.GamePicker]:
    """Return the per-user GamePicker, creating and populating it if needed.

    Each authenticated user gets their own GamePicker instance stored in
    ``_pickers``.  Private data (reviews, tags, playlists, backlog, budget,
    wishlist, schedule, history, favorites) is persisted in per-user
    sub-directories under ``_USER_DATA_DIR`` so it is never visible to other
    users.

    Args:
        username: Username to load games for. If None, uses current_user.

    Returns:
        The user's GamePicker instance, or None on failure.
    """
    global picker  # kept for backward-compat / demo mode

    if username is None:
        username = get_current_username()

    if not username:
        return None

    # Fast path: return existing instance with games already loaded
    with _pickers_lock:
        existing = _pickers.get(username)
        if existing is not None and existing.games:
            picker = existing  # keep backward-compat global in sync
            return existing

    # Slow path: create a new GamePicker for this user
    user_data_dir = os.path.join(_USER_DATA_DIR, _sanitize_username(username))
    try:
        os.makedirs(user_data_dir, exist_ok=True)
        p = gapi.GamePicker(config_path='config.json', data_dir=user_data_dir)
    except Exception as e:
        gui_logger.exception("Failed to create picker for user %s: %s", username, e)
        return None

    # Load the user's game library from the database cache
    if DB_AVAILABLE and ensure_db_available():
        try:
            db = database.SessionLocal()
            try:
                if _library_service:
                    cached_games = _library_service.get_cached(db, username)
                else:
                    cached_games = database.get_cached_library(db, username)

                if cached_games:
                    p.games = [
                        {
                            'appid': int(g['app_id']) if str(g['app_id']).isdigit() else g['app_id'],
                            'name': g['name'],
                            'playtime_forever': int(g.get('playtime_hours', 0) * 60),
                            'platform': g.get('platform', 'steam'),
                        }
                        for g in cached_games
                    ]
                    gui_logger.info(
                        "Loaded %d games for %s from database cache", len(p.games), username
                    )
                else:
                    gui_logger.warning("No cached games for %s", username)
                    p.games = list(DEMO_GAMES)
            finally:
                db.close()
        except Exception as e:
            gui_logger.exception("Failed to load games from database: %s", e)
            p.games = list(DEMO_GAMES)
    else:
        p.games = list(DEMO_GAMES)

    with _pickers_lock:
        # Another thread may have won the race; prefer the one that already has
        # games loaded (returned via the fast path above) to avoid double work.
        existing = _pickers.get(username)
        if existing is not None and existing.games:
            picker = existing
            return existing
        _pickers[username] = p

    picker = p  # keep backward-compat global in sync
    return p


@app.route('/api/status')
def api_status():
    """Get application status"""
    username = get_current_username()

    # Check if user is logged in
    if not username:
        return jsonify({
            'ready': False,
            'logged_in': False,
            'message': 'Please log in'
        })

    p = ensure_picker_initialized(username)

    if p is None:
        return jsonify({
            'ready': False,
            'logged_in': True,
            'message': 'Loading games...'
        })

    return jsonify({
        'ready': True,
        'logged_in': True,
        'current_user': username,
        'is_admin': user_manager.is_admin(username),
        'total_games': len(p.games) if p.games else 0,
        'favorites': len(p.favorites) if p.favorites else 0
    })


def _resolve_pick_filter_type(payload: Dict) -> str:
    """Resolve canonical pick filter from request payload.

    Supports both modern ``filter`` values and client-facing ``mode`` values.
    """
    data = payload if isinstance(payload, dict) else {}
    raw_filter = str(data.get('filter', '') or '').strip().lower()
    if raw_filter:
        return raw_filter

    mode = str(data.get('mode', '') or '').strip().lower()
    mode_to_filter = {
        'random': 'all',
        'all': 'all',
        'unplayed': 'unplayed',
        'barely_played': 'barely',
        'barely': 'barely',
        'well_played': 'well',
        'well': 'well',
        'favorites': 'favorites',
    }
    return mode_to_filter.get(mode, 'all')


def _legacy_pick_payload(game: Dict) -> Dict:
    """Return game payload compatible with extension/mobile clients."""
    platform = str(game.get('platform', 'steam') or 'steam')
    app_id = game.get('appid', game.get('app_id'))
    game_id = game.get('game_id')
    if not game_id and app_id is not None:
        game_id = f'{platform}:{app_id}'

    playtime_forever = game.get('playtime_forever')
    if playtime_forever is None:
        try:
            playtime_forever = int(round(float(game.get('playtime_hours', 0)) * 60))
        except Exception:
            playtime_forever = 0

    payload = {
        'name': game.get('name', 'Unknown Game'),
        'platform': platform,
        'appid': app_id,
        'app_id': app_id,
        'game_id': game_id,
        'playtime_forever': int(playtime_forever or 0),
        'playtime_hours': round((int(playtime_forever or 0) / 60), 1),
    }
    return payload


@app.route('/api/health', methods=['GET'])
def api_health():
    """Public lightweight health endpoint for external clients."""
    username = get_current_username()
    return jsonify({
        'ok': True,
        'status': 'healthy',
        'authenticated': bool(username),
        'current_user': username if username else None,
    })


# MIGRATED to FastAPI: GET /api/random-game -> backend/routers/pick.py


@app.route('/api/history', methods=['GET'])
@require_login
def api_history_legacy():
    """Return recent pick history for mobile client compatibility."""
    username = get_current_username()
    p = ensure_picker_initialized(username)
    if p is None:
        return jsonify({'history': []})

    games_by_id = {
        str(g.get('game_id')): g
        for g in (p.games or [])
        if g.get('game_id')
    }

    entries = []
    recent_ids = list(p.history[-50:]) if getattr(p, 'history', None) else []
    now_iso = datetime.now(timezone.utc).isoformat()
    for idx, game_id in enumerate(reversed(recent_ids), start=1):
        game = games_by_id.get(str(game_id), {})
        platform = game.get('platform', '')
        app_id = game.get('appid')
        if not platform and isinstance(game_id, str) and ':' in game_id:
            platform = game_id.split(':', 1)[0]
        if app_id is None and isinstance(game_id, str) and ':' in game_id:
            app_id = game_id.split(':', 1)[1]
        entries.append({
            'id': idx,
            'game_name': game.get('name') or str(game_id),
            'game_id': str(game_id),
            'platform': platform or 'steam',
            'picked_at': now_iso,
            'playtime_at_pick': int(game.get('playtime_forever', 0) or 0),
            'app_id': app_id,
        })

    return jsonify({'history': entries})


# ===========================================================================================
# Authentication Endpoints
# ===========================================================================================

# ===========================================================================================
# First-time Setup Endpoints
# ===========================================================================================

# MIGRATED to FastAPI: GET /api/filters/platform-options -> backend/routers/catalog.py (filters_router)


def _game_identity_tokens(game: Optional[Dict]) -> Set[str]:
    """Return comparable identifiers for a game payload."""
    if not isinstance(game, dict):
        return set()
    tokens: Set[str] = set()
    game_id = str(game.get('game_id') or '').strip()
    if game_id:
        tokens.add(game_id)
        if ':' in game_id:
            suffix = game_id.rsplit(':', 1)[-1].strip()
            if suffix:
                tokens.add(suffix)
    app_id = str(game.get('appid') or game.get('app_id') or game.get('id') or '').strip()
    if app_id:
        tokens.add(app_id)
        platform = str(game.get('platform') or 'steam').strip().lower()
        tokens.add(f'{platform}:{app_id}')
        tokens.add(f'steam:{app_id}')
    return {token for token in tokens if token}


# MIGRATED to FastAPI: POST /api/pick -> backend/routers/pick.py. The core
# single-user pick handler (filters, rarity, collection, Discord RPC, detail
# caching, background ProtonDB + webhook fan-out, pick audit) is served
# natively by the FastAPI app (backend.main:app).


# MIGRATED to FastAPI: POST /api/presence/update -> backend/routers/presence.py


# MIGRATED to FastAPI: POST /api/presence/clear -> backend/routers/presence.py


# MIGRATED to FastAPI: GET /api/game/<int:app_id>/details -> backend/routers/game.py


# MIGRATED to FastAPI: POST/DELETE /api/favorite/<int:app_id> -> backend/routers/catalog.py (favorite_router)


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
            'game_id': f"steam:{g.get('appid')}" if g.get('appid') else '',
            'name': g.get('name', 'Unknown'),
            'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
            'is_favorite': False,
            'platform': 'steam',
            'genres': g.get('genres', []) if isinstance(g.get('genres', []), list) else [],
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
                safe_app_token = str(app_id).strip() if app_id is not None else ''
                try:
                    app_id_int = int(app_id) if app_id else None
                except (ValueError, TypeError):
                    app_id_int = None

                games.append({
                    'app_id': app_id_int,
                    'game_id': game.get('game_id') or (f"{str(game.get('platform') or 'steam').strip().lower()}:{safe_app_token}" if safe_app_token else ''),
                    'name': name,
                    'playtime_hours': round(game.get('playtime_hours', 0), 1),
                    'is_favorite': str(app_id) in favorite_ids if app_id else False,
                    'platform': game.get('platform', 'steam'),
                    'last_played': game.get('last_played').isoformat() if game.get('last_played') else None,
                    'genres': game.get('genres', []) if isinstance(game.get('genres', []), list) else [],
                    'tags': game.get('tags', []) if isinstance(game.get('tags', []), list) else [],
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
            'game_id': f"steam:{g.get('appid')}" if g.get('appid') else '',
            'name': g.get('name', 'Unknown'),
            'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
            'is_favorite': False,
            'platform': 'steam',
            'genres': g.get('genres', []) if isinstance(g.get('genres', []), list) else [],
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


# MIGRATED to FastAPI: GET /api/favorites -> backend/routers/catalog.py (favorites_router)


# MIGRATED to FastAPI: see backend/routers/social_stats.py. The /api/stats
# (library statistics), /api/stats/compare/candidates, and /api/stats/compare
# routes are served natively by the FastAPI app (backend.main:app), reusing the
# same DB-backed _library_service / _db_favorites_service singletons. Removed
# from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


@app.route('/api/users')
@require_login
def api_users_list():
    """Get users for the multi-user game picker.

    Query params:
      scope: 'all' (default) | 'friends' | 'me_and_friends'
    """
    username = get_current_username()
    scope = (request.args.get('scope') or 'all').strip().lower()
    users = user_manager.get_all_users()

    if scope in ('friends', 'me_and_friends'):
        allowed_usernames = set()
        if scope == 'me_and_friends' and username:
            allowed_usernames.add(str(username).strip().lower())

        if ensure_db_available() and username:
            db = database.SessionLocal()
            try:
                friends_data = database.get_app_friends_with_platforms(db, username)
                for friend in friends_data.get('friends', []):
                    friend_username = str(friend.get('username') or '').strip().lower()
                    if friend_username:
                        allowed_usernames.add(friend_username)
            finally:
                db.close()

        users = [
            u for u in users
            if str(u.get('username') or '').strip().lower() in allowed_usernames
        ]

    if scope == 'all':
        users = [
            u for u in users
            if u.get('steam_id') or u.get('epic_id') or u.get('gog_id')
        ]

    return jsonify({'users': users})


# ===========================================================================================
# Ignored Games Endpoints
# ===========================================================================================

# MIGRATED to FastAPI: see backend/routers/ignored.py. The /api/ignored-games
# routes (list + toggle) are served natively by the FastAPI app
# (backend.main:app), reusing the same DB-backed _ignored_games_service.
# Removed from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# ===========================================================================================
# Achievement Hunting Endpoints
# ===========================================================================================

# MIGRATED to FastAPI: see backend/routers/achievements.py. The
# /api/achievements (hunt list), /api/achievement-hunt (start) and
# /api/achievement-hunt/<id> (update) routes are served natively by the
# FastAPI app (backend.main:app), reusing the DB-backed achievement_service.
# Other /api/achievements/* routes (Steam stats/sync) remain in Flask.


@app.route('/api/users/all')
@require_admin
def api_users_all():
    """Get all users with full details (admin only)"""
    users = user_manager.get_all_users()
    return jsonify({'users': users})


# ---------------------------------------------------------------------------
# Password-reset request endpoints
# ---------------------------------------------------------------------------

@app.route('/api/password-reset-request', methods=['POST'])
def api_password_reset_request():
    """Submit a password reset request (public, no authentication required)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.json or {}
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'Username is required'}), 400
    try:
        db = database.SessionLocal()
        user = db.query(database.User).filter(database.User.username == username).first()
        if not user:
            db.close()
            # Generic response to avoid username enumeration
            return jsonify({'message': 'If that username exists, your request has been recorded.'}), 200
        entry = database.PasswordResetRequest(username=username)
        db.add(entry)
        db.commit()
        db.close()
        gui_logger.info('Password reset requested for user: %s', username)
        return jsonify({'message': 'Password reset request submitted. An admin will contact you.'}), 200
    except Exception as e:
        gui_logger.exception('Error creating password reset request: %s', e)
        return jsonify({'error': 'Failed to submit request'}), 500


@app.route('/api/admin/password-reset-requests', methods=['GET'])
@require_admin
def api_admin_password_reset_requests():
    """List pending password reset requests (admin only)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    try:
        db = database.SessionLocal()
        rows = (
            db.query(database.PasswordResetRequest)
            .order_by(database.PasswordResetRequest.requested_at.desc())
            .all()
        )
        result = [
            {
                'id': r.id,
                'username': r.username,
                'requested_at': r.requested_at.isoformat() if r.requested_at else None,
                'status': r.status,
                'dismissed_by': r.dismissed_by,
                'dismissed_at': r.dismissed_at.isoformat() if r.dismissed_at else None,
            }
            for r in rows
        ]
        db.close()
        return jsonify({'requests': result})
    except Exception as e:
        gui_logger.exception('Error fetching password reset requests: %s', e)
        return jsonify({'error': 'Failed to fetch requests'}), 500


@app.route('/api/admin/password-reset-requests/<int:request_id>/dismiss', methods=['POST'])
@require_admin
def api_admin_password_reset_dismiss(request_id):
    """Mark a password reset request as dismissed (admin only)."""
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    admin_user = get_current_username()
    try:
        db = database.SessionLocal()
        entry = db.query(database.PasswordResetRequest).filter(
            database.PasswordResetRequest.id == request_id
        ).first()
        if not entry:
            db.close()
            return jsonify({'error': 'Request not found'}), 404
        entry.status = 'dismissed'
        entry.dismissed_by = admin_user
        entry.dismissed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.close()
        return jsonify({'message': 'Request dismissed'})
    except Exception as e:
        gui_logger.exception('Error dismissing password reset request: %s', e)
        return jsonify({'error': 'Failed to dismiss request'}), 500


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


# MIGRATED to FastAPI: POST /api/multiuser/pick -> backend/routers/multiuser.py


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

# MIGRATED to FastAPI: see backend/routers/voting.py. The /api/voting routes
# (create, vote, status, close) are served natively by the FastAPI app
# (backend.main:app), reusing the same multi_picker voting-session machinery.
# Removed from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# -----------------------------------------------------------------------
# Reviews endpoints
# -----------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/reviews.py. The /api/reviews routes
# are now served natively by the FastAPI app (backend.main:app), which reuses
# the same per-user picker review_service. Removed from the Flask layer per the
# strangler-fig migration (docs/MODERNIZATION_BRIEF.md).


# MIGRATED to FastAPI: see backend/routers/tags.py. The /api/tags and
# /api/library/by-tag routes are now served natively by the FastAPI app
# (backend.main:app), reusing the same per-user picker tag_service. Removed
# from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Game Night Scheduler endpoints
# ---------------------------------------------------------------------------

def _resolve_schedule_game_image_url(game: Optional[Dict] = None,
                                     game_appid: Optional[str] = None,
                                     existing_url: Optional[str] = None) -> str:
    """Resolve game image using same fallback strategy as game details UI.

    Order:
    1) explicit existing URL
    2) game.image_url
    3) game.header_image
    4) game.capsule_image
    5) Steam CDN header by appid
    """
    if existing_url:
        return str(existing_url).strip()

    game = game or {}
    # Direct image fields supplied by the various platform clients
    # (Steam: header/capsule image, PSN: image_url, Nintendo: boxart).
    for key in ('image_url', 'header_image', 'capsule_image', 'boxart'):
        value = str(game.get(key, '') or '').strip()
        if value:
            return value

    # Steam CDN fallback by appid is ONLY valid for Steam games. Other stores
    # (GOG, Epic, ...) also use numeric ids that are NOT Steam appids, so guard
    # on the platform to avoid building a wrong/broken Steam URL from a GOG id.
    platform = str(game.get('platform', '') or '').strip().lower()
    appid = str(game_appid or game.get('appid') or game.get('app_id') or '').strip()
    if appid.isdigit() and platform in ('', 'steam'):
        return f'https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg'

    return ''


def _build_schedule_game_links(game_appid: Optional[str], game_name: str = '') -> Dict[str, str]:
    """Build the same game links used in game details modal."""
    appid = str(game_appid or '').strip()
    safe_game_name = str(game_name or '').strip()
    links: Dict[str, str] = {
        'steam_url': '',
        'steamdb_url': '',
        'keyshop_url': '',
    }
    if appid:
        links['steam_url'] = f'https://store.steampowered.com/app/{appid}/'
        links['steamdb_url'] = f'https://steamdb.info/app/{appid}/'
    if safe_game_name:
        links['keyshop_url'] = (
            'https://www.allkeyshop.com/blog/catalogue/search/'
            f'{quote_plus(safe_game_name)}/?results=50'
        )
    return links


def _get_schedule_game_short_description(game_appid: Optional[str]) -> str:
    """Fetch game short description using the same source as game details API."""
    appid = str(game_appid or '').strip()
    if not appid.isdigit():
        return ''
    # Use the global picker as a best-effort helper (it is shared infrastructure
    # after the per-user migration; we only need the Steam client here, not user
    # data, so any initialised picker will do).
    p = picker
    if not p:
        return ''
    try:
        if p.steam_client and isinstance(p.steam_client, gapi.SteamAPIClient):
            details = p.steam_client.get_game_details(int(appid)) or {}
            return str(details.get('short_description', '') or '').strip()
    except Exception as exc:
        gui_logger.debug(f'Could not fetch short description for app {appid}: {exc}')
    return ''


def _build_discord_schedule_description(game_name: str,
                                        game_appid: Optional[str],
                                        notes: str,
                                        attendees: List[str]) -> str:
    """Build Discord event description including game description and links."""
    safe_game_name = str(game_name or '').strip() or 'TBA'
    safe_notes = str(notes or '').strip()
    safe_attendees = [str(a).strip() for a in (attendees or []) if str(a).strip()]
    links = _build_schedule_game_links(game_appid, safe_game_name)
    game_description = _get_schedule_game_short_description(game_appid)

    lines: List[str] = [f'🎮 {safe_game_name}']
    if safe_notes:
        lines.extend(['', safe_notes])
    if safe_attendees:
        lines.extend(['', f"👥 {', '.join(safe_attendees)}"])
    if game_description:
        lines.extend(['', f'📖 {game_description[:280]}'])

    link_lines = [
        f"🔗 Steam: {links['steam_url']}" if links.get('steam_url') else '',
        f"📊 SteamDB: {links['steamdb_url']}" if links.get('steamdb_url') else '',
        f"💰 AllKeyShop: {links['keyshop_url']}" if links.get('keyshop_url') else '',
    ]
    link_lines = [line for line in link_lines if line]
    if link_lines:
        lines.extend(['', *link_lines])

    lines.extend(['', '📅 Created by GAPI Game Night Scheduler'])
    description = '\n'.join(lines)
    return description[:1000]


def _schedule_local_to_utc(date_str: str,
                           time_str: str,
                           timezone_name: Optional[str] = None,
                           timezone_offset_minutes: Optional[int] = None):
    """Interpret schedule date/time as local time, then convert to UTC.

    This prevents treating local input as already-UTC, which causes shifted
    times in Discord scheduled events.
    """
    from datetime import datetime, timezone, timedelta

    dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
    if dt.tzinfo is None:
        tz_name = str(timezone_name or '').strip()
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

        if timezone_offset_minutes is not None:
            try:
                # Convention matches JS Date.getTimezoneOffset(): the value is
                # (UTC - local) in minutes (e.g. -120 for UTC+2), so UTC is
                # obtained by ADDING the offset to the local time.
                offset = int(timezone_offset_minutes)
                dt = dt + timedelta(minutes=offset)
                return dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


def _build_schedule_ical_token(username: str) -> str:
    """Return a signed token for authenticated iCal feed access."""
    from itsdangerous import URLSafeSerializer

    serializer = URLSafeSerializer(app.secret_key or app.config.get('SECRET_KEY') or 'gapi-dev', salt='schedule-ical-feed')
    return serializer.dumps({'username': str(username or '').strip()})


def _resolve_schedule_ical_username(token: str) -> Optional[str]:
    """Resolve a username from a signed iCal feed token."""
    from itsdangerous import BadSignature, URLSafeSerializer

    safe_token = str(token or '').strip()
    if not safe_token:
        return None
    serializer = URLSafeSerializer(app.secret_key or app.config.get('SECRET_KEY') or 'gapi-dev', salt='schedule-ical-feed')
    try:
        payload = serializer.loads(safe_token)
    except BadSignature:
        return None
    username = str((payload or {}).get('username') or '').strip()
    return username or None


def _build_schedule_ical_sync_urls(username: str, base_url: str = None) -> Dict[str, str]:
    """Build absolute HTTPS and webcal feed URLs for the current user.

    ``base_url`` lets a non-Flask caller (the FastAPI router) supply the request
    root; when omitted it falls back to the Flask request context.
    """
    token = _build_schedule_ical_token(username)
    root = (base_url or request.url_root).rstrip('/')
    feed_url = f"{root}/api/schedule/export.ics?token={quote_plus(token)}&download=0"
    scheme, _, remainder = feed_url.partition('://')
    webcal_scheme = 'webcals' if scheme == 'https' else 'webcal'
    return {
        'feed_url': feed_url,
        'webcal_url': f'{webcal_scheme}://{remainder}' if remainder else feed_url,
        'token': token,
    }


def _normalize_schedule_username(value: Optional[str]) -> str:
    return str(value or '').strip().lower()


def _schedule_invitee_pairs(event: Optional[Dict]) -> List[Tuple[str, str]]:
    event = event or {}
    attendees = event.get('invited_attendees', event.get('attendees', []))
    attendee_ids = event.get('invited_attendee_ids', event.get('attendee_ids', []))
    clean_attendees = attendees if isinstance(attendees, list) else []
    clean_attendee_ids = attendee_ids if isinstance(attendee_ids, list) else []
    pairs: List[Tuple[str, str]] = []
    for index, attendee_name in enumerate(clean_attendees):
        name = str(attendee_name or '').strip()
        if not name:
            continue
        attendee_id = str(clean_attendee_ids[index] if index < len(clean_attendee_ids) else name).strip() or name
        pairs.append((name, attendee_id))
    return pairs


def _schedule_event_members(event: Optional[Dict]) -> Dict[str, str]:
    """Return canonical username map for users linked to a schedule event."""
    members: Dict[str, str] = {}
    for name, attendee_id in _schedule_invitee_pairs(event):
        for candidate in (attendee_id, name):
            key = _normalize_schedule_username(candidate)
            if key and key not in members:
                members[key] = str(candidate).strip()
    host = str((event or {}).get('created_by') or '').strip()
    host_key = _normalize_schedule_username(host)
    if host_key and host_key not in members:
        members[host_key] = host
    return members


def _send_schedule_in_app_notifications(recipients: List[str],
                                        title: str,
                                        message: str,
                                        exclude_usernames: Optional[set] = None,
                                        link: Optional[str] = None) -> None:
    """Send in-app (+ Discord DM fallback) notifications for schedule events.

    Delegates to :func:`_send_invite_notifications` so behaviour is consistent
    with session invites.  The *link* parameter may be set after ``_send_invite_notifications``
    is defined; callers that already use this helper gain the Discord-DM fallback
    automatically.
    """
    # _send_invite_notifications is defined below this function in the file;
    # we call it lazily to avoid a forward-reference issue.
    _send_invite_notifications(
        recipients,
        title=title,
        message=message,
        link=link,
        exclude_usernames=exclude_usernames,
    )


def _load_discord_bot_token_from_config() -> Optional[str]:
    token = str(os.getenv('DISCORD_BOT_TOKEN', '') or '').strip()
    if token:
        return token
    config_path = os.environ.get('GAPI_DISCORD_CONFIG', 'config.json')
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, 'r') as handle:
            data = json.load(handle)
        token = str((data or {}).get('discord_bot_token') or '').strip()
        return token or None
    except Exception:
        return None


def _send_schedule_discord_dm(recipient_username: str, message: str) -> bool:
    """Best-effort Discord DM delivery for a linked user."""
    if not DB_AVAILABLE:
        return False
    safe_username = str(recipient_username or '').strip()
    if not safe_username:
        return False

    db = next(database.get_db())
    try:
        user = database.get_user_by_username(db, safe_username)
        discord_id = str(getattr(user, 'discord_id', '') or '').strip() if user else ''
    except Exception:
        discord_id = ''
    finally:
        if db:
            db.close()

    if not discord_id or not discord_id.isdigit():
        return False

    token = _load_discord_bot_token_from_config()
    if not token:
        return False

    try:
        import requests
        headers = {'Authorization': f'Bot {token}', 'Content-Type': 'application/json'}
        channel_resp = requests.post(
            'https://discord.com/api/v10/users/@me/channels',
            json={'recipient_id': discord_id},
            headers=headers,
            timeout=8,
        )
        if channel_resp.status_code not in (200, 201):
            return False
        channel_id = str((channel_resp.json() or {}).get('id') or '').strip()
        if not channel_id:
            return False
        message_resp = requests.post(
            f'https://discord.com/api/v10/channels/{channel_id}/messages',
            json={'content': message[:1800]},
            headers=headers,
            timeout=8,
        )
        return message_resp.status_code in (200, 201)
    except Exception as exc:
        gui_logger.warning('Failed schedule Discord DM to %s: %s', safe_username, exc)
        return False


def _send_invite_notification(recipient: str, title: str, message: str,
                               link: Optional[str] = None) -> bool:
    """Send an in-app notification to *recipient* and fall back to a Discord DM
    if the user is currently offline.

    Args:
        recipient: Target GAPI username.
        title:     Notification title.
        message:   Notification body text.
        link:      Optional deep-link stored on the notification (e.g. ``#schedule/42``).

    Returns:
        True if at least one channel (in-app or Discord) succeeded.
    """
    if not DB_AVAILABLE:
        return False
    recipient = str(recipient or '').strip()
    if not recipient:
        return False

    in_app_ok = False
    db = next(database.get_db())
    try:
        in_app_ok = database.create_notification(
            db, recipient, title=title, message=message, type='info', link=link
        )
        # Check online status to decide on Discord DM fallback
        user = database.get_user_by_username(db, recipient)
        is_online = False
        if user and getattr(user, 'last_seen', None):
            from datetime import timedelta as _td
            is_online = user.last_seen >= (datetime.utcnow() - _td(minutes=5))
    except Exception as exc:
        gui_logger.warning('Failed in-app invite notification to %s: %s', recipient, exc)
        is_online = True  # avoid unnecessary Discord call on error
    finally:
        if db:
            db.close()

    if not is_online:
        _send_schedule_discord_dm(recipient, message)

    return in_app_ok


def _send_invite_notifications(recipients: List[str], title: str, message: str,
                                link: Optional[str] = None,
                                exclude_usernames: Optional[set] = None) -> None:
    """Send invite notifications (in-app + Discord DM fallback) to a list of users.

    This is the single authoritative helper for both session and schedule
    invite flows to keep behaviour consistent.
    """
    excluded = {_normalize_schedule_username(u) for u in (exclude_usernames or set()) if u}
    seen: set = set()
    for recipient in recipients:
        key = _normalize_schedule_username(recipient)
        if not key or key in excluded or key in seen:
            continue
        seen.add(key)
        try:
            _send_invite_notification(recipient, title=title, message=message, link=link)
        except Exception as exc:
            gui_logger.warning('Invite notification failed for %s: %s', recipient, exc)


# MIGRATED to FastAPI (chunk 2): GET /api/schedule -> see
# backend/routers/schedule.py (event_router).


# MIGRATED to FastAPI (chunk 1 of the schedule domain): see
# backend/routers/schedule.py. The /api/schedules collection routes (list,
# create, update, delete) are served natively by the FastAPI app
# (backend.main:app), reusing the per-user picker schedule_service. The
# /api/schedule event routes below remain in Flask pending follow-up chunks.
# (docs/MODERNIZATION_BRIEF.md)


# MIGRATED to FastAPI (chunk 4c, completing the schedule domain): POST
# /api/schedule (create) and DELETE /api/schedule/<event_id> are served
# natively by the FastAPI app (backend/routers/schedule.py event_router),
# including the inline Discord event create/cancel integration. The entire
# schedule domain now lives in backend/routers/schedule.py.


# ---------------------------------------------------------------------------
# Schedule Fuzzy Search API - Games and Attendees
# ---------------------------------------------------------------------------

def _parse_search_limit(value, default: int = 10, maximum: int = 50) -> int:
    """Parse and clamp a search ``limit`` parameter from request input.

    Tolerates missing/invalid values (returns ``default``) and bounds the
    result to ``[1, maximum]`` so a client can't request an unbounded page.
    """
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    if limit < 1:
        return default
    return min(limit, maximum)


def _safe_playtime_hours(game: Dict) -> float:
    """Best-effort playtime in hours, tolerant of missing/invalid data."""
    try:
        hours = game.get('playtime_hours')
        if hours is None:
            minutes = float(game.get('playtime_forever', 0) or 0)
            hours = minutes / 60
        return round(float(hours or 0), 1)
    except (TypeError, ValueError):
        return 0.0


def _fuzzy_search_games(query: str, games: List[Dict], limit: int = 10) -> List[Dict]:
    """Fuzzy search games by name or app ID.
    
    Args:
        query: Search query (game title, partial title, or app ID).
        games: List of game dicts to search through.
        limit: Maximum number of results to return.
        
    Returns:
        List of matching game dicts, sorted by relevance.
    """
    from difflib import SequenceMatcher
    
    if not query or not games:
        return []
    
    query_lower = query.lower()
    scored_games = []
    
    for game in games:
        name = str(game.get('name', '')).lower()
        appid = str(game.get('appid') or game.get('app_id') or '')
        
        # Check exact matches first (app ID)
        if appid == query_lower:
            scored_games.append((game, 1.0))
            continue
        
        # Check if app ID contains query
        if query_lower in appid:
            ratio = 0.95
            scored_games.append((game, ratio))
            continue
        
        # Fuzzy match on name with prefix boost
        if name.startswith(query_lower):
            ratio = 0.9 + (0.1 * SequenceMatcher(None, query_lower, name).ratio())
        else:
            ratio = SequenceMatcher(None, query_lower, name).ratio()
        
        if ratio >= 0.6:  # Only include matches with 60%+ similarity
            scored_games.append((game, ratio))
    
    # Sort by score descending, then by name for ties
    scored_games.sort(key=lambda x: (-x[1], x[0].get('name', '')))
    return [game for game, score in scored_games[:limit]]


def _fuzzy_search_users(query: str, users: List[Dict], limit: int = 10) -> List[Dict]:
    """Fuzzy search users/friends by name.
    
    Args:
        query: Search query (user name or partial name).
        users: List of user dicts to search through.
        limit: Maximum number of results to return.
        
    Returns:
        List of matching user dicts, sorted by relevance.
    """
    from difflib import SequenceMatcher
    
    if not query or not users:
        return []
    
    query_lower = query.lower()
    scored_users = []
    
    for user in users:
        name = str(user.get('name', '')).lower()
        
        # Check for exact match
        if name == query_lower:
            scored_users.append((user, 1.0))
            continue
        
        # Fuzzy match on name with prefix boost
        if name.startswith(query_lower):
            ratio = 0.9 + (0.1 * SequenceMatcher(None, query_lower, name).ratio())
        else:
            ratio = SequenceMatcher(None, query_lower, name).ratio()
        
        if ratio >= 0.6:  # Only include matches with 60%+ similarity
            scored_users.append((user, ratio))
    
    scored_users.sort(key=lambda x: (-x[1], x[0].get('name', '')))
    return [user for user, score in scored_users[:limit]]


# MIGRATED to FastAPI (chunk 3): the /api/schedule/search-games,
# /search-attendees, /common-games and /common-games/random routes are served
# natively by the FastAPI app (backend/routers/schedule.py event_router).


# MIGRATED to FastAPI (chunk 4b): GET /api/schedule/discord-guilds and
# POST /api/schedule/<event_id>/create-discord-event are served natively by
# the FastAPI app (backend/routers/schedule.py event_router).


# ---------------------------------------------------------------------------
# Playlists API
# ---------------------------------------------------------------------------


# MIGRATED to FastAPI: see backend/routers/playlists.py. The /api/playlists
# routes (list, create, delete, and games add/list/remove) are served
# natively by the FastAPI app (backend.main:app), reusing the same per-user
# picker playlist_service. Removed from the Flask layer per the strangler-fig
# migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Backlog / Status Tracker API
# ---------------------------------------------------------------------------


def _parse_shared_member_usernames(raw_members) -> List[str]:
    """Normalize member usernames supplied as JSON arrays or comma-separated strings."""
    if isinstance(raw_members, str):
        return [value.strip() for value in raw_members.split(',') if value.strip()]
    return [str(value).strip() for value in (raw_members or []) if str(value).strip()]


def _serialize_backlog_summaries(backlogs: List[Dict], service, current_username: Optional[str]) -> List[Dict]:
    """Attach UI summary fields to backlog collections."""
    current_user_key = str(current_username or '').strip().lower()
    enriched = []
    for backlog in backlogs or []:
        item = dict(backlog or {})
        members = [str(member).strip() for member in (item.get('members') or []) if str(member).strip()]
        invited_count = len([member for member in members if member.lower() != current_user_key])
        item['entry_count'] = service.get_collection_entry_count(item.get('id'))
        item['invited_count'] = max(invited_count, 0)
        enriched.append(item)
    return enriched


# MIGRATED to FastAPI: see backend/routers/backlog.py. The /api/backlogs
# (collections) and /api/backlog (per-game status) routes are served natively
# by the FastAPI app (backend.main:app), reusing the same shared-backlog
# service and helpers. Removed from the Flask layer per the strangler-fig
# migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Budget Tracking API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/budget.py. The /api/budget routes
# (summary, set/update price, delete) are served natively by the FastAPI app
# (backend.main:app), reusing the same per-user picker budget_service.
# Removed from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Wishlist & Sale Alerts API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/wishlist.py. The /api/wishlist
# routes (list, add, remove, sale check) are now served natively by the
# FastAPI app (backend.main:app), reusing the same per-user picker
# wishlist_service. Removed from the Flask layer per the strangler-fig
# migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Achievement Tracking API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/achievements/<int:app_id> -> see
# backend/routers/achievements.py. The /sync POSTs remain in Flask.


# ---------------------------------------------------------------------------
# Achievement sync (Steam API → database)
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: POST /api/achievements/sync -> see
# backend/routers/achievements.py.


# ---------------------------------------------------------------------------
# Per-platform achievement sync
# ---------------------------------------------------------------------------

# Platform stub sync functions — extend these when real API clients are added
def _sync_platform_achievements_epic(username: str, user) -> Dict:
    """Stub for Epic Games achievement sync (not yet implemented)."""
    return {'status': 'not_configured', 'error': 'Epic Games integration not yet available', 'synced': [], 'errors': []}


def _sync_platform_achievements_gog(username: str, user) -> Dict:
    """Stub for GOG achievement sync (not yet implemented)."""
    return {'status': 'not_configured', 'error': 'GOG integration not yet available', 'synced': [], 'errors': []}


def _sync_platform_achievements_xbox(username: str, user) -> Dict:
    """Stub for Xbox/Microsoft achievement sync (not yet implemented)."""
    return {'status': 'not_configured', 'error': 'Xbox integration not yet available', 'synced': [], 'errors': []}


_PLATFORM_SYNC_HANDLERS: Dict[str, Any] = {
    'steam': None,  # handled by existing api_sync_achievements
    'epic': _sync_platform_achievements_epic,
    'gog': _sync_platform_achievements_gog,
    'xbox': _sync_platform_achievements_xbox,
}


# MIGRATED to FastAPI: POST /api/achievements/sync/platform -> see
# backend/routers/achievements.py. The _PLATFORM_SYNC_HANDLERS stubs above
# are retained and reused by the FastAPI handler.


# ---------------------------------------------------------------------------
# Achievement statistics dashboard
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/achievements/stats -> see
# backend/routers/achievements.py.


# ---------------------------------------------------------------------------
# iCalendar export for the game-night schedule
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI (chunk 4a): GET /api/schedule/ical-sync-info -> see
# backend/routers/schedule.py (event_router).


def _ical_escape(text) -> str:
    """Escape a value for an RFC 5545 TEXT property.

    Per RFC 5545 §3.3.11, backslash, semicolon and comma must be escaped, and
    embedded newlines become the literal ``\\n`` sequence. Without this, a
    title/note containing any of these characters produces a malformed .ics
    that calendar clients reject or truncate.
    """
    s = str(text or '')
    s = s.replace('\\', '\\\\')
    s = s.replace(';', '\\;')
    s = s.replace(',', '\\,')
    s = s.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
    return s


# MIGRATED to FastAPI (chunk 4a): GET /api/schedule/export.ics -> see
# backend/routers/schedule.py (event_router). _ical_escape stays here.


# ---------------------------------------------------------------------------
# Multiplayer Achievement Challenges
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/challenges.py. The multiplayer
# /api/achievement-challenges routes (create, list, get, join, progress,
# cancel) are served natively by the FastAPI app (backend.main:app), reusing
# the same DB challenge helpers.


# ---------------------------------------------------------------------------
# Friend Activity API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/friends -> backend/routers/friends.py


# ---------------------------------------------------------------------------
# Recommendations API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/recommendations -> backend/routers/recommendations.py


# ---------------------------------------------------------------------------
# Leaderboards API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/leaderboards -> backend/routers/leaderboards.py


# ---------------------------------------------------------------------------
# User Profiles API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Notifications API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/notifications/mock -> backend/routers/notifications.py


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


# MIGRATED to FastAPI: POST /api/friends/add -> backend/routers/friends.py


# MIGRATED to FastAPI: DELETE /api/friends/<username> -> backend/routers/friends.py


# MIGRATED to FastAPI: DELETE /api/friends/follow/<username> -> backend/routers/friends.py


# ---------------------------------------------------------------------------
# Direct Messaging API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/messages.py. The /api/messages
# routes (conversations + per-user thread GET/POST) are served natively by
# the FastAPI app (backend.main:app), reusing the same DB-backed DM helpers.
# Removed from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Library Comparison API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/library.py. The
# /api/library/compare/{username} route is served natively by the FastAPI
# app (backend.main:app), reusing the same cached-library helpers. Removed
# from the Flask layer per the strangler-fig migration
# (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Session History API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/sessions.py. The
# /api/sessions/history route is served natively by the FastAPI app
# (backend.main:app). Removed from the Flask layer per the strangler-fig
# migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# User Profile API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/profile.py. The /api/profile/me
# and /api/profile/update routes are served natively by the FastAPI app
# (backend.main:app). Removed from the Flask layer per the strangler-fig
# migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# Seasonal Leaderboards API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/leaderboards/seasonal -> backend/routers/leaderboards.py


# ---------------------------------------------------------------------------
# Phase 6: Advanced Features APIs
# ---------------------------------------------------------------------------


# Tournaments & Brackets: MIGRATED to FastAPI -> backend/routers/tournaments.py


    titles = [
        {'id': '1', 'title': '👑 Legendary', 'owned': True, 'active': True},
        {'id': '2', 'title': '⭐ Star Player', 'owned': True, 'active': False},
        {'id': '3', 'title': '🎯 Sharpshooter', 'owned': False, 'active': False},
        {'id': '4', 'title': '🌟 Rising Star', 'owned': False, 'active': False},
    ]
    
    return jsonify({'themes': themes, 'titles': titles})


# MIGRATED to FastAPI: POST /api/cosmetics/apply-theme -> backend/routers/misc.py (cosmetics_router)


# ---------------------------------------------------------------------------
# Phase 6: Advanced Features APIs
# ---------------------------------------------------------------------------

# Shop & Marketplace
# MIGRATED to FastAPI: GET /api/shop, POST /api/shop/purchase
# -> backend/routers/misc.py (shop_router)


# Streaming Center
# [migrated] /api/streaming/vods, /api/streaming/start
# -> backend/routers/engagement.py (streaming_router)


# Trading System
# MIGRATED to FastAPI: /api/trades* -> backend/routers/trades.py


# AI Recommendations
# MIGRATED to FastAPI: GET /api/recommendations/ai -> backend/routers/recommendations.py


# Clans & Teams
# [migrated] /api/teams, /api/teams/create, /api/teams/<team_id>/join
# -> backend/routers/community.py (teams_router)


# Ranked System
# [migrated] /api/ranked -> backend/routers/engagement.py (ranked_router)


# Anti-Cheat Dashboard
# MIGRATED to FastAPI: GET /api/anticheat -> backend/routers/misc.py (anticheat_router)


# ==================== PHASE 7: Advanced Features ====================

# Battle Pass System
# [migrated] /api/battlepass/current, /api/battlepass/claim/<level>
# -> backend/routers/engagement.py (battlepass_router)


# Tournaments: MIGRATED to FastAPI -> backend/routers/tournaments.py
# (the dead duplicate GET /api/tournaments handler was dropped during migration)


# Content Creator Program
# [migrated] /api/creator/dashboard, /api/creator/apply
# -> backend/routers/engagement.py (creator_router)


# Referral System
# [migrated] /api/referral/code, /api/referral/use/<code>
# -> backend/routers/engagement.py (referral_router)


# Seasonal Events
# MIGRATED to FastAPI: GET /api/events/seasonal, POST /api/events/<event_id>/claim
# -> backend/routers/misc.py (events_router)


# Guild System
# [migrated] /api/guilds, /api/guilds/create, /api/guilds/<guild_id>/join
# -> backend/routers/community.py (guilds_router)


# Progression Paths
# [migrated] /api/progression -> backend/routers/engagement.py (progression_router)


# Trading Market
# [migrated] /api/market, /api/market/sell, /api/market/<listing_id>/offer
# -> backend/routers/community.py (market_router)


# Cosmetic Collections
# MIGRATED to FastAPI: GET /api/collections -> backend/routers/catalog.py (collections_router)


# ==================== PERFORMANCE & CACHING ====================

# Cache Management & Performance Monitoring
# [migrated] /api/system/cache/stats, /api/system/cache/clear, /api/system/indexes
# -> backend/routers/community.py (system_router)


# Optimized List Endpoints with Pagination

# MIGRATED to FastAPI: GET /api/optimized/users, /api/optimized/games,
# /api/optimized/leaderboard, /api/optimized/chat/messages,
# /api/optimized/games/search -> backend/routers/catalog.py (optimized_router)


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

# MIGRATED to FastAPI: see backend/routers/analytics.py. The /api/analytics
# dashboard + export routes are served natively by the FastAPI app
# (backend.main:app), reusing the same AnalyticsService. Removed from the
# Flask layer per the strangler-fig migration (docs/MODERNIZATION_BRIEF.md).


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
# MIGRATED to FastAPI: POST /api/batch/* -> backend/routers/batch.py


# HowLongToBeat API


# MIGRATED to FastAPI: GET /api/hltb/<path:game_name> -> backend/routers/catalog.py (hltb_router)


# ---------------------------------------------------------------------------
# Duplicate Detection API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/duplicates -> backend/routers/duplicates.py


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


# MIGRATED to FastAPI: GET /api/export/library -> see backend/routers/export.py


# MIGRATED to FastAPI: GET /api/export/favorites -> see backend/routers/export.py


# ---------------------------------------------------------------------------
# User data backup / restore
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/export/user-data -> see backend/routers/export.py


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


# ---------------------------------------------------------------------------
# In-app Friends API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/social_stats.py. The
# /api/app-friends (list), /api/app-friends/request (send),
# /api/app-friends/respond (accept/decline), and /api/app-friends/remove routes
# are served natively by the FastAPI app (backend.main:app), reusing the same
# DB-backed _friend_service singleton. Removed from the Flask layer per the
# strangler-fig migration (docs/MODERNIZATION_BRIEF.md).


# ---------------------------------------------------------------------------
# User presence API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: POST /api/presence -> backend/routers/presence.py
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

def _get_db_linked_session(session_id: str):
    """Fetch a persistent linked session if it exists."""
    if not DB_AVAILABLE or not ensure_db_available() or not session_id:
        return None
    db = None
    try:
        db = database.SessionLocal()
        session = database.get_linked_pick_session(db, session_id)
        if not session:
            return None
        return _attach_live_session_common_count(database.linked_pick_session_to_dict(db, session))
    except Exception as exc:
        gui_logger.warning('Failed to load linked session %s: %s', session_id, exc)
        return None
    finally:
        if db:
            db.close()


def _get_current_user_record():
    """Return the current DB user record, when available."""
    if not DB_AVAILABLE or not ensure_db_available():
        return None
    username = get_current_username()
    if not username:
        return None
    db = None
    try:
        db = database.SessionLocal()
        user = database.get_user_by_username(db, username)
        if not user:
            return None
        return {
            'username': user.username,
            'discord_id': str(getattr(user, 'discord_id', '') or '').strip(),
            'steam_id': str(getattr(user, 'steam_id', '') or '').strip(),
        }
    except Exception as exc:
        gui_logger.warning('Failed to load current user record: %s', exc)
        return None
    finally:
        if db:
            db.close()

def _live_session_view(session: Dict) -> Dict:
    """Return a JSON-serialisable view of a live session dict."""
    vote_state = session.get('vote_state') or {}
    votes_by_user = vote_state.get('votes_by_user') or {}
    view = {
        'session_id': session['session_id'],
        'name': session.get('name', session['session_id']),
        'host': session['host'],
        'participants': session['participants'],
        'status': session['status'],
        'created_at': session['created_at'].isoformat(),
        'picked_game': session.get('picked_game'),
        'round': int(session.get('round', 0)),
        'coop_only': bool(session.get('coop_only', False)),
        'rejected_game_ids': list(session.get('rejected_game_ids', [])),
        'vote_state': {
            'round': int(vote_state.get('round', 0)),
            'required_for_majority': int(vote_state.get('required_for_majority', 0)),
            'yes_count': sum(1 for v in votes_by_user.values() if bool(v)),
            'no_count': sum(1 for v in votes_by_user.values() if not bool(v)),
            'votes_by_user': votes_by_user,
            'result': vote_state.get('result', 'pending'),
        },
    }
    return _attach_live_session_common_count(view)


def _count_filtered_common_games_for_session(participants: List[str], coop_only: bool, rejected_game_ids: Optional[List[str]] = None) -> int:
    """Count current common games for session participants under active filters."""
    participants = [str(p).strip() for p in (participants or []) if str(p).strip()]
    if not participants:
        return 0
    _ensure_multi_picker()
    if not multi_picker:
        return 0
    try:
        with multi_picker_lock:
            common_games = multi_picker.find_common_games(user_names=participants)
            if coop_only:
                common_games = multi_picker.filter_coop_games(common_games, max_players=len(participants))
            if rejected_game_ids:
                common_games = multi_picker.filter_games(common_games, exclude_game_ids=rejected_game_ids)
    except Exception as exc:
        gui_logger.warning('Failed to count common games for session participants %s: %s', participants, exc)
        return 0
    unique_ids = {
        str(game.get('game_id') or game.get('app_id') or game.get('appid') or '').strip()
        for game in common_games
        if str(game.get('game_id') or game.get('app_id') or game.get('appid') or '').strip()
    }
    return len(unique_ids)


def _attach_live_session_common_count(session_view: Optional[Dict]) -> Dict:
    """Attach filtered common-game count metadata to a session view."""
    if not isinstance(session_view, dict):
        return {}
    participants = session_view.get('participants') or []
    coop_only = bool(session_view.get('coop_only', False))
    rejected_ids = session_view.get('rejected_game_ids') or []
    session_view['common_game_count'] = _count_filtered_common_games_for_session(
        participants,
        coop_only,
        rejected_ids,
    )
    return session_view


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

# MIGRATED to FastAPI: GET /api/leaderboard -> backend/routers/leaderboards.py


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

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

# MIGRATED to FastAPI: GET /api/notifications, POST /api/notifications/read,
# POST /api/notifications/send -> backend/routers/notifications.py


# ---------------------------------------------------------------------------
# Plugins / Addons API
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: /api/plugins (GET, POST, PUT, DELETE) -> backend/routers/extensibility.py


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


def _discord_bot_token_configured(config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """Return True when the Discord bot has enough configuration to start."""
    if os.getenv('DISCORD_BOT_TOKEN'):
        return True

    config_path = _resolve_repo_path(config_path)
    if not os.path.exists(config_path):
        return False

    try:
        with open(config_path, 'r') as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False

    return bool(str(cfg.get('discord_bot_token', '')).strip())


def _validate_repo_config_path(config_path: str) -> str:
    """Resolve and validate a config path under the repository root."""
    abs_config = os.path.normpath(_resolve_repo_path(config_path))
    try:
        if os.path.commonpath([BASE_DIR, abs_config]) != BASE_DIR:
            raise ValueError('Invalid config_path')
    except ValueError as exc:
        raise ValueError('Invalid config_path') from exc
    return abs_config


def _start_managed_discord_bot(config_path: str) -> Tuple[bool, Optional[subprocess.Popen], str]:
    """Start the managed Discord bot subprocess."""
    global _discord_bot_process, _discord_bot_log_lines

    abs_config = _validate_repo_config_path(config_path)

    with _discord_bot_lock:
        if _discord_bot_is_running():
            return False, _discord_bot_process, 'Discord bot is already running'

        bot_script = os.path.join(BASE_DIR, 'discord_bot.py')
        if not os.path.exists(bot_script):
            return False, None, 'discord_bot.py not found'

        try:
            proc = subprocess.Popen(
                [sys.executable, bot_script],
                env={**os.environ, 'GAPI_DISCORD_CONFIG': abs_config},
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _discord_bot_process = proc
            _discord_bot_log_lines.clear()
        except OSError as exc:
            gui_logger.warning('Failed to start managed Discord bot: %s', exc)
            return False, None, 'Failed to start bot'

    t = threading.Thread(target=_capture_bot_output, args=(proc,), daemon=True)
    t.start()
    return True, proc, ''


def _auto_start_discord_bot_if_configured(config_path: str = DEFAULT_CONFIG_PATH) -> None:
    """Start the Discord bot during app startup when configured."""
    if os.getenv('GAPI_DISABLE_DISCORD_AUTOSTART', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        gui_logger.info('Discord bot auto-start disabled by environment')
        return

    resolved_config = _resolve_repo_path(config_path)
    if not _discord_bot_token_configured(resolved_config):
        return

    started, proc, error = _start_managed_discord_bot(resolved_config)
    if started:
        gui_logger.info('Discord bot started automatically (pid=%s)', getattr(proc, 'pid', None))
    elif error != 'Discord bot is already running':
        gui_logger.warning('Discord bot auto-start skipped: %s', error)


def _get_discord_linked_users_from_db() -> List[Dict]:
    """Return Discord-linked users from the primary users table."""
    if not DB_AVAILABLE or not ensure_db_available():
        return []
    db = None
    try:
        db = database.SessionLocal()
        users = db.query(database.User).filter(database.User.discord_id.isnot(None)).all()
        results = []
        for user in users:
            discord_id = str(getattr(user, 'discord_id', '') or '').strip()
            if not discord_id:
                continue
            results.append({
                'discord_id': discord_id,
                'steam_id': str(getattr(user, 'steam_id', '') or '').strip(),
                'username': getattr(user, 'username', '') or '',
            })
        return results
    except Exception as exc:
        gui_logger.warning('Failed to load Discord-linked users from DB: %s', exc)
        return []
    finally:
        if db:
            db.close()


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
    data = request.get_json(silent=True) or {}
    try:
        config_path = _validate_repo_config_path(data.get('config_path', DEFAULT_CONFIG_PATH))
    except ValueError:
        return jsonify({'error': 'Invalid config_path'}), 400

    started, proc, error = _start_managed_discord_bot(config_path)
    if not started:
        if error == 'Discord bot is already running':
            return jsonify({'error': error}), 409
        return jsonify({'error': error}), 500
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
    """Return Discord bot statistics from database-backed linked users (admin only).

    Response JSON:
      - ``running``: bool
      - ``linked_users``: int – number of Discord-linked users stored in DB
      - ``config_exists``: bool – whether the shared database is available
    """
    linked_users = len(_get_discord_linked_users_from_db())
    config_exists = bool(DB_AVAILABLE and ensure_db_available())

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
    config_path = DEFAULT_CONFIG_PATH
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

    config_path = DEFAULT_CONFIG_PATH
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
    global _discord_bot_process
    data = request.get_json(silent=True) or {}
    try:
        config_path = _validate_repo_config_path(data.get('config_path', DEFAULT_CONFIG_PATH))
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

    started, proc, error = _start_managed_discord_bot(config_path)
    if not started:
        return jsonify({'error': error}), 500
    return jsonify({'restarted': True, 'pid': proc.pid})


@app.route('/api/admin/discord-bot/users', methods=['GET'])
@require_admin
def api_discord_bot_list_users():
    """List all Discord-linked users stored in the database (admin only).

    Response JSON:
      - ``users``: list of ``{discord_id, steam_id, username}`` objects
    """
    return jsonify({'users': _get_discord_linked_users_from_db()})


@app.route('/api/admin/discord-bot/users', methods=['POST'])
@require_admin
def api_discord_bot_add_user():
    """Add or update a Discord→Steam mapping (admin only).

    Request JSON:
      - ``discord_id``: str (required)
      - ``steam_id``: str (required)
      - ``username``: str (optional; defaults to ``discord_<discord_id>``)
    """
    data = request.get_json(silent=True) or {}
    discord_id = str(data.get('discord_id', '')).strip()
    steam_id = str(data.get('steam_id', '')).strip()
    username = str(data.get('username', '')).strip()

    if not discord_id or not steam_id:
        return jsonify({'error': 'discord_id and steam_id are required'}), 400
    if not discord_id.isdigit():
        return jsonify({'error': 'discord_id must be numeric'}), 400
    if not steam_id.isdigit():
        return jsonify({'error': 'steam_id must be numeric'}), 400

    if not DB_AVAILABLE or not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503

    db = None
    try:
        db = database.SessionLocal()
        user = db.query(database.User).filter(database.User.steam_id == steam_id).first()
        if not user and username:
            user = database.get_user_by_username(db, username)
        if not user:
            return jsonify({'error': 'User with matching Steam ID or username not found'}), 404
        user.discord_id = discord_id
        if not getattr(user, 'steam_id', None):
            user.steam_id = steam_id
        db.commit()
    except Exception as exc:
        if db:
            db.rollback()
        gui_logger.warning('Failed to save Discord mapping: %s', exc)
        return jsonify({'error': 'Failed to save Discord mapping'}), 500
    finally:
        if db:
            db.close()

    return jsonify({'saved': True, 'discord_id': discord_id, 'steam_id': steam_id})


@app.route('/api/admin/discord-bot/users/<discord_id>', methods=['DELETE'])
@require_admin
def api_discord_bot_remove_user(discord_id: str):
    """Remove a Discord→Steam mapping from the database (admin only).

    Path parameter:
      - ``discord_id``: the Discord user ID string to remove

    Returns ``{'removed': True}`` on success or ``{'error': ...}`` if not found.
    """
    if not DB_AVAILABLE or not ensure_db_available():
        return jsonify({'error': 'Database not available'}), 503
    db = None
    try:
        db = database.SessionLocal()
        user = database.get_user_by_discord_id(db, discord_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        user.discord_id = None
        db.commit()
        return jsonify({'removed': True})
    except Exception as exc:
        if db:
            db.rollback()
        gui_logger.warning('Failed to remove Discord mapping: %s', exc)
        return jsonify({'error': 'Failed to remove user'}), 500
    finally:
        if db:
            db.close()


@app.route('/api/admin/discord-bot/diagnostics', methods=['GET'])
@require_admin
def api_discord_bot_diagnostics():
    """Get Discord bot diagnostics and environment info (admin only).

    Response JSON:
      - ``steam_api_key_source``: 'env'|'config'|'missing' – where the key comes from
      - ``steam_api_key_set``: bool – whether key is configured
      - ``discord_token_set``: bool – whether Discord token is configured  
      - ``config_file_exists``: bool – whether config.json exists
      - ``discord_config_exists``: bool – whether Discord user-link storage in DB is available
      - ``bot_invite_url``: str – Discord bot invite URL with permissions
      - ``python_version``: str – Python version running the bot
    """
    import sys
    config_path = 'config.json'
    
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
        'discord_config_exists': bool(DB_AVAILABLE and ensure_db_available()),
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


# MIGRATED to FastAPI: GET /api/i18n, GET /api/i18n/<lang> (both UNAUTHENTICATED)
# -> backend/routers/misc.py (i18n_router)


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


# MIGRATED to FastAPI: GET /api/twitch/trending, GET /api/twitch/library-overlap
# -> backend/routers/misc.py (twitch_router)


# ---------------------------------------------------------------------------
# Platform OAuth — Epic Games, GOG Galaxy, Xbox Game Pass
# ---------------------------------------------------------------------------

def _get_platform_client(platform: str):
    """Return the platform client for *platform*, or None."""
    username = get_current_username()
    p = ensure_picker_initialized(username) if username else picker
    return p.clients.get(platform) if p else None


# MIGRATED to FastAPI: /api/epic/*, /api/gog/*, /api/xbox/* ->
#   backend/routers/platforms.py (epic_router / gog_router / xbox_router)


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

# MIGRATED to FastAPI: /api/psn/* -> backend/routers/platforms.py (psn_router)


# ---------------------------------------------------------------------------
# Nintendo eShop
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: /api/nintendo/* -> backend/routers/platforms.py (nintendo_router)

# ---------------------------------------------------------------------------
# Smart Recommendations
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/recommendations/smart -> backend/routers/recommendations.py


# ---------------------------------------------------------------------------
# Machine Learning Recommendations
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/recommendations/ml -> backend/routers/recommendations.py


# ---------------------------------------------------------------------------
# Webhook Notifications — Slack, Teams, IFTTT, Home Assistant
# ---------------------------------------------------------------------------

def _get_webhook_notifier() -> 'WebhookNotifier':  # type: ignore[name-defined]
    """Return a WebhookNotifier initialised with the current picker config."""
    from webhook_notifier import WebhookNotifier
    cfg = (picker.config if picker else {}) or {}
    return WebhookNotifier(cfg)


# MIGRATED to FastAPI: POST /api/notifications/{slack,teams,ifttt,homeassistant}/test
# -> backend/routers/notifications.py


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

# MIGRATED to FastAPI: GET /api/permissions -> backend/routers/permissions.py


# MIGRATED to FastAPI: GET /api/users/<username>/permissions -> backend/routers/permissions.py


# MIGRATED to FastAPI: POST /api/admin/users/<username>/permissions -> backend/routers/permissions.py


# MIGRATED to FastAPI: POST /api/admin/roles/bulk-assign -> backend/routers/permissions.py


# ---------------------------------------------------------------------------
# Notification Preferences  (Tier 2, item 6)
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: see backend/routers/notifications.py. The
# /api/notifications/preferences (GET/PUT) and /api/notifications/history (GET)
# routes are served natively by the FastAPI app. The admin broadcast/send
# /api/notifications/* routes remain in Flask.


# MIGRATED to FastAPI: POST /api/admin/notifications/broadcast -> backend/routers/admin_notifications.py


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
# Email notification management  (Tier 2, item 6 — email notifications)
# ---------------------------------------------------------------------------

@app.route('/api/admin/email/status', methods=['GET'])
@require_admin
def api_admin_email_status():
    """Return the current email service configuration status (admin only).

    Response JSON:
      ``configured``  – ``true`` if ``SMTP_HOST`` is set
      ``sender``      – configured sender address (empty when unconfigured)
      ``host``        – SMTP host (empty when unconfigured)
      ``port``        – SMTP port (0 when unconfigured)
      ``use_tls``     – whether STARTTLS is enabled
      ``use_ssl``     – whether SMTPS is enabled
    """
    if _email_service is None:
        return jsonify({'configured': False, 'error': 'EmailService not loaded'})
    return jsonify(_email_service.config_info())


@app.route('/api/admin/email/test', methods=['POST'])
@require_admin
def api_admin_email_test():
    """Send a test email to verify SMTP configuration (admin only).

    Request JSON:
      ``to``  – recipient email address (required)

    Response JSON:
      ``success``   – ``true`` when the test email was delivered
      ``to``        – address the email was sent to
      ``message``   – human-readable status message
    """
    if _email_service is None:
        return jsonify({'success': False, 'message': 'EmailService not loaded'}), 503
    if not _email_service.is_configured():
        return jsonify({
            'success': False,
            'message': 'SMTP is not configured. Set SMTP_HOST in your environment.',
        }), 503
    data = request.get_json(silent=True, force=True) or {}
    to_address = str(data.get('to', '')).strip()
    if not _is_valid_email_address(to_address):
        return jsonify({'success': False, 'message': 'Invalid or missing "to" address'}), 400
    ok = _email_service.send_test_email(to_address)
    return jsonify({
        'success': ok,
        'to': to_address,
        'message': 'Test email sent successfully.' if ok else 'Failed to send test email.',
    })


# MIGRATED to FastAPI: POST /api/admin/notifications/send-digests -> backend/routers/admin_notifications.py


# MIGRATED to FastAPI: PUT /api/users/<username>/email -> backend/routers/users.py


# MIGRATED to FastAPI: GET /api/users/<username>/email -> backend/routers/users.py


# ---------------------------------------------------------------------------
# Web Push Notifications  (Phase 11)
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: /api/push/vapid-public-key, /api/push/subscribe,
# /api/push/unsubscribe, /api/push/subscriptions -> backend/routers/extensibility.py


@app.route('/api/admin/push/broadcast', methods=['POST'])
@require_admin
def api_admin_push_broadcast():
    """Send a push notification to all opted-in subscribers (admin only).

    Request JSON:
      ``title``     – notification title (required).
      ``body``      – notification body text (required).
      ``url``       – URL to open when the notification is clicked
                      (default ``'/'``).
      ``dry_run``   – when ``true`` count subscriptions but do not send
                      (default ``false``).

    Response JSON:
      ``total``     – subscriptions considered.
      ``sent``      – successfully delivered.
      ``failed``    – delivery failures.
      ``skipped``   – subscriptions skipped (dry_run).
      ``dry_run``   – whether dry_run was active.
    """
    if not DB_AVAILABLE:
        return jsonify({'error': 'Database not available'}), 503
    data = request.get_json(silent=True, force=True) or {}
    title = str(data.get('title', '')).strip()
    body = str(data.get('body', '')).strip()
    url = str(data.get('url', '/')).strip() or '/'
    dry_run = str(data.get('dry_run', 'false')).lower() in ('true', '1', 'yes')
    if not title or not body:
        return jsonify({'error': "'title' and 'body' are required"}), 400
    if not _push_service:
        return jsonify({'error': 'Push notification service not available'}), 503
    try:
        db = next(database.get_db())
        result = _push_service.broadcast(
            db, title, body, url=url, db_module=database, dry_run=dry_run
        )
    except Exception as e:
        gui_logger.error('api_admin_push_broadcast error: %s', e)
        return jsonify({'error': 'Internal server error'}), 500
    return jsonify(result)


# ---------------------------------------------------------------------------
# Similar Games endpoint  (Item 8)
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/games/<app_id>/similar -> backend/routers/catalog.py (games_router)


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


# MIGRATED to FastAPI: GET /api/recommendations/variant -> backend/routers/recommendations.py


# ---------------------------------------------------------------------------
# User Suspension / Account Status  (Item 5 — Advanced User Management)
# ---------------------------------------------------------------------------

# MIGRATED to FastAPI: GET /api/admin/users/search -> backend/routers/users.py


# MIGRATED to FastAPI: POST /api/admin/users/<username>/suspend -> backend/routers/users.py


# MIGRATED to FastAPI: DELETE /api/admin/users/<username>/suspend -> backend/routers/users.py


# MIGRATED to FastAPI: GET /api/admin/users/<username>/status -> backend/routers/users.py


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

# MIGRATED to FastAPI: GET /api/users/<username>/reputation -> backend/routers/users.py


# MIGRATED to FastAPI: GET /api/admin/users/low-reputation -> backend/routers/users.py


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
    parser.add_argument('--config', default=DEFAULT_CONFIG_PATH, help='Path to config file')
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
    config_path = _resolve_repo_path(args.config)
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

    _auto_start_discord_bot_if_configured(config_path)
    
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
