"""
test_create_tasks_batch.py — create_tasks_batch 批量 INSERT 单测 (change 2026-08-30-sweep-worker-queue)

sweep 提交从逐行 create_task (~2N DB 往返) 改 executemany 单往返。
覆盖:
  Case 1: N 组合 → 1 次 executemany INSERT (len(rows)==N), 回填 N 个 id (按 id 升序)
  Case 2: 权限校验只查 1 次 Strategy (不是 N 次)
  Case 3: 策略不存在 → ValueError, 不 INSERT
  Case 4: 权限不匹配 (strategy.user_id != user_id) → ValueError
  Case 5: combos 为空 → ValueError
  Case 6: 回填 id 数 != combos 数 → ValueError

策略: mock get_engine / Strategy.query_one, 不打真实 DB (无生产写入)。
"""
import pytest

from server.services.script_strategy.tasks import create_tasks_batch


def _mock_engine(insert_rows_count, backfill_ids):
    """构造 mock engine: begin() → conn; conn.execute(INSERT,rows) 记 rows;
    conn.execute(SELECT id) 返 backfill_ids 的 mappings."""
    from unittest.mock import MagicMock

    calls = {"insert": None, "select_count": 0}

    def _execute(sql, params=None):
        s = str(sql)
        if "INSERT" in s:
            calls["insert"] = params  # executemany 的 rows 列表
            return MagicMock()
        # SELECT id ... ORDER BY id
        calls["select_count"] += 1
        res = MagicMock()
        res.mappings.return_value.all.return_value = [{"id": i} for i in backfill_ids]
        return res

    conn = MagicMock()
    conn.execute.side_effect = _execute
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    engine.begin.return_value.__exit__.return_value = False
    return engine, calls


def test_create_tasks_batch_single_executemany():
    from unittest.mock import patch, MagicMock
    from server.tables import Strategy
    from server.tables.base import get_engine

    strat = MagicMock()
    strat._data = {"user_id": 1}

    engine, calls = _mock_engine(3, [101, 102, 103])
    with patch.object(Strategy, "query_one", return_value=strat) as q, \
         patch("server.tables.base.get_engine", return_value=engine):
        ids = create_tasks_batch(
            user_id=1, strategy_id=10, stock_code="159992.SZ",
            combos=[{"a": 1}, {"a": 2}, {"a": 3}],
            batch_no=7, mode="backtest",
        )
    assert ids == [101, 102, 103]
    # 1 次 executemany, 3 行
    assert calls["insert"] is not None
    assert len(calls["insert"]) == 3
    # Strategy 只查 1 次
    assert q.call_count == 1


def test_create_tasks_batch_permission_strict():
    from unittest.mock import patch, MagicMock
    from server.tables import Strategy

    engine, calls = _mock_engine(1, [1])
    with patch("server.tables.base.get_engine", return_value=engine):
        # 策略不存在
        with patch.object(Strategy, "query_one", return_value=None):
            with pytest.raises(ValueError, match="不存在"):
                create_tasks_batch(user_id=1, strategy_id=10, stock_code="X",
                                   combos=[{"a": 1}], batch_no=1)
        # 权限不匹配
        strat = MagicMock(); strat._data = {"user_id": 999}
        with patch.object(Strategy, "query_one", return_value=strat):
            with pytest.raises(ValueError, match="不属于"):
                create_tasks_batch(user_id=1, strategy_id=10, stock_code="X",
                                   combos=[{"a": 1}], batch_no=1)


def test_create_tasks_batch_empty_combos_rejected():
    from unittest.mock import patch, MagicMock
    from server.tables import Strategy
    strat = MagicMock(); strat._data = {"user_id": 1}
    with patch.object(Strategy, "query_one", return_value=strat):
        with pytest.raises(ValueError, match="不能为空"):
            create_tasks_batch(user_id=1, strategy_id=10, stock_code="X",
                               combos=[], batch_no=1)


def test_create_tasks_batch_backfill_mismatch_raises():
    from unittest.mock import patch, MagicMock
    from server.tables import Strategy

    strat = MagicMock(); strat._data = {"user_id": 1}
    # 回填 id 数 (2) != combos 数 (3) → ValueError
    engine, _ = _mock_engine(3, [101, 102])
    with patch.object(Strategy, "query_one", return_value=strat), \
         patch("server.tables.base.get_engine", return_value=engine):
        with pytest.raises(ValueError, match="回填"):
            create_tasks_batch(user_id=1, strategy_id=10, stock_code="X",
                               combos=[{"a": 1}, {"a": 2}, {"a": 3}], batch_no=7)


def test_create_tasks_batch_includes_metric_and_status():
    from unittest.mock import patch, MagicMock
    from server.tables import Strategy

    strat = MagicMock(); strat._data = {"user_id": 1}
    engine, calls = _mock_engine(2, [1, 2])
    with patch.object(Strategy, "query_one", return_value=strat), \
         patch("server.tables.base.get_engine", return_value=engine):
        create_tasks_batch(
            user_id=1, strategy_id=10, stock_code="159992.SZ",
            combos=[{"a": 1}, {"a": 2}], batch_no=7, mode="backtest",
            status="queued", metric="sharpe",
        )
    # 每行带 status/metric/batch_no
    for row in calls["insert"]:
        assert row["status"] == "queued"
        assert row["metric"] == "sharpe"
        assert row["batch_no"] == 7
        assert row["mode"] == "backtest"
