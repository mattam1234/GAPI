#!/usr/bin/env python3
import requests
import json

# Test login
login_response = requests.post('http://localhost:5000/api/auth/login', json={
    'username': 'mattam',
    'password': 'password'
})

print('Login:', login_response.status_code)
if login_response.ok:
    print('✓ Logged in as mattam')
    
    # Set up session with cookies
    session = requests.Session()
    session.cookies.update(login_response.cookies)
    
    # Make authenticated request to /api/pick
    pick_response = session.post('http://localhost:5000/api/pick', json={})
    
    if pick_response.ok:
        game_data = pick_response.json()
        print(f'\nPicked Game: {game_data.get("name", "Unknown")}')
        print(f'App ID: {game_data.get("app_id")}')
        print(f'Has description: {"description" in game_data}')
        if 'description' in game_data:
            desc = game_data['description'][:100] if game_data['description'] else 'None'
            print(f'Description preview: {desc}...')
        print(f'Has header_image: {"header_image" in game_data}')
        print(f'Has genres: {"genres" in game_data}')
        if 'genres' in game_data:
            print(f'Genres: {game_data["genres"]}')
        print(f'Has release_date: {"release_date" in game_data}')
        if 'release_date' in game_data:
            print(f'Release Date: {game_data["release_date"]}')
        print(f'Has metacritic_score: {"metacritic_score" in game_data}')
        if 'metacritic_score' in game_data:
            print(f'Metacritic: {game_data["metacritic_score"]}')
    else:
        print(f'Pick request failed: {pick_response.status_code}')
        print(pick_response.text)
else:
    print(f'Login failed: {login_response.status_code}')
    print(login_response.text)
