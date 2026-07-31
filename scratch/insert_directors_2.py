import json
import sqlite3
import re
from datetime import datetime

text = open(r'C:\Users\legen\.gemini\antigravity-ide\brain\4f53a9f7-572a-42aa-8969-3269799b92b4\browser\scratchpad_0u7mx20q.md', encoding='utf-8').read()
m = re.search(r'```json\n(.*?)```', text, re.DOTALL)
data = json.loads(m.group(1))

conn = sqlite3.connect('data/cache.sqlite')
cur = conn.cursor()
count = 0
for c in data:
    for d in c['directors']:
        cur.execute('''
            INSERT OR REPLACE INTO directors (cin, din, name, designation, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (c['cin'], d['din'], d['name'], d['designation'], datetime.now().isoformat()))
        count += 1
conn.commit()
print(f'Inserted {count} directors')
