"""
strategy_exec.data_access.strategy_task — 读 + 写 strategy_task / strategy_script_audit

📌 写操作都用乐观锁 (version 字段) — 防与 EvTrade signal_consumer 写竞争

策略:
- UPDATE WHERE id=:id AND version=:v (影响行数=0 → 冲突)
- 重试 3 次 (读最新 version 再写)
- 重试失败 → 抛 OptimisticLockError
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

from strategy_exec.data_access.db import get_session

log = logging.getLogger(__name__)

MAX_RETRIES = 3


class OptimisticLockError(Exception):
    """乐观锁冲突 — 重试 3 次仍失败"""


def _json_dumps(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


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
        # JSON 字段解析
        for f in ("params", "backtest_result", "best_params", "positions", "live_signals", "progress", "fields"):
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
) -> bool:
    """写 task.status (乐观锁)

    Returns: True=成功, False=task 不存在
    Raises: OptimisticLockError (3 次重试仍冲突)
    """
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            current_v = row[0]

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
                return True
            log.warning("[task:%d] optimistic lock conflict (attempt %d/%d)", task_id, attempt, MAX_RETRIES)
    raise OptimisticLockError(f"task {task_id} update status conflict after {MAX_RETRIES} retries")


def update_task_progress(task_id: int, progress: Dict[str, Any]) -> bool:
    """写 task.progress 字段 (乐观锁)

    Raises: OptimisticLockError
    """
    payload = _json_dumps(progress)
    for attempt in range(1, MAX_RETRIES + 1):
        with get_session() as session:
            row = session.execute(
                text("SELECT version FROM strategy_task WHERE id = :i LIMIT 1"),
                {"i": task_id},
            ).first()
            if row is None:
                return False
            current_v = row[0]

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