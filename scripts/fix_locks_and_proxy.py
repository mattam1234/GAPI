#!/usr/bin/env python3
"""Remove lock blocks and replace current_user with get_current_username()"""

import re

with open('gapi_gui.py', 'r') as f:
    lines = f.readlines()

output = []
i = 0

while i < len(lines):
    line = lines[i]
    
    # Skip lines with "with current_user_lock:"
    if 'with current_user_lock:' in line:
        i += 1
        # Remove the indentation from the following lines (dedent by 4 spaces)
        while i < len(lines):
            indent_line = lines[i]
            if indent_line.strip():  # Non-empty line
                if indent_line.startswith('    '):
                    output.append(indent_line[4:])  # Remove 4 spaces
                else:
                    output.append(indent_line)
            else:
                output.append(indent_line)  # Keep blank lines
            
            # Check if this is the last line of the block
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_indent = len(next_line) - len(next_line.lstrip())
                curr_line_indent = len(indent_line) - len(indent_line.lstrip())
                if next_line.strip() and next_indent <= len(line) - len(line.lstrip()):
                    i += 1
                    break
            i += 1
    else:
        # Replace current_user with get_current_username() in the line
        line = re.sub(r'(\w+)\s*=\s*current_user\b', r'\1 = get_current_username()', line)
        output.append(line)
        i += 1

with open('gapi_gui.py', 'w') as f:
    f.writelines(output)

print("Removed lock blocks and replaced current_user assignments")
