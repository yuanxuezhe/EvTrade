# Proposal — T0 任务管理（v18）

## Why

现状：
- `T0Trade.vue` 已经能快速做 T（买/卖/配平/快捷键）
- `Order.user_def = 'T0'` 作为隐式标签，事后通过 `/api/t0-stats/{code}`、`/api/t0-exposure`、`/api/t0-aggregate` 统计

缺口：
1. **没有显式"做T任务"实体**——"为某只券建一个 T0 任务"是用户心理动作，系统无对应概念
2. **没有"保留底仓"语义**——一键配平 = `balanceBtnState` 默认平到 0，跨日反复平会越界
3. **跨日配平不收敛**——`/t0-exposure` 按单日 trd_date 算，多日累计净敞口要客户端 sum
4. **整体做T收益和单券做T收益口径混乱**——aggregate 是按 user_def='T0' 拉全集，区分不出"哪些是为同一个任务服务的单子"
5. **"没有持仓先开仓"场景**——T0Trade 已支持开仓，但开出的仓位和未来"建任务"无关联

## What Changes

新增 **`T0Task` 一等公民实体**：
- 一份 task = 一只券 + 一个底仓量 + 一个目标量 + 一个生命周期（active / closed / archived）
- Order 表加 `task_id`（nullable, FK → t0_tasks.id），与现有 `user_def` 共存
- Task 视角聚合：开仓量、平仓量、净敞口、已实现盈亏、未实现盈亏、累计天数、胜率
- 新 API：
  - `POST /api/t0-tasks` —— 基于现仓位建任务
  - `GET /api/t0-tasks` —— 列表（按状态过滤）
  - `GET /api/t0-tasks/{id}` —— 详情（带统计）
  - `POST /api/t0-tasks/{id}/balance` —— 按 task 净敞口 - base_volume 配平
  - `POST /api/t0-tasks/{id}/close` —— 关任务（剩余敞口自动平 → close）
  - `DELETE /api/t0-tasks/{id}` —— 仅 archived 状态可删（级联删 task_id 关联；orders 保留）
- 新前端组件：
  - `<T0TaskList>` —— 侧栏任务列表（active / closed 切换）
  - `<T0TaskDetail>` —— 详情面板（持仓 + 历史 pnl + 操作按钮）
  - `<T0TaskCreateDialog>` —— 从持仓 / 报价入口建任务
  - 集成进 `T0Trade.vue` —— 顶部加任务切换下拉，下单按钮带 task_id

## Backward Compatibility

- **保留 `user_def = 'T0'`** —— 旧单（无 task_id）继续按 REQ-TRADE-006 统计
- **新建 task 后的新单**：同时写 `user_def = 'T0'` **和** `task_id` —— 双标识
- **旧 T0 客户端 UI**（无 task 概念）依然能跑：下单不带 task_id，`user_def='T0'` 旧路径聚合
- **迁移策略**：不必回填旧 task；用户可手动"导入"持仓为新 task

## Impact

| 文件 | 影响 |
|---|---|
| `server/models/orm.py` | 新增 `T0Task`；`Order` 加 `task_id` 列 + 索引 |
| `server/services/t0/` | 新增 `tasks.py`（task CRUD + 配平算法）|
| `server/api/` | 新增 `t0_tasks.py`（6 个端点）|
| `server/migrations/` | 新增 migration：`add-t0-tasks.py`（创建 t0_tasks 表 + orders 加 task_id 列）|
| `client/src/views/T0Trade.vue` | 顶部 task 切换下拉 + 下单带 task_id |
| `client/src/components/trade/T0TaskList.vue` | 新增 |
| `client/src/components/trade/T0TaskDetail.vue` | 新增 |
| `client/src/components/trade/T0TaskCreateDialog.vue` | 新增 |
| `client/src/api/t0_tasks.js` | 新增 API client |
| `client/src/stores/t0_tasks.js` | 新增 Pinia store |
| `openspec/specs/trading/spec.md` | 加 REQ-TRADE-013 ~ 017 |
| `openspec/specs/data-model/spec.md` | 加 T0Task 表 schema |

## Scope Boundaries

✅ **本 change 范围**：
- T0Task 实体 + 6 个 API
- 前端 task 列表 / 详情 / 创建对话框
- 配平函数基于 task 净敞口（与现有 balanceBtnState 同口径）
- 统计按 task 维度（已实现 + 未实现）

❌ **不在本 change**（下次）：
- 自动再平衡 / 策略触发（C 候选）
- 跨设备同步 / 多用户协作
- 后台任务调度 / 提醒
- 历史 user_def='T0' 单的回填归类