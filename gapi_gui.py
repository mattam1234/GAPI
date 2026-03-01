#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
import argparse
import uuid
from flask import Flask, render_template, jsonify, request, session, Response
import threading
import json
import os
import sys
import csv
import hashlib
import io
import tempfile
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from functools import wraps
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
app.secret_key = os.urandom(24)

# Use the shared GAPI logger so level is controlled by config/setup_logging()
gui_logger = logging.getLogger('gapi.gui')

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

# User authentication
current_user: Optional[str] = None
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
            return False, "Database not available"
            
        try:
            db = database.SessionLocal()
            password_hash = self.hash_password(password)
            is_valid = database.verify_user_password(db, username, password_hash)
            db.close()
            
            if is_valid:
                return True, "Login successful"
            else:
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
            
        try:
            db = database.SessionLocal()
            roles = database.get_user_roles(db, username)
            db.close()
            
            if 'admin' in roles:
                return 'admin'
            if roles:
                return roles[0]
            return 'user'
            
        except Exception as e:
            gui_logger.exception('Error getting user role: %s', e)
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


def require_login(f):
    """Decorator to require user to be logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        global current_user
        with current_user_lock:
            if not current_user:
                return jsonify({'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_admin(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        global current_user
        with current_user_lock:
            if not current_user:
                return jsonify({'error': 'Not logged in'}), 401
            if not user_manager.is_admin(current_user):
                return jsonify({'error': 'Admin privileges required'}), 403
        return f(*args, **kwargs)
    return decorated_function


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


@app.route('/api/status')
def api_status():
    """Get application status"""
    global picker, current_user
    
    # Check if user is logged in
    with current_user_lock:
        if not current_user:
            return jsonify({
                'ready': False,
                'logged_in': False,
                'message': 'Please log in'
            })
    
    if picker is None:
        return jsonify({
            'ready': False,
            'logged_in': True,
            'message': 'Loading games...'
        })
    
    return jsonify({
        'ready': True,
        'logged_in': True,
        'current_user': current_user,
        'is_admin': user_manager.is_admin(current_user),
        'total_games': len(picker.games) if picker.games else 0,
        'favorites': len(picker.favorites) if picker.favorites else 0
    })


# ===========================================================================================
# Authentication Endpoints
# ===========================================================================================

@app.route('/api/auth/current', methods=['GET'])
def api_auth_current():
    """Get current logged-in user"""
    with current_user_lock:
        if current_user:
            return jsonify({
                'username': current_user,
                'role': user_manager.get_user_role(current_user)
            })
    return jsonify({'username': None}), 401


@app.route('/api/auth/register', methods=['POST'])
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
def api_auth_login():
    """Log in a user"""
    global current_user, picker, multi_picker
    
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    gui_logger.info('Login endpoint called for username=%s', username)
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, message = user_manager.login(username, password)
    
    if not success:
        return jsonify({'error': message}), 401
    
    # Set current user
    with current_user_lock:
        current_user = username
    gui_logger.info('User logged in: %s', username)
    
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
    global current_user, picker, multi_picker

    with current_user_lock:
        gui_logger.info('User logged out: %s', current_user)
        current_user = None

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
    
    with current_user_lock:
        if not current_user:
            return jsonify({'error': 'Not logged in'}), 401
        username = current_user
    
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
    
    with current_user_lock:
        if not current_user:
            return jsonify({'error': 'Not logged in'}), 401
        username = current_user
    
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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user
    
    try:
        gui_logger.info(f"Pick request from user {username}")
        
        # Ensure picker is initialized for logged-in user
        # Create a minimal picker without config validation (we're just picking from cached games)
        if not picker:
            with picker_lock:
                # Create picker with minimal config to avoid requiring Steam API credentials
                picker = gapi.GamePicker.__new__(gapi.GamePicker)
                picker._log = logging.getLogger('gapi.picker')
                picker.config = {}
                picker.MAX_HISTORY = gapi.GamePicker.DEFAULT_MAX_HISTORY
                picker.BARELY_PLAYED_THRESHOLD_MINUTES = gapi.GamePicker.DEFAULT_BARELY_PLAYED_HOURS * 60
                picker.WELL_PLAYED_THRESHOLD_MINUTES = gapi.GamePicker.DEFAULT_WELL_PLAYED_HOURS * 60
                picker.API_TIMEOUT = gapi.GamePicker.DEFAULT_API_TIMEOUT
                picker.clients = {}
                picker.steam_client = None
                picker.games = []
                picker.history = []
                picker.favorites = []
                picker.reviews = {}
                picker.tags = {}
                picker.schedule = {}
                picker.playlists = {}
                picker.backlog = {}
                
                # Initialize steam_client for fetching game details
                try:
                    base_config = load_base_config()
                    api_key = base_config.get('steam_api_key', '').strip()
                    if api_key and not gapi.is_placeholder_value(api_key):
                        picker.steam_client = gapi.SteamAPIClient(api_key)
                        gui_logger.debug("Initialized SteamAPIClient for game details")
                    else:
                        gui_logger.warning("No valid Steam API key configured, game details may be limited")
                except Exception as e:
                    gui_logger.warning(f"Failed to initialize SteamAPIClient: {e}")
                
                gui_logger.debug("Initialized minimal picker for game selection")
        
        # Load user's games from database cache if available
        if not picker.games or len(picker.games) == 0:
            if DB_AVAILABLE and ensure_db_available():
                db = None
                try:
                    db = database.SessionLocal()
                    if _library_service:
                        cached_games = _library_service.get_cached(db, username)
                    else:
                        cached_games = database.get_cached_library(db, username)

                    if cached_games:
                        # Convert database format to picker format
                        picker.games = [
                            {
                                'appid': int(g['app_id']) if str(g['app_id']).isdigit() else g['app_id'],
                                'name': g['name'],
                                'playtime_forever': int(g.get('playtime_hours', 0) * 60),  # Convert hours to minutes
                                'platform': g.get('platform', 'steam')
                            }
                            for g in cached_games
                        ]
                        gui_logger.info(f"Loaded {len(picker.games)} games for {username} from database cache")
                    else:
                        picker.games = DEMO_GAMES
                        gui_logger.warning(f"No cached games for {username}, using demo games")
                except Exception as e:
                    gui_logger.exception(f"Failed to load games from database for {username}: {e}")
                    picker.games = DEMO_GAMES
                finally:
                    if db:
                        try:
                            db.close()
                        except Exception:
                            pass
            else:
                picker.games = DEMO_GAMES
                gui_logger.warning(f"Database not available for {username}, using demo games")
        
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

        with current_user_lock:
            username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user
    
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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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

    with current_user_lock:
        username = current_user

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

    with current_user_lock:
        username = current_user

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

    with current_user_lock:
        username = current_user

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

    with current_user_lock:
        username = current_user

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

    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        requesting_user = current_user
    
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
    with current_user_lock:
        requesting_user = current_user
    
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
    with current_user_lock:
        requesting_user = current_user

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

    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES
    with picker_lock:
        return jsonify(picker.review_service.get_all())


@app.route('/api/reviews/<game_id>', methods=['GET'])
@require_login
def api_get_review(game_id: str):
    """Return the review for a specific game."""
    global picker

    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES
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

    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES

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

    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES

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
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES
        if not picker.games:
            picker.games = DEMO_GAMES

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
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES
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
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES

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
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES

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
    if not picker or not picker.games:
        # Initialize with demo games if not loaded
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES
        if not picker.games:
            picker.games = DEMO_GAMES

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
    game_id = (data.get('game_id') or '').strip()
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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user
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

    with picker_lock:
        recs = picker.get_recommendations(count=count)

    return jsonify({'recommendations': recs})


# ---------------------------------------------------------------------------
# HowLongToBeat API
# ---------------------------------------------------------------------------

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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user

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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        sender = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    return {
        'session_id': session['session_id'],
        'name': session.get('name', session['session_id']),
        'host': session['host'],
        'participants': session['participants'],
        'status': session['status'],
        'created_at': session['created_at'].isoformat(),
        'picked_game': session.get('picked_game'),
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        if session['host'] != username:
            return jsonify({'error': 'Only the session host can start a pick'}), 403
        if session['status'] == 'completed':
            return jsonify({'error': 'Session has already completed'}), 400
        participants = list(session['participants'])
        session['status'] = 'picking'

    data = request.get_json() or {}
    coop_only = bool(data.get('coop_only', False))

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        game = multi_picker.pick_common_game(
            user_names=participants,
            coop_only=coop_only,
            max_players=len(participants),
        )

    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if session:
            if game:
                session['picked_game'] = game
            session['status'] = 'completed'

    if not game:
        return jsonify({'error': 'No common game found for all participants'}), 404

    # Notify all participants that a game was picked (best-effort)
    if DB_AVAILABLE:
        game_name = game.get('name', 'a game')
        for participant in participants:
            db = next(database.get_db())
            try:
                database.create_notification(
                    db,
                    participant,
                    title='Game picked!',
                    message=f'{username} picked "{game_name}" for your live session.',
                    type='success',
                )
            except Exception as exc:
                gui_logger.warning('Failed to notify %s after pick: %s', participant, exc)
            finally:
                if db:
                    db.close()

    # Publish completed session state to SSE subscribers
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if session:
            _sse_publish(session_id, 'session', _live_session_view(session))

    return jsonify(game)
@require_login
def api_live_session_get(session_id: str):
    """Return the current state of a specific live pick session."""
    with live_sessions_lock:
        session = live_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
    return jsonify(_live_session_view(session))


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
    with current_user_lock:
        username = current_user
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
      - ``room``:     room name (default 'general')
      - ``since_id``: return only messages with id > this value (default 0)
      - ``limit``:    max messages to return (default 50)
    """
    room = request.args.get('room', 'general')
    try:
        since_id = int(request.args.get('since_id', 0))
        limit = int(request.args.get('limit', 50))
    except ValueError:
        since_id, limit = 0, 50
    db = next(database.get_db())
    try:
        if _chat_service:
            messages = _chat_service.get_messages(db, room=room, limit=limit,
                                                  since_id=since_id)
        else:
            messages = database.get_chat_messages(db, room=room, limit=limit,
                                                  since_id=since_id)
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
    with current_user_lock:
        username = current_user
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    room = data.get('room', 'general').strip() or 'general'
    if not message:
        return jsonify({'error': 'message is required'}), 400
    if len(message) > 500:
        return jsonify({'error': 'message must be 500 characters or fewer'}), 400
    db = next(database.get_db())
    try:
        if _chat_service:
            msg = _chat_service.send(db, sender_username=username,
                                     message=message, room=room)
        else:
            msg = database.send_chat_message(db, sender_username=username,
                                             message=message, room=room)
    finally:
        if db:
            db.close()
    if not msg:
        return jsonify({'error': 'Failed to send message'}), 500
    return jsonify(msg), 201


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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        sender = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
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
    with current_user_lock:
        username = current_user
    db_check = next(database.get_db())
    try:
        if _app_settings_service:
            is_admin = _app_settings_service.is_admin(db_check, username)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username)
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
    with current_user_lock:
        username = current_user
    db_check = next(database.get_db())
    try:
        if _app_settings_service:
            is_admin = _app_settings_service.is_admin(db_check, username)
        else:
            is_admin = 'admin' in database.get_user_roles(db_check, username)
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
            ok = _app_settings_service.save(db, updates, updated_by=username)
        else:
            ok = database.set_app_settings(db, updates, updated_by=username)
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
    with current_user_lock:
        username = current_user

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
            </div>
            
            <button class="pick-button" onclick="pickGame()">🎲 Pick Random Game</button>
            
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
            
            try {
                const response = await fetch('/api/pick', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        filter: filterValue,
                        genre: genreValue
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
    args = parser.parse_args()

    demo_mode = args.demo
    config_path = args.config

    if demo_mode:
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
        with current_user_lock:
            global current_user
            current_user = 'demo'

    # Create templates
    create_templates()
    
    # Start background sync scheduler
    sync_scheduler.start()
    
    # Run Flask app
    print("\n" + "="*60)
    print("🎮 GAPI Web GUI is starting...")
    print("="*60)
    print("\nOpen your browser and go to:")
    print("  http://127.0.0.1:5000")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")
    
    try:
        app.run(host='127.0.0.1', port=5000, debug=False)
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
