#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
import argparse
from flask import Flask, render_template, jsonify, request, session
import threading
import json
import os
import sys
import hashlib
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from functools import wraps
import gapi
import multiuser

try:
    import database
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

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
USERS_AUTH_FILE = 'users_auth.json'
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


class UserManager:
    """Manages user authentication and platform IDs"""
    
    def __init__(self, users_file: str = USERS_AUTH_FILE):
        self.users_file = users_file
        self.users: Dict = {}
        self.load_users()
    
    def load_users(self):
        """Load users from file"""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r') as f:
                    data = json.load(f)
                    self.users = data.get('users', {})
                # Backfill roles for existing users
                updated = False
                has_admin = any(u.get('role') == 'admin' for u in self.users.values())
                for username, user_data in self.users.items():
                    if 'role' not in user_data:
                        # If no admin exists, make first user admin
                        user_data['role'] = 'admin' if not has_admin else 'user'
                        has_admin = True
                        updated = True
                if updated:
                    self.save_users()
            except (json.JSONDecodeError, IOError) as e:
                gui_logger.error("Error loading users: %s", e)
                self.users = {}
    
    def save_users(self):
        """Save users to file"""
        try:
            gapi._atomic_write_json(self.users_file, {'users': self.users})
        except Exception as e:
            gui_logger.error("Error saving users: %s", e)
    
    def hash_password(self, password: str) -> str:
        """Hash a password"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register(self, username: str, password: str, role: str = None) -> Tuple[bool, str]:
        """Register a new user"""
        if username in self.users:
            return False, "Username already exists"
        if len(username) < 3:
            return False, "Username must be at least 3 characters"
        if len(password) < 6:
            return False, "Password must be at least 6 characters"
        
        # First user becomes admin, rest are regular users
        if role is None:
            role = 'admin' if len(self.users) == 0 else 'user'
        
        self.users[username] = {
            'password': self.hash_password(password),
            'steam_id': '',
            'epic_id': '',
            'gog_id': '',
            'role': role
        }
        self.save_users()
        return True, "User registered successfully"
    
    def login(self, username: str, password: str) -> Tuple[bool, str]:
        """Verify user credentials"""
        if username not in self.users:
            return False, "Invalid username or password"
        
        if self.users[username]['password'] != self.hash_password(password):
            return False, "Invalid username or password"
        
        return True, "Login successful"
    
    def get_user_ids(self, username: str) -> Dict:
        """Get user's platform IDs"""
        if username not in self.users:
            return {}
        
        user = self.users[username]
        return {
            'steam_id': user.get('steam_id', ''),
            'epic_id': user.get('epic_id', ''),
            'gog_id': user.get('gog_id', '')
        }
    
    def update_user_ids(self, username: str, steam_id: str = '', epic_id: str = '', gog_id: str = '') -> bool:
        """Update user's platform IDs"""
        if username not in self.users:
            return False
        
        self.users[username]['steam_id'] = steam_id
        self.users[username]['epic_id'] = epic_id
        self.users[username]['gog_id'] = gog_id
        self.save_users()
        return True
    
    def get_user_role(self, username: str) -> str:
        """Get user's role"""
        if username not in self.users:
            return 'user'
        return self.users[username].get('role', 'user')
    
    def is_admin(self, username: str) -> bool:
        """Check if user is admin"""
        return self.get_user_role(username) == 'admin'
    
    def get_all_users(self) -> List[Dict]:
        """Get all users with their info (excluding passwords)"""
        users_list = []
        for username, user_data in self.users.items():
            users_list.append({
                'username': username,
                'steam_id': user_data.get('steam_id', ''),
                'epic_id': user_data.get('epic_id', ''),
                'gog_id': user_data.get('gog_id', ''),
                'role': user_data.get('role', 'user')
            })
        return users_list
    
    def delete_user(self, username: str, requesting_user: str) -> Tuple[bool, str]:
        """Delete a user (admin only)"""
        if not self.is_admin(requesting_user):
            return False, "Only admins can delete users"
        
        if username not in self.users:
            return False, "User not found"
        
        if username == requesting_user:
            return False, "Cannot delete yourself"
        
        del self.users[username]
        self.save_users()
        return True, "User deleted successfully"
    
    def update_user_role(self, username: str, role: str, requesting_user: str) -> Tuple[bool, str]:
        """Update user's role (admin only)"""
        if not self.is_admin(requesting_user):
            return False, "Only admins can change roles"
        
        if username not in self.users:
            return False, "User not found"
        
        if role not in ['admin', 'user']:
            return False, "Invalid role"
        
        self.users[username]['role'] = role
        self.save_users()
        return True, "Role updated successfully"


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
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, message = user_manager.register(username, password)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'message': message})


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """Log in a user"""
    global current_user, picker, multi_picker
    
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    success, message = user_manager.login(username, password)
    
    if not success:
        return jsonify({'error': message}), 401
    
    # Set current user
    with current_user_lock:
        current_user = username
    
    # Initialize picker for this user
    user_ids = user_manager.get_user_ids(username)
    
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
        
        # Initialize picker in background with proper GamePicker initialization
        def init_picker_async():
            try:
                # Write temporary config to a file for GamePicker to load
                temp_config_path = os.path.join(tempfile.gettempdir(), f'.gapi_user_{username}_config.json')
                
                with open(temp_config_path, 'w') as f:
                    json.dump(temp_config, f)
                
                with picker_lock:
                    global picker
                    picker = gapi.GamePicker(config_path=temp_config_path)
                    picker.fetch_games()
                    
                    # Initialize multi-user picker with config
                    with multi_picker_lock:
                        global multi_picker
                        multi_picker = multiuser.MultiUserPicker(picker.config)
                
                # Clean up temp config after initialization
                if os.path.exists(temp_config_path):
                    os.remove(temp_config_path)
                    
            except Exception as e:
                gui_logger.error("Error initializing picker: %s", e)
                # Clean up on error
                temp_config_path = os.path.join(tempfile.gettempdir(), f'.gapi_user_{username}_config.json')
                if os.path.exists(temp_config_path):
                    try:
                        os.remove(temp_config_path)
                    except:
                        pass
        
        threading.Thread(target=init_picker_async, daemon=True).start()
    
    return jsonify({'message': 'Login successful', 'username': username})


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """Log out the current user"""
    global current_user, picker, multi_picker
    
    with current_user_lock:
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
    
    # Reinitialize picker with new IDs
    user_ids = user_manager.get_user_ids(username)
    
    if user_ids.get('steam_id'):
        base_config = load_base_config()
        
        # Create temporary config for this user
        temp_config = {
            'steam_api_key': base_config.get('steam_api_key', ''),
            'steam_id': user_ids['steam_id'],
            'epic_enabled': user_ids.get('epic_id') != '',
            'epic_id': user_ids.get('epic_id', ''),
            'gog_enabled': user_ids.get('gog_id') != '',
            'gog_id': user_ids.get('gog_id', '')
        }
        
        # Write temp config to a file for GamePicker to load
        temp_config_path = os.path.join(tempfile.gettempdir(), f'.gapi_user_{username}_config.json')
        
        def init_picker_async():
            try:
                # Write temporary config
                with open(temp_config_path, 'w') as f:
                    json.dump(temp_config, f)
                
                with picker_lock:
                    global picker
                    picker = gapi.GamePicker(config_path=temp_config_path)
                    picker.fetch_games()
                    
                    # Initialize multi-user picker with config
                    with multi_picker_lock:
                        global multi_picker
                        multi_picker = multiuser.MultiUserPicker(picker.config)
                
                # Clean up temp config after initialization
                if os.path.exists(temp_config_path):
                    os.remove(temp_config_path)
                    
            except Exception as e:
                gui_logger.error("Error initializing picker: %s", e)
                # Clean up on error
                if os.path.exists(temp_config_path):
                    try:
                        os.remove(temp_config_path)
                    except:
                        pass
        
        threading.Thread(target=init_picker_async, daemon=True).start()
    
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
    return jsonify(user_ids)


