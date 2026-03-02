#!/usr/bin/env python
import json
import http.cookiejar
import urllib.request

print("=" * 70)
print("ADMIN ANNOUNCEMENT ROUND-TRIP TEST")
print("=" * 70)

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

# Login
login_data = json.dumps({'username': 'mattam1234', 'password': 'password'}).encode('utf-8')
req = urllib.request.Request('http://localhost:5000/api/auth/login', 
                             data=login_data,
                             headers={'Content-Type': 'application/json'})
opener.open(req)

# Step 1: Set announcement via API
print("\n[1] Setting announcement via API...")
save_data = json.dumps({
    'settings': {
        'announcement': 'IMPORTANT: This is an announcement from the API test'
    }
}).encode('utf-8')

req = urllib.request.Request('http://localhost:5000/api/admin/settings',
                             data=save_data,
                             headers={'Content-Type': 'application/json'},
                             method='POST')
opener.open(req)
print("✅ Announcement set via API")

# Step 2: Load settings as the frontend would
print("\n[2] Loading settings as frontend would (like loadAdminSettings())...")
response = opener.open('http://localhost:5000/api/admin/settings')
data = json.loads(response.read().decode())
settings_map = {s['key']: s['value'] for s in data['settings']}
announcement = settings_map.get('announcement', '')
print(f"✅ Frontend loads announcement: '{announcement}'")

# Step 3: Modify and save via frontend
print("\n[3] Simulating frontend modification and save...")
new_announcement = 'UPDATED: Changed via admin UI save button'
save_data = json.dumps({
    'settings': {
        'announcement': new_announcement
    }
}).encode('utf-8')

req = urllib.request.Request('http://localhost:5000/api/admin/settings',
                             data=save_data,
                             headers={'Content-Type': 'application/json'},
                             method='POST')
response = opener.open(req)
result = json.loads(response.read().decode())
print(f"✅ Frontend saved updated announcement")

# Step 4: Verify the update persisted
print("\n[4] Verifying the updated announcement persisted...")
response = opener.open('http://localhost:5000/api/admin/settings')
data = json.loads(response.read().decode())
settings_map = {s['key']: s['value'] for s in data['settings']}
final_announcement = settings_map.get('announcement', '')

if final_announcement == new_announcement:
    print(f"✅ SUCCESS: Announcement updated to: '{final_announcement}'")
else:
    print(f"❌ FAILED: Expected '{new_announcement}' but got '{final_announcement}'")

print("\n" + "=" * 70)
print("ROUND-TRIP TEST COMPLETE")
print("=" * 70)
print("\n📝 NEXT STEPS:")
print("1. Refresh your browser (F5)")
print("2. Login with mattam1234 / password")
print("3. Click the '🛠️ Admin' tab")
print("4. You should see the announcement in the text area")
print("5. Change it if you want")
print("6. Click '💾 Save Settings' button")
print("7. The announcement should persist after page refresh")
