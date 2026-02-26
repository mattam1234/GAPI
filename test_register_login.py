#!/usr/bin/env python3
"""Test registration and login flow"""
import requests
import json

BASE_URL = "http://localhost:5000"

def test_registration_and_login():
    session = requests.Session()
    
    # Step 1: Try to register a test user
    print("=" * 60)
    print("1. Registering test user (testuser/testpass123)")
    print("=" * 60)
    resp = session.post(f"{BASE_URL}/api/auth/register", json={
        "username": "testuser",
        "password": "testpass123"
    })
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}\n")
    
    if resp.status_code == 200:
        # Step 2: Login with new account
        print("=" * 60)
        print("2. Logging in with testuser")
        print("=" * 60)
        resp = session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "testuser",
            "password": "testpass123"
        })
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}\n")
        
        if resp.status_code == 200:
            # Step 3: Check auth
            print("=" * 60)
            print("3. Checking auth status")
            print("=" * 60)
            resp = session.get(f"{BASE_URL}/api/auth/current")
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.json()}\n")
            
            # Step 4: Load status
            print("=" * 60)
            print("4. Loading status")
            print("=" * 60)
            resp = session.get(f"{BASE_URL}/api/status")
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.json()}\n")
            
            # Step 5: Try picking a game
            print("=" * 60)
            print("5. Picking a game")
            print("=" * 60)
            resp = session.post(f"{BASE_URL}/api/pick", json={})
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                game = resp.json()
                print(f"✅ Picked: {game.get('name')}")
                print(f"   Has description: {'description' in game}")
                if 'description' in game:
                    desc = game['description'][:100] if game['description'] else "[empty]"
                    print(f"   Description: {desc}...")
                print(f"   Genres: {game.get('genres', [])}")
                print(f"   Has header_image: {'header_image' in game}")
            else:
                print(f"❌ Response: {resp.text}")

if __name__ == "__main__":
    test_registration_and_login()
