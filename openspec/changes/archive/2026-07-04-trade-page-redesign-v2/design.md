## Context

本 change 是 v13 (Trade 页面 Layout 优化) 的延续。前一轮 `archive/2026-07-04-trade-panel-layout-fill` 已把 Trade.vue 改成 grid 2 列布局，左列下单+行情，右列两个 mini-panel 内嵌委托/成交。本轮聚焦 5 项 UX 优化：

1. **Trade.vue 顶部 quicklinks 行删除** — 移除低价值入口（"今日委托 →"/"今日成交 →"外链 + 刷新按钮）
2. **Trade.vue 左列整屏填充** — 不留底部空白
3. **mini-panel 内嵌分页** — 20 行/页，活跃日不滚动
4. **删 TodayOrders.vue / TodayTrades.vue 冗余 view + 路由 redirect + sidebar 改名** — 单一入口原则（Trade.vue 内嵌）
5. **HistoryOrders / HistoryTrades 加预设 chip + 强制历史范围 + 双向高亮联动** — 用户不再重复键入昨日/3天/周/月

**当前代码状态**（基于 ground-truth read）：
- `views/Trade.vue` 197 行 — 含 `trade-quicklinks` 行 + `refreshAll` 函数（按钮仍存在）
- `components/trade/TodayOrdersPanel.vue` 222 行 — 含 Refresh 按钮 + ResizeObserver + scroll progress + `bodyMaxHeight = '100%'`
- `components/trade/TodayTradesPanel.vue` 173 行 — 同上
- `views/HistoryOrders.vue` 340 行 — `onMounted` 默认 `[activeDay, activeDay]`
- `views/HistoryTrades.vue` 332 行 — 同上
- `components/Sidebar.vue` — `委托查询` / `成交查询` + pendingCount badge
- `router/index.js` — `/orders → /today/orders`, `/trades → /today/trades`
- `stores/holdings_bootstrap.js` — `BOOTSTRAP_WINDOW_DAYS=1`（已满足"今日缓存 = 后端 start/end = activeDay"约束，本轮不动）

**Stakeholder**：交易员（高频用户）、admin（路由 / sidebar 改名影响次要）

## Goals / Non-Goals

**Goals:**
- Trade.vue 不再含顶部 quicklinks；左列 + 右列都通过 flex 链填满 viewport（不留白）
- mini-panel 委托 / 成交支持 20 行/页 el-pagination，活跃日不滚动 panel shell
- 委托 / 成交的入口收窄到 1 个：Trade.vue 右侧 mini-panel（删除 `TodayOrders.vue` / `TodayTrades.vue`，`/today/*` 路由 redirect 到 `/history/*`，sidebar 改名）
- HistoryOrders / HistoryTrades 提供 4 个预设 chip（昨日 / 最近三天 / 最近一周 / 最近一个月），点击即查
- History view 强制 dateRange 不含今日（picker 禁 today+）
- 撤单按钮物理隔离：只 TodayOrdersPanel 内嵌可撤

**Non-Goals:**
- 不改 holdings store / IDB 写穿契约 / ws push 入口
- 不动后端 FastAPI 端点（`start_date`/`end_date` 区间过滤已支持）
- 不改 21 个其它业务 view
- 不引入新依赖（el-pagination 已在 element-plus 内）
- 不动 chip 计算的精确日历算法（用 `shiftDateStr` 工具函数跨月跨年处理已实现）

## Decisions

### D1: 删 vs 保留 TodayOrders.vue / TodayTrades.vue

**决策**：删除。

**理由**：
- 当前路径：用户 Trade.vue 下单 → 顶部"今日委托 →" 外链 → 跳 `/today/orders` 完整页 → 看一遍 → 再回 Trade.vue。下单-查委托的"操作回路"被切两个页面，不符合"委托面板紧贴下单表单"的交易员心智模型
- v12 改"今日 = Pinia 实时 + IDB 写穿" 后，Trade.vue 内嵌 panel 已能用同样数据流
- 完整 view 价值 vs 内嵌 panel 价值对比：
  - 完整 view 提供 banner / 多维过滤 / 详情 / 多日历等（实际查 90% 用户只看今日）
  - mini panel 提供 紧贴下单/同屏/低滚动/click-to-cancel 高频场景
- 测试（grep）确认 `TodayOrders.vue` / `TodayTrades.vue` 除 router 外无任何引用 → 删除零风险

**替代方案对比**：
- A. **保留**：双入口 — 文件冗余 + 路由分裂 + sidebar 标签分歧
- B. **删除 + redirect**：单一入口（Trade.vue 内嵌）— **采纳**
- C. **合并 view 内容到 panel**：6 列 → 9 列变窄不可读 — 否决

