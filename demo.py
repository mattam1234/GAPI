#!/usr/bin/env python3
"""
Demo script to showcase GAPI functionality without requiring Steam credentials.
"""

import sys
import os

# Mock data for demonstration
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

# Temporarily modify sys.path to import gapi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Create a mock config
demo_config = {
    "steam_api_key": "DEMO_MODE",
    "steam_id": "DEMO_MODE"
}

print("=" * 60)
print("GAPI DEMO MODE")
print("=" * 60)
print("\nThis is a demonstration of GAPI using mock data.")
print("To use with your actual Steam library, follow the setup")
print("instructions in README.md\n")
print("=" * 60)

# Create temporary config file for demo
with open('.demo_config.json', 'w') as f:
    import json
    json.dump(demo_config, f)

try:
    # Import and monkey-patch gapi
    import gapi
    
    # Override the fetch_games method to use demo data
    original_fetch = gapi.GamePicker.fetch_games
    original_get_details = gapi.SteamAPIClient.get_game_details
    
    def demo_fetch_games(self):
        from colorama import Fore
        print(f"{Fore.CYAN}Loading demo game library...")
        self.games = DEMO_GAMES
        print(f"{Fore.GREEN}Found {len(self.games)} games in the demo library!")
        return True
    
    def demo_get_details(self, game_id):
        # Return None to skip detailed fetching in demo mode
        return None
    
    # Apply patches
    gapi.GamePicker.fetch_games = demo_fetch_games
    gapi.SteamAPIClient.get_game_details = demo_get_details
    
    # Update config validation to allow demo mode
    original_load_config = gapi.GamePicker.load_config
    
    def demo_load_config(self, config_path):
        if config_path == '.demo_config.json':
            return demo_config
        return original_load_config(self, config_path)
    
    gapi.GamePicker.load_config = demo_load_config
    
    # Run in demo mode
    picker = gapi.GamePicker(config_path='.demo_config.json')
    picker.interactive_mode()
    
finally:
    # Cleanup
    if os.path.exists('.demo_config.json'):
        os.remove('.demo_config.json')
