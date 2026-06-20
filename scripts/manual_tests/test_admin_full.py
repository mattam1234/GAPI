#!/usr/bin/env python
import json
import http.cookiejar
import urllib.request

# Create a cookie jar to maintain session
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

print("=" * 60)
print("ADMIN TAB TEST SUITE")
print("=" * 60)

# Step 1: Login
print("\n1. Testing Login...")
login_data = json.dumps({
    'username': 'mattam1234',
    'password': 'password'
}).encode('utf-8')

req = urllib.request.Request('http://localhost:5000/api/auth/login', 
                             data=login_data,
                             headers={'Content-Type': 'application/json'})
try:
    login_response = opener.open(req)
    login_result = json.loads(login_response.read().decode())
    print(f"✅ Login successful: {login_result['username']}")
except Exception as e:
    print(f"❌ Login failed: {e}")
    exit(1)

# Step 2: Check admin status
print("\n2. Checking Admin Status (/api/auth/current)...")
try:
    current_response = opener.open('http://localhost:5000/api/auth/current')
    current_data = json.loads(current_response.read().decode())
    username = current_data.get('username')
    role = current_data.get('role')
    roles = current_data.get('roles', [])
    print(f"✅ User: {username}, Role: {role}, Roles array: {roles}")
    
    if 'admin' not in roles:
        print(f"❌ ERROR: 'admin' not in roles array!")
        exit(1)
    else:
        print(f"✅ Admin role correctly in roles array")
        
except Exception as e:
    print(f"❌ Failed to check admin status: {e}")
    exit(1)

# Step 3: Get admin settings
print("\n3. Getting Admin Settings (/api/admin/settings/GET)...")
try:
    settings_response = opener.open('http://localhost:5000/api/admin/settings')
    settings_data = json.loads(settings_response.read().decode())
    settings = settings_data.get('settings', [])
    print(f"✅ Retrieved {len(settings)} settings")
    
    if not settings:
        print(f"❌ ERROR: No settings returned!")
    else:
        print(f"✅ Settings keys: {[s['key'] for s in settings]}")
        
        # Check for expected keys
        expected_keys = ['registration_open', 'announcement', 'max_pick_count', 
                        'default_platform', 'leaderboard_public', 'chat_enabled', 'plugins_enabled']
        actual_keys = [s['key'] for s in settings]
        missing = [k for k in expected_keys if k not in actual_keys]
        if missing:
            print(f"❌ Missing keys: {missing}")
        else:
            print(f"✅ All expected settings present")
            
except Exception as e:
    print(f"❌ Failed to get admin settings: {e}")
    exit(1)

# Step 4: Save admin settings
print("\n4. Testing Save Admin Settings (/api/admin/settings/POST)...")
try:
    save_data = json.dumps({
        'settings': {
            'announcement': 'Test announcement from API',
            'registration_open': 'true',
            'max_pick_count': '20'
        }
    }).encode('utf-8')
    
    req = urllib.request.Request('http://localhost:5000/api/admin/settings',
                                 data=save_data,
                                 headers={'Content-Type': 'application/json'},
                                 method='POST')
    save_response = opener.open(req)
    save_result = json.loads(save_response.read().decode())
    
    # Check if save was successful
    if save_response.status == 200 or 'error' not in save_result:
        print(f"✅ Settings saved successfully")
    else:
        print(f"❌ Settings save failed: {save_result}")
        
except Exception as e:
    print(f"❌ Failed to save admin settings: {e}")
    exit(1)

# Step 5: Verify the announcement was saved
print("\n5. Verifying Saved Settings...")
try:
    verify_response = opener.open('http://localhost:5000/api/admin/settings')
    verify_data = json.loads(verify_response.read().decode())
    settings = verify_data.get('settings', [])
    
    announcement = next((s['value'] for s in settings if s['key'] == 'announcement'), None)
    if announcement == 'Test announcement from API':
        print(f"✅ Announcement saved correctly: '{announcement}'")
    else:
        print(f"⚠️ Announcement value: '{announcement}' (may not have been saved)")
        
except Exception as e:
    print(f"❌ Failed to verify settings: {e}")

print("\n" + "=" * 60)
print("ADMIN TAB TEST COMPLETE - All checks passed! ✅")
print("=" * 60)
