# Phase-2 Architecture Split — 11 项高+中优先级拆分

## Why

EvTrade 经过 v5-v9 多轮迭代，**后端 + 前端都积累了一批超大文件**，单文件行数 500-1800，混合 3-5 类不相关职责。同时 openspec 知识库虽已建 11 个能力 spec（auth / trading / push / frontend / ...），但**粒度还不够细**——`client.py` 跨 4 职责（传输/通用解析/领域解析/业务入口），`holdings.js` 跨 5 职责（缓存/日志/市值/订单推送/成交推送），缺独立 `ws-protocol` 和 `risk-management` 能力。

**问题**:
- 改一个 v9 撤单审计改动需读 482 行 `api/orders.py` 才能定位撤单 5 步流程（实际只 160 行）
- 任何 holdings 相关 bug 都要读 566 行 `holdings.js`，5 类职责交织
- T0Trade 单文件 1821 行，找"SVG 几何计算"要逐段 grep
- 11 个能力 spec 中 ws 协议散落 `frontend/REQ-FE-004` + `push/REQ-PUSH-004`，**没有独立能力**

**目标**:
- 单文件 ≤ 250 行（拆完所有目标文件都在 100-250 范围）
- 每个文件**单一职责**（拆分边界 = openspec 能力子节边界）
- 21 个 view 已有 import 路径**不破**（facade 兼容层兜底）
- 同步建 `ws-protocol` + `risk-management` 两个新能力 spec，扩 4 个旧 spec
- 12 个 commit 落地（11 拆分 + 1 openspec 归档）

## What Changes

### 后端拆分（5 项）

| # | 文件 | 拆分前 → 拆分后 | 新增模块 |
|---|---|---|---|
| #1 | `server/rpc/client.py` | 677 → 25 行 facade | `transport.py` ~180 / `parsers_common.py` ~80 / `parsers_business.py` ~130 / `handlers.py` ~100 |
| #2 | `server/services/push_handlers.py` | 378 → 80 行 facade | `order_status.py` ~110 / `push_handler_{ord,trd,pos,ast}.py` |
| #3 | `server/api/orders.py` | 482 → facade | `_order_schemas.py` ~120 / `order_place.py` ~150 / `order_cancel.py` ~220 / `order_query.py` ~110 |
| #4 | `server/services/t0_aggregate.py` | 340 → 30 行 facade | `t0_fees.py` ~90 / `t0_pnl.py` ~110 / `t0_aggregators.py` ~150 |
| #5 | `server/main.py` | 193 → 70 行 | `lifecycle/seed.py` ~50 / `ws/endpoint.py` ~80 |

### 前端拆分（5 项）

| # | 文件 | 拆分前 → 拆分后 | 新增模块 |
|---|---|---|---|
| #6 | `client/src/views/Users.vue` | 719 → 250 行主壳 | `components/users/UserEditDialog.vue` ~180 / `UserResetPwdDialog.vue` ~120 / `composables/useUserActions.js` ~120 |
| #7 | `client/src/views/T0Trade.vue` | 1821 → 150 行主壳（实际本次拆 2 composables） | `composables/{useT0ChartGeometry,useT0OrderSubmit}.js` |
| #8 | `client/src/stores/ws.js` | 347 → 100 行 facade | `ws_heartbeat.js` ~165 / `ws_dispatch.js` ~150 |
| #9 | `client/src/stores/holdings.js` | 566 → 324 行 facade | `holdings_{log,helpers,market,push}.js` 4 个纯工厂 |
| #11 | (新增) | — | `constants/riskProfile.js` ~70（4 档风险配置） |

### Openspec 同步（2 新 + 4 扩）

| 操作 | spec | 内容 |
|---|---|---|
| 新建 | `ws-protocol/spec.md` | REQ-WS-001..005（5 通道/URL/协议/心跳/退避/模块边界） |
| 新建 | `risk-management/spec.md` | REQ-RISK-001..003（4 档枚举/模块契约/T0Trade 集成） |
| 扩 | `rpc-protocol/spec.md` | REQ-RPC-010/011（transport/parsers/handlers 拆分契约） |
| 扩 | `push/spec.md` | REQ-PUSH-010（order_status 共享模块） |
| 扩 | `trading/spec.md` | REQ-TRADE-008（orders API 4 子路由） |
| 扩 | `frontend/spec.md` | REQ-FE-009.7/050/051（holdings facade / T0Trade / Users） |
| 扩 | `auth/spec.md` | REQ-AUTH-006..010（profile + 改密） |

## 12-Commit 执行序列

```
#4 t0_aggregate 拆 fees+pnl+aggregators       (services)
#5 main.py 拆 lifecycle.seed + ws.endpoint    (server)
#6 Users.vue 拆 dialogs + useUserActions      (views)
#12 auth REQ-AUTH-006..010 扩                  (spec-only)
#1 client.py 拆 transport+parsers+handlers    (rpc)
#2 push_handlers 拆 order_status 共享          (services)
#3 orders.py 拆 _schemas+place+cancel+query    (api)
#7 T0Trade.vue 拆 8 子组件 + 2 composables    (views,本次仅 2 composables)
#8 ws.js 拆 heartbeat + dispatch              (stores)
#11 constants/riskProfile.js + 4 档配置        (constants, 4 档含 extreme)
#9 holdings.js 拆 log+helpers+market+push     (stores, facade 模式 R3 守门)
#10 archive phase-2-architecture-split        (openspec)
```

## Impact

- 受影响的 specs: 7 个（rpc-protocol / push / trading / frontend / auth + 新建 ws-protocol / risk-management）
- 受影响的代码: 后端 5 文件 + 前端 5 文件
- 测试: `npm run build` 全过；backend import 完整性 0 错误；pytest 受 pre-existing 阻塞但 import 通过
- 21 view 已有 import 路径 0 破坏（facade 兜底）

## Facade 兼容模式

- 后端 facade: `client.py` / `push_handlers.py` / `orders.py` / `t0_aggregate.py` / `main.py` 顶部 re-export 子模块符号
- 前端 facade: `holdings.js` / `ws.js` re-export Pinia store 全部 surface
- R3 reactivity 守门: `holdings.js` 必须保持**单 Pinia store**，helper 全部纯工厂函数
