## Why

`/t0-trade` (快速做T) 页面在 trader 实际快节奏下单流程中暴露 5 类痛点:
1. 资金/持仓校验缺失, broker 拒收后才反馈 (trader 误点)
2. `useT0Balance.js` 236 行 composable 完全闲置, 与 `useQuickT0.js` 平行实现
3. 30 持仓 → 30 GET 串行, 大账户首屏"今盈"列普遍 `--`, 差量更新没有
4. 副行 30 天 sparkline 与底部 7/30/90D 曲线同一数据画两次 SVG
5. 主表 50+ 持仓翻不动, 无排序/筛选/快捷键 (B/S/P/↑↓)

目的: 在 `/opsx:explore` 模式下确认后, 一次性出 OpenSpec 三件套, 让后续 `/opsx:apply` 多 commit 闭环.

## What Changes

- (b 接入) `useT0Balance.js` 拆 `client/src/lib/t0-calc.js` **纯函数层** (`roundToLot` / `calcInsufficientCash` / `calcInsufficientPosition` / `buildOrderParams` / `resolvePriceTypeCode`), T0Trade.vue 与未来批量页面共用; hook 本体保留给单标的 reactive wrapper
- (A 校验) T0Trade 主表 `买/卖/配平` 3 按钮 disabled 条件加 `insufficientCash / insufficientPosition`, tooltip 注明"缺资金 ¥X / 缺持仓 Y 股"
- (C 缓存) 新增 `client/src/composables/useT0Stats.js`: 30s TTL 内存 map (`stockCode -> { data, ts }`), `watch holdings.length` 只 diff 新增/移除标的, ws push 增量 invalid 对应 key
- (E 重复清理) 副行 sparkline 移除 (与底部曲线重复), 副行改为 hover tooltip 显示 30 日累计数值
- (F 排序+快捷键) 主表 `<el-table>` sortable 列 (今盈/净敞口/浮盈%/持仓); 新增 `useT0Keybindings.js` 全局 listener: `↑/↓` 切换 selectedRow, `B/S/P` 触发买/卖/配按钮, `Enter` 打开详情抽屉; 加 `uiStore.t0Keybindings` toggle 开关

**BREAKING**:
- `useT0Balance.js` 公开 API 重命名/拆分, 仅有 `useT0Balance()` 调用方需跟随 (`T0Trade.vue` 当前**未消费**该 hook, 所以无外部破坏)
- `useT0OrderSubmit.js` `submitOrder` 内部新增 disabled 校验分支 (不会改入参), 调用方行为不变
- `uiStore` 新增字段 (默认开启), 不破坏现有 store action

## Capabilities

### New Capabilities
- (无 — 全部在 frontend / trading 既有 spec 下覆盖)

### Modified Capabilities
- `frontend`: T0Trade 视图层行为增强 (UI 校验/缓存/排序/快捷键 + lib 拆分), 详细 `When/Then` 场景在 `specs/frontend/spec.md` delta
- `trading`: 资金/持仓校验作为下单前置 disabled (原仅"0 持仓"和"0 股"), 详细 `When/Then` 场景在 `specs/trading/spec.md` delta

## Impact

- 受影响文件 (单 change 多 commit 拆分):
  - `client/src/lib/t0-calc.js` (新, 纯函数层, ~80 行)
  - `client/src/composables/useT0Balance.js` (重构: 暴露 `@/lib/t0-calc.js` 函数 + 保留 reactive wrapper)
  - `client/src/composables/useT0Stats.js` (新, ~60 行)
  - `client/src/composables/useT0Keybindings.js` (新, ~40 行)
  - `client/src/composables/useT0OrderSubmit.js` (改: 接 insufficientCash/Position disabled 校验)
  - `client/src/views/T0Trade.vue` (改: 接 useT0Balance + useT0Stats + useT0Keybindings, 删副行 sparkline + 加 sortable 列)
  - `client/src/stores/ui.js` (新字段: `t0Keybindings` boolean, 默认 true)
  - `openspec/specs/frontend/spec.md` (MODIFIED scenarios)
  - `openspec/specs/trading/spec.md` (MODIFIED scenarios)
- 单测覆盖: `client/src/lib/t0-calc.test.js` (新, ~30 用例); 现有 `useQuickT0.test.js` 不动
- 集成验证: `npm test -- --run` (应 103+30+); `npx vite build`; dev 启后 `/t0-trade` 走通 5 个改动点
- 不动: ws push / RPC 数据契约 / broker 协议 ("卖1买1" UI≠协议问题 改 backends, 不在本 change)
