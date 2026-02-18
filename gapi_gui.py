#!/usr/bin/env python3
"""
GAPI GUI - Web-based Graphical User Interface for Game Picker
A modern web GUI for randomly picking games from your Steam library.
"""

from flask import Flask, render_template, jsonify, request
import threading
import json
import os
import sys
from typing import Optional, List, Dict
import gapi

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Global game picker instance
picker: Optional[gapi.GamePicker] = None
picker_lock = threading.Lock()
current_game: Optional[Dict] = None


def initialize_picker(config_path: str = 'config.json'):
    """Initialize the game picker"""
    global picker
    with picker_lock:
        try:
            picker = gapi.GamePicker(config_path=config_path)
            if picker.fetch_games():
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
            <button class="tab active" onclick="switchTab('picker')">Pick a Game</button>
            <button class="tab" onclick="switchTab('library')">Library</button>
            <button class="tab" onclick="switchTab('favorites')">Favorites</button>
            <button class="tab" onclick="switchTab('stats')">Statistics</button>
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
    </div>
    
    <script>
        let currentGame = null;
        
        // Initialize
        async function init() {
            await updateStatus();
            loadLibrary();
            loadFavorites();
            loadStats();
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
        
        function switchTab(tabName) {
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
        
        // Initialize on page load
        init();
    </script>
</body>
</html>
"""
    
    index_path = os.path.join(templates_dir, 'index.html')
    with open(index_path, 'w') as f:
        f.write(index_html)


def main():
    """Main entry point for GUI"""
    import sys
    
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
