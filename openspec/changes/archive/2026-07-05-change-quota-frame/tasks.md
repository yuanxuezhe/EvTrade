# Tasks — change-quota-frame

按 scope 拆 5 commit, 单 change。顺序按依赖（纯函数层 → 单测 → 接入 → 配额列 → 验证）。

## 1. useT0Quota composable (commit: feat(client): useT0Quota 纯函数层 + reactive wrapper)

- [x] 1.1 新建 `client/src/composables/useT0Quota.js` (~134 行): 导出 `aggregateQuota(asset, positions, t0StatsMap)` 纯函数 + `rowQuota(row, cash, price)` 纯函数 + `quotaLevel(n)` 颜色阈值 + `useT0Quota(t0StatsMapRef)` reactive wrapper (返回 aggregate computed + rowQuotaFor 闭包)
- [x] 1.2 验证: `useT0Quota()` 在 T0Trade.vue 中能 import，computed 自动响应 holdings.cachedAsset / positions / t0StatsMap 变化

## 2. useT0Quota 单测 (commit: test(client): useT0Quota composable 单测)

- [x] 2.1 新建 `client/tests/composables/useT0Quota.test.js` (24 用例): aggregateQuota 输入 null/空/正常/边界 + rowQuota 输入缺字段/价格=0/正常 + quotaLevel 颜色阈值 + reactive wrapper 集成
- [x] 2.2 验证: `npm test -- --run tests/composables/useT0Quota.test.js` 全过

## 3. T0Trade 顶部 quota frame (commit: feat(client): T0Trade quota frame 顶部 5 pill 概览)

- [x] 3.1 T0Trade.vue template 加 quota frame 块: 5 个 metric pill (现金余量 / 冻结资金 / T+0 可用持仓 / 今日已盈亏 / 持仓市值)，位于 header 设置条下方、主表上方
- [x] 3.2 接入 `useT0Quota(t0StatsMap)` → `quotaAggregate.value` 渲染 pill 数值 + `todayPnlText` / `todayPnlClass` computed (正绿 / 负红 / 0 灰)
- [x] 3.3 移动端 < 1100px 折叠: `.qf-pill--desktop-only` (持仓市值) 通过 `@media (max-width: 1100px)` 隐藏
- [x] 3.4 验证: `npm test -- --run tests/views/T0Trade.test.js` 现有 19 用例仍全过

## 4. T0Trade 行内配额列 (commit: feat(client): T0Trade 主表加 可买/可卖 配额列)

- [x] 4.1 T0Trade.vue template 主表加 2 列: 「可买」(80px) + 「可卖」(80px)，插在「浮盈%」与「操作」之间
- [x] 4.2 「可买」列: 调 `quotaForRow(row).maxBuyable`，颜色阈值 ≥1000 quota-high 绿 / 100-999 quota-mid 橙 / 1-99 quota-low 红 / =0 quota-none 灰
- [x] 4.3 「可卖」列: 调 `quotaForRow(row).maxSellable`，颜色阈值同上
- [x] 4.4 tooltip: 可买 hover 提示 "依赖最新价 ¥X" / "未到时显示 0"，可卖 hover 提示 "持仓可用 vol (avl_vol)"
- [x] 4.5 验证: 不破坏现有排序 (sortable=custom 列不变) + 快捷键 + 抽屉

## 5. T0Trade 单测追加 + 全量验证 (commit: test(client): T0Trade quota 配额列单测)

- [x] 5.1 追加 `tests/views/T0Trade.test.js` (8 用例): quota frame 5 pill 渲染 + quotaAggregate 计算 + todayPnlText 正负 + quotaForRow maxBuyable/maxSellable + quotaLevel 颜色阈值
- [x] 5.2 验证: `npm test -- --run` → 250 旧 + 24 useT0Quota + 8 quota 列 = 282 全过 (实际)
- [x] 5.3 单测时间 ~25s < 30s
- [x] 5.4 T0Trade.vue 行数 = 1040 行 (原 932 + quota frame + 配额列 ~108 行)，未超 1050 阈值，**无需拆子组件**

## 6. spec 同步 + 归档 (commit: docs(openspec))

- [x] 6.1 archive: `openspec archive change-quota-frame --skip-specs` → `openspec/changes/archive/2026-07-05-change-quota-frame/` (frontend spec 因先前 change 已存在结构性 invalid 报错, --skip-specs 跳过 spec sync, 单独 cp t0-quota-frame spec)
- [x] 6.2 归档同步: `openspec/specs/t0-quota-frame/spec.md` (新 capability, 9 Scenario) 已 cp; frontend spec 增量 Defer (待 frontend spec 结构修复)

## 实施偏差备注

- task 1.1 实测 134 行 (spec 估 ~80, quotaLevel + reactive wrapper 加 54 行)
- task 2.1 实测 24 用例 (spec 估 ~15, 多写了 9 个边界用例: NaN/null/undefined、t0StatsMap 缺字段、reactive wrapper 集成)
- task 5.2 实测 282 全过 (spec 估 273, quota composable 多写了 9 用例, 总数多 9)
- spec 修一处数学错误: rowQuota 场景 "cash=100000 price=12.5 → maxBuyable=800000" 应为 8000 (floor(100000/12.5/100)*100 = 80*100 = 8000 股)
- design.md 估 "T0Trade.vue +108 行增量 = 1040" 与实测一致