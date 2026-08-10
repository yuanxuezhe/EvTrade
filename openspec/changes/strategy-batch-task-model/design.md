# design — 策略/批次/任务 三层模型

## Context

当前策略体系（v122）三层关系是：
```
strategy_script（脚本库：code + params_schema + is_public）
strategy_task（每行 = 一组参数的一次运行，script_id 挂脚本，params JSON）
  + sweep_id/sweep_total/sweep_metric 3 列表达扫描
  + summary task（sweep_total=1）持有 best_params + sweep_results
```

用户对现状不满意：
- 想表达"一个脚本复用为多个策略"（同脚本既回测又实盘、或不同命名用途），但 task 只挂 `script_id`，没有"策略"实体。
- 扫描的 summary task 是特例、`best_params` 落在 task 上，实盘取参数要绕路。
- 扫描表单要按 `params_schema` 类型渲染（int/float 起止+步长、choice 逗号分隔），不是手打值列表。
- 实盘应在"回测过且生成最优参数"之后才允许。

约束：脚本库 `strategy_script` 及其 `params_schema` 契约不动；运行引擎仍在 `strategy_exec`（共享单库、只算不算单）；乐观锁 `version` 机制沿用；`strategy_script_audit.task_id` 关联沿用。

## Goals / Non-Goals

**Goals:**
- 新增显式 `strategy`（策略）层：一个脚本可建多个策略，任务挂 `strategy_id`。
- 用 `batch_no`（序号表生成器）统一"一次回测 / 一次扫描 / 一次实盘启动"，删除 sweep 3 列 + summary task。
- `best_params` 收敛到 `strategy` 表：每完成一个回测批次，按 batch 内 tasks 排序算 best 并直接覆盖。
- 实盘门禁：无 `strategy.best_params` 禁止启动实盘。
- 扫描表单按 `params_schema` 类型渲染；单次回测展示全部参数（默认值= `default`）。
- 批次任务结果表格：前几列参数（动态列）、后几列结果；点击行下钻详情。
- `strategy_id` / `task_id` 用 DB 自增；`batch_no` 走序号表；`params` DB 存 JSON。

**Non-Goals:**
- 实盘运行中参数热更新（后续 change）。
- 多指标并行排序 / best 缓存版本化（本期 `best_params` 直接覆盖，不追溯来源 batch）。
- 实盘参数手动微调（本期直接用 best_params，预填不可改）。
- `strategy_script_audit` 表改名/重构（沿用现状，仅关联 `task_id`）。
- 前端 sweep 结果图表（本期表格 + 下钻详情，图表后续）。

## Decisions

### D1: 三层模型 strategy_script → strategy → strategy_task

```
strategy_script（脚本库，不动）   id / user_id / name / code / params_schema / is_public / status
strategy（策略，新增）            strategy_id(自增 PK) / user_id / script_id / name / status / best_params / created_at / updated_at
strategy_task（任务，重构）       task_id(自增 PK) / strategy_id / batch_no / params / mode / stock_code / 日期 / period / fields / 结果 / status / progress / version / execution_service / execution_pid / live_signals
strategy_script_audit             task_id（不动）
```

- 一个脚本 → 多策略：策略表 `script_id` 引用脚本库；策略只表达"用哪个脚本 + 名称 + 状态 + 最优参数"。
- 建策略时不填参数、不定模式（回测/实盘由每次运行决定）。

**备选**：task 直接挂 `script_id` + 给脚本加别名实现"复用"。→ 否：没有独立策略实体，`best_params`/多实例无从挂载，语义不清晰。

### D2: batch_no 用序号表生成器，strategy_id/task_id 用自增

`order_no_seq` 泛化为多生成器表：

```
seq（原 order_no_seq 表）  seq_name PK / last_value / updated_at
  行: 'order_no'（现有） / 'task_batch'（新增）
next_seq(db, name) 原子 UPSERT +1（复用 next_order_no 的实现模式）
```

- `batch_no = next_seq('task_batch')`，全局唯一单调，无碰撞。
- `strategy_id` / `task_id` 直接用 DB 自增 id（现状 strategy_task.id 已是自增且被 audit/progress/URL 引用，零额外代码）。

**备选**：task_id 也走序号表 → 否：自增已全局唯一，序号表多一套分配代码无功能收益；用户已拍板自增。

### D3: batch 是虚拟聚合，无独立表

一次"开始回测 / 启动实盘" = 1 个 batch = N 行 task：

- 单次回测：batch 内 1 行（params = 用户填的一组）
- 参数扫描：batch 内 N 行（类型驱动的笛卡尔积）
- 实盘启动：batch 内 1 行（`mode='live'`，params = strategy.best_params）

batch 元信息由 task 派生（`GROUP BY (strategy_id, batch_no)` 取 created_at / mode / task_count）。批次列表 API 负责聚合，不落批头表。

**备选**：独立 batch 头表 → 否：字段几乎全冗余（batch 元信息都能从 task 派生），多一张表增加维护；数据量小聚合开销可忽略。

### D4: params 存储用 JSON；`k:v;k:v` 仅作展示

- DB 列 `params` 保持 JSON（保类型、无解析歧义，schema 类型可强转）。
- UI / API 展示时可拼 `key:value;key:value` 字符串（前端只读视角）。
- API 层是唯一读写入口，DB 格式属内部实现。

