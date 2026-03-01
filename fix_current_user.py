#!/usr/bin/env python3
"""Replace all instances of assignment from current_user with get_current_username()"""

import re

with open('gapi_gui.py', 'r') as f:
    content = f.read()

# Replace patterns like "username = current_user" with "username = get_current_username()"
# But be careful not to replace the LocalProxy definition line
content = re.sub(
    r'(\w+)\s*=\s*current_user\b(?!\s*=.*LocalProxy)',
    r'\1 = get_current_username()',
    content
)

with open('gapi_gui.py', 'w') as f:
    f.write(content)

print("Replaced all current_user assignments with get_current_username()")
