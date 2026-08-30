"""
test_worker_queue_dataaccess.py — worker 队列 data_access 单测 (change 2026-08-30-sweep-worker-queue)

覆盖:
  claim_next_queued:
    - 领到行 → UPDATE 执行, 返 {task_id, run_generation=cur+1, params 解析}
    - 队列空 (SELECT None) → 返 None
    - 竞争失败 (UPDATE rowcount=0) → 返 None
    - gen_cap 给定 → SQL 含 run_generation < :gc + 参数
  requeue_or_fail_on_timeout:
    - gen >= max_retries → UPDATE failed, 返 'failed'
    - gen <  max_retries → UPDATE queued, 返 'requeued'
  代际守卫 (update_task_status / update_task_progress):
    - 行 run_generation != 传入 gen → 静默返 False (不 UPDATE)
    - 行 run_generation == gen → 正常 UPDATE
    - gen=None → 不过滤 (正常 UPDATE)

策略: mock get_session (不打真实 DB), 与 test_audit_batch_write 同模式。
"""
from unittest.mock import MagicMock, patch

import strategy_exec.data_access.strategy_task as st


def _mock_session(execute_side_effect):
    """构造 mock session: execute 按顺序返回 execute_side_effect 列表."""
    session = MagicMock()
    if isinstance(execute_side_effect, list):
        session.execute.side_effect = execute_side_effect
    else:
        session.execute.side_effect = execute_side_effect
    return session


def _session_ctx(session):
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    return ctx


# ─────────────── claim_next_queued ───────────────


def test_claim_returns_task_with_incremented_gen():
    # SELECT 行: (id=10, run_generation=1, params='{"a":1}')
    sel = MagicMock(); sel.first.return_value = (10, 1, '{"a": 1}')
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([sel, upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.claim_next_queued(strategy_id=100, batch_no=5, execution_pid=1234, gen_cap=None)
    assert out == {"task_id": 10, "run_generation": 2, "params": {"a": 1}}
    # UPDATE SQL 含 run_generation+1 (ng=2) 和 gen 校验 (cg=1)
    upd_sql = str(session.execute.call_args_list[1][0][0])
    assert "run_generation = :ng" in upd_sql
    assert "run_generation = :cg" in upd_sql


def test_claim_empty_queue_returns_none():
    sel = MagicMock(); sel.first.return_value = None
    session = _mock_session([sel])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.claim_next_queued(strategy_id=100, batch_no=5, execution_pid=1, gen_cap=None)
    assert out is None


def test_claim_contention_rowcount0_returns_none():
    sel = MagicMock(); sel.first.return_value = (10, 1, "null")
    upd = MagicMock(); upd.rowcount = 0
    session = _mock_session([sel, upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.claim_next_queued(strategy_id=100, batch_no=5, execution_pid=1, gen_cap=None)
    assert out is None


def test_claim_gen_cap_adds_filter_clause():
    sel = MagicMock(); sel.first.return_value = (10, 1, "null")
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([sel, upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.claim_next_queued(strategy_id=100, batch_no=5, execution_pid=1, gen_cap=3)
    # SELECT SQL 含 gen 上限过滤
    sel_sql = str(session.execute.call_args_list[0][0][0])
    assert "run_generation < :gc" in sel_sql
    # SELECT 参数含 gc=3
    sel_params = session.execute.call_args_list[0][0][1]
    assert sel_params.get("gc") == 3
    assert out is not None


# ─────────────── requeue_or_fail_on_timeout ───────────────


def test_requeue_fail_when_retries_exhausted():
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.requeue_or_fail_on_timeout(task_id=10, run_generation=3, max_retries=3)
    assert out == "failed"
    sql = str(session.execute.call_args_list[0][0][0])
    assert "status = 'failed'" in sql


def test_requeue_requeue_when_under_limit():
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.requeue_or_fail_on_timeout(task_id=10, run_generation=1, max_retries=3)
    assert out == "requeued"
    sql = str(session.execute.call_args_list[0][0][0])
    assert "status = 'queued'" in sql


# ─────────────── 代际守卫 (update_task_status / update_task_progress) ───────────────


def _status_session(row_version_gen, upd_rowcount=1):
    """SELECT (version, run_generation) → row_version_gen; UPDATE rowcount=upd_rowcount."""
    sel = MagicMock(); sel.first.return_value = row_version_gen
    upd = MagicMock(); upd.rowcount = upd_rowcount
    return _mock_session([sel, upd])


def test_status_guard_stale_gen_returns_false_no_update():
    # 行 gen=2, 传入 gen=1 (孤儿线程) → 应静默 False, 不执行 UPDATE
    sel = MagicMock(); sel.first.return_value = (5, 2)  # version, run_generation
    session = _mock_session([sel])  # 只给 SELECT; 若误调 UPDATE 会 IndexError
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.update_task_status(task_id=10, status="finished", run_generation=1)
    assert out is False
    # 只执行了 SELECT, 没执行 UPDATE
    assert session.execute.call_count == 1


def test_status_guard_matching_gen_proceeds():
    # 行 gen=1, 传入 gen=1 → 正常 UPDATE 成功
    sel = MagicMock(); sel.first.return_value = (5, 1)
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([sel, upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.update_task_status(task_id=10, status="finished", run_generation=1)
    assert out is True
    assert session.execute.call_count == 2


def test_status_guard_none_gen_no_filter():
    # gen=None → 不过滤, 正常 UPDATE
    sel = MagicMock(); sel.first.return_value = (5, 99)  # 行 gen 无关
    upd = MagicMock(); upd.rowcount = 1
    session = _mock_session([sel, upd])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.update_task_status(task_id=10, status="finished", run_generation=None)
    assert out is True


def test_progress_guard_stale_gen_returns_false():
    sel = MagicMock(); sel.first.return_value = (5, 2)  # 行 gen=2
    session = _mock_session([sel])
    with patch.object(st, "get_session", side_effect=lambda: _session_ctx(session)):
        out = st.update_task_progress(task_id=10, progress={"phase": "running"}, run_generation=1)
    assert out is False
    assert session.execute.call_count == 1
