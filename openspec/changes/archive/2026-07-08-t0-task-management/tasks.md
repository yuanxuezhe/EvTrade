# Tasks — T0 任务管理（v18）

按 v6 拆小 commit。每个 commit 后必 `git log -1` 校验 hash；不自动 push，让用户拍板。

## Stage 1（草稿）

- [x] 写 proposal.md（本 change 立项）
- [x] 写 spec-deltas/trading.md（REQ-TRADE-013 ~ 018）
- [x] 写 spec-deltas/data-model.md（T0Task 表 schema + orders.task_id）
- [x] 写 tasks.md（本文件）

## Stage 2（拍板）

- [ ] **用户拍板**：本文档落 5 个 A：
  - [ ] A1 schema 加 T0Task + orders.task_id 索引（dual driver SQLite + MySQL）
  - [ ] A2 6 个 REST API（CRUD + balance + close + stats）
  - [ ] A3 前端 task 列表 + 详情 + 创建对话框（3 个新组件 + T0Trade.vue 集成）
  - [ ] A4 配平公式 `target - position`，保留底仓 base_volume
  - [ ] A5 统计口径（已实现 + 未实现 + 胜率）走 REQ-TRADE-006 的 calc_realized_pnl
- [ ] **用户确认** OpenSpec 草稿无歧义

## Stage 3（实施）

### Commit 1：OpenSpec 草稿（proposal + spec-deltas + tasks）

> 文件：`openspec/changes/2026-07-08-t0-task-management/{proposal.md, spec-deltas/trading.md, spec-deltas/data-model.md, tasks.md}`
> 命中"docs-only"豁免规则（不写业务代码）；单独 1 commit 便于审。

### Commit 2：migration — T0Task 表 + orders.task_id 列（幂等）

> 文件：`server/migrations/2026-07-08-add-t0-tasks.py`
> SQLAlchemy dual driver：MySQL 走 INFORMATION_SCHEMA 检测列存在；SQLite 走 PRAGMA table_info。
> 仅建表 + 加列 + 加索引，不动 ORM。

### Commit 3：ORM — T0Task model + Order.task_id 字段

> 文件：`server/models/orm.py`
> 加 `class T0Task(Base)` 完整字段；`class Order` 加 `task_id` 列 + 索引声明。
> 与 spec.md 一致。

### Commit 4：service 层 — task CRUD + balance + stats

> 文件：`server/services/t0/tasks.py`（新建）
> 函数：
> - `create_task(user_id, stock_code, base_volume, target_volume, coefficient, note)` → T0Task
> - `list_tasks(user_id, status, stock_code, days)` → List[T0Task + summary]
> - `get_task_detail(task_id)` → T0Task + summary
> - `balance_task(task_id, coefficient)` → {action: 'BUY'|'SELL', volume}
> - `close_task(task_id, force_balance)` → T0Task
> - `aggregate_task_stats(task_id)` → Dict（realized/unrealized/win_rate 等）
> 复用 `services/t0/pnl.py::calc_realized_pnl` 和 `services/t0/core.py::calc_t0_volume` / `round_to_lot`。

### Commit 5：API 层 — 8 个端点（CRUD + balance + close + stats）

> 文件：`server/api/t0_tasks.py`（新建）+ `server/api/__init__.py` 注册路由
> 端点（按 REQ-TRADE-014）：
> - POST /api/t0-tasks
> - GET /api/t0-tasks?status=&stock_code=&days=
> - GET /api/t0-tasks/{id}
> - PATCH /api/t0-tasks/{id}
> - DELETE /api/t0-tasks/{id}（仅 archived）
> - POST /api/t0-tasks/{id}/balance
> - POST /api/t0-tasks/{id}/close
> - GET /api/t0-tasks/{id}/stats
> + RBAC：trader 仅看自己 user_id 的 task；admin 看所有。

### Commit 6：下单路径写 task_id

> 文件：`server/api/orders/place.py`
> 接受可选 `task_id` 入参；写 orders.task_id 列。
> 与 user_def='T0' 共存；无 task_id 时保持 NULL。
> 单测：旧调用不带 task_id 行为不变；带 task_id 时落库正确。

### Commit 7：API client + Pinia store

> 文件：`client/src/api/t0_tasks.js`（新建）+ `client/src/stores/t0_tasks.js`（新建）
> API client 8 个方法；Pinia store 暴露 reactive `tasks / activeTask / selectedTaskId / summary`。

