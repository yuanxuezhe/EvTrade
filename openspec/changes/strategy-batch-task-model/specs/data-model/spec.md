# spec-delta: data-model — strategy 表 + strategy_task 重构 + 序号表泛化

> 配套 [proposal.md](../../proposal.md) / [design.md](../../design.md)。v123 三层模型：脚本库 → 策略 → 任务。

## ADDED Requirements

### Requirement: `strategy` 表（v123 新增）

策略实体：一个脚本可被多个策略复用；策略不存参数（参数在启动任务时按 `params_schema` 填），只持有绩效最优参数 `best_params`。

**PK**: `strategy_id`（自增 int）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | INT PK autoincrement | NO | — | 策略 ID |
| `user_id` | INT | NO | — | 所属用户 |
| `script_id` | VARCHAR(64) | NO | — | → `strategy_script.id`（FK 逻辑，一个脚本多策略） |
| `name` | VARCHAR(64) | NO | — | 策略名（用户可自命名） |
| `status` | VARCHAR(16) | NO | 'draft' | draft / active / archived |
| `best_params` | JSON | YES | NULL | 回测批次完成后按绩效回写；NULL=未回测（实盘门禁用） |
| `created_at` | DATETIME | NO | utcnow | |
| `updated_at` | DATETIME | NO | utcnow | onupdate |

**索引**：`INDEX (user_id, script_id)`。

#### Scenario: 一个脚本建多个策略

- **WHEN** 用户用脚本 `mas_v1` 分别创建策略 A 和策略 B
- **THEN** `strategy` 表新增 2 行，`script_id` 均指向 `mas_v1`，`strategy_id` 各自自增唯一

#### Scenario: 新建策略无 best_params

- **WHEN** 创建策略（只填 name + script_id，不填参数、不定模式）
- **THEN** `best_params = NULL`，`status='draft'`

#### Scenario: 回测批次完成后回写 best_params

- **WHEN** 策略下某回测批次全部 task 完成，按 metric 排序取 top1
- **THEN** `strategy.best_params` 被**覆盖**为该 top1 的 params（直接覆盖，不追溯来源批次）

### Requirement: `order_no_seq` 泛化为多生成器表（v123）

序号表从单行 `(id=1)` 泛化为按 `seq_name` 分键的多生成器表；新增 `task_batch` 生成器。`strategy_id` / `task_id` 走 DB 自增（不进序号表）。

**PK**: `seq_name`

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `seq_name` | VARCHAR(32) PK | NO | — | 生成器名：`order_no`（现有）/ `task_batch`（新增） |
| `last_value` | INT | NO | 10000000 | 当前值 |
| `updated_at` | DATETIME | NO | utcnow | onupdate |

原子操作 `next_seq(db, seq_name)` 返回 `last_value + 1`（复用 `next_order_no` 的 UPSERT 模式）。

#### Scenario: task_batch 序号单调递增

- **WHEN** 连续发起 3 次回测/实盘批次
- **THEN** `next_seq('task_batch')` 分别返回 N, N+1, N+2，全局唯一无碰撞

#### Scenario: 委托序号行为不变

- **WHEN** 调用 `next_order_no(db)`
- **THEN** 内部走 `next_seq(db, 'order_no')`，返回值与旧逻辑一致

### Requirement: `strategy_task` 表重构（v123）

任务表每行 = 一组参数的一次运行（回测/实盘）。关联改为 `strategy_id`；新增 `batch_no`；删除 `script_id` / `best_params` / `sweep_id` / `sweep_total` / `sweep_metric`。

**PK**: `task_id`（自增 int）

| 分组 | 字段 |
|---|---|
| 标识 | `task_id`(自增 PK)、`user_id`、`strategy_id`(→ strategy.id)、`batch_no`(→ seq task_batch)、`mode`(backtest/live)、`stock_code`、`backtest_start_date`、`backtest_end_date`、`period`、`fields` |
| 参数 | `params`(JSON，DB 规范格式；`key:value` 拼串仅前端展示视角) |
| 结果 | `backtest_result`(JSON)、`pnl`(float)、`trades_count`(int)、`positions`(JSON)、`started_at`、`finished_at`、`error_msg` |
| 运行态 | `status`、`progress`(JSON)、`version`(乐观锁)、`execution_service`、`execution_pid`、`live_signals`(JSON，仅 live) |

**删除字段**（v123）：`script_id`、`best_params`、`sweep_id`、`sweep_total`、`sweep_metric`。

**索引**：`INDEX (strategy_id, batch_no, status)`（批次聚合查询）。

#### Scenario: 扫描批次多行 task 共享 batch_no

- **WHEN** 参数扫描生成 16 组组合
- **THEN** 生成 1 个 `batch_no`，16 行 task 共享该 `batch_no`，每行 `params` 不同

#### Scenario: 单次回测 / 实盘各为独立批次

- **WHEN** 单次回测 1 组参数；随后启动实盘
- **THEN** 分别生成两个新 `batch_no`，各 1 行 task；实盘行 `mode='live'`

## REMOVED Requirements

### Requirement: `strategy_task.sweep_id/sweep_total/sweep_metric` 列

**Reason**: v122 用 3 列 + summary task 表达扫描，v123 由 `batch_no` 统一"一次回测/实盘 = 一批次"，删除该机制。

**Migration**: 历史 sweep 行（若有）由迁移脚本转成 `batch_no` 语义（按 created_at 派批次），列删除；存量数据量小，dev 期重建 DB 亦可。
