#!/usr/bin/env python3
"""
GAPI - Game Picker with Multi-Platform Integration
A tool to randomly pick a game from your Steam, Epic Games, and GOG libraries with detailed information.
"""

import json
import logging
import os
import re
import sys
import random
import argparse
import datetime
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
import requests
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored terminal output
init(autoreset=True)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(level: str = 'WARNING') -> logging.Logger:
    """Configure the root GAPI logger.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to WARNING so normal use is quiet.

    Returns:
        Configured logger instance.
    """
    numeric = getattr(logging, level.upper(), logging.WARNING)
    logger = logging.getLogger('gapi')
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(numeric)
    return logger


# Module-level logger used throughout gapi.py
logger = setup_logging()


def _atomic_write_json(path: str, data) -> None:
    """Write *data* as JSON to *path* atomically (write-then-rename).

    Creates a sibling temp file, writes the JSON, then renames it over the
    target path so the file is never left in a partially-written state.

    Args:
        path: Destination file path.
        data: JSON-serialisable Python object.

    Raises:
        IOError: If the write or rename fails.
    """
    dir_name = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file if anything goes wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def extract_game_id(game: Dict) -> Optional[str]:
    """Helper function to extract game ID from various formats"""
    return game.get('appid') or game.get('id') or game.get('game_id')


_PLACEHOLDER_VALUES = {'DEMO_MODE', 'DEMO_ID', 'DEMO_KEY', 'YOUR_STEAM_API_KEY_HERE',
                       'YOUR_STEAM_ID_HERE', 'YOUR_EPIC_ID_HERE', 'YOUR_GOG_ID_HERE',
                       'YOUR_DISCORD_BOT_TOKEN_HERE'}


def is_placeholder_value(value: str) -> bool:
    """Check if a value is a placeholder/demo sentinel that should not be used for real API calls."""
    if not value or not isinstance(value, str):
        return True
    return value.startswith('YOUR_') or value in _PLACEHOLDER_VALUES


def send_webhook(url: str, payload: Dict, timeout: int = 5) -> bool:
    """POST *payload* as JSON to *url* (Discord / Slack / IFTTT webhook).

    Discord-compatible: the payload includes a ``content`` key with a plain-text
    summary; all other webhook services receive the full JSON body.

    Args:
        url: Webhook URL to POST to.
        payload: JSON-serialisable dict.
        timeout: Request timeout in seconds.

    Returns:
        True on a 2xx response, False on any network or HTTP error.
    """
    _wh_log = logging.getLogger('gapi.webhook')
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        _wh_log.info("Webhook delivered to %s (HTTP %s)", url, resp.status_code)
        return True
    except requests.RequestException as e:
        _wh_log.warning("Webhook delivery failed (%s): %s", url, e)
        return False


def minutes_to_hours(minutes: int) -> float:
    """Convert playtime from minutes to hours

    Args:
        minutes: Playtime in minutes

    Returns:
        Playtime in hours, rounded to 1 decimal place
    """
    return round(minutes / 60, 1)


def _parse_release_year(date_str: str) -> Optional[int]:
    """Extract a 4-digit year from a Steam release date string such as '21 Mar, 2020'.

    Returns the year as an integer, or None if the string cannot be parsed.
    """
    if not date_str:
        return None
    m = re.search(r'\b(19|20)\d{2}\b', date_str)
    return int(m.group(0)) if m else None


def is_valid_steam_id(steam_id: str) -> bool:
    """Validate Steam ID format (64-bit SteamID)
    
    Args:
        steam_id: Steam ID to validate
        
    Returns:
        True if valid 64-bit Steam ID format, False otherwise
    """
    if not steam_id or not isinstance(steam_id, str):
        return False
    
    # Steam 64-bit IDs are 17-digit numbers starting with 7656119
    if not steam_id.isdigit():
        return False
    
    if len(steam_id) != 17:
        return False
    
    if not steam_id.startswith('7656119'):
        return False
    
    return True


