# 2026-08-10-init-push-gate — 日初初始化期间前端推送丢弃门

## Why

手动日初（POST /api/admin/sys-status/init）触发对账 + 切日时，后端 `do_reconcile(reconcile_kind='init')` 会与 broker 同步资金/持仓并全表覆盖 positions 表。该过程期间 broker 侧仍可能在推实时 `pos_push` / `ord_cfm` / `trd_cfm`，前端会：

1. **状态瞬时污染**：reconcile 尚未覆盖 positions 前，前端先写入零散 push，表格闪现中间态
2. **日志刷屏**：持仓洪峰（如 2197 只）在 reconcile 窗口内逐条 push → 逐条「持仓刷新/新持仓」日志（holdings-auto-sub-batch 只解决了订阅日志，push 写入日志仍逐条）

用户四点评估（2026-08-10）后采纳 ①②：
- ① 初始化时设置全局系统状态「初始化中」，推送到前端，前端丢弃全部推送
- ② 初始化中后端直接与 broker 同步资金/持仓，写数据库表（既有 `do_reconcile(init)` 已实现）
- ③ 后端同步完将数据同步到前端 IDB（现状已是拉取式同步，维持）
- ④ 前端从 IDB 整体判断 >100 全量订阅（由 holdings-auto-sub-batch 覆盖，维持）

## What Changes

### 后端广播 init_start / init_aborted（`server/api/admin/sys_status.py`）

`init_trading_day` 在生命周期关键点补广播（复用 `system_update` 频道 / `system_status_change` type）：

- **init_start**：`do_reconcile` **之前**广播，`status='initializing'` — 前端据此开丢弃门
- **init_aborted**：reconcile 失败分支补广播，`status='error'` — 前端据此关丢弃门（**原失败路径无广播，若缺失则前端门会死锁**）
- **init_completed**：既有成功广播保留（refactor 到共享 helper，语义不变）

统一承载字段：`{ type:'system_status_change', change_kind, trd_date, previous_trd_date, status, report_id, ts }`。

**不在范围**：
- ❌ 不写 `sys_status.status` 字段为 'initializing'（trade/day-init 守门依赖 status='active'，并发交易不能被日初阻塞）
- ❌ 不动 `do_reconcile` / positions 覆盖逻辑（既有 init 路径已满足 ②）

### 前端丢弃门（`holdings.js` + `ws_dispatch.js`）

- `holdings.js`：新增 `initializing` ref（默认 false），暴露
- `ws_dispatch.js`：
  - `_onSystemStatusChange` 处理 `init_start`（开 gate + 清零丢弃计数）/ `init_aborted`（关 gate + 一次日志）/ `init_completed`（关 gate + 一次日志 + 既有 resetForNewDay）
  - `_onPosPush` / `_onOrderCfm` / `_onTradeCfm` 顶部加 gate：`initializing` 期间直接丢弃（只计数，不逐条刷日志）
  - 模块级 `_discardedDuringInit` 计数，gate 关闭时**一条**汇总日志「初始化期间丢弃 N 条推送」
- **不 gate `quote`**（行情只更新价格显示，不写 positions/orders/trades，丢弃无意义）
- 兜底关门：`SystemInit.vue handleInit` finally 置 false（ws 广播丢失双保险）；`holdings_bootstrap` bootstrap/refreshAll finally 置 false（手动刷新清 stuck gate）

### 时序

```
前端          后端                     broker
 │ POST init   │                        │
 │───────────→│ init_start 广播         │
 │            │───────────→ gate 开      │
 │            │ do_reconcile(init)      │──→ 同步资金/持仓快照
 │            │  (pos_push 洪峰被丢弃)   │
 │            │ init_completed 广播      │
 │            │───────────→ gate 关 + resetForNewDay (RPC 全量拉权威数据)
 │←───────────│ HTTP 200 (finally 关 gate, 兜底)
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `server/api/admin/sys_status.py` | `init_trading_day` 加 init_start/init_aborted 广播，成功广播 refactor 到共享 helper |
| 前端 | `client/src/stores/holdings.js` | 新增 `initializing` ref |
| 前端 | `client/src/stores/ws_dispatch.js` | `_onSystemStatusChange` 三态处理 + pos/ord/trd 丢弃门 + 丢弃计数 |
| 前端 | `client/src/views/SystemInit.vue` | `handleInit` finally 关 gate（兜底） |
| 前端 | `client/src/stores/holdings_bootstrap.js` | bootstrap/refreshAll finally 关 gate（防御） |
| 知识库 | `openspec/specs/push/spec.md` | 新增 REQ-PUSH-043：init_start/init_aborted 广播 |
| 知识库 | `openspec/specs/frontend/spec.md` | 新增 REQ-FE-532：initializing 推送丢弃门 |

## 落地约束

- ✅ 与 OpenSpec 工作流一致：先补 spec → 再写代码
- ✅ 复用既有 `system_status_change` type 与 `system_update` 频道，不新增频道/协议
- ✅ gate 只丢 pos/ord/trd 三类写持仓状态的数据，行情不受影响
- ✅ 失败路径补广播，杜绝前端门死锁
- ✅ 不自动 push（用户硬性偏好）
- ✅ 验证：py_compile + esbuild 语法；node 模拟广播时序（gate 开/关、丢弃计数、一次汇总日志）

## 关联

- 上游：`push/spec.md` REQ-PUSH-041（system_update 频道）/ REQ-PUSH-006（init_completed 触发刷新）
- 上游：`push/spec.md` REQ-PUSH-034（pos_push 无变化跳过）——洪峰由前端门吸收
- 并行：`2026-08-10-holdings-auto-sub-batch`（auto-sub 全市场阈值 + 新持仓批量合并）
