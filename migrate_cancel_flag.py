"""一次性迁移脚本: 给 orders 加 order_flag + trades 加 trade_type (v9 撤单流水)"""
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

# orders.order_flag
cur.execute("PRAGMA table_info(orders)")
order_cols = [r[1] for r in cur.fetchall()]
print('orders cols before:', order_cols)
if 'order_flag' not in order_cols:
    cur.execute('ALTER TABLE orders ADD COLUMN order_flag INTEGER NOT NULL DEFAULT 0')
    conn.commit()
    print('ALTER TABLE orders ADD order_flag ok')
else:
    print('order_flag already exists, skip')

# trades.trade_type
cur.execute("PRAGMA table_info(trades)")
trade_cols = [r[1] for r in cur.fetchall()]
print('trades cols before:', trade_cols)
if 'trade_type' not in trade_cols:
    cur.execute('ALTER TABLE trades ADD COLUMN trade_type INTEGER NOT NULL DEFAULT 0')
    conn.commit()
    print('ALTER TABLE trades ADD trade_type ok')
else:
    print('trade_type already exists, skip')

cur.execute("PRAGMA table_info(orders)")
print('orders cols after:', [r[1] for r in cur.fetchall()])
cur.execute("PRAGMA table_info(trades)")
print('trades cols after:', [r[1] for r in cur.fetchall()])
conn.close()
