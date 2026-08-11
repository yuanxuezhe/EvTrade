"""
server/services/script_strategy — script + strategy + task 业务服务层 (facade)

职责: Script/Strategy/Task CRUD (直接读写 strategy_script / strategy / strategy_task /
strategy_script_audit) + 回测批次生成 (param_ranges 类型驱动)。纯回测 (v125): 实盘门禁已移除。
运行时 (回测/实盘) 已迁移到独立服务 strategy_exec (2026-08-09 strategy-exec-service),
本模块不启动任何引擎线程。

外部唯一入口: `from server.services import script_strategy as svc`
  - scripts.py    — Script CRUD (list / get / get_by_name / create / update / delete)
  - strategies.py — Strategy CRUD (list/get/create/update/delete)
  - batches.py    — 回测批次 + 聚合查询 (v123)
  - params.py     — param_ranges 类型驱动展开
  - tasks.py      — Task CRUD (list / get / create / delete / logs / signals / audit)
"""
from server.services.script_strategy.scripts import (
    list_scripts,
    get_script,
    get_script_by_name,
    create_script,
    update_script,
    delete_script,
)
from server.services.script_strategy.strategies import (
    StrategyError,
    list_strategies,
    get_strategy,
    create_strategy,
    update_strategy,
    delete_strategy,
)
from server.services.script_strategy.batches import (
    create_backtest_batch,
    list_batches,
    list_batch_tasks,
    retest_batch,
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
    "StrategyError",
    "list_scripts", "get_script", "get_script_by_name",
    "create_script", "update_script", "delete_script",
    "list_strategies", "get_strategy", "create_strategy",
    "update_strategy", "delete_strategy",
    "create_backtest_batch", "list_batches", "list_batch_tasks",
    "retest_batch",
    "list_tasks", "get_task", "create_task", "delete_task",
    "get_task_logs", "get_task_signals", "get_task_audit",
]
