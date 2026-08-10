"""strategy_exec.data_access — DB 数据访问层 (与 EvTrade 共享 MySQL)"""

from strategy_exec.data_access.db import get_engine, get_session, dispose_engine
from strategy_exec.data_access.strategy_script import get_script
from strategy_exec.data_access.strategy_task import (
    get_task,
    update_task_status,
    update_task_progress,
    write_audit,
    append_live_signals,
    # v122+ sweep helpers
    create_sweep_task,
    update_sweep_summary,
)

__all__ = [
    "get_engine", "get_session", "dispose_engine",
    "get_script",
    "get_task", "update_task_status", "update_task_progress", "write_audit",
    "append_live_signals",
    # v122+ sweep
    "create_sweep_task", "update_sweep_summary",
]