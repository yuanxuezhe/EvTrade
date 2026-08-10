# spec-delta: data-model（现有 spec 增量）

## MODIFIED Requirements

### Tables Overview — 删 4 张网格引擎表（19 → 15）

- 删除「🎯 策略体系」表中的 4 行：
  - ~~`strategy`（#7）~~
  - ~~`strategy_grid`（#9）~~
  - ~~`strategy_regime`（#10）~~
  - ~~`strategy_audit`（#11）~~
- 表计数 **19 → 15**：
  - Purpose：`19 张表（业务 6 + 策略 7 + 脚本策略 2 + 系统/用户 3 + 对账/序列 2）` → `15 张表（业务 6 + 策略 1 + 脚本策略 2 + 系统/用户 4 + 对账/序列 2）`
  - 策略体系分组标题：`（v66 strategy_trade change + v90 script-strategy change）` → `（v90 script-strategy change 起；v66 网格引擎 2026-08-10 已删）`
  - 剩余策略表：`strategy_task` / `strategy_script` / `strategy_script_audit`（重新编号）

### 变更说明 — 补 v120.5 网格引擎删除条目

在 v120 strategy-exec-service 条目下新增：

> - **v120.5 grid-engine-removal（2026-08-10）**：DROP `strategy` / `strategy_regime` / `strategy_grid` / `strategy_audit` / `stocks_legacy` 5 张表（migration `2026-08-10-drop-legacy-strategy-tables.py`，commit `aa70dae`）。网格引擎被脚本策略取代；schema.yml 同步移除 4 张表定义。

## 不变

- 其余 15 张表（orders / trades / positions / assets / t0_tasks / quote_snapshots / strategy_task / strategy_script / strategy_script_audit / users / sys_status / sys_config / stocks / reconcile_report / order_no_seq）
- Table Details 各节、ADDED Requirements（t0_tasks / orders.task_id / orders.strategy_type）均不受影响
