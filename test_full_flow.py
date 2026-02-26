#!/usr/bin/env python3
"""Test the full authentication and game loading flow"""
import requests
import json
import time

BASE_URL = "http://localhost:5000"

def test_flow():
    session = requests.Session()
    
    # Step 1: Check auth status (should be null)
    print("=" * 60)
    print("1. Checking auth status (not logged in)")
    print("=" * 60)
    resp = session.get(f"{BASE_URL}/api/auth/current")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}\n")
    
    # Step 2: Try to load status without login (should fail with 401)
    print("=" * 60)
    print("2. Trying to load status without login")
    print("=" * 60)
    resp = session.get(f"{BASE_URL}/api/status")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}\n")
    
    # Step 3: Login as mattam
    print("=" * 60)
    print("3. Logging in as mattam")
    print("=" * 60)
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "username": "mattam",
        "password": "mattam"
    })
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}\n")
    
    if resp.status_code != 200:
        print("❌ Login failed! Trying admin/admin...")
        resp = session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        print(f"Admin Status: {resp.status_code}")
        print(f"Admin Response: {resp.text}\n")
    
    # Step 4: Check auth status after login
    print("=" * 60)
    print("4. Checking auth status after login")
    print("=" * 60)
    resp = session.get(f"{BASE_URL}/api/auth/current")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}\n")
    
    # Step 5: Load status (should work now)
    print("=" * 60)
    print("5. Loading status after login")
    print("=" * 60)
    resp = session.get(f"{BASE_URL}/api/status")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}\n")
    
    # Step 6: Pick a game
    print("=" * 60)
    print("6. Picking a game")
    print("=" * 60)
    resp = session.post(f"{BASE_URL}/api/pick", json={})
    if resp.status_code == 200:
        game = resp.json()
        print(f"✅ Picked: {game.get('name')}")
        print(f"   Description: {game.get('description', 'NO DESCRIPTION')[:100]}...")
        print(f"   Genres: {game.get('genres', [])}")
        print(f"   Release Date: {game.get('release_date', 'N/A')}")
        print(f"   Image: {game.get('header_image', 'N/A')}")
    else:
        print(f"❌ Pick failed: {resp.status_code}")
        print(f"   Response: {resp.text}\n")

if __name__ == "__main__":
    test_flow()
