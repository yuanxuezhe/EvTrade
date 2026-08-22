"""
2026-07-28-add-assets-last-asset.py — assets 表加 last_asset 列

变更:
- assets 表加 last_asset FLOAT NOT NULL DEFAULT 0.0
  - 期初总资产 (do_reconcile 系统初始化时计算: 可用资金 + sum(昨收 * 持仓))
  - 当天不变 (供前端算当日盈亏 = 总资产 - last_asset)

幂等性:
- INFORMATION_SCHEMA.COLUMNS 探测列存在
- 默认 0 不需回填

执行:
    python server/migrations/2026-07-28-add-assets-last-asset.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.getcwd() != ROOT:
    os.chdir(ROOT)
sys.path.insert(0, ROOT)

from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError

from server.infra.db import engine as _engine
from sqlalchemy import create_engine as _create_engine
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, 'server', '.env'))


def column_exists(conn, table, column):
    insp = inspect(conn)
    cols = insp.get_columns(table)
    return any(c['name'] == column for c in cols)


def main():
    with _engine.connect() as conn:
        if column_exists(conn, 'assets', 'last_asset'):
            print('[skip] assets.last_asset 已存在, 无需 ALTER')
            return 0

    sql = "ALTER TABLE `assets` ADD COLUMN `last_asset` FLOAT NOT NULL DEFAULT 0.0 AFTER `total_asset`"
    print(f'[exec] {sql}')

    admin_url = os.environ.get('EVTRADE_DB_ADMIN_URL') or os.environ.get('EVTRADE_DB_URL', '')
    if not admin_url:
        load_dotenv(os.path.join(ROOT, 'server', '.env'))
        admin_url = os.environ.get('EVTRADE_DB_ADMIN_URL') or os.environ.get('EVTRADE_DB_URL', '')
    admin_eng = _create_engine(admin_url)
    with admin_eng.begin() as conn:
        conn.execute(text(sql))
    admin_eng.dispose()

    with _engine.connect() as conn:
        if not column_exists(conn, 'assets', 'last_asset'):
            print('[ERR] ALTER 后列仍不存在', file=sys.stderr)
            return 1
    print('[OK] assets.last_asset 已加入')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SQLAlchemyError as e:
        print(f'[FATAL] {e}', file=sys.stderr)
        sys.exit(2)