@app.route('/api/pick', methods=['POST'])
@require_login
def api_pick_game():
    """Pick a random game"""
    global picker, current_game, current_user

    # Ensure picker is initialized for logged-in user
    if not picker or not picker.games:
        # Initialize with demo games if not loaded
        if not picker:
            with picker_lock:
                picker = gapi.GamePicker()
                picker.games = DEMO_GAMES
        if not picker.games:
            picker.games = DEMO_GAMES

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

    # Get ignored games from database
    with current_user_lock:
        username = current_user
    
    if DB_AVAILABLE:
        try:
            ignored_games = database.get_ignored_games(database.SessionLocal(), username)
            if ignored_games:
                if exclude_game_ids:
                    exclude_game_ids.extend(ignored_games)
                else:
                    exclude_game_ids = ignored_games
        except Exception as e:
            gui_logger.warning(f"Could not fetch ignored games: {e}")

    # Build shared advanced-filter kwargs
    adv = {
        'genres': genres,
        'min_metacritic': int(min_metacritic) if min_metacritic is not None else None,
        'min_release_year': int(min_year) if min_year is not None else None,
        'max_release_year': int(max_year) if max_year is not None else None,
        'exclude_game_ids': exclude_game_ids,
    }

    with picker_lock:
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

        if filtered_games is not None and len(filtered_games) == 0:
            return jsonify({'error': 'No games match the selected filters'}), 400

        # Pick game
        game = picker.pick_random_game(filtered_games)

        if not game:
            return jsonify({'error': 'Failed to pick a game'}), 500

        current_game = game

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

        # Try to get details (non-blocking)
        def fetch_details():
            if app_id and picker and picker.steam_client:
                details = picker.steam_client.get_game_details(app_id)
                if details:
                    game['_details'] = details

        threading.Thread(target=fetch_details, daemon=True).start()

        # Fire webhook if one is configured (non-blocking, best-effort)
        webhook_url = picker.config.get('webhook_url', '').strip()
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