### D2: mini-panel 分页（20 行/页）

**决策**：el-pagination 默认 20 行，pageSizes [10, 20, 50, 100]。

**理由**：
- 当前活跃 A 股日内委托 30-80 笔属于常态，20 行/页是 el-pagination 行业默认值（与 HistoryOrders.vue 一致）
- 100 行硬上限合理（element-plus 默认 max 100，超过页码跳转体验差）
- panel-local page state（不入 Pinia）— panel 卸载/路由切换后分页归 1，符合直觉
- el-table `:data="pagedOrders"` 接 computed slice — Vue 响应式 + slice O(pageSize) 性能可忽略

**替代方案**：
- A. **滚动条 + virtual scroll**：实现复杂 + panel 体量小不需要
- B. **20 行/页**：采纳（行业默认 + 与 History 一致）

### D3: History view 的 "dateRange 不含今日" 约束

**决策**：picker `:disabled-date="isAfterToday"`；onMounted `dateRange=null`。

**理由**：
- 与 Trade.vue 内嵌 mini-panel 形成严格分层：今日 → mini panel（实时），历史 → history view（独立路由）
- 若 onMounted 默认查 activeDay，等于 history view 重复展示"今日"数据，违反分层语义
- picker 禁用 today+ 是 UI 保险丝，防止用户手动选错误（即使选 today 后再调整，也比"悄悄接受 today"更显式）

**替代方案**：
- A. **不限日期范围**：简洁但语义模糊 — 否决
- B. **picker 禁用 + onMounted 留空 + chip 引导**：3 重保险 — **采纳**

### D4: chip 预设范围的口径（"3 天 = today-3 ~ today-1"）

**决策**：所有预设范围严格"含 today-1 不含 today"（口径 = 日历日，**不**含今日）。

**理由**：
- 用户原话："历史查询，dateRange 都是历史，比如最近三天，表示 today-3, today-1"
- 这是显式的语义选择：history view 排除今天，由 mini panel 单独承担今天展示
- 注：与行业日历日定义一致（"最近 3 天" 不含今日以避免歧义）

**计算公式**：
- 昨日 = `[shiftDateStr(today, -1), shiftDateStr(today, -1)]`
- 最近三天 = `[shiftDateStr(today, -3), shiftDateStr(today, -1)]`  # 3 个日历日
- 最近一周 = `[shiftDateStr(today, -7), shiftDateStr(today, -1)]`  # 7 个日历日
- 最近一个月 = `[shiftDateStr(today, -30), shiftDateStr(today, -1)]`  # 30 个日历日

**工具**：`client/src/utils/date.js:shiftDateStr(yyyymmdd, deltaDays)` — 已实现跨月跨年闰年，git 历史可查（REQ-FE-009.8 v9 引入）

### D5: chip ↔ picker 双向联动高亮

**决策**：computed `activePreset` 监听 `dateRange`；任一 chip 命中时点亮，否则全灰。picker 改动实时刷新高亮。

**理由**：
- UX 直觉：用户用 picker 选了"恰好等于最近一周"的范围，chip 应自动高亮（双向 sync）
- 实现成本低：`activePreset = computed(() => presetRanges.findIndex(r => rangeEquals(dateRange, r)))`，每 preset 一个 `class:active`
- 解耦：chip 不依赖 picker 内部状态，仅依赖 panel 暴露的 `dateRange` ref

**替代方案**：
- A. **单向（chip→picker）**：简单但 picker 改后 chip 不响应 — 否决
- B. **双向 + computed**：自然 Vue idiom — **采纳**

### D6: 撤单按钮物理隔离

**决策**：仅在 `TodayOrdersPanel` 显示撤单按钮；`TodayTradesPanel` + `HistoryOrders` 永远不显示。

**理由**：
- 撤单数据流：`orderStore.cancelOrder(order_no, trd_date)` → broker 仅接受 `trd_date == activeDay`
- `HistoryOrders.vue` 因 dateRange ≠ activeDay 即使能撤也会被 broker 拒 — 加按钮误导用户
- `TodayTradesPanel` 是成交（终态历史），无可撤概念
- 当前架构已满足（grep 验证无 cancelOrder 调用在 forbidden views），spec 锁住防止后续回归

