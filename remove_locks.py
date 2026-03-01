#!/usr/bin/env python3
"""Remove all with current_user_lock blocks"""

with open('gapi_gui.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

output = []
i = 0

while i < len(lines):
    line = lines[i]
    
    if 'with current_user_lock:' in line:
        # Skip the with line
        i += 1
        # Get the indentation level of the with statement
        with_indent = len(line) - len(line.lstrip())
        
        # Process lines inside the block
        while i < len(lines):
            next_line = lines[i]
            next_indent = len(next_line) - len(next_line.lstrip())
            
            # If empty line, keep it
            if not next_line.strip():
                output.append(next_line)
                i += 1
            # If indented more than the with line, it's inside the block - dedent it
            elif next_indent > with_indent:
                # Dedent by removing 4 spaces
                if next_line.startswith('    '):
                    output.append(next_line[4:])
                else:
                    output.append(next_line)
                i += 1
            else:
                # End of block
                break
    else:
        output.append(line)
        i += 1

with open('gapi_gui.py', 'w', encoding='utf-8') as f:
    f.writelines(output)

print("Removed all with current_user_lock blocks")