@app.route('/api/game/<int:app_id>/details')
@require_login
def api_game_details(app_id):
    """Get detailed game information"""
    global picker
    
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400
    
    if not picker.steam_client:
        return jsonify({'error': 'Steam client not initialized'}), 400
    
    with picker_lock:
        details = picker.steam_client.get_game_details(app_id)
        
        if not details:
            return jsonify({'error': 'Could not fetch details'}), 404
        
        response = {}

        if 'header_image' in details:
            response['header_image'] = details['header_image']

        if 'capsule_image' in details:
            response['capsule_image'] = details['capsule_image']
        
        if 'short_description' in details:
            response['description'] = details['short_description']
        
        if 'genres' in details:
            response['genres'] = [g['description'] for g in details['genres']]
        
        if 'release_date' in details:
            response['release_date'] = details['release_date'].get('date', 'Unknown')
        
        if 'metacritic' in details:
            response['metacritic_score'] = details['metacritic'].get('score')

        # ProtonDB Linux compatibility rating (best-effort, non-blocking cache)
        if picker.steam_client and isinstance(picker.steam_client, gapi.SteamAPIClient):
            protondb = picker.steam_client.get_protondb_rating(app_id)
            if protondb:
                response['protondb'] = protondb

        return jsonify(response)


@app.route('/api/favorite/<int:app_id>', methods=['POST', 'DELETE'])
@require_login
def api_toggle_favorite(app_id):
    """Add or remove a game from favorites"""
    global picker
    
    # Ensure picker is initialized for logged-in user
    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES
    
    with picker_lock:
        if request.method == 'POST':
            picker.add_favorite(app_id)
            return jsonify({'success': True, 'action': 'added'})
        else:
            picker.remove_favorite(app_id)
            return jsonify({'success': True, 'action': 'removed'})


@app.route('/api/library')
@require_login
def api_library():
    """Get all games in library"""
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
    
    search = request.args.get('search', '').lower()
    
    with picker_lock:
        games = []
        sorted_games = sorted(picker.games, key=lambda g: g.get('name', '').lower())
        
        for game in sorted_games:
            name = game.get('name', 'Unknown')
            if search and search not in name.lower():
                continue
            
            app_id = game.get('appid')
            playtime_hours = game.get('playtime_forever', 0) / 60
            is_favorite = app_id in picker.favorites if app_id else False
            
            games.append({
                'app_id': app_id,
                'name': name,
                'playtime_hours': round(playtime_hours, 1),
                'is_favorite': is_favorite
            })
        
        return jsonify({'games': games})


@app.route('/api/favorites')
@require_login
def api_favorites():
    """Get all favorite games"""
    global picker
    
    # Ensure picker is initialized for logged-in user
    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES
    
    with picker_lock:
        favorites = []
        
        for app_id in picker.favorites:
            game = next((g for g in picker.games if g.get('appid') == app_id), None)
            if game:
                favorites.append({
                    'app_id': app_id,
                    'name': game.get('name', 'Unknown'),
                    'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1)
                })
            else:
                favorites.append({
                    'app_id': app_id,
                    'name': f'App ID {app_id} (Not in library)',
                    'playtime_hours': 0
                })
        
        return jsonify({'favorites': favorites})


