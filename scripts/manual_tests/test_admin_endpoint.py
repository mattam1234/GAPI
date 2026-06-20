#!/usr/bin/env python
import json
import http.cookiejar
import urllib.request
import urllib.parse

# Create a cookie jar to maintain session
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

# Step 1: Login
login_data = json.dumps({
    'username': 'mattam1234',
    'password': 'password'
}).encode('utf-8')

try:
    req = urllib.request.Request('http://localhost:5000/api/auth/login', 
                                 data=login_data,
                                 headers={'Content-Type': 'application/json'})
    login_response = opener.open(req)
    login_result = json.loads(login_response.read().decode())
    print(f"Login result: {login_result}")
    print(f"Cookies after login: {list(cookie_jar)}")
except Exception as e:
    print(f"Login failed: {e}")
    exit(1)

# Step 2: Get admin settings
try:
    settings_response = opener.open('http://localhost:5000/api/admin/settings')
    settings_data = json.loads(settings_response.read().decode())
    print(f"Admin settings response: {json.dumps(settings_data, indent=2)}")
except Exception as e:
    print(f"Settings fetch failed: {e}")
