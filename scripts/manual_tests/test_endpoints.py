#!/usr/bin/env python3
"""
Test script for new database endpoints.
"""
import requests
import json
from datetime import datetime
import time
import sys
import io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:5000"

def test_endpoints():
    print("=" * 60)
    print("TESTING NEW DATABASE ENDPOINTS")
    print("=" * 60)
    
    # Use unique username each run
    username = f"testuser_{int(time.time())}"
    password = "password123"
    
    # 1. Register a new user
    print("\n[1] REGISTER USER")
    resp = requests.post(f"{BASE_URL}/api/auth/register", json={
        "username": username,
        "password": password,
        "steam_id": "76561598000000000"
    })
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # 2. Login
    print("[2] LOGIN USER")
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": username,
        "password": password
    })
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Response: {data}")
    token = data.get('token')
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    print(f"Token: {token}\n")
    
    # 3. Test GET /api/ignored-games (should be empty)
    print("[3] GET IGNORED GAMES (should be empty)")
    resp = requests.get(f"{BASE_URL}/api/ignored-games", headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # 4. Test POST /api/ignored-games (add a game)
    print("[4] ADD IGNORED GAME")
    resp = requests.post(f"{BASE_URL}/api/ignored-games", json={
        "app_id": 107410,
        "game_name": "Test Game",
        "reason": "Not interested"
    }, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # 5. Test GET /api/ignored-games (should have 1)
    print("[5] GET IGNORED GAMES (should have 1)")
    resp = requests.get(f"{BASE_URL}/api/ignored-games", headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # 6. Test GET /api/achievements (empty)
    print("[6] GET ACHIEVEMENTS (should be empty)")
    resp = requests.get(f"{BASE_URL}/api/achievements", headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # 7. Test POST /api/achievement-hunt (start hunt)
    print("[7] START ACHIEVEMENT HUNT")
    resp = requests.post(f"{BASE_URL}/api/achievement-hunt", json={
        "app_id": 730,
        "game_name": "CS:GO",
        "difficulty": "medium"
    }, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
    hunt_id = resp.json().get('id') if resp.status_code == 201 else None
    print(f"Hunt ID: {hunt_id}\n")
    
    # 8. Test PUT /api/achievement-hunt/<id> (update progress)
    if hunt_id:
        print("[8] UPDATE ACHIEVEMENT HUNT PROGRESS")
        resp = requests.put(f"{BASE_URL}/api/achievement-hunt/{hunt_id}", json={
            "progress_percent": 45,
            "status": "in_progress"
        }, headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}\n")
    
    # 9. Test GET /api/achievements (should have hunt data)
    print("[9] GET ACHIEVEMENTS (after hunt)")
    resp = requests.get(f"{BASE_URL}/api/achievements", headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    print("=" * 60)
    print("SUCCESS: ENDPOINT TESTING COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_endpoints()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

