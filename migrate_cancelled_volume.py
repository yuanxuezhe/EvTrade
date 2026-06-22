"""一次性迁移脚本: 给 orders 表加 cancelled_volume 列"""
import os
import sqlite3

for path in ['evtrade.db', 'data/evtrade.db', 'server/evtrade.db', 'server/data/evtrade.db']:
    if os.path.exists(path):
        db_path = path
        break
else:
    print('evtrade.db not found')
    raise SystemExit(1)

print('db:', db_path)
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("PRAGMA table_info(orders)")
cols = [r[1] for r in cur.fetchall()]
print('orders cols before:', cols)
if 'cancelled_volume' not in cols:
    cur.execute('ALTER TABLE orders ADD COLUMN cancelled_volume INTEGER NOT NULL DEFAULT 0')
    conn.commit()
    print('ALTER TABLE ok')
else:
    print('cancelled_volume already exists, skip')
cur.execute("PRAGMA table_info(orders)")
print('orders cols after:', [r[1] for r in cur.fetchall()])
conn.close()