@app.route('/api/stats')
@require_login
def api_stats():
    """Get library statistics"""
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
        total_games = len(picker.games)
        unplayed = len([g for g in picker.games if g.get('playtime_forever', 0) == 0])
        total_playtime = sum(g.get('playtime_forever', 0) for g in picker.games) / 60
        
        # Top 10 most played
        sorted_by_playtime = sorted(
            picker.games,
            key=lambda g: g.get('playtime_forever', 0),
            reverse=True
        )[:10]
        
        top_games = []
        for game in sorted_by_playtime:
            top_games.append({
                'name': game.get('name', 'Unknown'),
                'playtime_hours': round(game.get('playtime_forever', 0) / 60, 1)
            })
        
        return jsonify({
            'total_games': total_games,
            'unplayed_games': unplayed,
            'played_games': total_games - unplayed,
            'unplayed_percentage': round(unplayed / total_games * 100, 1) if total_games > 0 else 0,
            'total_playtime': round(total_playtime, 1),
            'average_playtime': round(total_playtime / total_games, 1) if total_games > 0 else 0,
            'favorite_count': len(picker.favorites),
            'top_games': top_games
        })


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
        
        # Ensure user exists in database
        user = database.get_user_by_username(db, username)
        if not user:
            user = database.create_or_update_user(db, username)
        
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
            user = database.create_or_update_user(db, username)
        
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
                hunt.completed_at = datetime.utcnow()
        
        hunt.updated_at = datetime.utcnow()
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
            min_avg_playtime=min_avg_playtime
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
        users        – list of user names participating (optional – all users if omitted)
        num_candidates – number of game candidates to put to a vote (default: 5)
        duration     – voting window in seconds (optional)
        coop_only    – filter to co-op games only (default: false)
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
            candidates, voters=voters, duration=duration
        )

    return jsonify(session.to_dict()), 201


@app.route('/api/voting/<session_id>/vote', methods=['POST'])
@require_login
def api_voting_cast(session_id: str):
    """Cast a vote in an active voting session.

    Expected JSON body:
        user_name – name of the voter
        app_id    – app ID of the game being voted for
    """
    global multi_picker

    _ensure_multi_picker()
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    data = request.json or {}
    user_name = data.get('user_name', '').strip()
    app_id = str(data.get('app_id', '')).strip()

    if not user_name:
        return jsonify({'error': 'user_name is required'}), 400
    if not app_id:
        return jsonify({'error': 'app_id is required'}), 400

    with multi_picker_lock:
        session = multi_picker.get_voting_session(session_id)
        if session is None:
            return jsonify({'error': 'Voting session not found'}), 404

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

    return jsonify({
        'winner': {
            'app_id': app_id,
            'name': winner.get('name', 'Unknown'),
            'playtime_hours': round(winner.get('playtime_forever', 0) / 60, 1),
            'steam_url': f'https://store.steampowered.com/app/{app_id}/' if app_id else None,
            'steamdb_url': f'https://steamdb.info/app/{app_id}/' if app_id else None,
        },
        'vote_counts': session_data.get('vote_counts', {}),
        'total_votes': session_data.get('total_votes', 0),
    })


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
    
    # Ensure picker is initialized for logged-in user
    if not picker:
        with picker_lock:
            picker = gapi.GamePicker()
            picker.games = DEMO_GAMES
    if not picker.games:
        picker.games = DEMO_GAMES
        
    with picker_lock:
        return jsonify({'tags': picker.all_tags(), 'game_tags': picker.tags})


@app.route('/api/tags/<game_id>', methods=['GET'])
def api_get_game_tags(game_id: str):
    """Return the tags for a specific game."""
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400
    with picker_lock:
        return jsonify({'game_id': game_id, 'tags': picker.get_tags(game_id)})


@app.route('/api/tags/<game_id>', methods=['POST'])
def api_add_tag(game_id: str):
    """Add a tag to a game.

    Body JSON: {"tag": "cozy"}
    """
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400

    data = request.json or {}
    tag = data.get('tag', '').strip()
    if not tag:
        return jsonify({'error': 'tag is required'}), 400

    with picker_lock:
        added = picker.add_tag(game_id, tag)
        tags = picker.get_tags(game_id)

    return jsonify({'success': True, 'added': added,
                    'game_id': game_id, 'tags': tags})


@app.route('/api/tags/<game_id>/<tag>', methods=['DELETE'])
def api_remove_tag(game_id: str, tag: str):
    """Remove a tag from a game."""
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400

    with picker_lock:
        removed = picker.remove_tag(game_id, tag)
        tags = picker.get_tags(game_id)

    if not removed:
        return jsonify({'error': 'Tag not found'}), 404

    return jsonify({'success': True, 'game_id': game_id, 'tags': tags})


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
        if demo_mode and os.path.exists(config_path):
            os.remove(config_path)


if __name__ == "__main__":
    main()
