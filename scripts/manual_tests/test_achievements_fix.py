#!/usr/bin/env python3
"""
Test the fixed achievements endpoint
"""
from unittest.mock import MagicMock, patch
import sys
import gapi

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

print("Testing get_player_achievements (summary version)...\n")

client = gapi.SteamAPIClient('TEST_KEY')

# Mock successful response with achievements
payload = {
    'playerstats': {
        'achievements': [
            {'apiname': 'ACH1', 'achieved': 1, 'unlocktime': 1700000000},
            {'apiname': 'ACH2', 'achieved': 1, 'unlocktime': 1700000001},
            {'apiname': 'ACH3', 'achieved': 0, 'unlocktime': 0},
        ]
    }
}

mock_resp = MagicMock()
mock_resp.status_code = 200
mock_resp.json.return_value = payload

with patch.object(client.session, 'get', return_value=mock_resp):
    result = client.get_player_achievements('12345', '620')
    
    print(f"result type: {type(result)}")
    print(f"result: {result}")
    
    if isinstance(result, dict):
        print("\n✅ Correctly returns dict that can be unpacked with **")
        print(f"   Total achievements: {result.get('total')}")
        print(f"   Achieved: {result.get('achieved')}")
        print(f"   Percent: {result.get('percent')}%")
        
        # Test the dict unpacking that happens in the API
        test_dict = {'app_id': '620', **result}
        print(f"\n✅ Dict unpacking successful:")
        print(f"   {test_dict}")
    else:
        print(f"\n❌ Expected dict but got {type(result).__name__}")
        sys.exit(1)

print("\n" + "="*60)
print("Testing get_player_achievements_detailed (list version)...\n")

with patch.object(client.session, 'get', return_value=mock_resp):
    result = client.get_player_achievements_detailed('12345', '620')
    
    print(f"result type: {type(result)}")
    print(f"result count: {len(result)}")
    
    if isinstance(result, list):
        print("\n✅ Correctly returns list of achievements")
        for i, ach in enumerate(result, 1):
            print(f"   {i}. {ach.get('apiname')}: {'✓ Achieved' if ach.get('achieved') else '✗ Not achieved'}")
    else:
        print(f"\n❌ Expected list but got {type(result).__name__}")
        sys.exit(1)

print("\n" + "="*60)
print("✅ Both methods working correctly!")
print("="*60)
