# push-status-authority — 前端委托 status 防御性重算

> MED 级 / S 工作量。修复用户报障：成交 0 但显示"部成"（broker 推 status=50 透传到 WS，违反 spec REQ-PUSH-005）。

## 1. Why

### 1.1 真实 bug

用户截图：
```
单号 10000002 | 000002.SZ | 买 1000 @ 11.00 | 已成 0 | 状态 部成
```

按 spec REQ-PUSH-005，`traded_volume=0` + `volume=1000` 应推断为 `status="49"`（已报），不是"部成"。

### 1.2 根因（链路追踪）

1. **broker ord_cfm 推 `status="50"`**（broker 端"已报"语义，与本地推断 50=部成 语义不一致）
2. **后端** `server/services/push_handlers.py:handle_ord_cfm` 调 `_infer_order_status(order, broker_status="50")` → 因 `broker_status` 不在撤单类集合 `(52,53,54)`，走累计推断：`cum=0` → `return '49'`。**DB 写 status="49" ✓**
3. **后端** `server/rpc/client.py:_listen_pushs:236` 构造 WS payload：
   ```python
   enriched_row = {**row, "trd_date": active_trd_date}  # ← row 来自 broker, status=50
   ```
   **enriched_row.status=50**（broker 原始值，未被后端推断结果覆盖）❌
4. **前端** `client/src/stores/ws.js:_onOrderCfm` 收到 `row.status=50` → `enriched.status="50"`
5. **前端** `client/src/stores/holdings.js:applyOrderPush:428-432`：
   ```js
   row.status = inferOrderStatus(
     { status: row.status, volume: row.volume, traded_volume: row.traded_volume },
     row.status  // ← 把 row.status="50" 同时当作 brokerStatus 传
   )
   ```
   - current="50"（不在 TERMINAL_STATUSES）
   - broker_status="50"（不在 52/53/54）
   - 累计推断：cum=0 → 49 ✓

**理论上第 5 步应该修正回 49。** 实际却显示"部成"——意味着 bootstrap 拉数据时**没走 applyOrderPush**，直接用 `orders.value = rOrd.value`，而 `rOrd.value` 来自 `/api/orders`，那里 status="49"...

等等，bootstrap 路径是 49，但 applyOrderPush 路径在 push 到达时被覆盖为 50。**实际生效路径是 push 那次覆盖**——bootstrap 拉的数据被 push 改了。

### 1.3 决定性证据

`client/src/stores/holdings.js:233` 写：
```js
orders.value = Array.isArray(rOrd.value) ? rOrd.value
  : (Array.isArray(rOrd.value?.list) ? rOrd.value.list : [])
```
**没有 inferOrderStatus 防御性重算**。

而 `applyOrderPush` 路径虽然重算，但 **broker_status 误传**（用 `row.status` 当 brokerStatus）。

### 1.4 为什么走 A 方案（不修后端契约）

- 用户明确要求"按已成数量计算状态"——本质是前端展示策略
- A 方案改动小（前端 2-3 处）、无后端耦合
- 即使后端推错 status，前端永远按 `traded_volume/volume` 自推断
- 与 `archive/2026-06-16-frontend-infer-order-status/proposal.md` 第 25 行规划一致（"applyOrderPush 收到推送时调前端 inferOrderStatus 重算（防御性）"），但**该 change 实际未完成**

## 2. What Changes

### 2.1 `client/src/stores/holdings.js`：bootstrap + refresh + applyOrderPush 三处都重算

```js
function _recomputeStatus(o) {
  if (o == null) return o
  if (o.volume == null || o.traded_volume == null) return o
  return { ...o, status: inferOrderStatus(
    { status: o.status, volume: o.volume, traded_volume: o.traded_volume },
    null  // ← 不传 brokerStatus,完全按 cum/vol 算
  )}
}
```

- bootstrap (line 233): `orders.value = (...).map(_recomputeStatus)`
- refresh (line 308): `orders.value = (...).map(_recomputeStatus)`
- applyOrderPush (line 428-432): 改用 `_recomputeStatus(row)`，**不传 brokerStatus**

### 2.2 简化原因

- 不传 brokerStatus = 完全按本地累计推断 = 永远符合用户要求
- broker_status 仅用于"撤单类信号"（52/53/54），但那种情况后端 _infer_order_status 会处理（终态保持 + 撤单分支），前端不需要重复实现
- 用户的需求是"按已成数量算"，不关心撤单类特殊处理

### 2.3 spec 同步

- `openspec/specs/frontend/spec.md` REQ-FE-006：明确"所有 status 显示路径必须经 `inferOrderStatus` 防御性重算，不信任后端 status 字段"
- `openspec/specs/push/spec.md` REQ-PUSH-005：补"前端展示态以本地推断为准（cum/vol 决定）"，与"WS 透传 broker 原始 status"为两层契约

## 3. Capabilities

### Modified Capabilities
- `frontend`: status 防御性重算契约
- `push`: status 推送契约补注

## 4. 影响面

- 前端：`client/src/stores/holdings.js` (3 处重算入口)
- 后端：无改动
- 测试：手动验证（前端 UI 立即生效）

## 5. 不在本 change 范围

- 改 broker 协议——越界
- 改后端 push 链路 status 注入——选 A 方案不动
- `_infer_order_status` 推断规则本身——已正确

## 6. Tasks

- [ ] T1: `client/src/stores/holdings.js` 加 `_recomputeStatus` helper
- [ ] T2: bootstrap + refresh 列表赋值用 `.map(_recomputeStatus)`
- [ ] T3: `applyOrderPush` 改用 `_recomputeStatus(row)`，**不传 brokerStatus**
- [ ] T4: 改 `openspec/specs/frontend/spec.md` REQ-FE-006
- [ ] T5: 改 `openspec/specs/push/spec.md` REQ-PUSH-005 加注
- [ ] T6: 用户端验证：traded_volume=0 → 显示"已报"
- [ ] T7: commit
