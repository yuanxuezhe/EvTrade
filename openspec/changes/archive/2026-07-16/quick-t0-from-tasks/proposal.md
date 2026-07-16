# 2026-07-16-quick-t0-from-tasks — 快速做T 切到任务视角

## Why

`client/src/views/T0Trade.vue` v54 (commit `1cb019e/2f7cf0a/6f4d24f`) 重构后主表是 **holdings 视角**（每行 = 一持仓标的），但用户业务实际是 **task 视角**（每行 = 一做T 任务）：

- 用户在「管理任务」drawer 中维护 task，但主表看的是持仓 → **「快速做T」页面名不符实**
- 用户创建任务时**没有一个直观的入口** → 需要"点持仓行 → 自动填 stock_code → 创建"
- v54 引入的 lib/t0-calc.js 5 纯函数（calcT0Pnl / calcExposure / calcInitialQuota / calcT0ReturnRate / resolveBalancePrice）在 holdings 视角下不直接调用 → **主表切到 task 视角后这些函数会落空**

## What

**前端 3 文件改动 + 1 REQ 新增**（后端 0 改动，APIs/store 已完整）：

| 改动点 | 文件 | 内容 |
|---|---|---|
| **①** | `client/src/components/trade/T0TaskCreateDialog.vue` | 接 `externalStockCode` prop + emit `update:externalStockCode`（让 HoldingsPanel 点选能驱动 dialog 表单） |
| **②** | `client/src/components/trade/HoldingsPanel.vue` | 加 `@select-stock` emit（**单击** 触发，**不改** v53 dblclick 语义） |
| **③** | `client/src/views/T0Trade.vue` | a) header 按钮改"管理任务"→"添加任务"（type=primary，icon `+`）；b) 删 T0TaskList drawer；c) "添加任务" dialog 改宽 900px，**左 350px 嵌 HoldingsPanel + 右 520px 嵌 T0TaskCreateDialog**（grid 2 列）；d) **主表数据源** `holdingsPositions` → `t0TasksStore.tasks`，**主表列重设为 8 列**（状态/任务编号/标的/底仓+目标/当前持仓/做T盈亏/做T收益率/操作） |
| **④** | `openspec/specs/frontend/spec.md` | 新增 **REQ-FE-230** T0Trade 主表按 task 视角 + 添加任务 dialog 嵌入 HoldingsPanel |

## Impact

| 影响 | 说明 |
|---|---|
| v54 commit `1cb019e/2f7cf0a/6f4d24f` | 不 revert；本次新 commit 改在 master 顶层 → 历史可追溯 |
| v54 lib/t0-calc.js 5 函数 | **保留不动**，标记 Non-Goals（未来"持仓视角做T"扩展可复用） |
| HoldingsPanel 复用 | Trade.vue 也嵌入 HoldingsPanel，**不改其 dblclick 语义**；只在 dialog 副本上挂 click select |
| T0TaskList.vue | drawer 模式删除（不再用），inline 模式保留 |
| task 数据为空时 | 主表 `el-table empty-text="暂无 T0 任务，点击「添加任务」按钮创建"` |
| 后端 8 个 API + store 11 个 action | 全部已就绪，**0 改动** |

## Non-Goals

- ❌ 不删 v54 lib/t0-calc.js 5 函数（保留为 utility lib 备用）
- ❌ 不改 HoldingsPanel 的 dblclick 语义（仍归 v53 REQ-FE-HOLDINGS-DBLCLICK）
- ❌ 不改后端 API/store（已有完整 endpoints）
- ❌ 不改 T0TaskList 9 列结构（只删 drawer 模式）
- ❌ 不做 task 模板/批量创建（本期只手动逐个）

## Risk

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| dialog 900px 太宽挤压右栏卡片 | 低 | UX 略差 | 左 350 + 右 520 + 30px 间隔总 900px，fit 桌面 1280+ |
| HoldingsPanel 10 列在 350px 内挤 | 中 | 横向滚动 | 复用 v31.1 mini panel 列宽（总 ~718px），el-table 默认横向滚动 |
| task 0 行时 UX 冷启动 | 低 | 新用户困惑 | empty-text 引导点"添加任务"按钮 |
| v54 lib 死代码 | 低 | 技术债 | Non-Goals 标记，README 加注释 |

## verification

- vitest 全过（含 v54 lib 5 函数 + HoldingsPanel/T0TaskCreateDialog 兼容性）
- vue-tsc --noEmit 0 错误
- 浏览器实测：登录 → /quick-t0 → 主表 8 列精准 → 点"添加任务" → dialog 弹出（左侧 HoldingsPanel 可见持仓） → 点持仓行 → dialog stock_code 自动回填 → 创建 → 主表新增一行 task → DOM 验证