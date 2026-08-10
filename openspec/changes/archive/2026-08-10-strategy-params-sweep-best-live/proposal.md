# 2026-08-10-strategy-params-sweep-best-live — params_schema 真源化 + 回测扫描 + 实盘吃 best_params

> **作者**: Claude (after user conversation)
> **日期**: 2026-08-10
> **状态**: 📝 提案中 (待 opsx:apply)

## 为什么改 (Why)

### 问题陈述

当前 `strategy_script` 表存脚本 + `params_schema` JSON,但**代码里还要再写一遍 `params = (("fast", 5), ...)`**。三重真源:

| 来源 | 位置 | 谁用 |
|---|---|---|
| `code` 里 `params = (("fast", 5), ...)` | 用户脚本内 | backtrader 元类(只在 `addstrategy` 不传 kwargs 时用,本系统永远传 kwargs → **死代码**) |
| `params_schema` JSON | DB 列 | UI ScriptDev 编辑 / ScriptTask 默认值填充 |
| `task.params` dict | task 表 JSON 列 | 真正传给 `cerebro.addstrategy(strategy_cls, **params)` 的运行时值 |

**3 个真源互相独立,改一处忘另一处 → 静默错误**:
- code 加了 `("rsi_period", 14)`,schema 忘了 → UI 表单没 rsi_period → 永远跑 default 14
- schema 加了行,code 没加 → `self.p.rsi_period` AttributeError
- API 直传 `task.params = {"rsi_period": 99999}` → schema `max:30` 是 UI 端约束,后端无校验

更糟的是 **缺扫描优化**:
- 当前 1 个 task = 1 组 params,想试 16 组 fast/slow 组合 = 手动起 16 个 task,自己肉眼比
- `grid.py` 旧引擎 2026-08-10 grid-engine-removal 时已删,无现成扫描能力
- `best_params` 字段已存在但永远是 `== params`(单 run 退化),无比较价值

### 解决方案

1. **`params_schema` 当唯一契约**。`loader.py::load_strategy_class` 后注入 `cls.params` 元组(以 schema 为准)。代码不再声明 `params = (...)`,但仍可写 `self.p.fast` (backtrader 原生访问保留)
3. **新增 sweep 引擎**:笛卡尔积 + 并发回测 + 排序挑 best
4. **UI**:实盘启动支持"从历史回测选参数"(挑某次 sweep 或单 run 的 best_params)

## 范围 (Scope)

### 包含 (In)

| 项 | 详情 |
|---|---|
| Schema 注入 | `loader.py` 加 `_inject_params_from_schema(cls, schema)`;`load_strategy_class(code, cls, params_schema=None)` 多收 1 个可选参 |
| 引擎适配 | `backtest.py`/`live.py` 调 loader 时多传 `script_row["params_schema"]` |
| Sweep 引擎 | 新建 `strategy_exec/engines/backtrader/sweep.py`,并发跑笛卡尔积组合,统一挂 sweep_id |
| Sweep 端点 | 新增 `POST /internal/run-sweep-task` (strategy_exec) |
| EvTrade 转发 | `POST /api/strategy/tasks/{id}/run-sweep` (转发到 strategy_exec) |
| 历史回测查询 | 新增 `GET /api/strategy/tasks?script_id=&status=finished&has_best_params=1`(前端选 best 用) |
| DB 迁移 | `strategy_task` 加 3 列 nullable:`sweep_id`/`sweep_metric`/`sweep_total` |
| 前端 UI | `ScriptTask.vue` 加 sweep 启动表单 + "从历史回测选参数" 选 best 弹窗 |
| 存量迁移 | 新 alembic 脚本:把 `mas_v1` demo 脚本 code 里 `params = (...)` 6 行删掉 (schema 已含完整定义) |
| Spec 增量 | `strategy-exec/spec.md` 加 REQ-SE-008 (扫描) + REQ-SE-009 (live 接 best);`data-model/spec.md` 加 strategy_task 新 3 列;`strategy/spec.md` REQ-STRAT-014~017 加 sweep 路径 |

### 不包含 (Out)

| 项 | 详情 |
|---|---|
| 在线实盘参数热更新 | 本 change 只支持"启实盘时挑 best_params",运行中改 params → 单独 change |
| 多 metric 并行排序 | 本 change 1 次 sweep 1 个 metric;多次 sweep 用户自挑 |
| 跨脚本 best 复用 | best_params 仅同 script_id 间复用(参数 key 一致);跨脚本 → schema 重设计 |
| 删 grid 引擎 | 已在 grid-engine-removal change 删完,本 change 不重复 |
| 前端可视化 sweep 结果对比图 | UI 列文字表 + sharpe/pnl 列,图表 → 后续单独 change |

### 影响的现有能力

| Spec | 影响 |
|---|---|
| `strategy-exec/spec.md` | 加 REQ-SE-008 (sweep) + REQ-SE-009 (live 接 best) |
| `data-model/spec.md` | strategy_task 表加 3 列 (sweep_id / sweep_metric / sweep_total) — 全部 nullable |
| `strategy/spec.md` REQ-STRAT-016 | 端点签名扩 (sweep run + 历史回测查询) |
| `frontend/spec.md` REQ-FE-310 | /script-task 路由 UI 加 sweep + best 选择 (in-place, 路由不变) |
| `sandbox/spec.md` | `load_strategy_class` 签名多 1 个可选参 (向后兼容) |

## 关键决策 (Locked)

