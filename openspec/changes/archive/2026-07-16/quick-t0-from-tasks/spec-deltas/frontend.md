# spec-deltas/frontend.md — REQ-FE-230

> 增量 spec：`frontend` capability
> 对应 changeset：`2026-07-16-quick-t0-from-tasks`
> 合并目标：`openspec/specs/frontend/spec.md`（在 REQ-FE-220 之后）

---

## REQ-FE-230: T0Trade 主表按任务视角 + 添加任务 dialog 嵌入 HoldingsPanel

### Why

用户业务实际是「做T 任务」视角（每行 = 一做T 任务），而非「持仓」视角（每行 = 一持仓标的）。现有 v54 T0Trade 主表是 holdings 视角，与「快速做T」页面名不符实。

### What

1. **主表数据源** 从 `holdingsStore.positions` 切换到 `t0TasksStore.tasks`
2. **主表列重设 8 列**（聚焦任务语义，砍掉可买/可卖/浮盈%）
3. **header "管理任务" 按钮** 改名 "添加任务"（type=primary，icon `+`）
4. **添加任务 dialog 改宽 900px**，左 350px 嵌 HoldingsPanel，右 520px 嵌 T0TaskCreateDialog（grid 2 列布局）
5. **HoldingsPanel 加 select-stock emit**（单击触发），父组件 T0Trade 监听后写入 createForm.stock_code

### Scenario

#### S1: 添加任务 — 用户从持仓面板选中标的

- **GIVEN** admin/登录用户进入 `/quick-t0` 页面
- **AND** 主表为空或显示已有 task 列表
- **WHEN** 点击 header "添加任务" 按钮
- **THEN** "添加做T任务" dialog 弹出（宽 900px）
- **AND** dialog 左侧显示 HoldingsPanel（10 列：代码/名称/期初/持仓/可用/成本/最新/市值/浮盈/收益率）
- **AND** dialog 右侧显示 T0TaskCreateDialog（5 字段：stock_code / base_volume / target_volume / coefficient / note）
- **WHEN** 用户在 HoldingsPanel **单击** 某持仓行（如 000001.SZ 平安银行）
- **THEN** T0TaskCreateDialog 的 stock_code 字段自动回填为 `000001.SZ`
- **AND** dialog 不关闭
- **WHEN** 用户填写 base_volume / target_volume / coefficient 后点"创建"
- **THEN** `POST /api/t0-tasks` 返回 201 + 新 task（含 `id` / `stock_code` / `summary`）
- **AND** 主表新增一行 task（任务编号 = `task.id`，如 `#42`）

#### S2: 主表按任务视角展示

- **GIVEN** 用户在 `/quick-t0` 页面
- **WHEN** 页面加载完成
- **THEN** 主表显示 `t0TasksStore.tasks`（每行 = 1 task）
- **AND** 列依次为：
  1. **状态**（active 蓝 / closed 灰 / archived 红 el-tag）
  2. **任务编号**（`#${task.id}`，text-mono）
  3. **标的**（代码 + 名称，组合显示）
  4. **底仓+目标**（`base + target = 总持仓`，text-mono）
  5. **当前持仓**（`task.summary.position_vol`）
  6. **做T盈亏**（`task.summary.realized_pnl`，红涨绿跌）
  7. **做T收益率%**（`task.summary.unrealized_pnl / (task.base_volume * cost_price)`）
  8. **操作**（配平 / 平仓 / 详情 3 个 link button）

#### S3: 0 任务时 empty 引导

- **GIVEN** 用户首次进入 `/quick-t0`，无任何 task
- **WHEN** 主表渲染
- **THEN** el-table 显示 empty-text："暂无 T0 任务，点击「添加任务」按钮创建"

#### S4: HoldingsPanel 双击语义保持不变

- **GIVEN** HoldingsPanel 被嵌入 dialog（左栏）
- **WHEN** 用户**双击** 某持仓行
- **THEN** emit `apply-to-order`（v53 REQ-FE-HOLDINGS-DBLCLICK 行为保持）
- **AND** 不触发 dialog stock_code 回填（仅单击触发 select-stock）

#### S5: 创建后自动刷新主表

- **GIVEN** 用户在 dialog 中创建了 task
- **WHEN** `POST /api/t0-tasks` 返回 201
- **THEN** `t0TasksStore.createTask` 自动乐观插入 tasks 数组
- **AND** 主表 re-render 显示新行（无需手动刷新）

### Non-Goals

- ❌ 不删 v54 lib/t0-calc.js 5 函数（保留为 utility lib，未来可能复用）
- ❌ 不改 HoldingsPanel 的 dblclick 语义（仍归 v53 REQ-FE-HOLDINGS-DBLCLICK）
- ❌ 不改后端 API/store（已有完整 endpoints）
- ❌ 不做 task 模板/批量创建
- ❌ 不改 T0TaskList.vue 9 列结构（仅删 drawer 模式）

### Risk

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| dialog 900px 太宽挤压右栏卡片 | 低 | UX 略差 | 桌面 1280+ viewport 验证 |
| HoldingsPanel 10 列在 350px 宽内挤 | 中 | 横向滚动 | 复用 v31.1 mini panel 列宽（~718px），el-table 横向滚动 |
| v54 commit 推翻风险 | 低 | 历史 | 不 revert，新 commit 改在 master 顶层 |

### 相关文件

- `client/src/views/T0Trade.vue`（主改动）
- `client/src/components/trade/T0TaskCreateDialog.vue`（commit 1）
- `client/src/components/trade/HoldingsPanel.vue`（commit 2）
- `client/src/components/trade/T0TaskList.vue`（删 drawer 模式）
- `client/src/stores/t0_tasks.js`（0 改动，createTask 已有乐观插入）
- `server/api/t0_tasks.py`（0 改动，POST /t0-tasks 已就绪）