# Strategy Dev Page Optimize — 提案 [ARCHIVED 2026-08-27]

> **状态**：✅ Batch 1 完成并提交。其余 Batch（2/3）暂不实施 — 用户推翻"派 subagent"流程，决定主 agent 自己调 sandbox-cc 写代码 + 测试用 M2.7。
> 实施 commit：`399c8ef` (schemas 拆分) + `ce1f662` (删 unused import) + `2f32d7b` (_convert 注释)

## 背景

用户 2026-08-27 提出"检查 EvTrade 项目，优化策略开发页面"，明确范围为**前端策略页面 + 对应后端逻辑**。

**现状规模**（通过 `wc -l` 静态测量）：
- 前端 9 个 Vue 文件 2647 行（ScriptDev 668 / ScriptTask 563 / BacktestForm 326 / TaskDetail 501 / 4 个 strategy-order 子组件 445 / BatchTasksTable 144）
- 前端 API client `script_strategy.js` 185 行 26 个方法
- 后端 `server/api/script_strategy/` 4 个 router 文件 691 行
- 后端 `server/services/script_strategy/` 9 个 service 文件 1431 行
- 后端 `server/strategy/` 顶层（lib/runtime/templates/tests）
- **合计 5530+ 行**

## 已识别的初步问题（不全面扫描，凭 spec 推导 + 静态扫描）

### 前端（高优先级）

| # | 问题 | 证据 | 风险 |
|---|---|---|---|
| F1 | ScriptDev.vue 668 行单文件，`<script setup>` 内含 17+ 个 state ref + 10+ computed/methods，未拆 composable | wc -l + grep `const \w+ = ref` 计数 | 修改易引入未测 state 冲突 |
| F2 | ScriptTask.vue 563 行，编辑器 + 批次表 + 任务详情三段混一个文件 | grep 模板分段 | 复用差，props 流向不清 |
| F3 | BatchTasksTable.vue / BacktestForm.vue / TaskDetail.vue 三个组件本应在 ScriptTask.vue 拆分子组件，已拆但 props 透传复杂 | 读 ScriptTask.vue `<TaskDetail ...>` 引用 | 维护成本 |
| F4 | strategy-order 5 个子组件都很小（30-147 行），可能可合并或重组 | ls + wc | UI 一致性 |
| F5 | CodeMirror 集成（CodeEditor.vue）是近期集成，需验证 ScriptDev.vue 的 `CodeMirror 6 封装` 是否 v6（v5 已废弃） | Vue 3 + CodeMirror 6 skill 已知正确路径 | 编辑体验 |

### 后端（高优先级）

| # | 问题 | 证据 | 风险 |
|---|---|---|---|
| B1 | `services/script_strategy/batches.py:create_backtest_batch` 103 行超长函数，笛卡尔积生成 + 任务批量插入混一起 | AST scan (>80 lines) | 测试覆盖低 |
| B2 | `services/script_strategy/batches.py:retest_batch` 84 行 | 同上 | 同上 |
| B3 | `api/script_strategy/strategy_orders.py` 有未使用 import `STATUS_RUNNING` | AST unused-import 检测 | 误导阅读 |
| B4 | `server/strategy/runtime/backtest.py`（未读完，但 spec 已说明）单文件可能含 BacktestEngine 全部逻辑，~400+ 行 | skill 描述 | 难单元测试 |
| B5 | `services/script_strategy/_convert.py` 命名以下划线开头，规范是私有名，但被 `strategies.py` 等 import | grep `from ._convert` | 误导命名 |
| B6 | schemas.py 185 行集中所有 Pydantic model，按模块拆分更清晰 | wc | 改动易冲突 |

### 架构层（中优先级）

| # | 问题 | 证据 |
|---|---|---|
| A1 | 4 套路由（scripts/strategies/tasks/strategy_orders）混一个 prefix `/script-strategy`，tasks 跟 strategies 部分端点重叠 | `__init__.py` |
| A2 | `script_strategy` 跟 `strategy_order` 命名冲突（脚本策略 vs 策略下单母单），调用方易混 | skill 描述 |
| A3 | 数据库表 `strategy_script` / `strategy_strategy` / `strategy_task` / `strategy_strategy_order` / `strategy_script_audit` 共 5 张表（部分 v6 之后），FK 关系复杂 | skill 描述 |

## 优化目标（推荐分批实施）

### Batch 1：清理 + 抽公共层（低风险）
- 删未使用 import
- 长函数拆 helper
- _convert.py 重命名或加注释说明"内部模块"
- schemas.py 拆分到子模块

