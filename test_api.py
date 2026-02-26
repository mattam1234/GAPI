import requests
import json

# Try to load the library
resp = requests.get('http://localhost:5000/api/library')
print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")
