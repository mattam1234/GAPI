#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
import argparse
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
        cache_age = database.get_library_cache_age(db, username)
        
        # Don't sync if cache is less than 1 hour old (unless forced)
        if not force and cache_age is not None and cache_age < 3600:
            db.close()
            gui_logger.debug(f"Library cache for {username} is fresh ({cache_age:.0f}s old), skipping sync")
            return True, f"Cache is fresh ({int(cache_age/60)}m old)"
        
        # Fetch library from Steam API
        base_config = load_base_config()
        steam_api_key = base_config.get('steam_api_key', '')
        
        if not steam_api_key or gapi.is_placeholder_value(steam_api_key):
            db.close()
            return False, "Steam API key not configured"
        
        gui_logger.info(f"Syncing library for {username} from Steam API...")
        steam_client = gapi.SteamAPIClient(steam_api_key)
        games = steam_client.get_owned_games(steam_id)
        
        if not games:
            db.close()
            return False, "Failed to fetch games from Steam API"
        
        # Cache the games in database
        count = database.cache_user_library(db, username, games)
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
        count = database.get_user_count(db)
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
        count = database.get_user_count(db)
        if count > 0:
            db.close()
            return jsonify({'error': 'Users already exist'}), 409

        password_hash = user_manager.hash_password(password)
        user = database.create_or_update_user(db, username, password_hash, '', '', '', role='admin', roles=['admin'])
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
            db_user = database.get_user_by_username(db, username)
            if db_user:
                # override with DB values when present
                if getattr(db_user, 'steam_id', None):
                    user_ids['steam_id'] = db_user.steam_id
                if getattr(db_user, 'epic_id', None):
                    user_ids['epic_id'] = db_user.epic_id
                if getattr(db_user, 'gog_id', None):
                    user_ids['gog_id'] = db_user.gog_id
            db.close()
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
            db_user = database.get_user_by_username(db, username)
            if db_user:
                if getattr(db_user, 'steam_id', None):
                    user_ids['steam_id'] = db_user.steam_id
                if getattr(db_user, 'epic_id', None):
                    user_ids['epic_id'] = db_user.epic_id
                if getattr(db_user, 'gog_id', None):
                    user_ids['gog_id'] = db_user.gog_id
            db.close()
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
        
        if DB_AVAILABLE:
            db = None
            try:
                db = database.SessionLocal()
                ignored_games = database.get_ignored_games(db, username)
                if ignored_games:
                    if exclude_game_ids:
                        exclude_game_ids.extend(ignored_games)
                    else:
                        exclude_game_ids = ignored_games
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
                    filtered_games = picker.filter_by_tag(tag_filter, filtered_games)

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
                is_favorite = app_id in picker.favorites if app_id else False
                review = picker.get_review(game_id) if game_id else None
                tags = picker.get_tags(game_id) if game_id else []
                backlog_status = picker.get_backlog_status(game_id) if game_id else None

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
            database.update_game_details_cache(db, app_id, platform, response)
            return jsonify(response)
        
        # Step 4: No API data available. Return last cached data even if stale, or minimal response
        try:
            last_cache = db.query(database.GameDetailsCache).filter(
                database.GameDetailsCache.app_id == str(app_id),
                database.GameDetailsCache.platform == platform
            ).first()
            
            if last_cache:
                import json
                return jsonify({
                    **json.loads(last_cache.details_json),
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
        
        if request.method == 'POST':
            success = database.add_favorite(db, username, str(app_id))
            db.close()
            if success:
                return jsonify({'success': True, 'action': 'added'})
            else:
                return jsonify({'error': 'Failed to add favorite'}), 500
        else:
            success = database.remove_favorite(db, username, str(app_id))
            db.close()
            if success:
                return jsonify({'success': True, 'action': 'removed'})
            else:
                return jsonify({'error': 'Failed to remove favorite'}), 500
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
        
        # Get cached library
        cached_games = database.get_cached_library(db, username)
        
        # If cache is empty or old, trigger background sync
        if not cached_games:
            db.close()
            # Trigger sync in background
            def background_sync():
                success, msg = sync_library_to_db(username, force=True)
                gui_logger.info(f"Background library sync for {username}: {msg}")
            
            threading.Thread(target=background_sync, daemon=True).start()
            
            # Return empty library with message to refresh
            return jsonify({
                'games': [],
                'message': 'Library is being loaded from Steam. Please refresh in a few seconds.'
            })
        
        # Check if cache is old (>6 hours) and trigger background refresh
        cache_age = database.get_library_cache_age(db, username)
        if cache_age and cache_age > 21600:  # 6 hours
            # Trigger background refresh but return cached data
            def background_sync():
                success, msg = sync_library_to_db(username, force=False)
                gui_logger.info(f"Background library refresh for {username}: {msg}")
            
            threading.Thread(target=background_sync, daemon=True).start()
        
        search = request.args.get('search', '').lower()
        
        # Get user's favorites from database
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
        cache_age = database.get_library_cache_age(db, username)
        cached_games = database.get_cached_library(db, username)
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
        favorite_ids = database.get_user_favorites(db, username)
        
        # Get cached library to look up game details
        cached_games = database.get_cached_library(db, username)
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
        cached_games = database.get_cached_library(db, username)
        favorite_count = len(database.get_user_favorites(db, username))
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
    
    # Convert app_id to int
    try:
        app_id = int(app_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'app_id must be an integer'}), 400
    
    try:
        db = database.SessionLocal()
        
        # Verify user exists in database
        user = database.get_user_by_username(db, username)
        if not user:
            db.close()
            return jsonify({'error': 'User not found in database'}), 404
        
        success = database.toggle_ignore_game(db, username, app_id, game_name, reason)
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
        user = database.get_user_by_username(db, username)
        
        if not user:
            return jsonify({'achievements': []}), 200
        
        # Group achievements by game
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
        
        db.close()
        return jsonify({'achievements': list(achievements_by_game.values())}), 200
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
        user = database.get_user_by_username(db, username)
        
        if not user:
            db.close()
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
        
        db.close()
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
        hunt = db.query(database.AchievementHunt).filter(database.AchievementHunt.id == hunt_id).first()
        
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
        
        db.close()
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
        roles = database.get_roles(db)
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
        return jsonify(picker.reviews)


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
        review = picker.get_review(game_id)
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
        success = picker.add_or_update_review(game_id, rating, notes)

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
        removed = picker.remove_review(game_id)

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
            return jsonify({'tags': picker.all_tags(), 'game_tags': picker.tags})
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
            return jsonify({'game_id': game_id, 'tags': picker.get_tags(game_id)})
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
            added = picker.add_tag(game_id, tag)
            tags = picker.get_tags(game_id)

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
            removed = picker.remove_tag(game_id, tag)
            tags = picker.get_tags(game_id)

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
        games = picker.filter_by_tag(tag)
        result = [
            {
                'app_id': g.get('appid'),
                'game_id': g.get('game_id'),
                'name': g.get('name', 'Unknown'),
                'playtime_hours': round(g.get('playtime_forever', 0) / 60, 1),
                'tags': picker.get_tags(g.get('game_id', str(g.get('appid', '')))),
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
        events = picker.get_events()
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
        event = picker.add_event(title, date, time_str, attendees, game_name, notes)
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
        event = picker.update_event(event_id, **safe)
    if event is None:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify(event)


@app.route('/api/schedule/<event_id>', methods=['DELETE'])
def api_delete_event(event_id: str):
    """Delete a game night event."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.remove_event(event_id)
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
        return jsonify({'playlists': picker.list_playlists()})


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
        created = picker.create_playlist(name)
    if not created:
        return jsonify({'error': 'Playlist already exists'}), 409
    return jsonify({'success': True, 'name': name}), 201


@app.route('/api/playlists/<name>', methods=['DELETE'])
def api_delete_playlist(name: str):
    """Delete a playlist by name."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        deleted = picker.delete_playlist(name)
    if not deleted:
        return jsonify({'error': 'Playlist not found'}), 404
    return jsonify({'success': True})


@app.route('/api/playlists/<name>/games', methods=['GET'])
def api_get_playlist_games(name: str):
    """Get all games in a playlist."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        games = picker.get_playlist_games(name)
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
        added = picker.add_to_playlist(name, game_id)
    if not added:
        return jsonify({'error': 'Game already in playlist or invalid playlist'}), 409
    return jsonify({'success': True})


@app.route('/api/playlists/<name>/games/<game_id>', methods=['DELETE'])
def api_remove_from_playlist(name: str, game_id: str):
    """Remove a game from a playlist."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.remove_from_playlist(name, game_id)
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
        games = picker.get_backlog_games(status_filter)
    return jsonify({'games': games, 'count': len(games)})


@app.route('/api/backlog/<game_id>', methods=['GET'])
def api_get_backlog_status(game_id: str):
    """Get the backlog status for a specific game."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        status = picker.get_backlog_status(game_id)
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
        ok = picker.set_backlog_status(game_id, status)
    if not ok:
        return jsonify({'error': f'Invalid status. Valid: {list(gapi.GamePicker.BACKLOG_STATUSES)}'}), 400
    return jsonify({'success': True, 'game_id': game_id, 'status': status})


@app.route('/api/backlog/<game_id>', methods=['DELETE'])
def api_delete_backlog_status(game_id: str):
    """Remove a game from the backlog."""
    if not picker:
        return jsonify({'error': 'Not initialized'}), 400
    with picker_lock:
        removed = picker.remove_backlog_status(game_id)
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
            review = picker.get_review(game_id) or {}
            rows.append({
                'app_id': app_id,
                'name': game.get('name', ''),
                'platform': game.get('platform', 'steam'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
                'is_favorite': 'yes' if game_id in picker.favorites else 'no',
                'backlog_status': picker.get_backlog_status(game_id) or '',
                'tags': ','.join(picker.get_tags(game_id)),
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
            if game_id not in picker.favorites:
                continue
            review = picker.get_review(game_id) or {}
            rows.append({
                'app_id': app_id,
                'name': game.get('name', ''),
                'platform': game.get('platform', 'steam'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1),
                'tags': ','.join(picker.get_tags(game_id)),
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
                <div id="user-checkboxes" style="margin-top: 15px;">
                    <div class="loading">Loading users...</div>
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
                document.getElementById('common-games-list').innerHTML = '<div class="loading">Select users and click "Show Common Games"</div>';
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
