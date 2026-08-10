"""
test_strategy_endpoints.py — Phase 5 EvTrade 转发层测试

覆盖 v122+ of `2026-08-10-strategy-params-sweep-best-live`:
- _convert.task_row_to_dict 加 4 字段 (sweep_id/sweep_metric/sweep_total/backtest_metric_value)
- _extract_metric_value: sharpe / total_return / sweep summary best_metric_value / 空 result
- list_tasks service: 新 filter (script_id/has_best_params/limit) — 用 mock DB 测 SQL 拼接

不测 HTTP endpoint 整体 (需要 DB fixture + httpx mock, 复杂; 现有 test_holdings_api.py 那种 fresh_db 风格)
"""
import os
import sys
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SERVER_DIR = os.path.join(_PROJECT_ROOT, "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

import pytest


# ──── 1. _extract_metric_value 单测 ────

def test_extract_metric_value_sharpe():
    """单 run + result 含 sharpe → 返 sharpe"""
    from server.services.script_strategy._convert import _extract_metric_value
    result = {"sharpe": 1.82, "pnl": 1000, "initial_cash": 100000}
    assert _extract_metric_value(result) == 1.82


def test_extract_metric_value_sweep_summary_preferred():
    """sweep summary 优先用 best_metric_value (顶层)"""
    from server.services.script_strategy._convert import _extract_metric_value
    result = {"best_metric_value": 2.5, "sharpe": 0.5, "pnl": 1000}
    assert _extract_metric_value(result) == 2.5


def test_extract_metric_value_fallback_to_total_return():
    """无 sharpe / best_metric_value → 用 pnl / initial_cash"""
    from server.services.script_strategy._convert import _extract_metric_value
    result = {"pnl": 5000, "initial_cash": 100000}
    assert _extract_metric_value(result) == 0.05


def test_extract_metric_value_empty_returns_none():
    """空 / None / 非 dict → None"""
    from server.services.script_strategy._convert import _extract_metric_value
    assert _extract_metric_value(None) is None
    assert _extract_metric_value({}) is None
    assert _extract_metric_value("not a dict") is None


# ──── 2. task_row_to_dict 加 4 字段 ────

def test_task_row_to_dict_includes_sweep_fields():
    """task_row_to_dict 返回值含 sweep_id / sweep_metric / sweep_total / backtest_metric_value"""
    from server.services.script_strategy._convert import task_row_to_dict

    # 模拟一个 sweep combo task 行
    class FakeRow:
        _data = {
            "id": 100,
            "user_id": 6,
            "script_id": "mas_v1",
            "description": "",
            "stock_code": "000001.SZ",
            "mode": "backtest",
            "status": "completed",
            "params": '{"fast": 7}',
            "backtest_result": '{"sharpe": 1.82, "pnl": 5000, "initial_cash": 100000}',
            "best_params": '{"fast": 7}',
            "backtest_start_date": "20260101",
            "backtest_end_date": "20260110",
            "period": "1d",
            "fields": "open,close,high,low",
            "pnl": 5000,
            "positions": "{}",
            "trades_count": 5,
            "live_signals": "[]",
            "progress": "{}",
            "started_at": None,
            "finished_at": None,
            "error_msg": None,
            "created_at": None,
            "updated_at": None,
            # v122+ sweep 字段
            "sweep_id": "abc123def456",
            "sweep_metric": "sharpe",
            "sweep_total": 16,
        }
    out = task_row_to_dict(FakeRow())
    assert out["sweep_id"] == "abc123def456"
    assert out["sweep_metric"] == "sharpe"
    assert out["sweep_total"] == 16
    assert out["backtest_metric_value"] == 1.82


def test_task_row_to_dict_sweep_fields_default_none():
    """旧 task 行 (无 sweep 字段) → 4 字段全 None"""
    from server.services.script_strategy._convert import task_row_to_dict

    class FakeRow:
        _data = {
            "id": 50,
            "user_id": 6,
            "script_id": "mas_v1",
            "description": "",
            "stock_code": "000001.SZ",
            "mode": "backtest",
            "status": "completed",
            "params": "{}",
            "backtest_result": '{"sharpe": 0.5, "pnl": 100}',
            "best_params": '{"fast": 5}',  # 单 run 退化, 也算有 best
            "backtest_start_date": "20260101",
            "backtest_end_date": "20260110",
            "period": "1d",
            "fields": "open,close,high,low",
            "pnl": 100,
            "positions": "{}",
            "trades_count": 0,
            "live_signals": "[]",
            "progress": "{}",
            "started_at": None,
            "finished_at": None,
            "error_msg": None,
            "created_at": None,
            "updated_at": None,
            # 旧 task 行: 无 sweep 字段 (sweep_id 等 NULL)
            "sweep_id": None,
            "sweep_metric": None,
            "sweep_total": None,
        }
    out = task_row_to_dict(FakeRow())
    assert out["sweep_id"] is None
    assert out["sweep_metric"] is None
    assert out["sweep_total"] is None
    assert out["backtest_metric_value"] == 0.5  # 仍能取 sharpe


# ──── 3. list_tasks service 新 filter — 测 SQL 拼接 ────

def test_list_tasks_has_best_params_builds_sql():
    """has_best_params=True → 走自定义 SQL (best_params IS NOT NULL ...)"""
    from server.services.script_strategy import tasks as tasks_svc

    # Mock StrategyTask 不调, 直接测 has_best_params 路径
    fake_rows = [{"id": 100, "user_id": 6, "script_id": "mas_v1", "status": "completed",
                  "best_params": '{"fast": 7}', "params": "{}",
                  "backtest_result": '{"sharpe": 1.82}', "stock_code": "000001.SZ",
                  "description": "", "mode": "backtest",
                  "backtest_start_date": None, "backtest_end_date": None,
                  "period": None, "fields": None, "pnl": 0, "positions": "{}",
                  "trades_count": 0, "live_signals": "[]", "progress": "{}",
                  "started_at": None, "finished_at": None, "error_msg": None,
                  "created_at": None, "updated_at": None,
                  "sweep_id": None, "sweep_metric": None, "sweep_total": None}]
    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.mappings.return_value.all.return_value = fake_rows
    fake_engine.connect.return_value.__enter__.return_value = fake_conn

    with patch("server.tables.base.get_engine", return_value=fake_engine):
        result = tasks_svc.list_tasks(user_id=6, is_admin=False, has_best_params=True, limit=50)

    assert len(result) == 1
    assert result[0]["id"] == 100
    # 验证 SQL 含 best_params 非空判断
    sql_text = fake_conn.execute.call_args[0][0].text
    assert "best_params IS NOT NULL" in sql_text
    assert "user_id = :uid" in sql_text  # 非 admin 加 user 限制
    # 验证 params 传对
    params = fake_conn.execute.call_args[0][1]
    assert params["uid"] == 6
    assert params["lim"] == 50


def test_list_tasks_has_best_params_admin_no_user_filter():
    """admin + has_best_params=True → SQL 不含 user_id 限制"""
    from server.services.script_strategy import tasks as tasks_svc

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.mappings.return_value.all.return_value = []
    fake_engine.connect.return_value.__enter__.return_value = fake_conn

    with patch("server.tables.base.get_engine", return_value=fake_engine):
        tasks_svc.list_tasks(user_id=999, is_admin=True, has_best_params=True, limit=10)

    sql_text = fake_conn.execute.call_args[0][0].text
    assert "best_params IS NOT NULL" in sql_text
    assert "user_id" not in sql_text  # admin 无 user 限制
    params = fake_conn.execute.call_args[0][1]
    assert "uid" not in params
    assert params["lim"] == 10


def test_list_tasks_has_best_params_with_extra_filters():
    """has_best_params + script_id + status → SQL 含所有 AND 条件"""
    from server.services.script_strategy import tasks as tasks_svc

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.mappings.return_value.all.return_value = []
    fake_engine.connect.return_value.__enter__.return_value = fake_conn

    with patch("server.tables.base.get_engine", return_value=fake_engine):
        tasks_svc.list_tasks(
            user_id=6, is_admin=False,
            has_best_params=True, script_id="mas_v1", status="completed", limit=20,
        )

    sql_text = fake_conn.execute.call_args[0][0].text
    assert "script_id = :script_id" in sql_text
    assert "status = :status" in sql_text
    params = fake_conn.execute.call_args[0][1]
    assert params["script_id"] == "mas_v1"
    assert params["status"] == "completed"
    assert params["lim"] == 20


# ──── 4. list_tasks 不传新 filter → 老路径 (query_by_fields) ────

def test_list_tasks_legacy_filters_still_work():
    """只传 status / mode → 走 StrategyTask.query_by_fields 老路径"""
    from server.services.script_strategy import tasks as tasks_svc

    fake_query_result = [MagicMock(), MagicMock()]
    fake_strategy_task = MagicMock()
    fake_strategy_task.query_by_fields.return_value = fake_query_result

    with patch("server.tables.StrategyTask", fake_strategy_task):
        result = tasks_svc.list_tasks(
            user_id=6, is_admin=False, status="completed", mode="backtest",
        )

    # 验证走 query_by_fields, filter 含 user_id + status + mode
    call_args = fake_strategy_task.query_by_fields.call_args[0][0]
    assert call_args["user_id"] == 6
    assert call_args["status"] == "completed"
    assert call_args["mode"] == "backtest"
    assert len(result) == 2


def test_list_tasks_legacy_with_script_id():
    """script_id (无 has_best_params) → 老 query_by_fields 也支持"""
    from server.services.script_strategy import tasks as tasks_svc

    fake_strategy_task = MagicMock()
    fake_strategy_task.query_by_fields.return_value = []

    with patch("server.tables.StrategyTask", fake_strategy_task):
        tasks_svc.list_tasks(
            user_id=6, is_admin=False, script_id="mas_v1",
        )

    call_args = fake_strategy_task.query_by_fields.call_args[0][0]
    assert call_args["script_id"] == "mas_v1"
