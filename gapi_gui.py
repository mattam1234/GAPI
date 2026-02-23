#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

import logging
from flask import Flask, render_template, jsonify, request
import threading
import json
import os
import sys
from typing import Optional, List, Dict
import gapi
import multiuser

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
    global picker
    with picker_lock:
        if picker is None:
            return jsonify({
                'ready': False,
                'message': 'Initializing...'
            })
        return jsonify({
            'ready': True,
            'total_games': len(picker.games) if picker.games else 0,
            'favorites': len(picker.favorites) if picker.favorites else 0
        })


@app.route('/api/pick', methods=['POST'])
def api_pick_game():
    """Pick a random game"""
    global picker, current_game
    
    if not picker or not picker.games:
        return jsonify({'error': 'No games loaded'}), 400
    
    data = request.json or {}
    filter_type = data.get('filter', 'all')
    genre_text = data.get('genre', '').strip()
    genres = [g.strip() for g in genre_text.split(',')] if genre_text else None
    
    with picker_lock:
        # Apply filters
        filtered_games = None
        
        if filter_type == "unplayed":
            filtered_games = picker.filter_games(max_playtime=0, genres=genres)
        elif filter_type == "barely":
            filtered_games = picker.filter_games(
                max_playtime=picker.BARELY_PLAYED_THRESHOLD_MINUTES,
                genres=genres
            )
        elif filter_type == "well":
            filtered_games = picker.filter_games(
                min_playtime=picker.WELL_PLAYED_THRESHOLD_MINUTES,
                genres=genres
            )
        elif filter_type == "favorites":
            filtered_games = picker.filter_games(favorites_only=True, genres=genres)
        elif genres:
            filtered_games = picker.filter_games(genres=genres)
        
        if filtered_games is not None and len(filtered_games) == 0:
            return jsonify({'error': 'No games match the selected filters'}), 400
        
        # Pick game
        game = picker.pick_random_game(filtered_games)
        
        if not game:
            return jsonify({'error': 'Failed to pick a game'}), 500
        
        current_game = game
        
        app_id = game.get('appid')
        name = game.get('name', 'Unknown Game')
        playtime_minutes = game.get('playtime_forever', 0)
        playtime_hours = playtime_minutes / 60
        is_favorite = app_id in picker.favorites if app_id else False
        
        response = {
            'app_id': app_id,
            'name': name,
            'playtime_hours': round(playtime_hours, 1),
            'is_favorite': is_favorite,
            'steam_url': f'https://store.steampowered.com/app/{app_id}/',
            'steamdb_url': f'https://steamdb.info/app/{app_id}/'
        }
        
        # Try to get details (non-blocking)
        def fetch_details():
            if app_id:
                details = picker.steam_client.get_game_details(app_id)
                if details:
                    game['_details'] = details
        
        threading.Thread(target=fetch_details, daemon=True).start()
        
        return jsonify(response)


@app.route('/api/game/<int:app_id>/details')
def api_game_details(app_id):
    """Get detailed game information"""
    global picker
    
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400
    
    with picker_lock:
        details = picker.steam_client.get_game_details(app_id)
        
        if not details:
            return jsonify({'error': 'Could not fetch details'}), 404
        
        response = {}
        
        if 'short_description' in details:
            response['description'] = details['short_description']
        
        if 'genres' in details:
            response['genres'] = [g['description'] for g in details['genres']]
        
        if 'release_date' in details:
            response['release_date'] = details['release_date'].get('date', 'Unknown')
        
        if 'metacritic' in details:
            response['metacritic_score'] = details['metacritic'].get('score')
        
        return jsonify(response)


@app.route('/api/favorite/<int:app_id>', methods=['POST', 'DELETE'])
def api_toggle_favorite(app_id):
    """Add or remove a game from favorites"""
    global picker
    
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400
    
    with picker_lock:
        if request.method == 'POST':
            picker.add_favorite(app_id)
            return jsonify({'success': True, 'action': 'added'})
        else:
            picker.remove_favorite(app_id)
            return jsonify({'success': True, 'action': 'removed'})


@app.route('/api/library')
def api_library():
    """Get all games in library"""
    global picker
    
    if not picker or not picker.games:
        return jsonify({'error': 'No games loaded'}), 400
    
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
def api_favorites():
    """Get all favorite games"""
    global picker
    
    if not picker:
        return jsonify({'error': 'Picker not initialized'}), 400
    
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
def api_stats():
    """Get library statistics"""
    global picker
    
    if not picker or not picker.games:
        return jsonify({'error': 'No games loaded'}), 400
    
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