| # | 决策 | 选项 | 选 | 理由 |
|---|---|---|---|---|
| 1 | Schema vs code conflict 处理 | A.strict fail-fast / B.lenient merge / C. 警告 | **A** | 对齐"schema 是真源";静默宽容易养 bad habit;fail-fast 强迫 code 删 `params = (...)` |
| 2 | Sweep 范围 | A.schema 全字段参与 / B. 显式标记参与字段 | **A + UI 临时锁定** | schema 全字段默认扫;UI `lockForSweep: bool` 临时勾选某字段不参与 (不污染 DB) |
| 3 | Sweep 并发度 | A. 串行 / B. N worker 并发 | **B, N=2** | 2 worker 够用 (~30min 完成 16 组 sweep);env `STRATEGY_SWEEP_CONCURRENCY` 可调;写库走现有乐观锁 (3 次重试) |
| 4 | Sweep 排序指标 | A.sharpe / B.total_return / C.calmar | **A default + UI 下拉** | Backtrader 自带 `SharpeRatio` analyzer 已接入;UI 提供下拉切 |
| 5 | 实盘接 best 方式 | A. 一键自动用本 sweep best / B. 手动从历史回测挑 | **B** | 用户对小资金风控敏感;manual 更稳;UX 上 "一键用本 sweep best" 是 manual 的快捷版(可一行调用) |
| 6 | Sweep 大小上限 | A. 无上限 / B. 默认 64 / C. 硬上限 256 | **B 软 64 / C 硬 512** | 64 组 ~5min 完成 (UX 友好);硬上限 512 防失控;超限 → UI 警告 + 提交拒绝 |

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 知识库 | `openspec/changes/2026-08-10-strategy-params-sweep-best-live/` | proposal + design + tasks + spec-deltas |
| 知识库 | `openspec/specs/strategy-exec/spec.md` | 新增 REQ-SE-008 / REQ-SE-009 |
| 知识库 | `openspec/specs/data-model/spec.md` | strategy_task 表新增 3 列描述 |
| 知识库 | `openspec/specs/strategy/spec.md` | REQ-STRAT-016 端点签名扩展 |
| 服务端 | `strategy_exec/strategy_exec/sandbox/loader.py` | `_inject_params_from_schema` + `load_strategy_class` 多 1 参 |
| 服务端 | `strategy_exec/strategy_exec/engines/backtrader/backtest.py` | 调 loader 多传 schema |
| 服务端 | `strategy_exec/strategy_exec/engines/backtrader/live.py` | 同上 (live 路径,虽然 best_params 不影响 live 注入但路径要一致) |
| 服务端 | `strategy_exec/strategy_exec/engines/backtrader/sweep.py` (新建) | 笛卡尔积 + 并发 + 汇总 |
| 服务端 | `strategy_exec/strategy_exec/api/internal.py` | 新增 `run_sweep_task` endpoint |
| 迁移 | `server/migrations/2026-08-11-add-strategy-sweep-fields.py` (新建) | strategy_task 加 3 列 nullable |
| 迁移 | `server/migrations/2026-08-11-drop-mas-v1-params-from-code.py` (新建) | mas_v1 demo 删 `params = (...)` 6 行 |
| EvTrade 转发 | `server/api/script_strategy/endpoints.py` | 加 `run-sweep` + `list-finished-backtests` 端点 |
| 前端 | `client/src/views/ScriptDev.vue` | 无功能改动;schema 表 UI 提示 "代码里不要再写 params = (...)" |
| 前端 | `client/src/views/ScriptTask.vue` | 加 sweep 表单 + best 选择弹窗 |
| 前端 | `client/src/components/SweepForm.vue` (新建) | 独立子组件 (per CLAUDE.md 单文件 ≤250 行) |
| 测试 | `tests/server/strategy/test_sweep.py` (新建) | 笛卡尔积 + sweep_id 关联 + 软硬上限 |

## 落地约束

1. **零回归**:现有单 run 回测 (`POST /internal/run-task`) 行为不变;新 sweep 是新端点
2. **向后兼容**:`load_strategy_class(code, cls)` 旧调用仍工作 (新参数可选)
3. **数据迁移非破坏**:`strategy_task` 3 列均 nullable,旧 task 行 NULL,前端 fallback 显示 "单次回测"
4. **demo 脚本兼容**:mas_v1 demo `params = (...)` 6 行删后,沙箱自动接管;不删 schema (schema 是契约)
5. **Sweep 失败容错**:任一组合 run 失败 → 该 task.status='failed',其它组合继续;sweep_summary 记录 "16 中 12 完成,best 来自完成的"
6. **不持久化 sweep queue**:并发用 asyncio.Semaphore,不引入 Celery/Redis;重启 strategy_exec 不会丢 task (已持久化到 strategy_task)
7. **JSON 列加列不走 alembic**:直接 ALTER TABLE (3 列 nullable + 0 默认值,免回填)

## 风险与回退

| 风险 | 概率 | 影响 | 回退 |
|---|---|---|---|
| schema 注入破坏了某存量脚本 | 低 | 中 | 启 fail-fast 报错,提示用户删 code 里 `params = (...)`;存量脚本迁移脚本里已经处理 mas_v1 |
| sweep 跑太久拖垮 strategy_exec | 低 | 中 | N=2 worker;soft limit 64;前端跑前预估时长 |
| 并发写 strategy_task 撞乐观锁 | 中 | 低 | 现有 3 次重试 + 新 sweep_id 字段在同一 row 不同组合 → 不会撞 (每组合独立 row) |
| best_params schema 变更后误用 | 中 | 中 | live 启时校验 task.params key 集合 ⊆ 当前 script_id schema,否则警告 (不阻断) |