# Tasks: order-push-trd-date-authority

> 状态:✅ 已实施,3 commits 落盘并 push 到 origin/master
>
> | Commit | 主题 |
> |---|---|
> | `8087c1b` | feat(api): add GET /api/system/active-day for trading date authority |
> | `5dbac23` | feat(orders): PlaceOrderResponse +list 字段; push 链路注入 trd_date |
> | `49a5310` | refactor(frontend): 委托/成交模块统一 holdings 单一缓存源 |

## Step 1: 后端基座 (commit 8087c1b)

- [x] 新建 `server/api/system.py` — `GET /api/system/active-day` 返 `{code, msg, list: [{trd_date, status}]}`
- [x] `server/main.py` 加 `from api import system as system_api` + 挂载路由 `/api/system`
- [x] 写 `server/test_system_api.py` 5 测试:
  - 无 token 401
  - trader 看到 active 状态
  - 无 active 时看到 inactive
  - 跨日测试
  - DB 异常测试
- [x] pytest 通过: test_system_api 5/5,test_orders_api 12/12 零破坏

## Step 2: 后端 push 链路 (commit 5dbac23)

- [x] `server/api/orders.py`:
  - 加 `_to_order_out` helper(消除 3 处 OrderOut 重复构造)
  - `PlaceOrderResponse` 加 `list: List[OrderOut] = []` 字段
  - 3 个 return 都填 list
  - POST /place WS broadcast payload 加 `trd_date + order_no + remark`
- [x] `server/rpc/client.py`:
  - 加 `_resolve_active_trd_date_safe` 短连接 helper(异常返 None 不中断)
  - `_listen_pushs` 在 broadcast 前注入 `trd_date = activeTrdDate`(覆盖 broker 推的)
  - 持久化 row 也用 enriched_row
- [x] 写 `server/test_push_listener.py` 5 测试:
  - helper 正常返 active day
  - helper 异常返 None
  - listener 注入 trd_date 到 payload
  - listener None 降级
  - trd_cfm 同样注入
- [x] 写 `server/test_orders_api.py` +3 测试:
  - POST /place 成功响应有 list 字段
  - 柜台 RPC 失败时 list 也要返
  - WS broadcast payload 必带 trd_date + order_no
- [x] pytest 通过: 56/56 零破坏

## Step 3-7: 前端联动 (commit 49a5310)

- [x] `client/src/api/index.js`:
  - 加 `getActiveDay()` 走 `list[0]`
  - 注释说明 v8 list 字段语义
- [x] `client/src/stores/holdings.js`:
  - 加 `activeTrdDate/activeDayStatus` ref
  - `bootstrap` 第 1 步拉 active-day(失败降级, log warn)
  - `applyOrderPush/applyTradePush` 守门: `row.trd_date != activeTrdDate` 忽略
- [x] `client/src/stores/order.js`:
  - 重写为单一 actions(删除 orders/trades 持有)
  - `placeOrder` 内部 `_upsertToHoldings(list[0])` 立即写缓存
  - 修复 `createOrder` 旧 bug: push 数组进 orders 数组(类型错乱)
  - 不暴露 orders/trades getter 强制 view 走 holdings
- [x] `client/src/stores/ws.js`:
  - 删 `useOrderStore` 引用
  - `_onOrderCfm/_onTradeCfm` 改单点 `holdings.applyXxxPush`
  - 匹配键 `order_no`,兜底 `row.remark`
  - 防御性 status 重算走 holdings 内部
- [x] `client/src/views/Trade.vue`:
  - 删 5s `setInterval(fetchOrders, 5000)`
  - 删 onMounted fetchOrders
  - 删 `handleOrderSubmit` 后的 `fetchOrders()` 重复拉
  - 改用 `holdings.refreshAll` 手动刷新按钮(兜底)
  - `orderStore.orders` → `holdings.orders`
- [x] `client/src/views/T0Trade.vue`:
  - `submitOrder` 改走 `orderStore.placeOrder`
  - `res.code === 0` 改 `res`(拦截器解包后是 OrderOut 对象)

## Verification

- [x] 后端 56 测试全过(43 v8 涉及 + 13 既有零破坏)
- [x] 前端 42 测试通过(10 预存失败未变,跟 v8 无关)
- [x] git push 成功:`HEAD == origin/master == 49a5310`

## Out-of-scope (单独 change)

- [ ] ws.test.js / useT0Balance.test.js 10 个预存失败(独立 issue)
- [ ] vue 单测覆盖 v8 新逻辑(holdings/order 单测)
- [ ] 端到端 e2e 测试(需要 mock broker 就绪)
