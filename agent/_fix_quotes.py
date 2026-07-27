#!/usr/bin/env python3
with open('chain/suggest.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace Chinese curly double quotes with square brackets (safe in Python strings)
# “ = ", ” = "
content = content.replace('“', '「')  # " → 「
content = content.replace('”', '」')  # " → 」

with open('chain/suggest.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
