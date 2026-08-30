"""strategy_exec.data_access — DB 数据访问层 (与 EvTrade 共享 MySQL)"""

from strategy_exec.data_access.db import get_engine, get_session, dispose_engine
from strategy_exec.data_access.strategy_script import get_script
from strategy_exec.data_access.strategy_task import (
    get_task,
    get_batch_tasks,
    claim_next_queued,
    requeue_or_fail_on_timeout,
    update_task_metric,
    set_run_generation,
    get_run_generation,
    update_task_status,
    update_task_progress,
    write_audit,
    append_live_signals,
    update_strategy_best_params,
)

__all__ = [
    "get_engine", "get_session", "dispose_engine",
    "get_script",
    "get_task", "get_batch_tasks",
    "claim_next_queued", "requeue_or_fail_on_timeout", "update_task_metric",
    "set_run_generation", "get_run_generation",
    "update_task_status", "update_task_progress", "write_audit",
    "append_live_signals",
    "update_strategy_best_params",
]