### Commit 8：前端 — T0TaskList + T0TaskDetail + T0TaskCreateDialog

> 文件：
> - `client/src/components/trade/T0TaskList.vue`（新建）
> - `client/src/components/trade/T0TaskDetail.vue`（新建）
> - `client/src/components/trade/T0TaskCreateDialog.vue`（新建）
> 列表分 active / closed / archived 三 tab；详情抽屉显示摘要 + 每日 pnl 图表（沿用 `<T0ChartGeometry>`）+ 操作按钮；建任务对话框从持仓选择 stock_code 输入 base/target/note。

### Commit 9：T0Trade.vue 集成 task 切换 + 下单带 task_id

> 文件：`client/src/views/T0Trade.vue`
> 顶部加任务下拉（active 列表 + "未指定 task"）；下单按钮带 task_id；快捷键不变。
> 兼容：未选 task 时行为与 v17 一致（向后兼容）。

### Commit 10：单测 + e2e

> 文件：
> - `server/tests/services/test_t0_tasks.py`（新建）— balance / stats 公式
> - `server/tests/api/test_t0_tasks_api.py`（新建）— 鉴权 / 状态过滤 / close 强配
> - `client/tests/components/trade/T0TaskList.test.js`（新建）
> - `client/tests/components/trade/T0TaskDetail.test.js`（新建）
> - `client/tests/components/trade/T0TaskCreateDialog.test.js`（新建）

## Stage 4（归档）

- [ ] `/openspec:sync` 把 REQ-TRADE-013 ~ 018 合并到 `openspec/specs/trading/spec.md`
- [ ] `/openspec:sync` 把 T0Task 表 + orders.task_id 合并到 `openspec/specs/data-model/spec.md`
- [ ] git mv `changes/2026-07-08-t0-task-management` → `changes/archive/2026-07-08-t0-task-management`
- [ ] tasks.md 加 ARCHIVED banner + 实际 commit hash
- [ ] 1 commit docs(openspec): archive ...
- [ ] push（按 v6 SSH 路径）

## 验证清单（commit 6 + 10 时必过）

- [ ] pytest `server/tests/services/test_t0_tasks.py` 全过
- [ ] pytest `server/tests/api/test_t0_tasks_api.py` 全过
- [ ] pytest `server/tests/orders/test_place_task_id.py` 全过
- [ ] npm test `client/tests/components/trade/T0Task*.test.js` 全过
- [ ] `python3 scripts/evctl.py start backend` → curl `/api/t0-tasks` 200
- [ ] curl POST `/api/t0-tasks` 建任务 → GET `/api/t0-tasks/{id}` 返回详情
- [ ] curl POST `/api/t0-tasks/{id}/balance` 模拟配平（mock position + asset）
- [ ] curl GET `/api/t0-tasks/{id}/stats` 返回 summary + daily
- [ ] 浏览器 `/t0-trade` 任务下拉可切换，新组件渲染正常

## 风险

| 风险 | 缓解 |
|---|---|
| 跨日配平公式错（base_volume 漏算） | 单测覆盖 6 种 base_volume / target_volume / position 组合 |
| 前端 task 下拉 reload 闪烁 | Pinia store 缓存，selectedTaskId 落 localStorage |
| migration 在 MySQL 上 IF NOT EXISTS 不支持（MySQL 8 才支持 IF NOT EXISTS for ADD COLUMN） | 用 INFORMATION_SCHEMA 检测 |
| 旧 user_def='T0' 单不算 task 影响 | 兼容路径：保留 stats 端点聚合 user_def='T0' 单，给"导入为 task"按钮 |
| Order.task_id 不加 FK 约束 → 删 task 后 orders.task_id 变野值 | commit 5 DELETE 端点显式 set orders.task_id = NULL where task_id = X |

## 与现有 change 冲突检查

| change | 冲突？ | 备注 |
|---|---|---|
| `add-manual-adjust-and-history-pages` | ❌ 不冲突 | T0Task 独立表 |
| `phase-2-architecture-split` | ❌ 不冲突 | t0_tasks.py 进 services/t0/ |
| `t0-quota-frame` | ⚠️ 部分重合 | quota frame 与 task overview 都用 realized_pnl；task overview 在 quota 之外（更深入）。并存。 |
| `2026-07-08-sqlite-to-mysql` | ❌ 不冲突 | migration 走 dual driver + INFORMATION_SCHEMA |