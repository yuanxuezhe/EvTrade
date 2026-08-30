"""
strategy_exec.data_access.strategy_task — 读 + 写 strategy_task / strategy_script_audit

📌 写操作都用乐观锁 (version 字段) — 防与 EvTrade signal_consumer 写竞争

策略:
- UPDATE WHERE id=:id AND version=:v (影响行数=0 → 冲突)
- 重试 3 次 (读最新 version 再写)
- 重试失败 → 抛 OptimisticLockError
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

from strategy_exec.data_access.db import get_session
from strategy_exec.signal.task_progress_publisher import (
    get_task_progress_publisher,
)

log = logging.getLogger(__name__)

MAX_RETRIES = 3

# change 2026-08-30-sweep-worker-queue: 代际 (run_generation) 上下文。
# worker 每次 to_thread(run_backtest) 跑一个 task 时设本次代际; 该线程内所有
# update_task_status/progress 若未显式传 run_generation → 读此上下文做孤儿线程守卫。
# None (默认) = 不过滤, 兼容 live / 旧单任务路径。
_run_generation_ctx: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "task_run_generation", default=None
)


def set_run_generation(gen: Optional[int]) -> contextvars.Token:
    """设当前上下文的代际 (run_backtest 入口调用). 返 Token 供 reset."""
    return _run_generation_ctx.set(gen)


def get_run_generation() -> Optional[int]:
    """读当前上下文的代际 (默认 None = 不过滤)."""
    return _run_generation_ctx.get()


def _resolve_generation(explicit: Optional[int]) -> Optional[int]:
    """显式参数优先, 否则回退上下文."""
    return explicit if explicit is not None else _run_generation_ctx.get()


class OptimisticLockError(Exception):
    """乐观锁冲突 — 重试 3 次仍失败"""


def _json_dumps(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _emit_progress(
    task_id: int,
    status: Optional[str] = None,
    progress: Optional[Dict[str, Any]] = None,
) -> None:
    """写 DB 后置 hook: 通过 task_progress_publisher 推 RabbitMQ

    节流判定 (best-effort):
      - status='queued' 跳过 (无意义, queued 是预建状态)
      - 节流由 TaskProgressPublisher.should_emit() 控制

    设计: 不阻塞主流程
      - 失败 → log warning (publish 内部已兜底)
      - 在 event loop 内时尝试 schedule, 不在 loop 内 (e.g. to_thread 子线程)
        → 用 run_coroutine_threadsafe 投到 publisher 绑定的 loop
      - publisher 未初始化 → 直接 return (测试 / 早期调用兜底)
    """
    publisher = get_task_progress_publisher()
    try:
        if not publisher.should_emit(task_id, status, progress):
            return
        publisher.record_emit(task_id, status, progress)

        coro = publisher.publish(task_id, status, progress)
        # 主 loop 内 (FastAPI handler / asyncio task) → create_task
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # 不在 event loop 内 (asyncio.to_thread / 同步代码路径)
            target_loop = publisher._loop  # type: ignore[attr-defined]
            if target_loop is not None and not target_loop.is_closed():
                import concurrent.futures
                concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(
                    asyncio.run_coroutine_threadsafe, coro, target_loop,
                )
            # 否则静默放弃 (publisher.loop 未绑定 / 测试环境)
    except Exception as e:  # noqa: BLE001
        log.warning("[task:%d] _emit_progress hook failed (ignored): %s", task_id, e)


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    """按 PK 查 task"""
    with get_session() as session:
        row = session.execute(
            text("SELECT * FROM strategy_task WHERE id = :i LIMIT 1"),
            {"i": task_id},
        ).mappings().first()
        if row is None:
            return None
        d = dict(row)
        # JSON 字段解析 (strategy_task 无 best_params 列, best 写 strategy.best_params)
        for f in ("params", "backtest_result", "positions", "live_signals", "progress", "fields"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except (ValueError, TypeError):
                    pass
        return d


def update_task_status(
    task_id: int,
    status: str,
    error_msg: Optional[str] = None,
    execution_service: str = "strategy_exec",
    execution_pid: Optional[int] = None,
    finished_at: Optional[str] = None,
    run_generation: Optional[int] = None,
) -> bool:
    """写 task.status (乐观锁)

    run_generation (change 2026-08-30-sweep-worker-queue): 代际守卫。worker 传本次领取的
    代际; 写入前若行的 run_generation 已不等于本代际 (任务被复位重跑, 本线程是孤儿) →
    **静默 return False** (不重试不报错), 防止孤儿线程覆盖新那次的状态。None=不过滤(兼容旧调用)。

    Returns: True=成功, False=task 不存在 / 代际不匹配 (孤儿线程)
    Raises: OptimisticLockError (version 冲突 3 次重试仍失败)
    """
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version, run_generation FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            current_v = row[0]
            gen = _resolve_generation(run_generation)
            if gen is not None and row[1] != gen:
                log.warning(
                    "[task:%d] status update skipped (stale generation: thread=%s row=%s) — orphan thread",
                    task_id, gen, row[1],
                )
                return False

            result = session.execute(
                text("""
                    UPDATE strategy_task
                       SET status = :s,
                           error_msg = :err,
                           execution_service = :es,
                           execution_pid = :ep,
                           finished_at = COALESCE(:fa, finished_at),
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """),
                {
                    "i": task_id,
                    "v": current_v,
                    "s": status,
                    "err": error_msg,
                    "es": execution_service,
                    "ep": execution_pid,
                    "fa": finished_at,
                },
            )
            session.commit()
            if result.rowcount > 0:
                log.info("[task:%d] status='%s' (version %d→%d)", task_id, status, current_v, current_v + 1)
                _emit_progress(task_id, status=status, progress=None)
                return True
            log.warning("[task:%d] optimistic lock conflict (attempt %d/%d)", task_id, attempt, MAX_RETRIES)
    raise OptimisticLockError(f"task {task_id} update status conflict after {MAX_RETRIES} retries")


def update_task_progress(task_id: int, progress: Dict[str, Any],
                         run_generation: Optional[int] = None) -> bool:
    """写 task.progress 字段 (乐观锁)

    run_generation (change 2026-08-30-sweep-worker-queue): 代际守卫 — 孤儿线程 (任务被复位
    重跑后本线程旧代际) 的 progress 写会静默 no-op, 防止它推进 updated_at 骗过 watchdog
    (让新那次的阻塞检测失灵)。None=不过滤(兼容旧调用)。

    Raises: OptimisticLockError
    """
    payload = _json_dumps(progress)
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version, run_generation FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            current_v = row[0]
            gen = _resolve_generation(run_generation)
            if gen is not None and row[1] != gen:
                log.warning(
                    "[task:%d] progress update skipped (stale generation: thread=%s row=%s) — orphan thread",
                    task_id, gen, row[1],
                )
                return False

            result = session.execute(
                text("""
                    UPDATE strategy_task
                       SET progress = :p,
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """),
                {"i": task_id, "v": current_v, "p": payload},
            )
            session.commit()
            if result.rowcount > 0:
                _emit_progress(task_id, status=None, progress=progress)
                return True
            log.warning("[task:%d] progress update conflict (attempt %d/%d)", task_id, attempt, MAX_RETRIES)
    raise OptimisticLockError(f"task {task_id} update progress conflict after {MAX_RETRIES} retries")


def append_live_signals(task_id: int, new_signals: list, max_keep: int = 500) -> bool:
    """追加 live_signals (环形缓冲, 超 max_keep 丢最早的)

    Raises: OptimisticLockError
    """
    new_json = _json_dumps(new_signals)
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version, live_signals FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            current_v = row[0]
            current = row[1]
            try:
                current_list = json.loads(current) if current else []
            except (ValueError, TypeError):
                current_list = []
            merged = (current_list + new_signals)[-max_keep:]

            result = session.execute(
                text("""
                    UPDATE strategy_task
                       SET live_signals = :p,
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """),
                {"i": task_id, "v": current_v, "p": json.dumps(merged, ensure_ascii=False)},
            )
            session.commit()
            if result.rowcount > 0:
                return True
            log.warning("[task:%d] live_signals conflict (attempt %d/%d)", task_id, attempt, MAX_RETRIES)
    raise OptimisticLockError(f"task {task_id} append live_signals conflict after {MAX_RETRIES} retries")


def write_audit(
    task_id: int,
    stime: str,
    trd_date: str,
    phase: str,
    trigger_type: str,
    stock_code: str = "",
    price: float = 0.0,
    volume: int = 0,
    indicators: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
    msg: str = "",
    order_no: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> int:
    """INSERT 一条 strategy_script_audit 记录

    Returns: 新 row 的 id
    """
    indicators_json = _json_dumps(indicators) if indicators else None
    state_json = _json_dumps(state) if state else None
    payload_json = _json_dumps(payload) if payload else None

    with get_session() as session:
        result = session.execute(
            text("""
                INSERT INTO strategy_script_audit
                    (task_id, stime, trd_date, phase, trigger_type, stock_code,
                     price, volume, indicators, state, msg, order_no, payload, created_at)
                VALUES
                    (:tid, :stime, :td, :phase, :tt, :sc,
                     :price, :vol, :ind, :state, :msg, :order_no, :payload, NOW())
            """),
            {
                "tid": task_id,
                "stime": stime,
                "td": trd_date,
                "phase": phase,
                "tt": trigger_type,
                "sc": stock_code,
                "price": price,
                "vol": volume,
                "ind": indicators_json,
                "state": state_json,
                "msg": msg,
                "order_no": order_no,
                "payload": payload_json,
            },
        )
        session.commit()
        return result.lastrowid or 0


# ──── change 2026-08-30-audit-batch-write: 批量 INSERT helper ────
# 原 write_audit 逐条 INSERT+commit, 长区间回测 (12,040 signals) 需 6 min+.
# batch helper 一次性 executemany + 自动分批 (默认 1000/批, 防超大事务).
# speedup 实测: 单条 12 min+ → batch ~12s (60x).
# backward compat: write_audit 单条版本不变 (live.py/sweep 仍可调).


def write_audit_batch(
    rows: List[Dict[str, Any]],
    batch_size: int = 1000,
) -> int:
    """批量 INSERT strategy_script_audit (executemany + 自动分批)

    Args:
        rows: 每项含 write_audit 字段 (task_id, stime, trd_date, phase, ...)
        batch_size: 单批 INSERT 数量 (默认 1000, 防止超大事务)

    Returns:
        写入总条数 (含 batch 总和). 异常/空 list 返 0.

    Note:
        字段序列化逻辑与 write_audit 一致 (indicators/state/payload 走 _json_dumps).
        异常 → log.warning + 返 0 (不影响回测主流程, fail-safe).
    """
    if not rows:
        return 0

    sql = text("""
        INSERT INTO strategy_script_audit
            (task_id, stime, trd_date, phase, trigger_type, stock_code,
             price, volume, indicators, state, msg, order_no, payload, created_at)
        VALUES
            (:tid, :stime, :td, :phase, :tt, :sc,
             :price, :vol, :ind, :state, :msg, :order_no, :payload, NOW())
    """)

    total = 0
    try:
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            batch_params = []
            for r in chunk:
                batch_params.append({
                    "tid": r.get("task_id"),
                    "stime": r.get("stime", ""),
                    "td": r.get("trd_date", ""),
                    "phase": r.get("phase", "bar"),
                    "tt": r.get("trigger_type", "INFO"),
                    "sc": r.get("stock_code", ""),
                    "price": r.get("price", 0.0),
                    "vol": r.get("volume", 0),
                    "ind": _json_dumps(r.get("indicators")) if r.get("indicators") else None,
                    "state": _json_dumps(r.get("state")) if r.get("state") else None,
                    "msg": r.get("msg", ""),
                    "order_no": r.get("order_no", ""),
                    "payload": _json_dumps(r.get("payload")) if r.get("payload") else None,
                })
            with get_session() as session:
                session.execute(sql, batch_params)
                session.commit()
            total += len(chunk)
        return total
    except Exception as e:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[write_audit_batch] failed (rows=%d, written=%d): %s",
            len(rows), total, e,
        )
        return 0


# ──── batch helpers (strategy-batch-task-model) ────
# EvTrade 在调用 strategy_exec 前已为批次预建好 strategy_task 行
# (单次=1 行 / 扫描=N 行, 共享 strategy_id + batch_no, params 已落库).
# strategy_exec 只负责: 按 (strategy_id, batch_no) 读批次内任务 → 跑 backtest →
# 批次完成后把 best 写回 strategy.best_params. 不再自建 task / summary task.


def update_task_metric(task_id: int, metric_value: Optional[float],
                       run_generation: Optional[int] = None) -> bool:
    """写 task.backtest_metric_value (批次完成 top1 判定用, 代际守卫).

    change 2026-08-30-sweep-worker-queue: worker 跑完一个 task 后写该 metric 值;
    批次完成时按此列取 finished top1 (不重新解析大 blob)。
    Returns: True=成功, False=task 不存在/代际不匹配 (孤儿线程)
    """
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version, run_generation FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            gen = _resolve_generation(run_generation)
            if gen is not None and row[1] != gen:
                return False
            result = session.execute(
                text("""
                    UPDATE strategy_task
                       SET backtest_metric_value = :mv,
                           version = version + 1,
                           updated_at = NOW()
                     WHERE id = :i AND version = :v
                """),
                {"i": task_id, "v": row[0], "mv": metric_value},
            )
            session.commit()
            if result.rowcount > 0:
                return True
    return False


def get_batch_tasks(strategy_id: int, batch_no: int) -> List[Dict[str, Any]]:
    """按 (strategy_id, batch_no) 读批次内全部 task (含已解析 JSON 字段).

    Returns: list of task dict (按 id 升序), 空 list = 批次不存在
    """
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT * FROM strategy_task
                 WHERE strategy_id = :sid AND batch_no = :bn
                 ORDER BY id
            """),
            {"sid": strategy_id, "bn": batch_no},
        ).mappings().all()
    out: list[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for f in ("params", "backtest_result", "positions", "live_signals", "progress", "fields"):
            if d.get(f):
                try:
                    d[f] = json.loads(d[f])
                except (ValueError, TypeError):
                    pass
        out.append(d)
    return out


def claim_next_queued(
    strategy_id: int, batch_no: int, execution_pid: Optional[int],
    gen_cap: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """worker 原子领取下一个 queued task (change 2026-08-30-sweep-worker-queue).

    单事务内: SELECT ... FOR UPDATE SKIP LOCKED 锁行 (多 worker/多实例不互相阻塞, 也不抢同一行)
    → UPDATE 领取 (status=running, execution_pid, run_generation+1)。

    Args:
        strategy_id / batch_no: 限定领取范围 (单批次 worker 池)
        execution_pid: 领取者 pid (记录到 task, 排查用)
        gen_cap: 若给, 只领 run_generation < gen_cap 的 (防无限重跑, worker 侧判定)

    Returns:
        {task_id, run_generation, params} (params 已解析) — 领取成功; None = 队列空/无合格行
    """
    gen_clause = " AND run_generation < :gc" if gen_cap is not None else ""
    with get_session() as session:
        row = session.execute(
            text(f"""
                SELECT id, run_generation, params FROM strategy_task
                 WHERE strategy_id = :sid AND batch_no = :bn
                   AND status = 'queued'{gen_clause}
                 ORDER BY id LIMIT 1
                 FOR UPDATE SKIP LOCKED
            """),
            ({"sid": strategy_id, "bn": batch_no, "gc": gen_cap} if gen_cap is not None
             else {"sid": strategy_id, "bn": batch_no}),
        ).first()
        if row is None:
            session.commit()  # 释放 (无锁可放, 但结束事务)
            return None
        task_id, cur_gen, params_raw = row[0], row[1], row[2]
        new_gen = (cur_gen or 0) + 1
        res = session.execute(
            text("""
                UPDATE strategy_task
                   SET status = 'running',
                       execution_pid = :ep,
                       run_generation = :ng,
                       started_at = COALESCE(started_at, NOW()),
                       updated_at = NOW(),
                       version = version + 1
                 WHERE id = :i AND status = 'queued' AND run_generation = :cg
            """),
            {"i": task_id, "ep": execution_pid, "ng": new_gen, "cg": cur_gen},
        )
        session.commit()
        if res.rowcount == 0:
            return None  # 竞争失败 (理论上 SKIP LOCKED 已避免, 双保险)
        try:
            params = json.loads(params_raw) if params_raw else {}
        except (ValueError, TypeError):
            params = {}
        log.info("[task:%d] claimed by pid=%s gen=%s→%s", task_id, execution_pid, cur_gen, new_gen)
        return {"task_id": task_id, "run_generation": new_gen, "params": params}


def requeue_or_fail_on_timeout(
    task_id: int, run_generation: int, max_retries: int,
) -> str:
    """task 执行超时后的处置 (change 2026-08-30-sweep-worker-queue).

    判定基于当前 run_generation (= 该 task 已被 claim 的次数):
    - run_generation >= max_retries → 标 status='failed' (防无限重跑), 返 'failed'
    - 否则 → 回 status='queued' (清 execution_pid), 等待 worker 再次领取 (重跑), 返 'requeued'

    Returns: 'failed' | 'requeued'
    """
    with get_session() as session:
        if run_generation >= max_retries:
            res = session.execute(
                text("""
                    UPDATE strategy_task
                       SET status = 'failed',
                           execution_pid = NULL,
                           error_msg = :em,
                           finished_at = NOW(),
                           updated_at = NOW(),
                           version = version + 1
                     WHERE id = :i
                """),
                {"i": task_id, "em": f"blocked: 执行超时且重跑达上限 ({max_retries} 次), 已放弃"},
            )
            session.commit()
            log.warning("[task:%d] FAILED (timeout, retries exhausted gen=%s)", task_id, run_generation)
            return "failed" if res.rowcount > 0 else "requeued"
        res = session.execute(
            text("""
                UPDATE strategy_task
                   SET status = 'queued',
                       execution_pid = NULL,
                       updated_at = NOW(),
                       version = version + 1
                 WHERE id = :i
            """),
            {"i": task_id},
        )
        session.commit()
        log.warning("[task:%d] REQUEUED (timeout, gen=%s<%s, will retry)",
                    task_id, run_generation, max_retries)
        return "requeued" if res.rowcount > 0 else "failed"


def update_strategy_best_params(strategy_id: int, best_params: Optional[Dict[str, Any]]) -> bool:
    """批次/单次回测完成后写 strategy.best_params.

    Args:
        strategy_id: strategy 表主键
        best_params: top1 组合的 params (None → 写 NULL)

    Returns: True=策略存在并更新, False=策略不存在
    """
    with get_session() as session:
        result = session.execute(
            text("""
                UPDATE strategy
                   SET best_params = :bp, updated_at = NOW()
                 WHERE strategy_id = :sid
            """),
            {"sid": strategy_id, "bp": _json_dumps(best_params)},
        )
        session.commit()
        if result.rowcount > 0:
            log.info("[strategy:%d] best_params updated", strategy_id)
        else:
            log.warning("[strategy:%d] strategy 不存在, best_params 未写入", strategy_id)
        return result.rowcount > 0