@app.route('/api/users')
def api_users_list():
    """Get all users"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    with multi_picker_lock:
        return jsonify({'users': multi_picker.users})


@app.route('/api/users/add', methods=['POST'])
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
            return jsonify({'success': True, 'message': f'User {name} added successfully'})
        else:
            return jsonify({'error': 'User already exists'}), 400


@app.route('/api/users/update', methods=['POST'])
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
def api_multiuser_common():
    """Get common games for selected users"""
    global multi_picker
    
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
def api_multiuser_pick():
    """Pick a common game for multiple users"""
    global multi_picker
    
    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400
    
    data = request.json or {}
    user_names = data.get('users', [])
    coop_only = data.get('coop_only', False)
    max_players = data.get('max_players')
    
    with multi_picker_lock:
        game = multi_picker.pick_common_game(
            user_names if user_names else None,
            coop_only=coop_only,
            max_players=max_players
        )
        
        if not game:
            return jsonify({'error': 'No common games found'}), 404
        
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
def api_multiuser_stats():
    """Get multi-user library statistics"""
    global multi_picker

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
def api_voting_create():
    """Create a new voting session from common games.

    Expected JSON body:
        users        – list of user names participating (optional – all users if omitted)
        num_candidates – number of game candidates to put to a vote (default: 5)
        duration     – voting window in seconds (optional)
        coop_only    – filter to co-op games only (default: false)
    """
    global multi_picker

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
def api_voting_cast(session_id: str):
    """Cast a vote in an active voting session.

    Expected JSON body:
        user_name – name of the voter
        app_id    – app ID of the game being voted for
    """
    global multi_picker

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
def api_voting_status(session_id: str):
    """Get the current status and vote tallies for a voting session."""
    global multi_picker

    if not multi_picker:
        return jsonify({'error': 'Multi-user picker not initialized'}), 400

    with multi_picker_lock:
        session = multi_picker.get_voting_session(session_id)
        if session is None:
            return jsonify({'error': 'Voting session not found'}), 404
        return jsonify(session.to_dict())


@app.route('/api/voting/<session_id>/close', methods=['POST'])
def api_voting_close(session_id: str):
    """Close a voting session and return the winner."""
    global multi_picker

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


def create_templates():
    """Create HTML templates directory and files"""
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
            <div class="user-form" style="background: #f8f9fa; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
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
            <div style="background: #f8f9fa; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
                <h3>Select Players</h3>
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
            <div id="multiuser-result" style="display: none; background: #f8f9fa; padding: 25px; border-radius: 10px;">
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
                                    <small style="color: #666;">${user.email || 'No email'}</small>
                                </div>
                                <div>
                                    <small style="color: #666;">Steam ID:</small><br>
                                    ${user.steam_id}
                                </div>
                                <div>
                                    <small style="color: #666;">Discord ID:</small><br>
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
    config_path = 'config.json'
    demo_mode = False
    
    # Check for demo mode
    if len(sys.argv) > 1 and sys.argv[1] == '--demo':
        demo_mode = True
        print("\n" + "="*60)
        print("GAPI WEB GUI - DEMO MODE")
        print("="*60)
        print("\nRunning with demo data...")
        
        # Create demo config
        demo_config = {
            "steam_api_key": "DEMO_MODE",
            "steam_id": "DEMO_MODE"
        }
        
        config_path = '.demo_config_gui.json'
        with open(config_path, 'w') as f:
            json.dump(demo_config, f)
        
        # Monkey-patch for demo mode
        DEMO_GAMES = [
            {"appid": 620, "name": "Portal 2", "playtime_forever": 2720},
            {"appid": 440, "name": "Team Fortress 2", "playtime_forever": 15430},
            {"appid": 570, "name": "Dota 2", "playtime_forever": 0},
            {"appid": 730, "name": "Counter-Strike: Global Offensive", "playtime_forever": 4560},
            {"appid": 72850, "name": "The Elder Scrolls V: Skyrim", "playtime_forever": 890},
            {"appid": 8930, "name": "Sid Meier's Civilization V", "playtime_forever": 0},
            {"appid": 292030, "name": "The Witcher 3: Wild Hunt", "playtime_forever": 85},
            {"appid": 4000, "name": "Garry's Mod", "playtime_forever": 320},
            {"appid": 271590, "name": "Grand Theft Auto V", "playtime_forever": 5670},
            {"appid": 4920, "name": "Natural Selection 2", "playtime_forever": 125},
            {"appid": 203160, "name": "Tomb Raider", "playtime_forever": 1250},
            {"appid": 550, "name": "Left 4 Dead 2", "playtime_forever": 3420},
        ]
        
        original_fetch = gapi.GamePicker.fetch_games
        original_load_config = gapi.GamePicker.load_config
        
        def demo_fetch_games(self):
            self.games = DEMO_GAMES
            return True
        
        def demo_load_config(self, path):
            if path == config_path:
                return demo_config
            return original_load_config(self, path)
        
        gapi.GamePicker.fetch_games = demo_fetch_games
        gapi.GamePicker.load_config = demo_load_config
    
    # Create templates
    create_templates()
    
    # Initialize picker in background
    def init_async():
        success, message = initialize_picker(config_path)
        if success:
            print(f"✅ {message}")
        else:
            print(f"❌ Error: {message}")
    
    threading.Thread(target=init_async, daemon=True).start()
    
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
    finally:
        # Cleanup demo config
        if demo_mode and os.path.exists(config_path):
            os.remove(config_path)


if __name__ == "__main__":
    main()