**备选**：DB 存 `k:v;k:v` 字符串 → 否：丢类型（int/float/str 需靠 schema 强转）、值含 `:`/`;` 会解析错；用户已在方案评审中选择 JSON。

### D5: 扫描按 params_schema 类型驱动

| schema type | 扫描表单 | 生成规则 |
|---|---|---|
| `int` / `float` | 起止 + 步长（默认带出 schema min/max/step，可手调） | `range(start, end+step, step)`，**含端点** |
| `choice` | 逗号分隔值列表（默认带出 schema values，可手调） | 每个值一个组合 |
| `string` | 固定值，不参与扫描 | 单值 |

- 扫描组合 = 参与字段的笛卡尔积；不参与字段取固定值。
- 单次回测：展示全部字段，默认值取 schema `default`。
- 软上限 64 组合（警告）、硬上限 512（拒绝），沿用 v122 约束。

**备选**：`params_schema` 加 `sweepable: bool` 标记 → 否：类型本身已决定可扫性，另加标记冗余（用户已拍板按类型）。

### D6: best_params 回写策略表（直接覆盖）

- 每完成一个回测批次，按该 batch 内 `status='finished'` 的 tasks 以所选 metric（默认 sharpe）排序，取 top1 的 params 覆盖 `strategy.best_params`。
- 单次回测的 batch（1 行）同样覆盖（best = 该组 params）。
- 本期只存绩效最优参数本身，不追溯来源 batch（后续方案再扩展）。
- 写入方：strategy_exec（共享单库，回测完成后算 best 并 UPDATE `strategy`），需在 run 请求中携带 `user_id/strategy_id`。

### D7: 实盘门禁 + 实盘走批次

- 启动实盘：POST `/strategy/{id}/live`，先校验 `strategy.best_params` 非空；否则返 400 `{"code": "NO_BEST_PARAMS", "msg": "请先回测生成最优参数"}`。
- 校验通过 → 建 1 个 batch（新 `task_batch`），1 行 task：`mode='live'`、`params=best_params`、`stock_code/fields` 由用户在启动时填。
- UI：实盘 batch/task 显示"实盘"徽章，与回测批次区分。

### D8: 引擎/端点语义

- `strategy_exec` 内部端点 `run-task` 请求体 `script_id` → `strategy_id`（或两者都给，引擎按 strategy 解析脚本）。
- `run-sweep-task` 改为按 batch 语义：请求体带 `strategy_id / batch_no / param_ranges(类型化) / metric / concurrency`；strategy_exec 内部展开组合、并发跑、完成后回写 best。
- 进度/乐观锁/审计逻辑沿用 REQ-SE-007 不变。

## Risks / Trade-offs

- **[命名/字段全局替换 script_id→strategy_id]** 后端（endpoints / tables / 序号服务）+ strategy_exec（data_access / internal API / engines）+ 前端多处联动 → 用 grep 全量清单 + 迁移脚本一次性对齐；先改 data-model spec 再动代码。
- **[存量数据迁移]** 现有 `strategy_task.script_id` 需映射到新策略 → 迁移脚本为每个 `strategy_script` 建一条 `strategy`（同名），再把 task 按 script_id 归到对应 strategy；孤儿的 task 归到"脚本同名策略"或标 failed 保留审计。
- **[并发回测批次乱序完成，best_params 被旧批覆盖]** 概率低（单人/低并发）→ 本期接受直接覆盖；后续 change 加 `best_batch_no` 溯源或按完成时间取最新。
- **[float 步长精度 / choice 值含逗号]** 步长用 decimal 或足够小数位；schema `values` 约定用 JSON 数组（不含裸逗号），前端展示时拼逗号分隔。
- **[批次聚合性能]** batch 列表按 (strategy_id, batch_no) GROUP BY，task 行数小，可接受；必要时加复合索引 `(strategy_id, batch_no, status)`。

## Migration Plan

1. **序号表泛化**：`order_no_seq` 增加 `seq_name` 列（现有行 `seq_name='order_no'`），新增 `task_batch` 行；`next_order_no` 改为 `next_seq(db, 'order_no')`。
2. **建 `strategy` 表**：`strategy_id` 自增 PK / `user_id` / `script_id`(FK→strategy_script.id) / `name` / `status` / `best_params`(JSON NULL) / 时间戳；索引 `(user_id, script_id)`。
3. **`strategy_task` 重构**：加 `strategy_id` / `batch_no`；回填：每行按 `script_id` 映射到对应 `strategy`，`batch_no` 先按历史 created_at 派一个批次（或统一补一个初始 batch）；删 `script_id` / `sweep_id` / `sweep_total` / `sweep_metric` / `best_params` 列。
4. **API/引擎**：endpoints 改挂 strategy；strategy_exec run 请求带 strategy_id；sweep 改 batch 语义 + best 回写。
5. **前端**：ScriptTask 批次/任务两段 UI + 类型化扫描表单 + 实盘门禁提示 + 实盘徽章。
6. **回滚**：迁移脚本均幂等（探测列/表存在再 ALTER）；dev 期可重建 DB。因 v122 sweep 刚上、数据量小，回滚成本低。

## Open Questions

- metric 选择：本期扫描时用户选（默认 sharpe），不落库到策略表；是否要记录"best 由哪次 batch/哪个 metric 得出"→ 后续 change。
- 实盘 params 微调：本期强制用 best_params；后续是否放开编辑。
- `strategy.status` 枚举沿用 `draft/active/archived` 即可；实盘/回测不占用 status（由 task.mode 表达）。
