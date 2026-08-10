# spec-delta: strategy — EvTrade 转发层加 sweep + 历史回测查询

> 配套 [proposal.md](../proposal.md) + [strategy-exec spec-delta](./strategy-exec.md)

## REQ-STRAT-016 扩展

原 REQ-STRAT-016 描述 EvTrade 转发 `/tasks/{id}/run` 到 strategy_exec。本 change 扩 2 端点:

### POST /api/strategy/tasks/{id}/run-sweep

转发到 strategy_exec 的 `POST /internal/run-sweep-task`。

Request (前端发):
```jsonc
{
    "param_grid": { "fast": [3,5,7,10], "slow": [15,20,30,60] },
    "metric": "sharpe",
    "select_top_n": 1,
    "concurrency": 2
}
```

Response:
```jsonc
{
    "sweep_id": "abc123...",
    "total_runs": 16,
    "summary_task_id": 42
}
```

行为:
- 鉴权同 `run-task` (需登录,普通用户只能 sweep 自己的,admin 任意)
- `task_id` (path) 必须是该用户的未开始 task (status='pending');sweep 创建子 task 全部继承此父 task 的 script_id / stock_code
- EvTrade 端不存 sweep 状态 (strategy_exec 单独写 strategy_task 表)

### GET /api/strategy/tasks

新增 query:
- `script_id`: 限定脚本
- `status='finished'`: 仅已完成
- `has_best_params=1`: 仅 best_params 非空 (含单 run 退化 + sweep summary)
- `limit=50`: 默认 50,最大 200

Response: List[TaskOut] (见下扩展)

### TaskOut 扩展

`task_out` 加 4 字段:
- `sweep_id: Optional[str]`
- `sweep_metric: Optional[str]`
- `sweep_total: Optional[int]`
- `backtest_metric_value: Optional[float]` — 单 run 取自 backtest_result.sharpe (或所选 metric);sweep summary 取自 backtest_result.sweep_results[0].metric_value

## 影响

- `server/api/script_strategy/endpoints.py`:加 2 端点 + TaskOut 扩字段
- `server/tables/strategy_task.py`:类定义补 3 字段 (跟 data-model spec-delta 同步)
- `client/src/api/script_strategy.js`:加 `runSweepTask` / `listFinishedBacktests` wrappers
- 前端 ScriptTask.vue:接 sweep + best 选择 (见 strategy-exec spec-delta REQ-SE-009)