### Batch 2：前端 ScriptDev.vue 拆 composable（中风险）
- 抽 `useScriptEditor()` composable（state + computed + save/compile/test 方法）
- 抽 `useParamsSchema()` composable（参数 schema 表格的 CRUD）
- ScriptDev.vue 从 668 行降到 ~300 行模板 + ~80 行 setup

### Batch 3：后端 batches.py 长函数拆分（中风险）
- `create_backtest_batch` 拆 `grid_expand()` + `bulk_insert_tasks()` + 主调度
- `retest_batch` 拆 `deprecate_old_batch()` + `rebuild_tasks()`
- 补单元测试覆盖（现在可能覆盖不足）

### Batch 4：架构重构（高风险，需多拍板）
- 命名清理（避免 script_strategy vs strategy_order 混淆）
- 路由 prefix 拆分
- 表名收敛

## 基线扫描报告（2026-08-27 实施前）

| 测试 | 命令 | 结果 |
|---|---|---|
| 后端 pytest | `pytest server/tests/ tests/` | **133 collected, 121 passed, 12 failed**（失败集中在 `tests/test_quota_batch.py` quota 阈值类 + `test_env_override`，与策略开发无关，属历史基线） |
| 前端 build | `cd client && npm run build` | ✓ 19.48s built |
| 前端 lint | `cd client && npm run lint` | ❌ **package.json 无 lint script** — 项目未配置 ESLint，需要顺手装 |
| chunk 体积 | rollup warning | `ScriptTask-EeYWeqdW.js` 511.59 kB + `ScriptDev-bnDbBuqK.js` 475.91 kB 超 500kB 警告 — Batch 2 拆 composable + 异步 import 有机会降到 250kB 以下 |
| `server/strategy/tests/` | ls | ❌ **不存在**（skill 描述错位，实际测试在 `server/tests/strategy/` + `tests/server/strategy/`） |

## 实施原则

- **每个 Batch 独立 OpenSpec change**，独立 commit，不耦合
- **改动前必须跑 baseline 测试**：`pytest server/strategy/tests/ -v` + `cd client && npm run build` 必须绿
- **每个函数抽 helper 必须带单测**
- **拆 composable 必须保持原 props/事件契约**，不让 ScriptDev.vue 父级用法变
- **不改数据库 schema**（Batch 4 除外）
- **不开新 API endpoint**（除非 batch 2/3 重构自然产生）

## 验收标准

1. `pytest server/strategy/tests/ server/tests/script_strategy/ -v` 全绿
2. `cd client && npm run build` 成功
3. `cd client && npm run lint` 零 error
4. ScriptDev.vue 行数下降 ≥ 30%
5. batches.py 单函数最长 ≤ 50 行
6. 后端 4 个 router 改动后端到端 `curl /api/script-strategy/scripts` 返 200

## 不做的事

- 不动 hqserverd / strategy_exec（不在本次范围）
- 不重写 BacktestEngine（仅抽函数，不改算法）
- 不换前端 UI 框架
- 不改数据库 schema（Batch 4 提议但本 proposal 不实施）
- 不引入新依赖

## 时间估算

| Batch | 估时 | 风险 |
|---|---|---|
| 1（清理） | 30 分钟 | 低 |
| 2（前端 composable） | 1.5 小时 | 中 |
| 3（后端 batches.py） | 1.5 小时 | 中 |
| 4（架构） | 跳过（需独立 proposal） | 高 |

**Batch 1+2+3 总计约 3.5 小时**，可一次完成或拆 2 次。

## 决策点（需用户拍板）

### Q1: 范围
- A: 仅 Batch 1（清理） — 最小风险
- B: Batch 1+2（清理 + 前端拆 composable） — 推荐，覆盖 80% 易得收益
- C: Batch 1+2+3 — 完整技术债清理
- D: 加 Batch 4（架构重构）— 需独立 proposal

### Q2: 实施方式
- A: 主 agent (M3.0) 全程执行（违反 USER PROFILE "主 agent 不亲自写代码" 铁律，不推荐）
- B: 主 agent 拆任务 → 派 M2.7 subagent → 走 sandbox-cc 改（符合铁律，推荐）
- C: 不派 subagent，主 agent 跳过，按"参考架构导向"先整体改 demo

### Q3: 改动是否走 OpenSpec 完整流程
- A: 是（按 CLAUDE.md §三 强制工作流）
- B: 跳过 OpenSpec，直接进 change（违反铁律）
