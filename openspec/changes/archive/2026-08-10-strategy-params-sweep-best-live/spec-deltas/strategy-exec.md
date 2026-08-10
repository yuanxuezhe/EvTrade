# spec-delta: strategy-exec — 新增 REQ-SE-008 (参数扫描) + REQ-SE-009 (实盘接历史 best)

> 配套 [proposal.md](../proposal.md) + [tasks.md](../tasks.md) + [design.md](../design.md)

## REQ-SE-008: 参数扫描 (sweep backtest)

StrategyExec MUST 支持一次提交多组参数组合的回测,并按指定指标排序挑 best。

### API

新增 endpoint:
```
POST /internal/run-sweep-task
```

Request:
```jsonc
{
    "user_id": 6,
    "script_id": "mas_v1",
    "stock_code": "000001.SZ",
    "backtest_start_date": "20250101",
    "backtest_end_date": "20260701",
    "param_grid": {
        "fast": [3, 5, 7, 10],
        "slow": [15, 20, 30, 60]
    },
    "metric": "sharpe",       // sharpe | total_return | calmar
    "select_top_n": 1,        // 默认 1 (只存 top1 best_params)
    "concurrency": 2          // 默认 2, env STRATEGY_SWEEP_CONCURRENCY 可覆盖
}
```

Response (202 Accepted, 异步):
```jsonc
{
    "sweep_id": "abc123...",
    "total_runs": 16,
    "summary_task_id": 42
}
```

### 行为约束

- **笛卡尔积**:`iter_param_grid(param_grid)` 生成所有组合;若某字段仅 1 个值 (= 未扫描),该字段不参与笛卡尔积
- **大小校验**:
  - 软警告 64 组合 (前端黄警告)
  - 硬拒绝 512 组合 (返 400 + msg)
- **并发控制**:`asyncio.Semaphore(concurrency)` 控制同时跑的 backtest 数
- **失败容错**:任一组合失败 → 该 task status='failed',其余继续;sweep_summary 记录 N 成功 M 失败
- **指标**:`metric` ∈ {`sharpe`, `total_return`, `calmar`};`sharpe` 取 `SharpeRatio` analyzer,`total_return` 取 `TimeReturn` 累计,`calmar` = total_return / max_drawdown
- **持久化**:每个组合 = 独立 `strategy_task` row,共享 `sweep_id`;额外生成 1 个 summary task,`sweep_id=sweep_id, is_summary=1`(`sweep_total` 字段标 N)

### 数据契约

`strategy_task` 表新增 3 列 nullable:
- `sweep_id VARCHAR(32) NULL` — 同 sweep 共享 id
- `sweep_metric VARCHAR(32) NULL` — 排序指标名
- `sweep_total INT NULL` — 同 sweep 的 task 数 (含 summary)

现有 `best_params` 字段复用:
- 单 run task: `best_params = params` (退化为自身)
- summary task: `best_params = top1 组合 params`

### Scenario: 16 组合 sweep 全成功

- **WHEN** POST /internal/run-sweep-task with `param_grid = {fast: [3,5,7,10], slow: [15,20,30,60]}`
- **THEN** 创建 16 个 task (sweep_id 共享) + 1 个 summary task
- **AND** 全部 status='finished'
- **AND** summary task.best_params = 排序 top1 组合
- **AND** summary task.backtest_result.sweep_results = 16 行 metric 排序数组

### Scenario: 部分组合失败

- **WHEN** sweep 中 2 个组合 backtest 抛错
- **THEN** 这 2 个 task status='failed',error_msg 记录
- **AND** 其余 14 个 task 正常 finished
- **AND** summary task.best_params 来自 14 个成功的 (不选失败的)

## REQ-SE-009: 实盘任务接历史 best_params

实盘任务的 `params` MUST 可源自任一历史 backtest task (含 sweep summary task) 的 `best_params`。

### 数据契约

启动实盘 task 时,校验:
- `task.params` 的 key 集合 ⊆ 当前 `script_id` 的 `params_schema` 的 key 集合
- 任一 key 缺失 → 启动前返 400,msg 列出缺失 key
- 所有 key 都已存在 → 启动 live,行为与原一致

### API 扩展

新增查询端点 (EvTrade 转发到 strategy_exec 或直接读 strategy_task 表):
```
GET /api/strategy/tasks
  ?script_id=mas_v1
  &status=finished
  &has_best_params=1   // 限定 finished + best_params 非空
  &limit=50
```

Response:
```jsonc
[
    {
        "task_id": 42,
        "script_id": "mas_v1",
        "sweep_id": "abc123...",
        "sweep_metric": "sharpe",
        "sweep_total": 16,
        "best_params": {"fast": 7, "slow": 30, "qty": 100, "rsi_period": 14},
        "backtest_metric_value": 1.82,
        "finished_at": "2026-08-10T15:30:00",
        "mode": "backtest"  // single 或 sweep
    },
    ...
]
```

前端用此查询渲染 "从历史回测选参数" 弹窗。

### Scenario: live 启动用 sweep 的 best_params

- **WHEN** 用户在 ScriptTask 启实盘,选 task #42 (sweep best: fast=7, slow=30)
- **THEN** POST /api/strategy/tasks with `mode='live', params={fast:7, slow:30, qty:100, rsi_period:14}`
- **AND** EvTrade 转发到 strategy_exec 启 live runner
- **AND** live runner 用 cls.p.fast=7, cls.p.slow=30 计算信号

### Scenario: best_params 引用了已删字段

- **WHEN** schema 升级,删了 `rsi_period` 字段;但旧 task #42 的 best_params 还含 rsi_period=14
- **AND** 用户想用 task #42 的 best 启 live
- **THEN** 启动前校验 `best_params.key ⊆ current_schema.key`,发现 rsi_period 多余
- **AND** 返 400: "best_params 包含 schema 已删除字段: rsi_period; 请改用其他回测或手动重选"

## 不在本 spec

- ❌ 在线实盘参数热更新 (单独 change)
- ❌ Sweep 结果可视化对比图 (单独 change)
- ❌ 跨脚本 best_params 复用 (需 schema 重设计)