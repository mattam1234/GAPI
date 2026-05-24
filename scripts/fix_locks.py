#!/usr/bin/env python3
"""Remove all with current_user_lock: blocks from gapi_gui.py"""

import re

with open('gapi_gui.py', 'r') as f:
    lines = f.readlines()

output = []
i = 0

while i < len(lines):
    line = lines[i]
    
    if 'with current_user_lock:' in line:
        # Skip the lock line - don't add it
        # Get the indentation level of the with statement
        with_indent = len(line) - len(line.lstrip())
        i += 1
        
        # Process lines that are indented more than the with statement
        while i < len(lines):
            next_line = lines[i]
            next_indent = len(next_line) - len(next_line.lstrip())
            
            # If line is blank, keep it as is
            if not next_line.strip():
                output.append(next_line)
                i += 1
            # If line is indented more than the with statement (inside the block)
            elif next_indent > with_indent:
                # Dedent by 4 spaces
                if next_line.startswith('    '):
                    output.append(next_line[4:])
                else:
                    output.append(next_line)
                i += 1
            else:
                # End of the with block
                break
    else:
        output.append(line)
        i += 1

with open('gapi_gui.py', 'w') as f:
    f.writelines(output)

print("Removed all with current_user_lock blocks successfully")
