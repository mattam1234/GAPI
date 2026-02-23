#!/usr/bin/env python3
"""
Multi-User Game Picker Module
Handles multiple Steam accounts and finding common games for co-op play.
"""

import json
import logging
import os
import random
import uuid
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple
from collections import Counter
import gapi

logger = logging.getLogger('gapi.multiuser')


class VotingSession:
    """Manages a multi-user voting session for picking a game"""

    def __init__(self, session_id: str, candidates: List[Dict],
                 voters: Optional[List[str]] = None,
                 duration: Optional[int] = None):
        """
        Initialize a voting session.

        Args:
            session_id: Unique identifier for this session
            candidates: List of game dicts that users can vote for
            voters: Optional list of eligible voter names. If None, any user may vote.
            duration: Optional voting duration in seconds. If None, session stays open
                      until explicitly closed.
        """
        self.session_id = session_id
        self.candidates: List[Dict] = candidates
        self.votes: Dict[str, str] = {}   # user_name -> app_id
        self.voters: Set[str] = set(voters) if voters else set()
        self.created_at: datetime = datetime.now()
        self.duration: Optional[int] = duration
        self.closed: bool = False

    def cast_vote(self, user_name: str, app_id: str) -> Tuple[bool, str]:
        """Cast a vote for a game.

        Args:
            user_name: Name of the voter
            app_id: App ID of the game being voted for

        Returns:
            (success, message) tuple
        """
        if self.closed:
            return False, "Voting session is closed"
        if self.is_expired():
            self.closed = True
            return False, "Voting session has expired"
        if self.voters and user_name not in self.voters:
            return False, f"User '{user_name}' is not eligible to vote in this session"
        # Validate app_id is a valid candidate
        candidate_ids = {str(c.get('appid') or c.get('app_id') or c.get('game_id', ''))
                         for c in self.candidates}
        if str(app_id) not in candidate_ids:
            return False, f"Game ID '{app_id}' is not a candidate in this session"
        self.votes[user_name] = str(app_id)
        return True, "Vote cast successfully"

    def get_results(self) -> Dict[str, Dict]:
        """Get vote tallies for all candidates.

        Returns:
            Dict mapping app_id -> {'game': dict, 'count': int, 'voters': list}
        """
        tallies: Dict[str, Dict] = {}
        for candidate in self.candidates:
            app_id = str(candidate.get('appid') or candidate.get('app_id')
                         or candidate.get('game_id', ''))
            tallies[app_id] = {
                'game': candidate,
                'count': 0,
                'voters': []
            }
        for user, voted_id in self.votes.items():
            if voted_id in tallies:
                tallies[voted_id]['count'] += 1
                tallies[voted_id]['voters'].append(user)
        return tallies

    def get_winner(self) -> Optional[Dict]:
        """Determine the winning game.

        In case of a tie the winner is chosen randomly from the tied games.
        If nobody voted, a random candidate is returned.

        Returns:
            The winning game dict, or None if there are no candidates.
        """
        if not self.candidates:
            return None
        tallies = self.get_results()
        if not tallies:
            return None
        max_votes = max(t['count'] for t in tallies.values())
        if max_votes == 0:
            # Nobody voted – pick randomly
            return random.choice(self.candidates)
        tied = [app_id for app_id, t in tallies.items() if t['count'] == max_votes]
        winner_id = random.choice(tied)
        return tallies[winner_id]['game']

    def is_expired(self) -> bool:
        """Return True if a timed session has exceeded its duration."""
        if self.duration is None:
            return False
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed >= self.duration

    def close(self):
        """Close the voting session."""
        self.closed = True

    def to_dict(self) -> Dict:
        """Serialise session state for API responses."""
        tallies = self.get_results()
        return {
            'session_id': self.session_id,
            'closed': self.closed or self.is_expired(),
            'candidates': [
                {
                    'app_id': str(c.get('appid') or c.get('app_id') or c.get('game_id', '')),
                    'name': c.get('name', 'Unknown'),
                    'playtime_hours': round(c.get('playtime_forever', 0) / 60, 1),
                }
                for c in self.candidates
            ],
            'vote_counts': {
                app_id: {'count': t['count'], 'voters': t['voters']}
                for app_id, t in tallies.items()
            },
            'total_votes': len(self.votes),
            'eligible_voters': sorted(self.voters),
            'duration': self.duration,
            'created_at': self.created_at.isoformat(),
        }


