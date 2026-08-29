"""
test_progress_throttle.py — strategy_exec task_progress 节流单测

覆盖节流规则 (与 strategy_exec/signal/task_progress_publisher.py 一一对应):
- status='queued' → 跳过 (无意义)
- 首次推送 (last_emit 无记录) → 推
- status 变化 → 推
- progress.phase 变化 → 推
- bar_idx 增量 < 5% → 跳过
- bar_idx 增量 ≥ 5% 但 < 2s → 跳过
- bar_idx 增量 ≥ 5% 且 ≥ 2s → 推
- status 重复 + progress 不变 → 跳过
- 多 task 独立节流

策略:
- 测纯函数 _should_emit + _record_emit (不连 RabbitMQ)
- 测 TaskProgressPublisher 实例方法 should_emit / record_emit (业务封装)
- 不创建 strategy_task 行 (conftest autouse 清 orders, 但 strategy_task 表无 fixture 清理,
  本测试不操作 DB, 安全)
"""

import pytest

from strategy_exec.signal.task_progress_publisher import (
    THROTTLE_BAR_PCT,
    THROTTLE_MIN_INTERVAL_S,
    TaskProgressPublisher,
    _record_emit,
    _should_emit,
    get_task_progress_publisher,
    reset_for_test,
)


# ─────────────── Constants sanity ───────────────


def test_throttle_constants():
    """节流参数符合提案 (2s/5%)"""
    assert THROTTLE_MIN_INTERVAL_S == 2.0
    assert THROTTLE_BAR_PCT == 0.05


# ─────────────── _should_emit 纯函数规则 ───────────────


def test_should_emit_skips_queued():
    """status='queued' → 跳过 (queued 是预建状态, 推无意义)"""
    last = {}
    assert _should_emit(1, "queued", {"phase": "running"}, last, 1000.0) is False


def test_should_emit_first_push():
    """首次推送 (last_emit 无记录) + 任一参数 → 推"""
    last: dict = {}
    t0 = 1000.0
    # 仅 status
    assert _should_emit(1, "running", None, last, t0) is True
    # 仅 progress
    assert _should_emit(2, None, {"phase": "load_script"}, last, t0) is True


def test_should_emit_no_change_skips():
    """status 不变 + progress 为空 → 跳过"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running"}}
    assert _should_emit(1, "running", None, last, 1001.0) is False


def test_should_emit_status_change_pushes():
    """status 变化 → 推"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running"}}
    assert _should_emit(1, "finished", None, last, 1001.0) is True


def test_should_emit_phase_change_pushes():
    """progress.phase 变化 → 推"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "load_script"}}
    assert _should_emit(1, None, {"phase": "build_cerebro"}, last, 1001.0) is True


def test_should_emit_bar_idx_small_delta_skips():
    """bar_idx 增量 < 5% → 跳过"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running", "bar_idx": 100}}
    # 增量 4% (104-100)/100, 距上次 5s
    assert _should_emit(
        1, None, {"phase": "running", "bar_idx": 104, "total_bars": 100}, last, 1005.0
    ) is False


def test_should_emit_bar_idx_big_delta_but_too_soon_skips():
    """bar_idx 增量 ≥ 5% 但距上次 < 2s → 跳过"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running", "bar_idx": 100}}
    # 增量 10%, 距上次 1s
    assert _should_emit(
        1, None, {"phase": "running", "bar_idx": 110, "total_bars": 100}, last, 1001.0
    ) is False


def test_should_emit_bar_idx_big_delta_after_interval_pushes():
    """bar_idx 增量 ≥ 5% 且距上次 ≥ 2s → 推"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running", "bar_idx": 100}}
    # 增量 10%, 距上次 3s
    assert _should_emit(
        1, None, {"phase": "running", "bar_idx": 110, "total_bars": 100}, last, 1003.0
    ) is True


def test_should_emit_multi_task_isolated():
    """多 task 独立节流 — task 2 首次推, task 1 不受影响"""
    last = {1: {"ts_s": 1000.0, "status": "running", "phase": "running", "bar_idx": 100}}
    # task 2 首次
    assert _should_emit(2, "running", {"phase": "load_script"}, last, 1001.0) is True
    # task 1 同参数 (running, 100, 100, 距 1s) → 应跳过
    assert _should_emit(
        1, None, {"phase": "running", "bar_idx": 104, "total_bars": 100}, last, 1001.0
    ) is False


def test_record_emit_preserves_status_when_not_provided():
    """_record_emit: status=None 时保留上次 status (避免后续比较状态丢失)"""
    last: dict = {1: {"ts_s": 1000.0, "status": "running", "phase": "running"}}
    _record_emit(1, None, {"phase": "build_cerebro"}, last, 1001.0)
    assert last[1]["status"] == "running", "应保留 running"
    assert last[1]["phase"] == "build_cerebro"


# ─────────────── Publisher 实例方法 ───────────────


def test_publisher_instance_should_emit():
    """TaskProgressPublisher 实例方法应走同一节流逻辑"""
    reset_for_test()
    pub = get_task_progress_publisher()

    # 首次推
    assert pub.should_emit(42, "running", {"phase": "load_script"}) is True
    pub.record_emit(42, "running", {"phase": "load_script"})

    # phase 变
    assert pub.should_emit(42, None, {"phase": "build_cerebro"}) is True
    pub.record_emit(42, None, {"phase": "build_cerebro"})

    # 同 phase + 同 status
    assert pub.should_emit(42, None, {"phase": "build_cerebro", "msg": "建中"}) is False


def test_publisher_singleton():
    """get_task_progress_publisher() 返单例"""
    reset_for_test()
    p1 = get_task_progress_publisher()
    p2 = get_task_progress_publisher()
    assert p1 is p2
    reset_for_test()
    p3 = get_task_progress_publisher()
    assert p3 is not p1


def test_publisher_attach_loop_safe_no_loop():
    """attach_loop() 在无 running loop 时不抛错 (可重复调用)"""
    pub = TaskProgressPublisher()
    # 不在 event loop 中 → attach_loop 应静默 OK (loop=None)
    pub.attach_loop()
    pub.attach_loop()  # 幂等
    assert pub._loop is None