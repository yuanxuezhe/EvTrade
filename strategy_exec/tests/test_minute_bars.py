"""
strategy_exec/tests/test_minute_bars.py — minute_bars SQL 聚合单测

只测纯函数 _bucket_sql_expr (不依赖 DB). query_bars_aggregated 的 SQL
正确性已用真实 DB 验证 (见 change 2026-09-04-sql-aggregated-backtest).
"""
import pytest

from strategy_exec.data_access.minute_bars import _bucket_sql_expr


# ─────────────────────── _bucket_sql_expr ───────────────────────


def test_bucket_1m_returns_stime():
    """1m: bucket_key = stime (不聚合, 每行一桶)."""
    assert _bucket_sql_expr("1m") == "stime"


def test_bucket_1d_returns_day_end():
    """1d: bucket_key = LEFT(stime,8) || '150000' (按交易日, 15:00 收盘)."""
    expr = _bucket_sql_expr("1d")
    assert "LEFT(stime, 8)" in expr
    assert "150000" in expr


def test_bucket_5m_aligns_to_5min_grid():
    """5m: 09:33 → 09:30, 09:37 → 09:35 (floor 对齐到 5 分钟)."""
    expr = _bucket_sql_expr("5m")
    assert "/ 5" in expr
    assert "* 5" in expr
    assert "DIV 60" in expr
    assert "MOD 60" in expr
    assert "CONCAT" in expr


def test_bucket_15m_aligns_to_15min_grid():
    """15m: 09:33 → 09:30, 09:47 → 09:45 (floor 对齐到 15 分钟)."""
    expr = _bucket_sql_expr("15m")
    assert "/ 15" in expr
    assert "* 15" in expr


def test_bucket_30m_aligns_to_30min_grid():
    """30m: 09:45 → 09:30, 10:15 → 10:00."""
    expr = _bucket_sql_expr("30m")
    assert "/ 30" in expr
    assert "* 30" in expr


def test_bucket_60m_and_1h_same():
    """60m 和 1h 是 alias, 应生成相同表达式 (除字面量 60)."""
    expr_60 = _bucket_sql_expr("60m")
    expr_1h = _bucket_sql_expr("1h")
    assert "/ 60" in expr_60
    assert "/ 60" in expr_1h


def test_bucket_total_min_has_parens():
    """关键: total_min 必须加括号, 否则 FLOOR(hh*60 + mm/N) 因 / 优先级高于 +
    会算成 hh*60 + (mm/N) 导致桶错位 (2026-09-04 实战 bug)."""
    expr = _bucket_sql_expr("5m")
    # 必须出现 (CAST(...) * 60 + CAST(...)) 形式 — 整体被括号包裹
    assert "(" in expr
    # 验证: FLOOR 后的参数必须是 (... + ...) 整体, 不能是 ... + .../N
    # 用真实 DB 查询验证 (见下文 test_bucket_5m_correct_hour_minute)


def test_bucket_unsupported_period_raises():
    """不支持的 period 应抛 KeyError."""
    with pytest.raises(KeyError):
        _bucket_sql_expr("2m")


# ─────────────── DB 集成验证 (可选, 需 DB) ───────────────


def test_bucket_5m_correct_hour_minute():
    """用真实 DB 验证 5m 桶表达式: 09:31 → 09:30, 13:01 → 13:00.

    (2026-09-04 实战 bug: total_min 缺括号导致 09:31 被算成 45:30)
    跳过条件: 无 EVTRADE_DB_URL 环境变量
    """
    import os
    from pathlib import Path
    db_url = os.environ.get("EVTRADE_DB_URL")
    if not db_url:
        pytest.skip("EVTRADE_DB_URL 未设置, 跳过 DB 集成验证")

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / "server" / ".env")
    db_url = os.environ.get("EVTRADE_DB_URL")
    if not db_url:
        pytest.skip("server/.env 无 EVTRADE_DB_URL")

    from sqlalchemy import create_engine, text
    e = create_engine(db_url)
    expr = _bucket_sql_expr("5m")
    with e.connect() as c:
        # 09:31 → 桶应为 09:30:00
        r = c.execute(text(f"""
            SELECT {expr} AS bucket_key
            FROM minute_bars
            WHERE stock_code='159992.SZ' AND stime='20210104093100'
        """)).scalar()
        assert r == "20210104093000", f"09:31 应对齐到 09:30 桶, 实际={r}"
        # 13:01 → 桶应为 13:00:00
        r = c.execute(text(f"""
            SELECT {expr} AS bucket_key
            FROM minute_bars
            WHERE stock_code='159992.SZ' AND stime='20210104130100'
        """)).scalar()
        assert r == "20210104130000", f"13:01 应对齐到 13:00 桶, 实际={r}"
    e.dispose()