class MultiUserPicker:
    """Handles game picking for multiple users across multiple platforms"""
    
    USERS_FILE = 'users.json'
    
    def __init__(self, config: Dict, users_file: str = None):
        self.config = config
        self.users_file = users_file or self.USERS_FILE
        self.users: List[Dict] = []

        # Active voting sessions keyed by session_id
        self.voting_sessions: Dict[str, VotingSession] = {}

        # Initialize platform clients
        self.clients: Dict[str, gapi.GamePlatformClient] = {}
        
        # Initialize Steam client
        if config.get('steam_api_key') and config['steam_api_key'] != 'YOUR_STEAM_API_KEY_HERE':
            self.clients['steam'] = gapi.SteamAPIClient(config['steam_api_key'])
        
        # Initialize Epic client if enabled
        if config.get('epic_enabled', False):
            try:
                self.clients['epic'] = gapi.EpicAPIClient()
            except Exception:
                pass
        
        # Initialize GOG client if enabled
        if config.get('gog_enabled', False):
            try:
                self.clients['gog'] = gapi.GOGAPIClient()
            except Exception:
                pass
        
        # For backward compatibility
        self.steam_client = self.clients.get('steam')
        self.steam_api_key = config.get('steam_api_key')
        
        if os.path.exists(self.users_file):
            self.load_users()
    
    def load_users(self):
        """Load users from configuration file"""
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
                self.users = data.get('users', [])

                # Convert old format to new format with platforms
                for user in self.users:
                    if 'steam_id' in user and 'platforms' not in user:
                        user['platforms'] = {
                            'steam': user['steam_id'],
                            'epic': '',
                            'gog': ''
                        }
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Error loading users: %s", e)
            self.users = []

    def save_users(self):
        """Save users to configuration file (atomic write)"""
        try:
            gapi._atomic_write_json(self.users_file, {'users': self.users})
        except IOError as e:
            logger.error("Error saving users: %s", e)

    def add_user(self, name: str, steam_id: str = "", email: str = "", discord_id: str = "",
                 epic_id: str = "", gog_id: str = "", **kwargs) -> bool:
        """Add a new user with platform information"""
        # Check if user already exists by name or discord_id
        for user in self.users:
            if user.get('name') == name:
                logger.warning("User with name %s already exists", name)
                return False
            if discord_id and user.get('discord_id') == discord_id:
                logger.warning("User with Discord ID %s already exists", discord_id)
                return False
        
        user_data = {
            'name': name,
            'email': email,
            'discord_id': discord_id,
            'platforms': {
                'steam': steam_id,
                'epic': epic_id,
                'gog': gog_id
            }
        }
        
        # Add any additional fields passed via kwargs
        user_data.update(kwargs)
        
        self.users.append(user_data)
        self.save_users()
        return True
    
    def update_user(self, identifier: str, **updates) -> bool:
        """Update user information by name or discord_id"""
        user_found = False
        for user in self.users:
            # Support backward compatibility for steam_id
            steam_id = user.get('platforms', {}).get('steam', '') if 'platforms' in user else user.get('steam_id', '')
            
            if (user.get('name') == identifier or 
                steam_id == identifier or 
                user.get('discord_id') == identifier):
                user.update(updates)
                user_found = True
                break
        
        if user_found:
            self.save_users()
            return True
        return False
    
    def remove_user(self, name: str) -> bool:
        """Remove a user by name"""
        original_count = len(self.users)
        self.users = [u for u in self.users if u['name'] != name]
        
        if len(self.users) < original_count:
            self.save_users()
            return True
        return False
    
    def get_user_libraries(self, user_names: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """
        Fetch game libraries for specified users from all platforms
        Returns dict mapping user names to their game lists
        """
        users_to_fetch = self.users
        if user_names:
            users_to_fetch = [u for u in self.users if u['name'] in user_names]
        
        libraries = {}
        for user in users_to_fetch:
            all_games = []
            
            # Get platforms for this user (support both old and new format)
            platforms = user.get('platforms', {})
            if not platforms and 'steam_id' in user:
                # Old format - convert to new format
                platforms = {'steam': user['steam_id']}
            
            # Fetch games from each platform
            for platform_name, user_id in platforms.items():
                if not user_id or gapi.is_placeholder_value(user_id):
                    continue
                
                if platform_name in self.clients:
                    try:
                        games = self.clients[platform_name].get_owned_games(user_id)
                        if games:
                            # Add composite game ID and platform info
                            for game in games:
                                game_id = gapi.extract_game_id(game)
                                game['game_id'] = f"{platform_name}:{game_id}"
                                game['platform'] = platform_name
                                if 'appid' not in game:
                                    game['appid'] = game_id
                            all_games.extend(games)
                            logger.info("Loaded %d games from %s for %s",
                                        len(games), platform_name, user['name'])
                    except Exception as e:
                        logger.error("Error fetching %s games for %s: %s",
                                     platform_name, user['name'], e)
            
            if all_games:
                libraries[user['name']] = all_games
        
        return libraries
    
    def find_common_games(self, user_names: Optional[List[str]] = None) -> List[Dict]:
        """
        Find games that all specified users own (supports multi-platform)
        Returns list of games with aggregated info
        """
        libraries = self.get_user_libraries(user_names)
        
        if not libraries:
            return []
        
        if len(libraries) == 1:
            # Only one user, return their entire library
            return list(libraries.values())[0]
        
        # Find common game IDs across all users (using composite game_id)
        game_id_sets = []
        game_map = {}  # Map game_id to game info
        
        for user_name, games in libraries.items():
            user_game_ids = set()
            for game in games:
                game_id = game.get('game_id')
                if game_id:
                    user_game_ids.add(game_id)
                    # Store game info (prefer info with more playtime)
                    if game_id not in game_map or game.get('playtime_forever', 0) > game_map[game_id].get('playtime_forever', 0):
                        game_map[game_id] = game.copy()
                        game_map[game_id]['owners'] = []
                    game_map[game_id]['owners'].append(user_name)
            
            game_id_sets.append(user_game_ids)
        
        # Find intersection of all sets
        common_game_ids = set.intersection(*game_id_sets) if game_id_sets else set()
        
        # Build result list with common games
        common_games = []
        for game_id in common_game_ids:
            game = game_map[game_id]
            game['total_owners'] = len(game['owners'])
            common_games.append(game)
        
        return common_games
    
    def filter_coop_games(self, games: List[Dict], max_players: int = None) -> List[Dict]:
        """
        Filter games to only include co-op/multiplayer games
        Optionally filter by maximum player count
        """
        coop_games = []
        
        for game in games:
            app_id = gapi.extract_game_id(game)
            platform = game.get('platform', 'steam')
            
            if not app_id or platform not in self.clients:
                continue
            
            # Fetch detailed info to check for multiplayer
            details = self.clients[platform].get_game_details(str(app_id))
            
            if not details:
                continue
            
            # Check categories for multiplayer/coop indicators
            categories = details.get('categories', [])
            is_multiplayer = False
            is_coop = False
            
            for category in categories:
                cat_desc = category.get('description', '').lower()
                if 'multi-player' in cat_desc or 'multiplayer' in cat_desc:
                    is_multiplayer = True
                if 'co-op' in cat_desc or 'cooperative' in cat_desc:
                    is_coop = True
            
            # If max_players specified, try to check if game supports that many
            if max_players and is_multiplayer:
                # This is a simplified check - Steam API doesn't always provide exact player counts
                # We'll include the game if it's multiplayer
                game['is_coop'] = is_coop
                game['is_multiplayer'] = is_multiplayer
                coop_games.append(game)
            elif is_coop or is_multiplayer:
                game['is_coop'] = is_coop
                game['is_multiplayer'] = is_multiplayer
                coop_games.append(game)
        
        return coop_games
    
    def pick_common_game(self, user_names: Optional[List[str]] = None, 
                        coop_only: bool = False, 
                        max_players: int = None) -> Optional[Dict]:
        """
        Pick a random game from the common library
        """
        common_games = self.find_common_games(user_names)
        
        if not common_games:
            return None
        
        if coop_only:
            common_games = self.filter_coop_games(common_games, max_players)
        
        if not common_games:
            return None

        return random.choice(common_games)
    
    def get_library_stats(self, user_names: Optional[List[str]] = None) -> Dict:
        """Get statistics about user libraries"""
        libraries = self.get_user_libraries(user_names)
        
        if not libraries:
            return {}
        
        total_games_per_user = {name: len(games) for name, games in libraries.items()}
        common_games = self.find_common_games(user_names)
        
        return {
            'users': list(libraries.keys()),
            'total_games_per_user': total_games_per_user,
            'common_games_count': len(common_games),
            'total_unique_games': len(set(
                game.get('appid')
                for games in libraries.values()
                for game in games
                if game.get('appid')
            ))
        }

    # ------------------------------------------------------------------
    # Voting session management
    # ------------------------------------------------------------------

    def create_voting_session(self, candidates: List[Dict],
                              voters: Optional[List[str]] = None,
                              duration: Optional[int] = None) -> VotingSession:
        """Create a new voting session.

        Args:
            candidates: List of game dicts that users can vote for.
            voters: Optional list of eligible voter names. If None, any name is accepted.
            duration: Optional voting window in seconds.

        Returns:
            The newly created VotingSession.
        """
        session_id = str(uuid.uuid4())
        session = VotingSession(session_id, candidates, voters=voters, duration=duration)
        self.voting_sessions[session_id] = session
        return session

    def get_voting_session(self, session_id: str) -> Optional[VotingSession]:
        """Return an active voting session by ID, or None if not found."""
        return self.voting_sessions.get(session_id)

    def close_voting_session(self, session_id: str) -> Optional[Dict]:
        """Close a voting session and return the winning game.

        Args:
            session_id: ID of the session to close.

        Returns:
            The winning game dict, or None if session not found / no candidates.
        """
        session = self.voting_sessions.get(session_id)
        if session is None:
            return None
        session.close()
        return session.get_winner()
