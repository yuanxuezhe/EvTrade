## 1. Schema 数据模型（v12 Phase 1）

- [x] 1.1 删除 `Position.today_buy` / `Position.today_sell` 两列（`server/models/orm.py`）
- [x] 1.2 同步注释与 `synced_from` 含义（manual 调平标记） — `orm.py:Position` docstring + synced_from 注释（`'rpc_full'`/`'push_partial'`/`'manual'`）
- [x] 1.3 DB 迁移脚本：`ALTER TABLE positions DROP COLUMN today_buy; ALTER TABLE positions DROP COLUMN today_sell;` — `scripts/migrations/2026-07-03-drop-position-today-buy-sell.sql`
- [x] 1.4 静态扫 `server/` `client/` 确认 0 引用 `today_buy` / `today_sell`（仅剩注释/docstring 中的 v12 移除注解 + `t0_stats.py` 的 T0Stats 字段重名 `today_buy_volume`/`today_sell_volume` 业务无关）
- [x] 1.5 同步修订 `openspec/specs/data-model/spec.md`（v12 修订 Position 字段表 + 业务规则段） + `positioning/spec.md` REQ-POS-001/003/004 + `push/spec.md` REQ-PUSH-031 删字段引用
- [x] 1.6 `tests/server/models/test_orm.py` 加回归：11 个用例覆盖 today_buy/today_sell 缺席 + Position 核心列 + Asset 单行约束 + Order/Trade PK 不变

## 2. 调平 API（v12 Phase 2）

- [x] 2.1 `server/api/asset_adjust.py` (NEW): `AdjustAssetRequest` + `AssetOut` + `AdjustAssetResponse` + `register_adjust(router)` + handler（admin 鉴权 + Pydantic validator NaN + at-least-one-delta 手动校验）
- [x] 2.2 `server/api/asset.py` facade 装配：`from server.api.asset_adjust import register_adjust; register_adjust(router)`
- [x] 2.3 `server/api/position_adjust.py` (NEW): `AdjustPositionRequest` + `PositionOut` + `AdjustPositionResponse` + `register_adjust(router)` + handler（`{stock_code}` path param + 404 when row missing + at-least-one-delta 手动校验）
- [x] 2.4 `server/api/positions.py` facade 装配
- [x] 2.5 `require_admin` 鉴权：`server/auth/deps.py::require_admin` 直接挂端点 `dependencies=[Depends(require_admin)]`
- [x] 2.6 `tests/server/api/asset/test_adjust.py` 8 用例：调增 cash 成功 / 调增 total_asset（cash 不动）/ 调减负值（broker 可透支）/ 空 body 422 / 全 None 422 / 仅 reason 422 / trader 403 / 未登录 401 — **8/8 PASSED**
- [x] 2.7 `tests/server/api/positions/test_adjust.py` 10 用例：调增 vol / 同时调两字段 / unknown 404 / trader 403 / 未登录 401 / 只传 vol 不动 avl / 只传 avl 不动 vol / synced_from manual 标记持续 / 空 body 422 / 仅 reason 422 — **10/10 PASSED**
- [x] 2.8 `openspec/specs/trading/spec.md`：REQ-TRADE-001 加 v12 历史查询三参数强化；REQ-TRADE-004 加 admin-only PUT 调平鉴权；新增 REQ-TRADE-009 调平 API 完整契约（含 5 个 Scenarios）；API Surface 表加 2 行 PUT

## 3. 前端 IDB 持久化层（v12 Phase 3）

- [x] 3.1 `client/src/utils/idb.js` (NEW): 薄 IDB Promise 封装 `openDB / idbGet / idbPut / idbDelete / idbClear / _resetForTests`，单例 connection 缓存，Node/SSR 不可用时 reject
- [x] 3.2 `client/src/stores/holdings_idb.js` (NEW): `initIDB / saveOrdersForDate / loadOrdersForDate / saveTradesForDate / loadTradesForDate / clearDate / _resetForTests`，DB 名 `EvTrade-holdings-cache` v=1，含 `orders`/`trades` 两个 store
- [x] 3.3 `client/src/stores/holdings_bootstrap.js`：改造 `_tryIDBFirst()` helper — IDB 命中跳过 orders/trades HTTP，asset/positions 仍拉；`_saveAfterBootstrap()` fire-and-forget 写 IDB
- [x] 3.4 `client/src/stores/holdings_push.js`：`applyOrderPush` 末尾 + `applyTradePush` 末尾（含 orders 间接累计处）调 `_persistOrders/_persistTrades`（fire-and-forget）
- [x] 3.5 `openspec/specs/frontend/spec.md`: REQ-FE-100 加 v12 IDB 豁免段（4 个 Scenario 重写含 IDB 路径）；新增 REQ-FE-300 IDB 模块契约段（7 个 Scenario 覆盖 6 个 export + 写异常 + ws push 双写 + bootstrap IDB 优先 + 跨日降级 + 拉完写 IDB）
- [x] 3.6 `openspec/specs/intraday-orders-trades-cache/spec.md` (delta)：change 自带 delta，已完整覆盖 (REQ-idb-cache-001~005：TodayOrders/TodayTrades 数据流 / IDB write-through 行为 / bootstrap 加载顺序 / 多 tab 行为 / ws push fire-and-forget) — **无需再改**
- [x] 3.7 `client/tests/stores/holdings_idb.test.js` 14 用例：读写回路 5 + 跨日清理 3 + fire-and-forget 3 + IDB 降级 2 — **14/14 PASSED**（通过 `vi.mock` 注入 Map 模拟 IDB，避免真 indexedDB）

