"""
server/services/script_strategy — script + task 业务服务层 (facade)

职责: Script/Task CRUD (直接读写 strategy_script / strategy_task / strategy_script_audit)。
运行时 (回测/实盘) 已迁移到独立服务 strategy_exec (2026-08-09 strategy-exec-service),
本模块不启动任何引擎线程。

外部唯一入口: `from server.services import script_strategy as svc`
  - scripts.py — Script CRUD (list / get / get_by_name / create / update / delete)
  - tasks.py   — Task CRUD (list / get / create / delete / logs / signals / audit)
"""
from server.services.script_strategy.scripts import (
    list_scripts,
    get_script,
    get_script_by_name,
    create_script,
    update_script,
    delete_script,
)
from server.services.script_strategy.tasks import (
    list_tasks,
    get_task,
    create_task,
    delete_task,
    get_task_logs,
    get_task_signals,
    get_task_audit,
)

__all__ = [
    "list_scripts", "get_script", "get_script_by_name",
    "create_script", "update_script", "delete_script",
    "list_tasks", "get_task", "create_task", "delete_task",
    "get_task_logs", "get_task_signals", "get_task_audit",
]
