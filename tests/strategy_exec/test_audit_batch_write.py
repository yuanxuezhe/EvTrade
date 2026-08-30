"""
test_audit_batch_write.py — write_audit_batch 单测 (change 2026-08-30-audit-batch-write)

覆盖:
  Case 1: 单批 INSERT (rows < 1000) 一次性 executemany
  Case 2: 多批 INSERT (rows > 1000) 自动分批, commit 多次
  Case 3: 空 list 跳过 (返 0)
  Case 4: 字段序列化 (indicators / payload JSON 正确)
  Case 5: DB 异常 fail-safe (返 0, log.warning)

策略:
  - mock session.execute 不打真实 DB (快, 无副作用)
  - 验证 execute 调用次数 (单批 = 1 次, 10批 = 10 次)
  - 验证 SQL 参数正确 (含 JSON 序列化)
"""
from unittest.mock import MagicMock, patch
import pytest

from strategy_exec.data_access.strategy_task import write_audit_batch


def _make_rows(n: int, task_id: int = 999):
    """生成 n 行测试 audit rows."""
    return [
        {
            "task_id": task_id,
            "stime": f"2099010{i + 1:02d}093100",
            "trd_date": "20990101",
            "phase": "bar",
            "trigger_type": "BUY" if i % 2 == 0 else "SELL",
            "stock_code": "TEST.BATCH",
            "price": 100.0 + i,
            "volume": 100 + i,
            "indicators": {"rsi": 50.0 + i} if i % 3 == 0 else None,
            "state": None,
            "msg": f"test msg {i}",
            "order_no": "",
            "payload": {"order_id": f"oid_{i}"} if i % 5 == 0 else None,
        }
        for i in range(n)
    ]


# ─────────────── Case 1: 单批 (rows < 1000) ───────────────


def test_single_batch_insert():
    """rows < batch_size=1000 → 单次 executemany + 1 次 commit"""
    rows = _make_rows(50)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows)

    # 单批 → session.execute 调用 1 次
    assert mock_session.execute.call_count == 1
    # commit 1 次
    assert mock_session.commit.call_count == 1
    # 返 50
    assert result == 50


# ─────────────── Case 2: 多批 (rows > 1000) ───────────────


def test_multi_batch_insert():
    """rows > batch_size=1000 → 自动分批 (3 批: 1000 + 1000 + 30 = 2030 rows)"""
    rows = _make_rows(2030)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows)

    # 3 批 → session.execute 调用 3 次
    assert mock_session.execute.call_count == 3
    # commit 3 次
    assert mock_session.commit.call_count == 3
    # 返 2030
    assert result == 2030
    # 验证第一/第二批都是 1000 (executemany 接受列表)
    first_call_args = mock_session.execute.call_args_list[0]
    assert len(first_call_args[0][1]) == 1000  # params list


def test_multi_batch_exact_3000():
    """rows = 3000 → 3 批 (每批 1000)"""
    rows = _make_rows(3000)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows)

    assert mock_session.execute.call_count == 3
    assert result == 3000


# ─────────────── Case 3: 空 list ───────────────


def test_empty_rows_skips():
    """rows=[] → 跳过, 返 0, 不调用 session.execute"""
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch([])

    assert result == 0
    assert mock_session.execute.call_count == 0


# ─────────────── Case 4: 字段序列化 ───────────────


def test_field_serialization_json():
    """indicators / payload 字段序列化 (走 _json_dumps)"""
    rows = [{
        "task_id": 999,
        "stime": "20990101093100",
        "trd_date": "20990101",
        "phase": "bar",
        "trigger_type": "BUY",
        "stock_code": "TEST.BATCH",
        "price": 100.0,
        "volume": 100,
        "indicators": {"rsi": 50.0, "macd": 1.5},
        "state": None,
        "msg": "test",
        "order_no": "",
        "payload": {"order_id": "oid_1", "qty": 100},
    }]
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        write_audit_batch(rows)

    # 验证 params 含 JSON 序列化结果
    call_args = mock_session.execute.call_args_list[0]
    params_list = call_args[0][1]  # executemany params
    assert len(params_list) == 1
    p = params_list[0]
    # indicators / payload → JSON 字符串
    assert '"rsi": 50.0' in p["ind"] or '"rsi":50.0' in p["ind"]
    assert '"order_id": "oid_1"' in p["payload"] or '"order_id":"oid_1"' in p["payload"]
    # None 字段 → None
    assert p["state"] is None


def test_field_serialization_none_passthrough():
    """indicators=None / payload=None → DB NULL (不是字符串 'null')"""
    rows = [{
        "task_id": 999,
        "stime": "20990101093100",
        "trd_date": "20990101",
        "phase": "bar",
        "trigger_type": "BUY",
        "stock_code": "TEST.BATCH",
        "price": 100.0,
        "volume": 100,
        "indicators": None,
        "state": None,
        "msg": "",
        "order_no": "",
        "payload": None,
    }]
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        write_audit_batch(rows)

    call_args = mock_session.execute.call_args_list[0]
    params_list = call_args[0][1]
    p = params_list[0]
    assert p["ind"] is None
    assert p["payload"] is None


# ─────────────── Case 5: DB 异常 fail-safe ───────────────


def test_db_exception_returns_zero():
    """session.execute raise → log.warning + 返 0 (不影响调用方)"""
    rows = _make_rows(10)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("MySQL connection lost")
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows)

    # fail-safe: 返 0
    assert result == 0


def test_db_exception_in_middle_returns_partial():
    """第二批失败 → 已写的条数也返 0 (fail-safe)"""
    rows = _make_rows(2500)  # 3 批: 1000 + 1000 + 500
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        # 第二批 raise
        mock_session.execute.side_effect = [
            MagicMock(),  # 第一批 OK
            RuntimeError("second batch failed"),  # 第二批 raise
            MagicMock(),  # 第三批不会执行 (异常提前)
        ]
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows)

    # fail-safe: 返 0 (不是 partial 1000)
    assert result == 0


# ─────────────── Case 6: batch_size 参数 ───────────────


def test_custom_batch_size():
    """batch_size=500 自定义 → 分批为 500/批"""
    rows = _make_rows(1200)  # 1200 / 500 = 3 批 (500 + 500 + 200)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows, batch_size=500)

    assert mock_session.execute.call_count == 3
    assert result == 1200


def test_batch_size_one_legacy_mode():
    """batch_size=1 → 退化为逐条 (与 write_audit 等价)"""
    rows = _make_rows(5)
    with patch("strategy_exec.data_access.strategy_task.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = mock_session
        result = write_audit_batch(rows, batch_size=1)

    # 5 批
    assert mock_session.execute.call_count == 5
    assert result == 5