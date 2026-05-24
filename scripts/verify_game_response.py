#!/usr/bin/env python3
"""Verify that game responses include descriptions"""
import requests
import json

BASE_URL = "http://localhost:5000"

session = requests.Session()

# Register and login
session.post(f"{BASE_URL}/api/auth/register", json={
    "username": "test2",
    "password": "test2"
})

resp = session.post(f"{BASE_URL}/api/auth/login", json={
    "username": "test2",
    "password": "test2"
})

print(f"Login: {resp.status_code}\n")

# Pick a game
print("Picking a game...")
resp = session.post(f"{BASE_URL}/api/pick", json={})
game = resp.json()

print(f"Game: {game.get('name')}")
print(f"App ID: {game.get('app_id')}")
print(f"Playtime: {game.get('playtime_hours')}h")
print(f"\n✅ HAS DESCRIPTION: {'description' in game and bool(game['description'])}")
if 'description' in game and game['description']:
    print(f"Description: {game['description'][:150]}...")
else:
    print("Description: MISSING OR EMPTY")

print(f"\n✅ HAS GENRES: {'genres' in game and bool(game['genres'])}")
if 'genres' in game:
    print(f"Genres: {game['genres']}")

print(f"\n✅ HAS IMAGE: {'header_image' in game and bool(game['header_image'])}")
if 'header_image' in game:
    print(f"Image URL: {game['header_image'][:80]}...")

print(f"\n✅ HAS METACRITIC: {'metacritic_score' in game}")
if 'metacritic_score' in game:
    print(f"Metacritic: {game['metacritic_score']}")

print("\n" + "=" * 60)
print("Full game response:")
print(json.dumps(game, indent=2))
