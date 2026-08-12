"""
server/tables/strategy_task.py — 自动生成 (tables-codegen skill)

表: `strategy_task`  (29 字段, 主键: ['id'])
描述: 脚本策略任务：回测 / 实盘运行态 + 结果

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Tuple


class StrategyTask(TableBase):
    """脚本策略任务：回测 / 实盘运行态 + 结果

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_task'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'user_id': '',
        'stock_code': '',
        'mode': '回测/实盘: 创建时不填, 运行 /tasks/{id}/run 时再写',
        'status': '',
        'params': '',
        'backtest_result': '',
        'backtest_start_date': '',
        'backtest_end_date': '',
        'period': '',
        'pnl': '',
        'positions': '',
        'trades_count': '',
        'started_at': '',
        'finished_at': '',
        'error_msg': '',
        'created_at': '',
        'updated_at': '',
        'live_signals': '实盘信号流: 用户 script signal() + doorder 自动记录 (限 500 条, LiveRunner 每 5s flush)',
        'fields': '历史行情字段白名单, 默认 open,close,high,low',
        'progress': '实时回测进度 (phase/current/total/bar_idx/total_bars/elapsed_ms)',
        'execution_service': '执行服务标识 (evtrade / strategy_exec)',
        'execution_pid': 'strategy_exec 进程 pid (用于排查)',
        'version': '',
        'description': '策略(任务)描述: 新建策略时填写',
        'strategy_id': '→ strategy.strategy_id (v123)',
        'batch_no': '回测/实盘批次号 (v123, 序号表 task_batch)',
        'metric': '批次排序指标 (sweep top1 选择, 重测还原用)',
        'backtest_metric_value': '单 run 指标值 (sharpe→total_return→pnl/initial_cash)'
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'user_id': 'int',
        'stock_code': 'varchar(16)',
        'mode': 'varchar(8)',
        'status': 'varchar(16)',
        'params': 'json',
        'backtest_result': 'json',
        'backtest_start_date': 'varchar(8)',
        'backtest_end_date': 'varchar(8)',
        'period': 'varchar(8)',
        'pnl': 'float',
        'positions': 'json',
        'trades_count': 'int',
        'started_at': 'datetime',
        'finished_at': 'datetime',
        'error_msg': 'varchar(500)',
        'created_at': 'datetime',
        'updated_at': 'datetime',
        'live_signals': 'json',
        'fields': 'varchar(64)',
        'progress': 'json',
        'execution_service': 'varchar(16)',
        'execution_pid': 'int',
        'version': 'int',
        'description': 'varchar(500)',
        'strategy_id': 'int',
        'batch_no': 'int',
        'metric': 'varchar(16)',
        'backtest_metric_value': 'float'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    user_id: int
    stock_code: str
    mode: str
    status: str
    params: Any
    backtest_result: Any
    backtest_start_date: str
    backtest_end_date: str
    period: str
    pnl: float
    positions: Any
    trades_count: int
    started_at: datetime
    finished_at: datetime
    error_msg: str
    created_at: datetime
    updated_at: datetime
    live_signals: Any
    fields: str
    progress: Any
    execution_service: str
    execution_pid: int
    version: int
    description: str
    strategy_id: int
    batch_no: int
    metric: str
    backtest_metric_value: float
