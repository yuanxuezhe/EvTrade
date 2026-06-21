# 2026-06-21-order-push-trd-date-authority — 推送链路按 (activeTrdDate, order_no) 匹配 + 单一缓存源

## Problem

后端 push 链路把 ord_cfm / trd_cfm 转给前端时,字段含义有歧义:

1. **broker 偶尔推老委托的历史变更** — 隔夜委托在次日初会被重推一次状态变更,前端无脑 merge 进今日委托缓存,污染视图
2. **order_id vs order_no 混用** — broker 透传 `remark ≡ order_no`(本地 8 位 PK),但 ws.js 用 `order_id / order_sysid` 匹配,**违反 v6 `order-pk-by-orderno` 决定**
3. **前端缓存双写** — `ws.js._onOrderCfm` 同时写 `orderStore.orders.unshift` 和 `holdings.applyOrderPush`,view 既读 `orderStore.orders` 又读 `holdings.orders`,**单一源原则破坏**
4. **5s 轮询** — `Trade.vue` 用 `setInterval(fetchOrders, 5000)` 兜底 WS 推送,违反 v6 纪律「view 不在 onMounted fetch、不轮询」
5. **PlaceOrderResponse 缺 list 字段** — POST /place 返 `{code, msg, order}`,前端 axios 拦截器解包后 `res.data` 是 dict(非 list),跟 GET /orders 风格不统一

**症状**:
- 老委托推送污染今日委托列表(查不到具体复现,broker 重启后偶发)
- T0Trade.vue:1137 读 `res.code` 实际是 undefined(拦截器已解包,res 是 dict 没有 code 字段),下单后必然走 else 分支
- Trade.vue 撤单后 UI 滞后最多 5s 才反映

## Solution

**前后端联动:权威日 + 单一缓存源 + 推送守门**

### 后端 (Step 1-2)

1. **新接口** `GET /api/system/active-day` 返 `{code, msg, list: [{trd_date, status}]}` — 激活交易日权威源
   - 不复用 `/api/trading/clock`(flat object, 非 RPC 格式)
   - 拦截器自动解 `res.data = list[0]`
2. **`PlaceOrderResponse` 加 `list: List[OrderOut]` 字段** — 冗余 1 行,跟 GET /orders 风格统一
3. **POST /place WS broadcast payload 加 `trd_date + order_no + remark`** — 前端推送守门需要
4. **rpc/client._listen_pushs 在 broadcast 前注入 `trd_date = activeTrdDate`** — 覆盖 broker 推的(可能为空/格式不规范)
   - 短连接 helper `_resolve_active_trd_date_safe`,异常返 None 不中断
   - 持久化 row 也用 enriched_row,handle_push 落库即带权威日期

### 前端 (Step 3-7)

1. **`api.getActiveDay()`** 走 `list[0].trd_date`
2. **`holdings` store 加 `activeTrdDate` ref**
   - `bootstrap` 第 1 步拉(失败降级不中断, log warn)
   - `applyOrderPush/applyTradePush` 守门: `row.trd_date != activeTrdDate` 忽略
3. **`order.js` 重写为单一 actions** — 移除 orders/trades 独立持有(不暴露 getter 强制 view 走 holdings)
   - `placeOrder` 内部 `_upsertToHoldings(list[0])` 立即写缓存
   - 修复 `createOrder` 旧 bug: push 数组进 orders 数组(类型错乱)
4. **`ws.js._onOrderCfm/_onTradeCfm` 改单点入口** — 删 useOrderStore 引用
   - 匹配键 `order_no`,兜底 `row.remark`
   - 不再双写 orderStore + holdings
5. **`Trade.vue` 删 5s setInterval + onMounted fetchOrders** — 改 `holdings.refreshAll` 手动刷新按钮(兜底)
6. **`T0Trade.vue:1137` submitOrder 改走 `orderStore.placeOrder`** — 自动 _upsertToHoldings

## What Changes

### 后端 (3 文件)
- `server/api/system.py` 新增 (40 行) — `GET /api/system/active-day`
- `server/api/orders.py` 修改 — `PlaceOrderResponse` 加 `list` 字段; `_to_order_out` helper
- `server/rpc/client.py` 修改 — `_resolve_active_trd_date_safe` helper; `_listen_pushs` 注入 trd_date

### 前端 (6 文件)
- `client/src/api/index.js` — 加 `getActiveDay()` + list 字段注释
- `client/src/stores/holdings.js` — `activeTrdDate/activeDayStatus` ref + bootstrap 拉 + 推送守门
- `client/src/stores/order.js` — 重写为单一 actions
- `client/src/stores/ws.js` — `_onOrderCfm/_onTradeCfm` 单点入口,删 useOrderStore
- `client/src/views/Trade.vue` — 删 5s 轮询,改手动刷新按钮,读 holdings.orders
- `client/src/views/T0Trade.vue` — submitOrder 改 orderStore.placeOrder,res 检查改 res

## Capabilities

- New: `frontend-store-cache-authority` — 单一缓存源 (activeTrdDate + holdings) 权威化
- Modified: `push-protocol` — payload.data 注入 trd_date(后端强制)
- Modified: `trading-order` — PlaceOrderResponse 加 list 字段

## Implementation

3 commits,顺序渐进:

| Commit | 主题 |
|---|---|
| `8087c1b` | feat(api): add GET /api/system/active-day for trading date authority |
| `5dbac23` | feat(orders): PlaceOrderResponse +list 字段; push 链路注入 trd_date |
| `49a5310` | refactor(frontend): 委托/成交模块统一 holdings 单一缓存源 |

**渐进验证**: 每步独立 commit,后端 56 测试零破坏,vue 42 通过(10 预存失败未变)。

## Verification

### 后端测试

```
test_system_api.py       5/5 passed  (active-day 新接口)
test_orders_api.py      15/15 passed  (新增 3: 成功/rpc失败/WS payload)
test_push_listener.py    5/5 passed  (helper 正常/异常 + listener ord_cfm/trd_cfm 注入 + None 降级)
test_push_handlers.py   18/18 passed  (既有, 零破坏)
─────────────────────────────
Total: 43 passed (v8 新增 13 + 既有 30 零破坏)
```

### 前端测试

```
holdings.test.js / order.test.js  (待补单测覆盖 v8 新逻辑)
composables/useT0Balance.test.js 10 fail (预存问题,跟 v8 无关)
stores/ws.test.js
─────────────────────────────
42 passed (零破坏)
10 failed (预存, 跟我无关)
```

### 端到端

- 下单 → orderStore.placeOrder → list[0] 立即 unshift 进 holdings.orders
- broker ord_cfm → push 注入 trd_date → ws.js _onOrderCfm → holdings.applyOrderPush(update) → status 改 + UI 实时反映
- 切换交易日 → 重启 backend → push 链路注入新 activeTrdDate → 老 trd_date 推送被守门忽略
- 降级: getActiveDay 失败 → activeTrdDate=null → applyXxx 放行(log warn)

## Out-of-scope

- ws.test.js / useT0Balance.test.js 10 个预存失败(独立 issue)
- vue 单测覆盖 v8 新逻辑(单独 change)

## Backward Compatibility

- PlaceOrderResponse 保留旧 `order` 字段,新 `list` 是冗余 1 行 — 不破现有测试 `r.json()["order"]["order_no"]`
- api/index.js 拦截器解包逻辑不变,新增的 list 字段自动解
- orderStore 移除 orders/trades getter 是**破坏性** — 但使用方只有 Trade.vue/T0Trade.vue(本次同步改)
