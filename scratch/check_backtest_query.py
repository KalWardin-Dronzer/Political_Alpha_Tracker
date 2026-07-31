import sqlite3
conn = sqlite3.connect('data/cache.sqlite')
rows = conn.execute("SELECT a.scrip_code, a.date, c.cin, c.name FROM announcements a JOIN companies c ON a.scrip_code = c.scrip_code WHERE a.is_contract = 1 AND a.date >= date('now', '-5 years')").fetchall()
print('Total rows:', len(rows))
for r in rows:
    print(r)
