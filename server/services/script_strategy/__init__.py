"""
server/services/script_strategy — script + strategy + task 业务服务层 (facade)

职责: Script/Strategy/Task CRUD (直接读写 strategy_script / strategy / strategy_task /
strategy_script_audit) + 回测批次生成 (param_ranges 类型驱动)。纯回测: 无实盘门禁。
运行时 (回测) 在独立服务 strategy_exec,
本模块不启动任何引擎线程。

外部唯一入口: `from server.services import script_strategy as svc`
  - scripts.py    — Script CRUD (list / get / get_by_name / create / update / delete)
  - strategies.py — Strategy CRUD (list/get/create/update/delete)
  - batches.py    — 回测批次 + 聚合查询
  - params.py     — param_ranges 类型驱动展开
  - tasks.py      — Task CRUD (list / get / create / delete / logs / signals / audit)
  - strategy_orders.py — 策略下单母单 (create/list/get/start/stop/close)
"""
from server.services.script_strategy.scripts import (
    list_scripts,
    get_script,
    get_script_by_name,
    create_script,
    auto_create_script,
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
from server.services.script_strategy.strategy_orders import (
    STATUS_CLOSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    ALL_STATUSES,
    list_strategy_orders,
    get_strategy_order,
    list_strategy_order_children,
    create_strategy_order,
    close_strategy_order,
)
from server.services.script_strategy.strategy_order_lifecycle import (
    start_strategy_order,
    stop_strategy_order,
    build_start_forward_payload,
)

__all__ = [
    "StrategyError",
    "list_scripts", "get_script", "get_script_by_name",
    "create_script", "auto_create_script", "update_script", "delete_script",
    "list_strategies", "get_strategy", "create_strategy",
    "update_strategy", "delete_strategy",
    "create_backtest_batch", "list_batches", "list_batch_tasks",
    "retest_batch",
    "list_tasks", "get_task", "create_task", "delete_task",
    "get_task_logs", "get_task_signals", "get_task_audit",
    "STATUS_STOPPED", "STATUS_RUNNING", "STATUS_CLOSED", "ALL_STATUSES",
    "list_strategy_orders", "get_strategy_order", "list_strategy_order_children",
    "create_strategy_order", "start_strategy_order",
    "stop_strategy_order", "close_strategy_order",
    "build_start_forward_payload",
]
