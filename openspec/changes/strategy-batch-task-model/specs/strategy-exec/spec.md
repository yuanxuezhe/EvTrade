# spec-delta: strategy-exec — batch 语义 + best 回写策略表（v123）

> 配套 [proposal.md](../../proposal.md) / [design.md](../../design.md)。任务关联从 `script_id` 改 `strategy_id`；sweep 改 batch 语义；完成后回写 `strategy.best_params`；移除 summary task。

## MODIFIED Requirements

### REQ-SE-002: 4 internal REST endpoints

`run-task` 请求体 `script_id` → `strategy_id`（strategy_exec 按 strategy_id 解析所属脚本与 schema；`script_id` 仍随请求下发供引擎取 code，但任务关联以 strategy 为准）。

- `run-task` 请求体：`task_id / user_id / strategy_id / script_id / stock_code / mode(backtest|live) / params / period / backtest_start_date / backtest_end_date / fields`

#### Scenario: 启动任务带 strategy_id

- **WHEN** EvTrade POST `/internal/run-task` 带 `{task_id, user_id, strategy_id, script_id, mode, params}`
- **THEN** strategy_exec 后台异步跑引擎；DB `strategy_task.status='running'`、`execution_service='strategy_exec'`、`strategy_id` 已落库

### REQ-SE-008: 参数扫描（sweep backtest）

> v123 批量化：一次扫描 = 一个 `batch_no`，N 行 task；完成回写 `strategy.best_params`；移除 summary task / sweep_summary。

新增 endpoint（沿用路径，请求体改为 batch 语义）：

```
POST /internal/run-sweep-task
```

Request：

```jsonc
{
    "user_id": 6,
    "strategy_id": 12,
    "script_id": "mas_v1",
    "stock_code": "000001.SZ",
    "backtest_start_date": "20250101",
    "backtest_end_date": "20260701",
    "param_ranges": {
        "fast":  {"type": "int",   "start": 3,  "end": 10, "step": 2},
        "slow":  {"type": "int",   "start": 15, "end": 60, "step": 15},
        "entry": {"type": "choice", "values": ["golden_cross", "ma5_above"]}
    },
    "metric": "sharpe",
    "concurrency": 2
}
```

Response（202，异步）：`{"batch_no": 42, "total_runs": 32}`

行为约束：

- **组合展开**：`int/float` 区间生成**含端点**（`start..end` 步进 step）；`choice` 每个 value 一组；`string` 不参与扫描（取固定值）；其余字段笛卡尔积
- **大小校验**：软警告 64、硬拒绝 512（`GRID_TOO_LARGE` 400）
- **并发控制**：`asyncio.Semaphore(concurrency)`（默认 2）
- **失败容错**：单组合失败 → 该 task `status='failed'`，其余继续
- **K 线共享**：1 次 `fetch_his_bars` 拉全区间，同 batch 组合共用
- **完成后回写 best**：batch 全部结束后，按 `status='finished'` 的 tasks 以 `metric` 排序取 top1，`UPDATE strategy SET best_params = top1.params WHERE strategy_id=:id`（直接覆盖；全部失败则不写，保留原值）
- **乐观锁**：task 写仍走 `version`（REQ-SE-007）；strategy.best_params 本期直接覆盖（无版本冲突处理）

#### Scenario: 16 组合扫描全部成功

- **WHEN** `param_ranges` 展开 16 组合
- **THEN** 创建 16 行 task（共享 `batch_no`），全部 `status='finished'`
- **AND** `strategy.best_params` = 按 metric 排序 top1 组合的 params

#### Scenario: 部分组合失败仍回写 best

- **WHEN** 16 组合中 2 个抛错
- **THEN** 2 task `status='failed'` 带 error_msg；14 个 finished
- **AND** `strategy.best_params` 从 14 个成功的里挑 top1（不选失败的）

#### Scenario: 全部失败不回写

- **WHEN** batch 全部组合失败
- **THEN** `strategy.best_params` 保持原值（不被清空）

#### Scenario: grid 超硬上限拒绝

- **WHEN** 组合数 > 512
- **THEN** 抛 `ValueError`，EvTrade 返 400 `GRID_TOO_LARGE`，不创建任何 task

### REQ-SE-009: 实盘任务接历史 best_params

> v123 门禁 + 来源改 `strategy.best_params`；本期强制使用、不开放编辑。

启动实盘 task 时：

- 校验 `strategy.best_params` 非空，否则 400 `{"code":"NO_BEST_PARAMS","msg":"请先回测生成最优参数"}`（EvTrade 转发层拦截）
- `params` 直接 = `strategy.best_params`
- 校验 `best_params` 的 key 集合 ⊆ 当前 `script_id` 的 `params_schema` key 集合；任一 key 缺失 → 400 列出缺失 key（沿用）
- live runner 用 `cls.p.<key>=<value>` 计算信号

#### Scenario: 无 best_params 拒绝实盘

- **WHEN** 策略未回测，POST live
- **THEN** 返 400 `NO_BEST_PARAMS`，不创建 task

#### Scenario: 有 best_params 启动实盘

- **WHEN** `strategy.best_params={fast:7, slow:30}`，POST live `{strategy_id, stock_code}`
- **THEN** 创建 1 行 task `mode='live'`、`params={fast:7, slow:30}`、新 `batch_no`
- **AND** LiveRunner 用 `cls.p.fast=7 / cls.p.slow=30` 计算信号

## REMOVED Requirements

### REQ-SE-008: summary task / sweep_summary 语义

**Reason**: v122 用 summary task（`sweep_total=1`）持有 best_params + sweep_results；v123 改为"批次内现算 best 并回写 `strategy.best_params`"，summary task 特例删除。

**Migration**: 历史 sweep 行由迁移脚本按 created_at 转成 `batch_no` 分组；前端批次列表直接从 tasks 聚合，不再依赖 summary task。
