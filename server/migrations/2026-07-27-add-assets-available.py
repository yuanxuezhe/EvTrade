"""
2026-07-27-add-assets-available.py — v110 assets 表加 available 列

变更:
- assets 表加 available FLOAT NOT NULL DEFAULT 0.0
  含义: 可用资金 (与 cash 等价; xtquant 协议 cash = EvTrade available)
  来源: rpc_health.py 每 5s 调 qry_asset 时同时写入 cash + available

幂等性:
- 列存在探测 (INFORMATION_SCHEMA.COLUMNS via SQLAlchemy inspect)

执行:
    python server/migrations/2026-07-27-add-assets-available.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import sys
import os

# 让 cwd = EvTrade 项目根
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


def column_exists(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    cols = insp.get_columns(table)
    return any(c['name'] == column for c in cols)


def main() -> int:
    with _engine.connect() as conn:
        if column_exists(conn, 'assets', 'available'):
            print(f'[skip] assets.available 已存在, 无需 ALTER')
            return 0

    sql = "ALTER TABLE `assets` ADD COLUMN `available` FLOAT NOT NULL DEFAULT 0.0 AFTER `cash`"
    print(f'[exec] {sql}')
    admin_url = os.environ.get('EVTRADE_DB_ADMIN_URL') or os.environ.get('EVTRADE_DB_URL', '')
    if not admin_url:
        # v20 fallback 直接读 server/.env
        load_dotenv(os.path.join(ROOT, 'server', '.env'))
        admin_url = os.environ.get('EVTRADE_DB_ADMIN_URL') or os.environ.get('EVTRADE_DB_URL', '')
    admin_url = admin_url.replace('mysql+pymysql://', 'mysql+pymysql://').replace('+pymysql', '+pymysql')
    admin_eng = _create_engine(admin_url)
    with admin_eng.begin() as conn:
        conn.execute(text(sql))
    admin_eng.dispose()

    # 校验
    with _engine.connect() as conn:
        if not column_exists(conn, 'assets', 'available'):
            print('[ERR] ALTER 后列仍不存在', file=sys.stderr)
            return 1
    print('[OK] assets.available 已加入')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SQLAlchemyError as e:
        print(f'[FATAL] {e}', file=sys.stderr)
        sys.exit(2)
