#!/usr/bin/env python3
"""
GAPI - Game Picker with SteamDB Integration
A tool to randomly pick a game from your Steam library with detailed information.
"""

import json
import os
import sys
import random
import argparse
from typing import Dict, List, Optional
import requests
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored terminal output
init(autoreset=True)


class SteamAPIClient:
    """Client for interacting with Steam Web API"""
    
    BASE_URL = "https://api.steampowered.com"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
    
    def get_owned_games(self, steam_id: str, include_appinfo: bool = True) -> List[Dict]:
        """Get list of games owned by a Steam user"""
        url = f"{self.BASE_URL}/IPlayerService/GetOwnedGames/v0001/"
        params = {
            'key': self.api_key,
            'steamid': steam_id,
            'include_appinfo': 1 if include_appinfo else 0,
            'include_played_free_games': 1,
            'format': 'json'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'response' in data and 'games' in data['response']:
                return data['response']['games']
            return []
        except requests.RequestException as e:
            print(f"{Fore.RED}Error fetching games from Steam API: {e}")
            return []
    
    def get_game_details(self, app_id: int) -> Optional[Dict]:
        """Get detailed information about a specific game"""
        url = "https://store.steampowered.com/api/appdetails"
        params = {'appids': app_id}
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if str(app_id) in data and data[str(app_id)]['success']:
                return data[str(app_id)]['data']
            return None
        except requests.RequestException as e:
            print(f"{Fore.YELLOW}Warning: Could not fetch details for app {app_id}: {e}")
            return None


class GamePicker:
    """Main game picker application"""
    
    HISTORY_FILE = '.gapi_history.json'
    MAX_HISTORY = 20
    BARELY_PLAYED_THRESHOLD_MINUTES = 120  # 2 hours
    WELL_PLAYED_THRESHOLD_MINUTES = 600    # 10 hours
    
    def __init__(self, config_path: str = 'config.json'):
        self.config = self.load_config(config_path)
        self.steam_client = SteamAPIClient(self.config['steam_api_key'])
        self.games: List[Dict] = []
        self.history: List[int] = self.load_history()
    
    def load_history(self) -> List[int]:
        """Load game picking history"""
        if os.path.exists(self.HISTORY_FILE):
            try:
                with open(self.HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []
    
    def save_history(self):
        """Save game picking history"""
        try:
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(self.history[-self.MAX_HISTORY:], f)
        except IOError:
            pass  # Silently fail if we can't save history
    
    def load_config(self, config_path: str) -> Dict:
        """Load configuration from JSON file"""
        if not os.path.exists(config_path):
            print(f"{Fore.RED}Error: Config file '{config_path}' not found!")
            print(f"{Fore.YELLOW}Please copy 'config_template.json' to 'config.json' and add your Steam API key and ID.")
            sys.exit(1)
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            if config.get('steam_api_key') == 'YOUR_STEAM_API_KEY_HERE':
                print(f"{Fore.RED}Error: Please configure your Steam API key in config.json")
                sys.exit(1)
            
            if config.get('steam_id') == 'YOUR_STEAM_ID_HERE':
                print(f"{Fore.RED}Error: Please configure your Steam ID in config.json")
                sys.exit(1)
            
            return config
        except json.JSONDecodeError as e:
            print(f"{Fore.RED}Error parsing config file: {e}")
            sys.exit(1)
    
    def fetch_games(self) -> bool:
        """Fetch games from Steam library"""
        print(f"{Fore.CYAN}Fetching your Steam library...")
        self.games = self.steam_client.get_owned_games(self.config['steam_id'])
        
        if not self.games:
            print(f"{Fore.RED}No games found or error fetching games.")
            return False
        
        print(f"{Fore.GREEN}Found {len(self.games)} games in your library!")
        return True
    
    def filter_games(self, min_playtime: int = 0, max_playtime: Optional[int] = None) -> List[Dict]:
        """Filter games based on playtime criteria"""
        filtered = self.games
        
        if min_playtime > 0:
            filtered = [g for g in filtered if g.get('playtime_forever', 0) >= min_playtime]
        
        if max_playtime is not None:
            filtered = [g for g in filtered if g.get('playtime_forever', 0) <= max_playtime]
        
        return filtered
    
    def pick_random_game(self, filtered_games: Optional[List[Dict]] = None, avoid_recent: bool = True) -> Optional[Dict]:
        """Pick a random game from the library"""
        games_to_pick = filtered_games if filtered_games is not None else self.games
        
        if not games_to_pick:
            return None
        
        # Try to avoid recently picked games if possible
        if avoid_recent and self.history and len(games_to_pick) > len(self.history):
            available = [g for g in games_to_pick if g.get('appid') not in self.history[-10:]]
            if available:
                games_to_pick = available
        
        game = random.choice(games_to_pick)
        
        # Add to history
        app_id = game.get('appid')
        if app_id:
            if app_id in self.history:
                self.history.remove(app_id)
            self.history.append(app_id)
            self.save_history()
        
        return game
    
    def display_game_info(self, game: Dict, detailed: bool = True):
        """Display information about a game"""
        app_id = game.get('appid')
        name = game.get('name', 'Unknown Game')
        playtime_minutes = game.get('playtime_forever', 0)
        playtime_hours = playtime_minutes / 60
        
        print(f"\n{Fore.GREEN}{'='*60}")
        print(f"{Fore.CYAN}{Style.BRIGHT}🎮 {name}")
        print(f"{Fore.GREEN}{'='*60}")
        print(f"{Fore.YELLOW}App ID: {Fore.WHITE}{app_id}")
        print(f"{Fore.YELLOW}Playtime: {Fore.WHITE}{playtime_hours:.1f} hours")
        
        if detailed and app_id:
            print(f"\n{Fore.CYAN}Fetching detailed information from Steam Store...")
            details = self.steam_client.get_game_details(app_id)
            
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
        
        print(f"\n{Fore.YELLOW}Steam Store: {Fore.WHITE}https://store.steampowered.com/app/{app_id}/")
        print(f"{Fore.YELLOW}SteamDB: {Fore.WHITE}https://steamdb.info/app/{app_id}/")
        print(f"{Fore.GREEN}{'='*60}\n")
    
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
            print(f"{Fore.YELLOW}5. {Fore.WHITE}Show library stats")
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
                    self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No unplayed games found!")
            elif choice == '3':
                filtered = self.filter_games(max_playtime=self.BARELY_PLAYED_THRESHOLD_MINUTES)
                if filtered:
                    print(f"{Fore.GREEN}Found {len(filtered)} barely played games.")
                    game = self.pick_random_game(filtered)
                    self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No barely played games found!")
            elif choice == '4':
                filtered = self.filter_games(min_playtime=self.WELL_PLAYED_THRESHOLD_MINUTES)
                if filtered:
                    print(f"{Fore.GREEN}Found {len(filtered)} well-played games.")
                    game = self.pick_random_game(filtered)
                    self.display_game_info(game)
                else:
                    print(f"{Fore.YELLOW}No well-played games found!")
            elif choice == '5':
                self.show_stats()
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.")
    
    def show_stats(self):
        """Display library statistics"""
        if not self.games:
            print(f"{Fore.RED}No games loaded.")
            return
        
        total_games = len(self.games)
        unplayed = len([g for g in self.games if g.get('playtime_forever', 0) == 0])
        total_playtime = sum(g.get('playtime_forever', 0) for g in self.games) / 60  # Convert to hours
        
        print(f"\n{Fore.CYAN}{Style.BRIGHT}📊 Library Statistics")
        print(f"{Fore.GREEN}{'='*40}")
        print(f"{Fore.YELLOW}Total Games: {Fore.WHITE}{total_games}")
        print(f"{Fore.YELLOW}Unplayed Games: {Fore.WHITE}{unplayed} ({unplayed/total_games*100:.1f}%)")
        print(f"{Fore.YELLOW}Played Games: {Fore.WHITE}{total_games - unplayed}")
        print(f"{Fore.YELLOW}Total Playtime: {Fore.WHITE}{total_playtime:.1f} hours")
        print(f"{Fore.YELLOW}Average Playtime: {Fore.WHITE}{total_playtime/total_games:.1f} hours per game")
        print(f"{Fore.GREEN}{'='*40}\n")


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
        
        # Non-interactive modes
        if args.stats or args.random or args.unplayed or args.barely_played or args.well_played or args.min_hours is not None or args.max_hours is not None:
            if not picker.fetch_games():
                sys.exit(1)
            
            if args.stats:
                picker.show_stats()
                return
            
            # Determine which filter to use
            filtered_games = None
            
            if args.unplayed:
                filtered_games = picker.filter_games(max_playtime=0)
                print(f"{Fore.GREEN}Filtering to unplayed games...")
            elif args.barely_played:
                filtered_games = picker.filter_games(max_playtime=picker.BARELY_PLAYED_THRESHOLD_MINUTES)
                print(f"{Fore.GREEN}Filtering to barely played games (< 2 hours)...")
            elif args.well_played:
                filtered_games = picker.filter_games(min_playtime=picker.WELL_PLAYED_THRESHOLD_MINUTES)
                print(f"{Fore.GREEN}Filtering to well-played games (> 10 hours)...")
            elif args.min_hours is not None or args.max_hours is not None:
                min_minutes = int(args.min_hours * 60) if args.min_hours is not None else 0
                max_minutes = int(args.max_hours * 60) if args.max_hours is not None else None
                filtered_games = picker.filter_games(min_playtime=min_minutes, max_playtime=max_minutes)
                filter_desc = []
                if args.min_hours is not None:
                    filter_desc.append(f">= {args.min_hours} hours")
                if args.max_hours is not None:
                    filter_desc.append(f"<= {args.max_hours} hours")
                print(f"{Fore.GREEN}Filtering to games with {' and '.join(filter_desc)}...")
            
            if filtered_games is not None and not filtered_games:
                print(f"{Fore.RED}No games found matching the filter criteria.")
                sys.exit(1)
            
            game = picker.pick_random_game(filtered_games)
            if game:
                picker.display_game_info(game, detailed=not args.no_details)
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