class GamePlatformClient(ABC):
    """Abstract base class for game platform API clients"""
    
    def __init__(self):
        self.session = requests.Session()
        self.details_cache = {}
    
    @abstractmethod
    def get_owned_games(self, user_id: str) -> List[Dict]:
        """
        Get list of games owned by a user.
        Returns list of dicts with at minimum: name, appid/game_id, playtime_forever
        """
        pass
    
    @abstractmethod
    def get_game_details(self, game_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific game.
        Returns dict with game details or None if not found
        """
        pass
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the platform name (e.g., 'steam', 'epic', 'gog')"""
        pass


class SteamAPIClient(GamePlatformClient):
    """Client for interacting with Steam Web API"""

    BASE_URL = "https://api.steampowered.com"

    def __init__(self, api_key: str, timeout: int = 10):
        super().__init__()
        self.api_key = api_key
        self.timeout = timeout
        self._log = logging.getLogger('gapi.steam')
        self._protondb_cache: Dict = {}

    def get_platform_name(self) -> str:
        return "steam"

    def get_owned_games(self, user_id: str, include_appinfo: bool = True) -> List[Dict]:
        """Get list of games owned by a Steam user"""
        url = f"{self.BASE_URL}/IPlayerService/GetOwnedGames/v0001/"
        params = {
            'key': self.api_key,
            'steamid': user_id,
            'include_appinfo': 1 if include_appinfo else 0,
            'include_played_free_games': 1,
            'format': 'json'
        }

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            if 'response' in data and 'games' in data['response']:
                games = data['response']['games']
                # Add platform info to each game
                for game in games:
                    game['platform'] = self.get_platform_name()
                return games
            return []
        except requests.RequestException as e:
            self._log.error("Error fetching games from Steam API: %s", e)
            return []

    def get_game_details(self, game_id: str) -> Optional[Dict]:
        """Get detailed information about a specific game"""
        # Convert to int for Steam API
        try:
            app_id_int = int(game_id)
        except (ValueError, TypeError):
            return None

        # Check cache first
        if app_id_int in self.details_cache:
            return self.details_cache[app_id_int]

        url = "https://store.steampowered.com/api/appdetails"
        params = {'appids': app_id_int}

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            if str(app_id_int) in data and data[str(app_id_int)]['success']:
                details = data[str(app_id_int)]['data']
                self.details_cache[app_id_int] = details
                return details
            return None
        except requests.RequestException as e:
            self._log.warning("Could not fetch details for app %s: %s", game_id, e)
            return None

    def get_protondb_rating(self, app_id: str) -> Optional[Dict]:
        """Fetch ProtonDB Linux compatibility tier for a Steam game.

        Returns a dict with ``tier``, ``score``, and ``total`` (report count),
        or ``None`` if no data is available or the fetch fails.
        Tier values: platinum, gold, silver, bronze, borked, pending.
        Results are cached in memory for the lifetime of the client instance.
        """
        try:
            app_id_int = int(app_id)
        except (ValueError, TypeError):
            return None

        if app_id_int in self._protondb_cache:
            return self._protondb_cache[app_id_int]

        url = f"https://www.protondb.com/api/v1/reports/summaries/{app_id_int}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                result: Optional[Dict] = {
                    'tier': data.get('tier', 'unknown'),
                    'score': data.get('score'),
                    'total': data.get('total', 0),
                }
                self._protondb_cache[app_id_int] = result
                return result
            # Cache the miss (404 = no reports yet) so we don't retry
            self._protondb_cache[app_id_int] = None
        except requests.RequestException as e:
            self._log.debug("ProtonDB fetch failed for %s: %s", app_id, e)
        return None

    def get_player_achievements(self, steam_id: str, app_id) -> Optional[Dict]:
        """Fetch achievement stats for *steam_id* + *app_id*.

        Returns a dict with ``total``, ``achieved``, and ``percent`` keys, or
        ``None`` if the request fails or achievements are not available.
        """
        try:
            app_id_int = int(app_id)
        except (ValueError, TypeError):
            return None

        url = f"{self.BASE_URL}/ISteamUserStats/GetPlayerAchievements/v0001/"
        params = {
            'key': self.api_key,
            'steamid': steam_id,
            'appid': app_id_int,
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return None
            data = resp.json()
            achievements = data.get('playerstats', {}).get('achievements', [])
            if not achievements:
                return None
            total = len(achievements)
            achieved = sum(1 for a in achievements if a.get('achieved'))
            return {
                'total': total,
                'achieved': achieved,
                'percent': round(achieved / total * 100, 1) if total else 0,
            }
        except requests.RequestException as e:
            self._log.debug("Achievement fetch failed for app %s: %s", app_id, e)
        return None

    def get_friend_list(self, steam_id: str) -> List[Dict]:
        """Return the friend list for *steam_id*.

        Each entry is a dict with at least ``steamid`` and ``friend_since``
        keys (epoch timestamp).  Returns an empty list on error or if the
        profile is private.
        """
        url = f"{self.BASE_URL}/ISteamUser/GetFriendList/v0001/"
        params = {
            'key': self.api_key,
            'steamid': steam_id,
            'relationship': 'friend',
            'format': 'json',
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get('friendslist', {}).get('friends', [])
        except requests.RequestException as e:
            self._log.debug("Friend list fetch failed for %s: %s", steam_id, e)
        return []

    def get_player_summaries(self, steam_ids: List[str]) -> List[Dict]:
        """Return basic profile info for up to 100 Steam IDs.

        Each entry contains ``steamid``, ``personaname``, ``avatarfull``,
        ``personastate`` (0=offline…6), ``gameextrainfo`` (current game name,
        if any) and ``gameid`` (current game app id, if any).
        """
        if not steam_ids:
            return []
        # Steam API accepts up to 100 IDs per request
        chunk = steam_ids[:100]
        url = f"{self.BASE_URL}/ISteamUser/GetPlayerSummaries/v0002/"
        params = {
            'key': self.api_key,
            'steamids': ','.join(chunk),
            'format': 'json',
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get('response', {}).get('players', [])
        except requests.RequestException as e:
            self._log.debug("Player summaries fetch failed: %s", e)
        return []

    def get_recently_played(self, steam_id: str, count: int = 10) -> List[Dict]:
        """Return recently played games for *steam_id*.

        Each entry has ``appid``, ``name``, ``playtime_2weeks`` (minutes),
        and ``playtime_forever`` (minutes).
        """
        url = f"{self.BASE_URL}/IPlayerService/GetRecentlyPlayedGames/v0001/"
        params = {
            'key': self.api_key,
            'steamid': steam_id,
            'count': count,
            'format': 'json',
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get('response', {}).get('games', [])
        except requests.RequestException as e:
            self._log.debug("Recently played fetch failed for %s: %s", steam_id, e)
        return []


class EpicAPIClient(GamePlatformClient):
    """Client for interacting with Epic Games Store API"""

    def __init__(self):
        super().__init__()
        self._log = logging.getLogger('gapi.epic')
        try:
            from epicstore_api import EpicGamesStoreAPI
            self.api = EpicGamesStoreAPI()
        except ImportError:
            self._log.warning("epicstore-api not installed. Epic Games support disabled.")
            self.api = None

    def get_platform_name(self) -> str:
        return "epic"

    def get_owned_games(self, user_id: str) -> List[Dict]:
        """
        Get list of games from Epic Games Store.
        Note: Epic doesn't provide a user library API without OAuth,
        so this returns an empty list for now.
        """
        if not self.api:
            return []

        # Epic Games Store API doesn't provide user library access without OAuth
        self._log.info("Epic Games library access requires OAuth authentication. "
                       "Epic integration currently supports store browsing only.")
        return []

    def get_game_details(self, game_id: str) -> Optional[Dict]:
        """Get detailed information about a specific Epic game"""
        if not self.api:
            return None

        # Check cache first
        if game_id in self.details_cache:
            return self.details_cache[game_id]

        try:
            # Try to get product details
            product = self.api.get_product(game_id)
            if product:
                # Normalize to match Steam API format
                details = {
                    'name': product.get('title', 'Unknown'),
                    'short_description': product.get('description', ''),
                    'developers': [product.get('developer', 'Unknown')],
                    'publishers': [product.get('publisher', 'Unknown')],
                }
                self.details_cache[game_id] = details
                return details
        except Exception as e:
            self._log.warning("Could not fetch details for Epic game %s: %s", game_id, e)

        return None


class GOGAPIClient(GamePlatformClient):
    """Client for interacting with GOG Galaxy API"""

    def __init__(self):
        super().__init__()
        # GOG Galaxy API is primarily for plugin development
        # Direct library access requires authentication
        self.authenticated = False
        self._log = logging.getLogger('gapi.gog')

    def get_platform_name(self) -> str:
        return "gog"

    def get_owned_games(self, user_id: str) -> List[Dict]:
        """
        Get list of games from GOG library.
        Note: GOG's API requires authentication and is meant for Galaxy plugins.
        This returns an empty list for now.
        """
        self._log.info("GOG library access requires Galaxy plugin authentication. "
                       "GOG integration is currently not fully supported.")
        return []

    def get_game_details(self, game_id: str) -> Optional[Dict]:
        """Get detailed information about a specific GOG game"""
        # Check cache first
        if game_id in self.details_cache:
            return self.details_cache[game_id]

        # GOG API requires authentication for most operations
        # For now, return minimal info
        return None


class GamePicker:
    """Main game picker application"""

    HISTORY_FILE = '.gapi_history.json'
    FAVORITES_FILE = '.gapi_favorites.json'
    CACHE_FILE = '.gapi_details_cache.json'
    REVIEWS_FILE = '.gapi_reviews.json'
    TAGS_FILE = '.gapi_tags.json'
    SCHEDULE_FILE = '.gapi_schedule.json'
    PLAYLISTS_FILE = '.gapi_playlists.json'
    BACKLOG_FILE = '.gapi_backlog.json'

    BACKLOG_STATUSES = ('want_to_play', 'playing', 'completed', 'dropped')

    # Default values (can be overridden by config)
    DEFAULT_MAX_HISTORY = 20
    DEFAULT_BARELY_PLAYED_HOURS = 2
    DEFAULT_WELL_PLAYED_HOURS = 10
    DEFAULT_API_TIMEOUT = 10
    
    def __init__(self, config_path: str = 'config.json'):
        self._log = logging.getLogger('gapi.picker')
        self.config = self.load_config(config_path)

        # Re-apply log level from config (allows "log_level": "DEBUG" in config.json)
        log_level = self.config.get('log_level', 'WARNING')
        setup_logging(log_level)

        # Load configurable values from config or use defaults
        self.MAX_HISTORY = self.config.get('max_history_size', self.DEFAULT_MAX_HISTORY)
        self.BARELY_PLAYED_THRESHOLD_MINUTES = self.config.get('barely_played_hours', self.DEFAULT_BARELY_PLAYED_HOURS) * 60
        self.WELL_PLAYED_THRESHOLD_MINUTES = self.config.get('well_played_hours', self.DEFAULT_WELL_PLAYED_HOURS) * 60
        self.API_TIMEOUT = self.config.get('api_timeout_seconds', self.DEFAULT_API_TIMEOUT)

        # Initialize platform clients
        self.clients: Dict[str, GamePlatformClient] = {}

        # Always try to initialize Steam if API key is available and not a placeholder
        if not is_placeholder_value(self.config.get('steam_api_key', '')):
            self.clients['steam'] = SteamAPIClient(self.config['steam_api_key'], timeout=self.API_TIMEOUT)

        # Initialize Epic Games client if enabled
        if self.config.get('epic_enabled', False):
            try:
                self.clients['epic'] = EpicAPIClient()
            except Exception as e:
                self._log.warning("Could not initialize Epic Games client: %s", e)

        # Initialize GOG client if enabled
        if self.config.get('gog_enabled', False):
            try:
                self.clients['gog'] = GOGAPIClient()
            except Exception as e:
                self._log.warning("Could not initialize GOG client: %s", e)

        # For backward compatibility, keep steam_client reference
        self.steam_client = self.clients.get('steam')

        self.games: List[Dict] = []
        self.history: List[str] = self.load_history()  # Now stores composite IDs
        self.favorites: List[str] = self.load_favorites()  # Now stores composite IDs
        self.reviews: Dict[str, Dict] = self.load_reviews()  # game_id -> review dict
        self.tags: Dict[str, List[str]] = self.load_tags()  # game_id -> [tag, ...]
        self.schedule: Dict[str, Dict] = self.load_schedule()  # event_id -> event dict
        self.playlists: Dict[str, List[str]] = self.load_playlists()  # name -> [game_id, ...]
        self.backlog: Dict[str, str] = self.load_backlog()  # game_id -> status

        # Load persistent details cache and push it into all platform clients
        self._load_details_cache()

    def _load_details_cache(self):
        """Load the on-disk details cache and populate all platform clients."""
        if not os.path.exists(self.CACHE_FILE):
            return
        try:
            with open(self.CACHE_FILE, 'r') as f:
                data = json.load(f)
            # Steam cache keys are integers; restore them properly
            steam_cache = data.get('steam', {})
            epic_cache = data.get('epic', {})
            gog_cache = data.get('gog', {})
            loaded = 0
            if 'steam' in self.clients:
                self.clients['steam'].details_cache = {
                    int(k): v for k, v in steam_cache.items()
                }
                loaded += len(steam_cache)
            if 'epic' in self.clients:
                self.clients['epic'].details_cache = dict(epic_cache)
                loaded += len(epic_cache)
            if 'gog' in self.clients:
                self.clients['gog'].details_cache = dict(gog_cache)
                loaded += len(gog_cache)
            self._log.debug("Loaded %d cached game details from disk.", loaded)
        except (json.JSONDecodeError, IOError) as e:
            self._log.warning("Could not load details cache: %s", e)

    def save_details_cache(self):
        """Persist the in-memory details cache to disk (atomic write)."""
        data = {
            'steam': {str(k): v for k, v in self.clients['steam'].details_cache.items()}
            if 'steam' in self.clients else {},
            'epic': dict(self.clients['epic'].details_cache)
            if 'epic' in self.clients else {},
            'gog': dict(self.clients['gog'].details_cache)
            if 'gog' in self.clients else {},
        }
        try:
            _atomic_write_json(self.CACHE_FILE, data)
            self._log.debug("Details cache saved (%d steam entries).",
                            len(data['steam']))
        except IOError as e:
            self._log.warning("Could not save details cache: %s", e)

    # ------------------------------------------------------------------
    # Game Reviews
    # ------------------------------------------------------------------

    def load_reviews(self) -> Dict[str, Dict]:
        """Load personal game reviews from disk.

        Returns:
            Dict mapping game_id → {'rating': int, 'notes': str, 'updated_at': str}
        """
        if os.path.exists(self.REVIEWS_FILE):
            try:
                with open(self.REVIEWS_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log.warning("Could not load reviews: %s", e)
        return {}

    def save_reviews(self):
        """Persist reviews to disk (atomic write)."""
        try:
            _atomic_write_json(self.REVIEWS_FILE, self.reviews)
        except IOError as e:
            self._log.error("Error saving reviews: %s", e)

    def add_or_update_review(self, game_id: str, rating: int, notes: str = "") -> bool:
        """Add or update a personal review for a game.

        Args:
            game_id: Composite game ID (e.g. 'steam:620') or plain app ID string.
            rating: Score from 1 to 10.
            notes: Optional personal notes.

        Returns:
            True on success, False if rating is out of range.
        """
        if not 1 <= rating <= 10:
            return False
        self.reviews[str(game_id)] = {
            'rating': rating,
            'notes': notes,
            'updated_at': datetime.datetime.now().isoformat(),
        }
        self.save_reviews()
        return True

    def remove_review(self, game_id: str) -> bool:
        """Remove a review for a game.

        Returns:
            True if the review existed and was removed, False otherwise.
        """
        if str(game_id) in self.reviews:
            del self.reviews[str(game_id)]
            self.save_reviews()
            return True
        return False

    def get_review(self, game_id: str) -> Optional[Dict]:
        """Return the review dict for a game, or None if not reviewed."""
        return self.reviews.get(str(game_id))

    # ------------------------------------------------------------------
    # Custom Game Tags
    # ------------------------------------------------------------------

    def load_tags(self) -> Dict[str, List[str]]:
        """Load custom game tags from disk.

        Returns:
            Dict mapping game_id → list of tag strings.
        """
        if os.path.exists(self.TAGS_FILE):
            try:
                with open(self.TAGS_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log.warning("Could not load tags: %s", e)
        return {}

    def save_tags(self):
        """Persist tags to disk (atomic write)."""
        try:
            _atomic_write_json(self.TAGS_FILE, self.tags)
        except IOError as e:
            self._log.error("Error saving tags: %s", e)

    def add_tag(self, game_id: str, tag: str) -> bool:
        """Add a tag to a game (case-insensitive, normalised to lower-case).

        Returns:
            True if the tag was added, False if it was already present.
        """
        tag = tag.strip().lower()
        if not tag:
            return False
        gid = str(game_id)
        if gid not in self.tags:
            self.tags[gid] = []
        if tag in self.tags[gid]:
            return False
        self.tags[gid].append(tag)
        self.save_tags()
        return True

    def remove_tag(self, game_id: str, tag: str) -> bool:
        """Remove a tag from a game.

        Returns:
            True if removed, False if it wasn't there.
        """
        tag = tag.strip().lower()
        gid = str(game_id)
        if gid in self.tags and tag in self.tags[gid]:
            self.tags[gid].remove(tag)
            if not self.tags[gid]:
                del self.tags[gid]
            self.save_tags()
            return True
        return False

    def get_tags(self, game_id: str) -> List[str]:
        """Return the tag list for a game (empty list if none)."""
        return self.tags.get(str(game_id), [])

    def all_tags(self) -> List[str]:
        """Return a sorted list of every unique tag across all games."""
        seen: set = set()
        for tags in self.tags.values():
            seen.update(tags)
        return sorted(seen)

    def filter_by_tag(self, tag: str,
                      games: Optional[List[Dict]] = None) -> List[Dict]:
        """Return games (from ``games`` or the full library) that have the given tag.

        Args:
            tag: Tag string (case-insensitive).
            games: Optional pre-filtered game list to further filter.

        Returns:
            Filtered list of game dicts.
        """
        tag = tag.strip().lower()
        pool = games if games is not None else self.games
        return [
            g for g in pool
            if tag in self.tags.get(str(g.get('game_id', g.get('appid', ''))), [])
        ]

    # ------------------------------------------------------------------
    # Game Night Scheduler
    # ------------------------------------------------------------------

    def load_schedule(self) -> Dict[str, Dict]:
        """Load game night events from disk."""
        if os.path.exists(self.SCHEDULE_FILE):
            try:
                with open(self.SCHEDULE_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log.warning("Could not load schedule: %s", e)
        return {}

    def save_schedule(self) -> None:
        """Persist game night events to disk (atomic write)."""
        _atomic_write_json(self.SCHEDULE_FILE, self.schedule)

    def add_event(self, title: str, date: str, time_str: str,
                  attendees: Optional[List[str]] = None,
                  game_name: str = '', notes: str = '') -> Dict:
        """Create a new game night event and persist it.

        Args:
            title:     Short event title (required).
            date:      ISO date string, e.g. ``"2026-03-01"``.
            time_str:  Time string, e.g. ``"20:00"``.
            attendees: List of participant names.
            game_name: Optional pre-chosen game name.
            notes:     Free-text notes.

        Returns:
            The new event dict (includes generated ``id`` and ``created_at``).
        """
        event_id = str(uuid.uuid4())[:8]
        event: Dict = {
            'id': event_id,
            'title': title,
            'date': date,
            'time': time_str,
            'attendees': attendees or [],
            'game_name': game_name,
            'notes': notes,
            'created_at': datetime.datetime.utcnow().isoformat(),
        }
        self.schedule[event_id] = event
        self.save_schedule()
        return event

    def update_event(self, event_id: str, **kwargs) -> Optional[Dict]:
        """Update an existing event's fields.

        Only ``title``, ``date``, ``time``, ``attendees``, ``game_name``, and
        ``notes`` are accepted; any other keys in *kwargs* are ignored.

        Returns:
            Updated event dict, or ``None`` if not found.
        """
        if event_id not in self.schedule:
            return None
        event = self.schedule[event_id]
        for key in ('title', 'date', 'time', 'attendees', 'game_name', 'notes'):
            if key in kwargs:
                event[key] = kwargs[key]
        event['updated_at'] = datetime.datetime.utcnow().isoformat()
        self.save_schedule()
        return event

    def remove_event(self, event_id: str) -> bool:
        """Delete an event by ID.

        Returns:
            True if the event existed and was removed, False if not found.
        """
        if event_id in self.schedule:
            del self.schedule[event_id]
            self.save_schedule()
            return True
        return False

    def get_events(self) -> List[Dict]:
        """Return all events sorted by date then time (ascending)."""
        events = list(self.schedule.values())
        events.sort(key=lambda e: (e.get('date', ''), e.get('time', '')))
        return events

    # ------------------------------------------------------------------
    # Custom Playlists
    # ------------------------------------------------------------------

    def load_playlists(self) -> Dict[str, List[str]]:
        """Load playlists from disk."""
        if os.path.exists(self.PLAYLISTS_FILE):
            try:
                with open(self.PLAYLISTS_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log.warning("Could not load playlists: %s", e)
        return {}

    def save_playlists(self) -> None:
        """Persist playlists to disk (atomic write)."""
        _atomic_write_json(self.PLAYLISTS_FILE, self.playlists)

    def create_playlist(self, name: str) -> bool:
        """Create a new empty playlist. Returns False if it already exists."""
        name = name.strip()
        if not name or name in self.playlists:
            return False
        self.playlists[name] = []
        self.save_playlists()
        return True

    def delete_playlist(self, name: str) -> bool:
        """Delete a playlist by name. Returns False if not found."""
        if name not in self.playlists:
            return False
        del self.playlists[name]
        self.save_playlists()
        return True

    def add_to_playlist(self, name: str, game_id: str) -> bool:
        """Add *game_id* to a playlist (creates it if absent). Returns True if added."""
        name = name.strip()
        if not name:
            return False
        if name not in self.playlists:
            self.playlists[name] = []
        if game_id in self.playlists[name]:
            return False  # already present
        self.playlists[name].append(game_id)
        self.save_playlists()
        return True

    def remove_from_playlist(self, name: str, game_id: str) -> bool:
        """Remove *game_id* from a playlist. Returns False if not found."""
        if name not in self.playlists or game_id not in self.playlists[name]:
            return False
        self.playlists[name].remove(game_id)
        self.save_playlists()
        return True

    def get_playlist_games(self, name: str) -> Optional[List[Dict]]:
        """Return game dicts for every ID stored in playlist *name*.

        Unknown / stale IDs are silently skipped.  Returns ``None`` if the
        playlist itself does not exist.
        """
        if name not in self.playlists:
            return None
        id_set = set(self.playlists[name])
        return [g for g in self.games if g.get('game_id') in id_set]

    def list_playlists(self) -> List[Dict]:
        """Return a summary list of all playlists with name and game count."""
        return [{'name': n, 'count': len(ids)} for n, ids in self.playlists.items()]

    # ------------------------------------------------------------------
    # Game Backlog / Status Tracker
    # ------------------------------------------------------------------

    def load_backlog(self) -> Dict[str, str]:
        """Load backlog statuses from disk."""
        if os.path.exists(self.BACKLOG_FILE):
            try:
                with open(self.BACKLOG_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._log.warning("Could not load backlog: %s", e)
        return {}

    def save_backlog(self) -> None:
        """Persist backlog to disk (atomic write)."""
        _atomic_write_json(self.BACKLOG_FILE, self.backlog)

    def set_backlog_status(self, game_id: str, status: str) -> bool:
        """Set the backlog status for a game.

        Args:
            game_id: Composite game ID (e.g. ``"steam:440"``).
            status:  One of ``BACKLOG_STATUSES``.

        Returns:
            True on success, False if *status* is invalid.
        """
        if status not in self.BACKLOG_STATUSES:
            return False
        self.backlog[game_id] = status
        self.save_backlog()
        return True

    def remove_backlog_status(self, game_id: str) -> bool:
        """Remove a game from the backlog. Returns False if not present."""
        if game_id not in self.backlog:
            return False
        del self.backlog[game_id]
        self.save_backlog()
        return True

    def get_backlog_status(self, game_id: str) -> Optional[str]:
        """Return the backlog status for *game_id*, or ``None`` if not tracked."""
        return self.backlog.get(game_id)

    def get_backlog_games(self, status: Optional[str] = None) -> List[Dict]:
        """Return game dicts for all backlog entries, optionally filtered by *status*.

        The returned dicts have an extra ``backlog_status`` key.
        """
        id_to_status = dict(self.backlog)
        if status:
            id_to_status = {k: v for k, v in id_to_status.items() if v == status}
        id_set = set(id_to_status)
        result = []
        for g in self.games:
            gid = g.get('game_id')
            if gid in id_set:
                entry = dict(g)
                entry['backlog_status'] = id_to_status[gid]
                result.append(entry)
        return result

    def load_history(self):
        """Load game picking history (supports both old int and new composite ID formats)"""
        if os.path.exists(self.HISTORY_FILE):
            try:
                with open(self.HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                    # Convert old integer IDs to composite format (steam:id)
                    return [f"steam:{item}" if isinstance(item, int) else item for item in data]
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def save_history(self):
        """Save game picking history (atomic write)"""
        try:
            _atomic_write_json(self.HISTORY_FILE, self.history[-self.MAX_HISTORY:])
        except IOError as e:
            self._log.warning("Could not save history: %s", e)

    def load_favorites(self) -> List[str]:
        """Load favorite games list (supports both old int and new composite ID formats)"""
        if os.path.exists(self.FAVORITES_FILE):
            try:
                with open(self.FAVORITES_FILE, 'r') as f:
                    data = json.load(f)
                    # Convert old integer IDs to composite format (steam:id)
                    return [f"steam:{item}" if isinstance(item, int) else item for item in data]
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def save_favorites(self):
        """Save favorite games list (atomic write)"""
        try:
            _atomic_write_json(self.FAVORITES_FILE, self.favorites)
        except IOError as e:
            self._log.error("Error saving favorites: %s", e)
    
    def add_favorite(self, game_id: str) -> bool:
        """Add a game to favorites (accepts composite ID like 'steam:620' or int for backward compatibility)"""
        # Convert int to composite ID for backward compatibility
        if isinstance(game_id, int):
            game_id = f"steam:{game_id}"
        
        if game_id not in self.favorites:
            self.favorites.append(game_id)
            self.save_favorites()
            return True
        return False
    
    def remove_favorite(self, game_id: str) -> bool:
        """Remove a game from favorites (accepts composite ID like 'steam:620' or int for backward compatibility)"""
        # Convert int to composite ID for backward compatibility
        if isinstance(game_id, int):
            game_id = f"steam:{game_id}"
        
        if game_id in self.favorites:
            self.favorites.remove(game_id)
            self.save_favorites()
            return True
        return False
    
    def export_history(self, filepath: str):
        """Export game history to a file"""
        try:
            export_data = {
                'history': self.history,
                'exported_at': datetime.datetime.now().isoformat()
            }
            _atomic_write_json(filepath, export_data)
            print(f"{Fore.GREEN}History exported to {filepath}")
        except IOError as e:
            print(f"{Fore.RED}Error exporting history: {e}")

    def import_history(self, filepath: str):
        """Import game history from a file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if isinstance(data, dict) and 'history' in data:
                self.history = data['history']
            elif isinstance(data, list):
                self.history = data
            else:
                print(f"{Fore.RED}Invalid history file format")
                return

            self.save_history()
            print(f"{Fore.GREEN}History imported from {filepath}")
        except (IOError, json.JSONDecodeError) as e:
            print(f"{Fore.RED}Error importing history: {e}")

    def load_config(self, config_path: str) -> Dict:
        """Load configuration from JSON file with environment variable support

        Environment variables take precedence over config file values:
        - STEAM_API_KEY overrides steam_api_key
        - STEAM_ID overrides steam_id
        - DISCORD_BOT_TOKEN overrides discord_bot_token
        - EPIC_ID overrides epic_id
        - GOG_ID overrides gog_id
        """
        if not os.path.exists(config_path):
            print(f"{Fore.RED}Error: Config file '{config_path}' not found!")
            print(f"{Fore.YELLOW}Please copy 'config_template.json' to 'config.json' and add your Steam API key and ID.")
            sys.exit(1)

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Override with environment variables if present
            if os.getenv('STEAM_API_KEY'):
                config['steam_api_key'] = os.getenv('STEAM_API_KEY')
            if os.getenv('STEAM_ID'):
                config['steam_id'] = os.getenv('STEAM_ID')
            if os.getenv('DISCORD_BOT_TOKEN'):
                config['discord_bot_token'] = os.getenv('DISCORD_BOT_TOKEN')
            if os.getenv('EPIC_ID'):
                config['epic_id'] = os.getenv('EPIC_ID')
            if os.getenv('GOG_ID'):
                config['gog_id'] = os.getenv('GOG_ID')

            # Validate required Steam credentials
            if is_placeholder_value(config.get('steam_api_key', '')):
                print(f"{Fore.RED}Error: Please configure your Steam API key in config.json or set STEAM_API_KEY environment variable")
                print(f"{Fore.YELLOW}Get a free key at: https://steamcommunity.com/dev/apikey")
                sys.exit(1)

            if is_placeholder_value(config.get('steam_id', '')):
                print(f"{Fore.RED}Error: Please configure your Steam ID in config.json or set STEAM_ID environment variable")
                print(f"{Fore.YELLOW}Find your 17-digit Steam ID at: https://steamid.io/")
                sys.exit(1)

            # Validate Steam ID format
            steam_id = config.get('steam_id', '')
            if not is_valid_steam_id(steam_id):
                print(f"{Fore.RED}Error: Invalid Steam ID format!")
                print(f"{Fore.YELLOW}Steam IDs should be 17-digit numbers starting with 7656119")
                print(f"{Fore.YELLOW}Find your Steam ID at: https://steamid.io/")
                print(f"{Fore.YELLOW}Your provided ID: {steam_id}")
                sys.exit(1)

            return config
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}Error parsing config file: {e}")
            sys.exit(1)

    def fetch_games(self) -> bool:
        """Fetch games from all configured platform libraries"""
        self.games = []
        total_games = 0

        # Fetch from each platform
        for platform_name, client in self.clients.items():
            user_id_key = f'{platform_name}_id' if platform_name != 'steam' else 'steam_id'
            user_id = self.config.get(user_id_key)

            if not user_id or is_placeholder_value(user_id):
                continue

            print(f"{Fore.CYAN}Fetching your {platform_name.title()} library...")
            try:
                games = client.get_owned_games(user_id)
                if games:
                    # Add composite game ID for multi-platform support
                    for game in games:
                        game_id = extract_game_id(game)
                        game['game_id'] = f"{platform_name}:{game_id}"
                        game['platform'] = platform_name
                        # Ensure appid exists for backward compatibility
                        if 'appid' not in game:
                            game['appid'] = game_id

                    self.games.extend(games)
                    print(f"{Fore.GREEN}Found {len(games)} games on {platform_name.title()}!")
                    total_games += len(games)
            except Exception as e:
                self._log.error("Error fetching games from %s: %s", platform_name, e)

        if not self.games:
            print(f"{Fore.RED}No games found or error fetching games from any platform.")
            return False

        print(f"{Fore.GREEN}Total: {total_games} games across all platforms!")
        return True
    
    def filter_games(self, min_playtime: int = 0, max_playtime: Optional[int] = None,
                     genres: Optional[List[str]] = None, exclude_genres: Optional[List[str]] = None,
                     favorites_only: bool = False,
                     min_metacritic: Optional[int] = None,
                     min_release_year: Optional[int] = None,
                     max_release_year: Optional[int] = None,
                     exclude_game_ids: Optional[List[str]] = None) -> List[Dict]:
        """Filter games based on various criteria

        Args:
            min_playtime: Minimum playtime in minutes
            max_playtime: Maximum playtime in minutes (None for no max)
            genres: List of genres to include (OR logic - game must have at least one)
            exclude_genres: List of genres to exclude (game must not have any of these)
            favorites_only: Only include favorite games
            min_metacritic: Minimum Metacritic score (0-100). Requires Steam details fetch.
            min_release_year: Earliest release year (inclusive)
            max_release_year: Latest release year (inclusive)
            exclude_game_ids: List of appids/game IDs to exclude from results

        Returns:
            List of filtered games
        """
        filtered = self.games

        # Filter by playtime
        if min_playtime > 0:
            filtered = [g for g in filtered if g.get('playtime_forever', 0) >= min_playtime]

        if max_playtime is not None:
            filtered = [g for g in filtered if g.get('playtime_forever', 0) <= max_playtime]

        # Filter by favorites
        if favorites_only:
            filtered = [g for g in filtered if g.get('game_id') in self.favorites]

        # Exclude specific games by app/game id
        if exclude_game_ids:
            exclude_set = {str(gid) for gid in exclude_game_ids}
            filtered = [
                g for g in filtered
                if str(g.get('appid', '')) not in exclude_set
                and str(g.get('game_id', '')) not in exclude_set
            ]

        # Filters that require fetching game details
        needs_details = bool(genres or exclude_genres or min_metacritic is not None
                             or min_release_year is not None or max_release_year is not None)

        if needs_details:
            genres_lower = [g.lower() for g in genres] if genres else []
            exclude_lower = [g.lower() for g in exclude_genres] if exclude_genres else []

            # Build list of (game, platform, game_id) for games that need details
            fetchable = []
            no_details = []
            for game in filtered:
                platform = game.get('platform', 'steam')
                game_id = extract_game_id(game)
                if game_id and platform in self.clients:
                    fetchable.append((game, platform, game_id))
                else:
                    no_details.append(game)

            # Fetch details in parallel (cache hits are instant, so threads just
            # fan out the network calls for games not yet cached)
            def _fetch(item: Tuple) -> Tuple:
                game, platform, game_id = item
                details = self.clients[platform].get_game_details(str(game_id))
                return game, details

            results: Dict[int, Tuple] = {}
            max_workers = min(len(fetchable), 16) if fetchable else 1
            with ThreadPoolExecutor(max_workers=max_workers,
                                    thread_name_prefix='gapi_filter') as executor:
                future_map = {executor.submit(_fetch, item): idx
                              for idx, item in enumerate(fetchable)}
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        results[idx] = future.result()
                    except Exception as exc:
                        self._log.debug("Detail fetch error: %s", exc)
                        results[idx] = (fetchable[idx][0], None)

            # Preserve original order then apply filters
            detail_filtered = []
            for idx in range(len(fetchable)):
                game, details = results.get(idx, (fetchable[idx][0], None))
                if details:
                    # --- Genre filter ---
                    if genres_lower or exclude_lower:
                        game_genres = [g['description'].lower()
                                       for g in details.get('genres', [])]
                        if exclude_lower and any(eg in game_genres for eg in exclude_lower):
                            continue
                        if genres_lower and not any(g in game_genres for g in genres_lower):
                            continue

                    # --- Metacritic filter ---
                    if min_metacritic is not None:
                        score = details.get('metacritic', {}).get('score')
                        if score is None or int(score) < min_metacritic:
                            continue

                    # --- Release year filter ---
                    if min_release_year is not None or max_release_year is not None:
                        raw_date = details.get('release_date', {}).get('date', '')
                        year = _parse_release_year(raw_date)
                        if year is None:
                            continue
                        if min_release_year is not None and year < min_release_year:
                            continue
                        if max_release_year is not None and year > max_release_year:
                            continue

                    detail_filtered.append(game)
                else:
                    # Details unavailable – include only when no positive filter set
                    if not genres_lower and min_metacritic is None \
                            and min_release_year is None and max_release_year is None:
                        if not exclude_lower:
                            detail_filtered.append(game)

            # Games without a client are included only when no positive filter is active
            if not genres_lower and min_metacritic is None \
                    and min_release_year is None and max_release_year is None \
                    and not exclude_lower:
                detail_filtered.extend(no_details)

            filtered = detail_filtered

        return filtered
    
    def pick_random_game(self, filtered_games: Optional[List[Dict]] = None, avoid_recent: bool = True) -> Optional[Dict]:
        """Pick a random game from the library"""
        games_to_pick = filtered_games if filtered_games is not None else self.games
        
        if not games_to_pick:
            return None
        
        # Try to avoid recently picked games if possible
        if avoid_recent and self.history and len(games_to_pick) > len(self.history):
            available = [g for g in games_to_pick if g.get('game_id') not in self.history[-10:]]
            if available:
                games_to_pick = available
        
        game = random.choice(games_to_pick)
        
        # Add to history using composite ID
        game_id = game.get('game_id')
        if game_id:
            if game_id in self.history:
                self.history.remove(game_id)
            self.history.append(game_id)
            self.save_history()
        
        return game
    
    def display_game_info(self, game: Dict, detailed: bool = True, show_favorite_prompt: bool = True):
        """Display information about a game"""
        game_id = game.get('game_id')
        app_id = game.get('appid')
        name = game.get('name', 'Unknown Game')
        platform = game.get('platform', 'steam')
        playtime_minutes = game.get('playtime_forever', 0)
        playtime_hours = minutes_to_hours(playtime_minutes)
        is_favorite = game_id in self.favorites if game_id else False
        
        print(f"\n{Fore.GREEN}{'='*60}")
        print(f"{Fore.CYAN}{Style.BRIGHT}🎮 {name}")
        if is_favorite:
            print(f"{Fore.YELLOW}⭐ FAVORITE")
        print(f"{Fore.GREEN}{'='*60}")
        print(f"{Fore.YELLOW}Platform: {Fore.WHITE}{platform.title()}")
        print(f"{Fore.YELLOW}Game ID: {Fore.WHITE}{app_id}")
        print(f"{Fore.YELLOW}Playtime: {Fore.WHITE}{playtime_hours:.1f} hours")
        
        if detailed and app_id and platform in self.clients:
            print(f"\n{Fore.CYAN}Fetching detailed information from {platform.title()} store...")
            details = self.clients[platform].get_game_details(str(app_id))
            
            if details:
                if 'short_description' in details:
                    print(f"\n{Fore.YELLOW}Description:")
                    print(f"{Fore.WHITE}{details['short_description']}")
                
                if 'genres' in details:
                    genres = [g['description'] for g in details['genres']]
                    print(f"\n{Fore.YELLOW}Genres: {Fore.WHITE}{', '.join(genres)}")
                
                if 'release_date' in details:
                    release = details['release_date'].get('date', 'Unknown')
                    print(f"{Fore.YELLOW}Release Date: {Fore.WHITE}{release}")
                
                if 'metacritic' in details:
                    score = details['metacritic'].get('score', 'N/A')
                    print(f"{Fore.YELLOW}Metacritic Score: {Fore.WHITE}{score}")
        
        # Platform-specific store links
        if platform == 'steam':
            print(f"\n{Fore.YELLOW}Steam Store: {Fore.WHITE}https://store.steampowered.com/app/{app_id}/")
            print(f"{Fore.YELLOW}SteamDB: {Fore.WHITE}https://steamdb.info/app/{app_id}/")
        elif platform == 'epic':
            print(f"\n{Fore.YELLOW}Epic Store: {Fore.WHITE}https://store.epicgames.com/")
        elif platform == 'gog':
            print(f"\n{Fore.YELLOW}GOG Store: {Fore.WHITE}https://www.gog.com/")
        
        print(f"{Fore.GREEN}{'='*60}\n")
        
        # Prompt to add/remove from favorites in interactive mode
        if show_favorite_prompt and game_id:
            if is_favorite:
                choice = input(f"{Fore.YELLOW}Remove from favorites? (y/n): {Fore.WHITE}").strip().lower()
                if choice == 'y':
                    self.remove_favorite(game_id)
                    print(f"{Fore.GREEN}Removed from favorites!")
            else:
                choice = input(f"{Fore.YELLOW}Add to favorites? (y/n): {Fore.WHITE}").strip().lower()
                if choice == 'y':
                    self.add_favorite(game_id)
                    print(f"{Fore.GREEN}Added to favorites!")
    
    def interactive_mode(self):
        """Run in interactive mode"""
        if not self.fetch_games():
            return
        
        while True:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}GAPI - Game Picker")
            print(f"{Fore.WHITE}{'='*40}")
            print(f"{Fore.YELLOW}1. {Fore.WHITE}Pick a random game")
            print(f"{Fore.YELLOW}2. {Fore.WHITE}Pick from unplayed games")
            print(f"{Fore.YELLOW}3. {Fore.WHITE}Pick from barely played games (< 2 hours)")
            print(f"{Fore.YELLOW}4. {Fore.WHITE}Pick from well-played games (> 10 hours)")
            print(f"{Fore.YELLOW}5. {Fore.WHITE}Pick by genre/tag")
            print(f"{Fore.YELLOW}6. {Fore.WHITE}Pick from favorites")
            print(f"{Fore.YELLOW}7. {Fore.WHITE}Show library stats")
            print(f"{Fore.YELLOW}8. {Fore.WHITE}Manage favorites")
            print(f"{Fore.YELLOW}9. {Fore.WHITE}Export/Import history")
            print(f"{Fore.YELLOW}q. {Fore.WHITE}Quit")
            print(f"{Fore.WHITE}{'='*40}")
            
            choice = input(f"\n{Fore.GREEN}Enter your choice: {Fore.WHITE}").strip().lower()
            
            if choice == 'q':
                print(f"\n{Fore.CYAN}Thanks for using GAPI! Happy gaming! 🎮")
                break
            elif choice == '1':
                game = self.pick_random_game()
                if game:
                    self.display_game_info(game)
            elif choice == '2':
                filtered = self.filter_games(max_playtime=0)
                if filtered:
                    print(f"{Fore.GREEN}Found {len(filtered)} unplayed games.")
                    game = self.pick_random_game(filtered)
                    if game:
                        self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No unplayed games found!")
            elif choice == '3':
                filtered = self.filter_games(max_playtime=self.BARELY_PLAYED_THRESHOLD_MINUTES)
                if filtered:
                    print(f"{Fore.GREEN}Found {len(filtered)} barely played games.")
                    game = self.pick_random_game(filtered)
                    if game:
                        self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No barely played games found!")
            elif choice == '4':
                filtered = self.filter_games(min_playtime=self.WELL_PLAYED_THRESHOLD_MINUTES)
                if filtered:
                    print(f"{Fore.GREEN}Found {len(filtered)} well-played games.")
                    game = self.pick_random_game(filtered)
                    if game:
                        self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No well-played games found!")
            elif choice == '5':
                self.pick_by_genre()
            elif choice == '6':
                self.pick_from_favorites()
            elif choice == '7':
                self.show_stats()
            elif choice == '8':
                self.manage_favorites_menu()
            elif choice == '9':
                self.export_import_menu()
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.")
    
    def show_stats(self):
        """Display library statistics"""
        if not self.games:
            print(f"{Fore.RED}No games loaded.")
            return
        
        total_games = len(self.games)
        unplayed = len([g for g in self.games if g.get('playtime_forever', 0) == 0])
        total_playtime = minutes_to_hours(sum(g.get('playtime_forever', 0) for g in self.games))
        
        print(f"\n{Fore.CYAN}{Style.BRIGHT}📊 Library Statistics")
        print(f"{Fore.GREEN}{'='*40}")
        print(f"{Fore.YELLOW}Total Games: {Fore.WHITE}{total_games}")
        print(f"{Fore.YELLOW}Unplayed Games: {Fore.WHITE}{unplayed} ({unplayed/total_games*100:.1f}%)")
        print(f"{Fore.YELLOW}Played Games: {Fore.WHITE}{total_games - unplayed}")
        print(f"{Fore.YELLOW}Total Playtime: {Fore.WHITE}{total_playtime:.1f} hours")
        print(f"{Fore.YELLOW}Average Playtime: {Fore.WHITE}{total_playtime/total_games:.1f} hours per game")
        print(f"{Fore.YELLOW}Favorite Games: {Fore.WHITE}{len(self.favorites)}")
        print(f"{Fore.GREEN}{'='*40}\n")
    
    def pick_by_genre(self):
        """Interactive genre selection and game picking"""
        genre_input = input(f"\n{Fore.GREEN}Enter genre(s) separated by commas (e.g., Action, RPG): {Fore.WHITE}").strip()
        
        if not genre_input:
            print(f"{Fore.YELLOW}No genre specified.")
            return
        
        genres = [g.strip() for g in genre_input.split(',')]
        print(f"\n{Fore.CYAN}Searching for games with genres: {', '.join(genres)}...")
        print(f"{Fore.YELLOW}This may take a moment as we fetch game details...")
        
        filtered = self.filter_games(genres=genres)
        
        if filtered:
            print(f"{Fore.GREEN}Found {len(filtered)} games matching the genre(s).")
            game = self.pick_random_game(filtered)
            if game:
                self.display_game_info(game)
        else:
            print(f"{Fore.YELLOW}No games found with the specified genre(s)!")
    
    def pick_from_favorites(self):
        """Pick a random game from favorites"""
        if not self.favorites:
            print(f"{Fore.YELLOW}No favorite games yet! Add some favorites first.")
            return
        
        filtered = self.filter_games(favorites_only=True)
        
        if filtered:
            print(f"{Fore.GREEN}Picking from {len(filtered)} favorite games...")
            # Still avoid recent picks to provide variety
            game = self.pick_random_game(filtered, avoid_recent=True)
            if game:
                self.display_game_info(game)
        else:
            print(f"{Fore.YELLOW}None of your favorite games are in your library anymore.")
    
    def manage_favorites_menu(self):
        """Manage favorite games"""
        while True:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}Manage Favorites")
            print(f"{Fore.WHITE}{'='*40}")
            print(f"{Fore.YELLOW}1. {Fore.WHITE}List all favorites")
            print(f"{Fore.YELLOW}2. {Fore.WHITE}Remove a favorite")
            print(f"{Fore.YELLOW}3. {Fore.WHITE}Clear all favorites")
            print(f"{Fore.YELLOW}b. {Fore.WHITE}Back to main menu")
            print(f"{Fore.WHITE}{'='*40}")
            
            choice = input(f"\n{Fore.GREEN}Enter your choice: {Fore.WHITE}").strip().lower()
            
            if choice == 'b':
                break
            elif choice == '1':
                self.list_favorites()
            elif choice == '2':
                self.remove_favorite_interactive()
            elif choice == '3':
                confirm = input(f"{Fore.RED}Clear all favorites? (y/n): {Fore.WHITE}").strip().lower()
                if confirm == 'y':
                    self.favorites = []
                    self.save_favorites()
                    print(f"{Fore.GREEN}All favorites cleared!")
            else:
                print(f"{Fore.RED}Invalid choice.")
    
    def list_favorites(self):
        """List all favorite games"""
        if not self.favorites:
            print(f"\n{Fore.YELLOW}No favorite games yet!")
            return
        
        print(f"\n{Fore.CYAN}{Style.BRIGHT}⭐ Your Favorite Games ({len(self.favorites)})")
        print(f"{Fore.GREEN}{'='*60}")
        
        for game_id in self.favorites:
            game = next((g for g in self.games if g.get('game_id') == game_id), None)
            if game:
                name = game.get('name', 'Unknown')
                platform = game.get('platform', 'unknown')
                playtime = minutes_to_hours(game.get('playtime_forever', 0))
                print(f"{Fore.YELLOW}{game_id}: {Fore.WHITE}{name} {Fore.MAGENTA}[{platform}] {Fore.CYAN}({playtime:.1f} hours)")
            else:
                print(f"{Fore.YELLOW}{game_id}: {Fore.RED}(Not in library)")
        
        print(f"{Fore.GREEN}{'='*60}\n")
    
    def remove_favorite_interactive(self):
        """Remove a favorite game interactively"""
        if not self.favorites:
            print(f"{Fore.YELLOW}No favorites to remove.")
            return
        
        self.list_favorites()
        game_id_str = input(f"\n{Fore.GREEN}Enter Game ID to remove: {Fore.WHITE}").strip()
        
        if self.remove_favorite(game_id_str):
            print(f"{Fore.GREEN}Removed from favorites!")
        else:
            print(f"{Fore.YELLOW}Game not found in favorites.")
    
    def export_import_menu(self):
        """Export/Import history menu"""
        while True:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}Export/Import")
            print(f"{Fore.WHITE}{'='*40}")
            print(f"{Fore.YELLOW}1. {Fore.WHITE}Export history")
            print(f"{Fore.YELLOW}2. {Fore.WHITE}Import history")
            print(f"{Fore.YELLOW}b. {Fore.WHITE}Back to main menu")
            print(f"{Fore.WHITE}{'='*40}")
            
            choice = input(f"\n{Fore.GREEN}Enter your choice: {Fore.WHITE}").strip().lower()
            
            if choice == 'b':
                break
            elif choice == '1':
                filepath = input(f"{Fore.GREEN}Enter export file path (default: history_export.json): {Fore.WHITE}").strip()
                if not filepath:
                    filepath = 'history_export.json'
                self.export_history(filepath)
            elif choice == '2':
                filepath = input(f"{Fore.GREEN}Enter import file path: {Fore.WHITE}").strip()
                if filepath:
                    self.import_history(filepath)
                else:
                    print(f"{Fore.YELLOW}No file path specified.")
            else:
                print(f"{Fore.RED}Invalid choice.")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='GAPI - Game Picker with SteamDB Integration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 gapi.py                    # Run in interactive mode
  python3 gapi.py --random           # Pick a random game and exit
  python3 gapi.py --unplayed         # Pick from unplayed games
  python3 gapi.py --barely-played    # Pick from barely played games (< 2 hours)
  python3 gapi.py --stats            # Show library statistics only
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        default='config.json',
        help='Path to config file (default: config.json)'
    )
    parser.add_argument(
        '--random', '-r',
        action='store_true',
        help='Pick a random game and exit (non-interactive)'
    )
    parser.add_argument(
        '--unplayed', '-u',
        action='store_true',
        help='Pick from unplayed games only'
    )
    parser.add_argument(
        '--barely-played', '-b',
        action='store_true',
        help='Pick from barely played games (< 2 hours)'
    )
    parser.add_argument(
        '--well-played', '-w',
        action='store_true',
        help='Pick from well-played games (> 10 hours)'
    )
    parser.add_argument(
        '--min-hours',
        type=float,
        help='Minimum playtime in hours (must be non-negative)'
    )
    parser.add_argument(
        '--max-hours',
        type=float,
        help='Maximum playtime in hours (must be non-negative)'
    )
    parser.add_argument(
        '--stats', '-s',
        action='store_true',
        help='Show library statistics and exit'
    )
    parser.add_argument(
        '--no-details',
        action='store_true',
        help='Skip fetching detailed game information'
    )
    parser.add_argument(
        '--genre',
        type=str,
        help='Filter by genre(s), comma-separated (e.g., "Action,RPG")'
    )
    parser.add_argument(
        '--exclude-genre',
        type=str,
        help='Exclude games with these genre(s), comma-separated (e.g., "Horror,Puzzle")'
    )
    parser.add_argument(
        '--favorites',
        action='store_true',
        help='Pick from favorite games only'
    )
    parser.add_argument(
        '--export-history',
        type=str,
        metavar='FILE',
        help='Export game history to a file'
    )
    parser.add_argument(
        '--import-history',
        type=str,
        metavar='FILE',
        help='Import game history from a file'
    )
    parser.add_argument(
        '--list-favorites',
        action='store_true',
        help='List all favorite games and exit'
    )
    parser.add_argument(
        '--count',
        type=int,
        default=1,
        metavar='N',
        help='Number of games to pick (default: 1, max: 10)'
    )
    parser.add_argument(
        '--min-score',
        type=int,
        metavar='SCORE',
        help='Minimum Metacritic score (0-100). Requires fetching game details.'
    )
    parser.add_argument(
        '--min-year',
        type=int,
        metavar='YEAR',
        help='Earliest release year to include (e.g., 2015)'
    )
    parser.add_argument(
        '--max-year',
        type=int,
        metavar='YEAR',
        help='Latest release year to include (e.g., 2023)'
    )
    parser.add_argument(
        '--exclude-game',
        type=str,
        metavar='ID',
        help='Comma-separated app IDs or game IDs to exclude (e.g., "730,570")'
    )
    
    args = parser.parse_args()
    
    print(f"{Fore.CYAN}{Style.BRIGHT}")
    print("  ____    _    ____ ___ ")
    print(" / ___|  / \\  |  _ \\_ _|")
    print("| |  _  / _ \\ | |_) | | ")
    print("| |_| |/ ___ \\|  __/| | ")
    print(" \\____/_/   \\_\\_|  |___|")
    print(f"{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Game Picker with SteamDB Integration\n")
    
    try:
        picker = GamePicker(config_path=args.config)
        
        # Validate hour arguments
        if args.min_hours is not None and args.min_hours < 0:
            print(f"{Fore.RED}Error: --min-hours must be non-negative")
            sys.exit(1)
        if args.max_hours is not None and args.max_hours < 0:
            print(f"{Fore.RED}Error: --max-hours must be non-negative")
            sys.exit(1)
        
        # Validate count argument
        if args.count < 1:
            print(f"{Fore.RED}Error: --count must be at least 1")
            sys.exit(1)
        if args.count > 10:
            print(f"{Fore.RED}Error: --count cannot exceed 10 (to avoid overwhelming output)")
            sys.exit(1)
        
        # Handle export/import operations
        if args.export_history:
            if not picker.fetch_games():
                sys.exit(1)
            picker.export_history(args.export_history)
            return
        
        if args.import_history:
            picker.import_history(args.import_history)
            return
        
        if args.list_favorites:
            if not picker.fetch_games():
                sys.exit(1)
            picker.list_favorites()
            return
        
        # Parse genres if provided
        genres = None
        if args.genre:
            genres = [g.strip() for g in args.genre.split(',')]

        exclude_genres = None
        if args.exclude_genre:
            exclude_genres = [g.strip() for g in args.exclude_genre.split(',')]

        exclude_game_ids = None
        if args.exclude_game:
            exclude_game_ids = [gid.strip() for gid in args.exclude_game.split(',')]

        # Show detail-fetch warning early
        needs_details = bool(genres or exclude_genres or args.min_score is not None
                             or args.min_year is not None or args.max_year is not None)
        if needs_details:
            print(f"{Fore.YELLOW}Note: Advanced filtering may take a moment as we fetch game details...")

        # Common advanced filter kwargs
        adv_kwargs = {
            'genres': genres,
            'exclude_genres': exclude_genres,
            'min_metacritic': args.min_score,
            'min_release_year': args.min_year,
            'max_release_year': args.max_year,
            'exclude_game_ids': exclude_game_ids,
        }

        # Non-interactive modes
        if (args.stats or args.random or args.unplayed or args.barely_played or args.well_played
                or args.min_hours is not None or args.max_hours is not None or args.favorites
                or needs_details or exclude_game_ids):
            if not picker.fetch_games():
                sys.exit(1)

            if args.stats:
                picker.show_stats()
                return

            # Determine which filter to use
            filtered_games = None

            if args.favorites:
                filtered_games = picker.filter_games(favorites_only=True, **adv_kwargs)
                print(f"{Fore.GREEN}Filtering to favorite games...")
            elif args.unplayed:
                filtered_games = picker.filter_games(max_playtime=0, **adv_kwargs)
                print(f"{Fore.GREEN}Filtering to unplayed games...")
            elif args.barely_played:
                filtered_games = picker.filter_games(
                    max_playtime=picker.BARELY_PLAYED_THRESHOLD_MINUTES, **adv_kwargs)
                barely_played_hours = minutes_to_hours(picker.BARELY_PLAYED_THRESHOLD_MINUTES)
                print(f"{Fore.GREEN}Filtering to barely played games (< {barely_played_hours} hours)...")
            elif args.well_played:
                filtered_games = picker.filter_games(
                    min_playtime=picker.WELL_PLAYED_THRESHOLD_MINUTES, **adv_kwargs)
                well_played_hours = minutes_to_hours(picker.WELL_PLAYED_THRESHOLD_MINUTES)
                print(f"{Fore.GREEN}Filtering to well-played games (> {well_played_hours} hours)...")
            elif args.min_hours is not None or args.max_hours is not None:
                min_minutes = int(args.min_hours * 60) if args.min_hours is not None else 0
                max_minutes = int(args.max_hours * 60) if args.max_hours is not None else None
                filtered_games = picker.filter_games(
                    min_playtime=min_minutes, max_playtime=max_minutes, **adv_kwargs)
                filter_desc = []
                if args.min_hours is not None:
                    filter_desc.append(f">= {args.min_hours} hours")
                if args.max_hours is not None:
                    filter_desc.append(f"<= {args.max_hours} hours")
                print(f"{Fore.GREEN}Filtering to games with {' and '.join(filter_desc)}...")
            elif needs_details or exclude_game_ids:
                filtered_games = picker.filter_games(**adv_kwargs)
                if genres:
                    print(f"{Fore.GREEN}Filtering to games with genres: {', '.join(genres)}...")
                if exclude_genres:
                    print(f"{Fore.GREEN}Excluding games with genres: {', '.join(exclude_genres)}...")
                if args.min_score is not None:
                    print(f"{Fore.GREEN}Filtering to games with Metacritic score >= {args.min_score}...")
                if args.min_year is not None or args.max_year is not None:
                    yr_desc = []
                    if args.min_year:
                        yr_desc.append(f">= {args.min_year}")
                    if args.max_year:
                        yr_desc.append(f"<= {args.max_year}")
                    print(f"{Fore.GREEN}Filtering by release year: {' and '.join(yr_desc)}...")
            
            if filtered_games is not None and not filtered_games:
                print(f"{Fore.RED}No games found matching the filter criteria.")
                sys.exit(1)
            
            # Pick multiple games if count > 1
            if args.count == 1:
                game = picker.pick_random_game(filtered_games)
                if game:
                    picker.display_game_info(game, detailed=not args.no_details, show_favorite_prompt=False)
                else:
                    print(f"{Fore.RED}No games available to pick from.")
                    sys.exit(1)
            else:
                # Pick multiple games
                games_pool = filtered_games if filtered_games is not None else picker.games
                if len(games_pool) < args.count:
                    print(f"{Fore.YELLOW}Warning: Only {len(games_pool)} games available, picking all of them.")
                    count_to_pick = len(games_pool)
                else:
                    count_to_pick = args.count
                
                print(f"{Fore.CYAN}Picking {count_to_pick} games...\n")
                picked_games = []
                
                for i in range(count_to_pick):
                    game = picker.pick_random_game(games_pool, avoid_recent=True)
                    if game:
                        picked_games.append(game)
                        # Add to history to avoid in next picks
                        game_id = game.get('game_id')
                        if game_id and game_id not in picker.history:
                            picker.history.append(game_id)
                        # Remove from pool to avoid duplicate picks
                        games_pool = [g for g in games_pool if g.get('game_id') != game_id]
                
                # Display all picked games
                for i, game in enumerate(picked_games, 1):
                    print(f"\n{Fore.MAGENTA}{'='*60}")
                    print(f"{Fore.MAGENTA}Game {i} of {count_to_pick}")
                    print(f"{Fore.MAGENTA}{'='*60}")
                    picker.display_game_info(game, detailed=not args.no_details, show_favorite_prompt=False)
                
                if picked_games:
                    picker.save_history()
                    print(f"\n{Fore.GREEN}✅ Successfully picked {len(picked_games)} games!")
                else:
                    print(f"{Fore.RED}No games available to pick from.")
                    sys.exit(1)
        else:
            # Interactive mode
            picker.interactive_mode()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n{Fore.RED}An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