## 4. 页面拆分（v12 Phase 4）

- [x] 4.1 新建 `client/src/views/TodayOrders.vue`：读 Pinia.orders + IDB 持久化（无 HTTP）
- [x] 4.2 新建 `client/src/views/TodayTrades.vue`：读 Pinia.trades（无 HTTP）
- [x] 4.3 新建 `client/src/views/HistoryOrders.vue`：局部 state + el-date-picker + `getOrders({ startDate, endDate, stockCode })`
- [x] 4.4 新建 `client/src/views/HistoryTrades.vue`：同 上 + `getTrades(...)`
- [x] 4.5 `client/src/router/index.js`：新增 4 个路由 + 旧 `/orders` `/trades` redirect 到 today
- [x] 4.6 删除 `client/src/views/Orders.vue` 与 `Trades.vue`
- [x] 4.7 `client/src/views/Trade.vue` 删除"今日委托"块，加"今日委托 →"链接
- [x] 4.8 同步修订 `openspec/specs/frontend/spec.md` 路由段 + `orders-trades-history-query/spec.md` 视图契约
- [x] 4.9 `client/src/api/index.js`：加 `api.adjustAsset` + `api.adjustPosition` 封装
- [x] 4.10 `client/src/views/admin/cache/CachePositions.vue`：加"调平"按钮
- [ ] 4.11 `tests/client/views/test_history_orders.vue.spec.js` + `test_today_orders.vue.spec.js`：分别测试 history 不走 Pinia / today 不走 HTTP — **scope 决策后再做**（见 §6.7 备注）

## 5. Spec 同步 + 跨 spec 影响

- [x] 5.1 同步 `openspec/specs/data-model/spec.md` 表 3 字段表 + 业务规则段
- [x] 5.2 同步 `openspec/specs/positioning/spec.md` REQ-POS-001/003/004 移除 today_buy/sell（REQ-POS-005 调平入口 = Phase 2.8）
- [x] 5.3 同步 `openspec/specs/trading/spec.md` REQ-TRADE 历史参数强调 + 新加 adjust API 段
- [ ] 5.4 同步 `openspec/specs/system-init/spec.md` REQ-INIT-003 reconcile 边界
- [ ] 5.5 同步 `openspec/specs/frontend/spec.md` REQ-FE-100 豁免 + 路由段 + ws push 双写 + IDB 模块契约
- [x] 5.6 同步 `openspec/specs/push/spec.md`：调平不影响 push，trd_cfm 增量 vol 保留语义（cross-reference 已加）
- [ ] 5.7 同步 `openspec/specs/rpc-protocol/spec.md`：无影响（broker 仍只发 ord/trd）

## 6. 验证 + 归档

- [ ] 6.1 跑测试：`pytest tests/server/` 全过（含新加的 adjust 测试）
- [ ] 6.2 跑前端测试：`npm test` 全过（含新建的 holdings_idb + view 测试）
- [ ] 6.3 手动验证：login → `/today/orders` → 看到当日委托 → F5 → 立刻显示（来自 IDB）→ 等待 ws push → 增量合并 → admin 调平 `Position.vol += 100` → 持仓页 +100 → 触发 manual reconcile → 调平消失
- [ ] 6.4 手动验证：login → `/history/orders` → 选 2026-06-01 → 2026-06-30 → 看到该区间所有委托
- [ ] 6.5 DB 迁移脚本 prod dry-run（dev DB）
- [ ] 6.6 `openspec validate add-manual-adjust-and-history-pages --strict` 通过
- [ ] 6.7 commit 准备：每步独立 commit（per memory `feedback_commit_granularity.md`），最终合并 5-6 个 commit
- [ ] 6.8 `/opsx:archive add-manual-adjust-and-history-pages`

## Reference

- 提案：`openspec/changes/add-manual-adjust-and-history-pages/proposal.md`
- 设计：`openspec/changes/add-manual-adjust-and-history-pages/design.md`
- Specs：`openspec/changes/add-manual-adjust-and-history-pages/specs/`
  - 修改：`data-model` / `positioning` / `trading` / `system-init` / `frontend`
  - 新增：`asset-position-adjust` / `intraday-orders-trades-cache` / `orders-trades-history-query`
- 依赖的 OpenSpec change：
  - `consolidate-position-data-flow` —— 提供 `trd_cfm` 增量 `Position.vol` 语义（保留不动）
  - `align-status-codes-to-xtconstant` —— broker xtconstant 字典（不冲突，但 IDB 缓存的 orders.status 应是 broker 码）