**回归护栏**：建议 PR review 检查 `HistoryOrders.vue` 的新增列不含 "操作" col

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `pendingCount` badge 删除后, 委托面板的"待成交"视觉提示减弱 | AppHeader 已有总持仓 badge; pending 状态通过 ws `applyOrderPush` 实时反映 (`<OrderStatusBadge>` 自动 re-render); 不依赖 sidebar badge |
| History view onMounted 改留空, 首屏空白用户可能困惑 | el-empty 文案明确"请选择起止日期查询"; 4 个 chip 是首选入口; 视觉引导 (chip 用蓝色 brand-color 高亮) |
| 老用户书签 `/today/orders` 404 风险 | router 加 `/today/orders → /history/orders` + `/today/trades → /history/trades` redirect, 全 0 损耗 |
| chip "3 天不含今天" 与 Pingan / 同花顺等行业的"最近 N 天"语义不一致 (后者含今天) | chip label 明确"昨日"/"最近三天 (历史)" + 加 tooltip; spec 文档明确语义; 后续可加 toggle (历史 / 含今天) 但本期不做 |
| mini-panel 分页切换后 el-table 滚动条不归顶 | el-pagination `@current-change` hook + nextTick + el-table scrollTop=0; 或样式上让 el-table 自带 reset |
| BOOTSTRAP_WINDOW_DAYS=1 注释模糊 (后续维护者不易识别"今日单日"是设计而非简化) | 在 `holdings_bootstrap.js` 加注释 `// v13: 单日窗口即"今日缓存"语义, mini panel 客户端再守门 trd_date === activeDay` |
| el-pagination 加入 mini-panel 后行数少 (<20) 显示空组件 | `<el-pagination v-if="total > pageSize">` 隐藏 (避免视觉噪声) |
| History view onMounted 留空 → 用户首次进入看不到表格 | 加 v-loading="loading" 让 spinner 仍在初始挂载时显示, 立即被 el-empty 替换 |

## Migration Plan

### 部署顺序 (5 个 commit, 严格顺序)

```
1. feat(client): Trade.vue 删 .trade-quicklinks + 左列 flex 链整屏填充
2. refactor(client): TodayOrdersPanel/TodayTradesPanel 加分页 + 精简 (去 refresh + scroll progress)
3. refactor(client): 删 TodayOrders/TodayTrades view + 路由 redirect + sidebar 改名 + 删 pending badge
4. feat(client): HistoryOrders/HistoryTrades 加预设日期 chip + 强制历史范围 + 双向高亮
5. docs(openspec): archive change + 改 specs/frontend + orders-trades-history-query + intraday-orders-trades-cache
```

### 单 commit 内部步骤

每个 commit 包含：
1. 代码改动 (`Edit` / `Write`)
2. `cd client && npm test -- --run` — 103 单测全过 (panel 分页不引入 store 变更, 无 unit test 改动)
3. `cd client && npx vite build` — 构建验证
4. 手动 UI smoke (若开发环境可起):
   - 登录 `/trade` → 顶部无 quicklinks + 左右列等分
   - 委托 / 成交 >20 笔 → 出现分页器, 翻页正常
   - sidebar "委托查询" → "历史委托", 无 badge
   - `/orders` → 跳 `/history/orders`, 默认空 + 4 chip 出现
   - 点"最近三天" → 自动查 + chip 高亮
   - picker 改范围 → chip 高亮即时变化
   - picker 选 today+ → 不可点

### 回滚策略

每个 commit 独立 revert 即可:
- commit 1 revert → 恢复 quicklinks + 左列留白 (不破坏其它功能)
- commit 2 revert → 恢复 refresh + scroll progress, 分页消失 (panel 仍可用)
- commit 3 revert → 恢复 view 文件 + 改回 redirect, sidebar 旧 label
- commit 4 revert → 删 chip, history view 恢复 onMounted 默认 activeDay (注: 此 revert 与未来"history 强制不含今日"语义不一致, 完整回滚需要 spec 也 revert)

整体回滚顺序: 5 → 4 → 3 → 2 → 1 (依赖反向)

## Open Questions

无。本轮决策已与用户对齐:
- chip 自动查询 ✓
- 历史范围 = 日历日 (不含今日) ✓
- onMounted 留空 ✓
- mini-panel 撤单按钮保留 ✓ (panel 数据范围 = activeDay, 满足"只有今日委托可撤")
- BOOTSTRAP_WINDOW_DAYS=1 不动 ✓ (满足"今日缓存 = 后端 start/end = activeDay")

后续可考虑 (下一轮):
- chip 加 toggle (历史 / 含今天 切换), 让用户能快速看 N 天含今天 (如"最近一周含今天")
- 历史 view 加导出按钮 (CSV/XLSX) — 当前 CSV 仅导出按钮已有, 此项已是事实
- TodayOrdersPanel 加 keyword 搜索 (按 stock_code 过滤) — YAGNI, 暂不实现
