## Context

`trades.amount` 与 `orders.cancelled_volume` 的写入在多路径上分散：

```
                       price × volume        broker.traded_amount       ↓ trust
                     ┌─────────────────────────────────────────────────────────┐
   后端 trd_cfm      │ trades.amount  ← broker.traded_amount (现状)        │  ★ 本 change 改本地算
                     │ orders.traded_volume ← broker trd_cfm 单笔累加     │
                     │ orders.traded_amount += trade.amount                │
                     │ orders.avg_price = traded_amt / traded_vol (守卫)   │  ★ 改去掉 price 守卫
                     └─────────────────────────────────────────────────────────┘
                       broker ord_cfm          API 主动 broadcast      ↓ trust
                     ┌──────────────────────────────────────────────────────┐
   后端取消 / 废单  │ orders.cancelled_volume 由 broker ord_cfm 累加      │
                     │   + broker 未推时本地零推 (当前)                      │  ★ 改 R1/R2a/R2b 抹平到 volume
                     │ place.py ack.code!=0 → status=55,不写 cancelled    │  ★ 改 R2a 同步
                     │ cancel.py ack.code==0 → 不动 orig.cancelled        │  ★ 改 R1 抹平 orig
                     └──────────────────────────────────────────────────────┘
                       ws push payload        前端 spread                 ↓ trust
                     ┌──────────────────────────────────────────────────────┐
   前端 ws 合并      │ applyOrderPush { ...ref, ...row }                    │  ★ 改为只读元数据
                     │ applyTradePush unshift 整行                         │  ★ 改独立增量累计
                     │ applyOrders* map recomputeStatus 仅重算 status     │  ★ 改 amount/avg/cancelled 全本地化
                     │ bootstrap 信任 row 累计                             │
                     └──────────────────────────────────────────────────────┘
```

本次设计把"前后端算法对齐 + 前端独立累计"作为单一口径收齐：
- 后端负责落 DB 权威值
- 前端在缓存层独立重建累计字段（不信任 ws payload 的 cumulative 字段）
- 双方算法逐字镜像：trades.amount = price × volume / orders.cancelled_volume = volume in {撤单成功, 废单}

## Goals / Non-Goals

**Goals:**
- 服务端 trd_cfm 本地算 `trades.amount = price × volume`，不再采纳 `broker.traded_amount`
- 服务端在 4 个写入点（trd_cfm / DELETE 成功 / place.py 拒单 / broker ord_cfm 推回废单）维护 `cancelled_volume` 的"抹平到 volume"语义
- 前端独立算法：从 ws 单笔 trade 增量累计；ws order_update payload 只读 PK 与元数据
- Vue ref 响应式渲染保留：所有改动通过 `value[idx] = newObj` 触发
- 保留 11 个已有 trd_cfm 用例继续通过

**Non-Goals:**
- 不改 trades / orders 表结构（schema 不变）
- 不改 broker 协议层
- 不改推送通道 / ws_manager 实现
- 不做实时 reconcile 同步；reconcile 后续动作（手动 / 自动）走现有路径
- 不引入任务队列 / EventBus 跨模块信号（Vue reactivity 是单点机制）

## Decisions

### D1 — `trades.amount` 由后端 trd_cfm 本地算
**理由**：与 `data-model/spec.md` §2 trades.amount 的业务规则"成交额 = price × volume"对齐；消除对 broker 推送字段的信任，规避 broker 推 `traded_amount` 与本地 `price × volume` 不一致的可能（精度、含费用等）
**替代方案**：保留 broker 字段 + 一致性断言（warn 而非覆写）—— 复杂度更高而收益低
**实现**：`server/services/push/trd.py:74` 改为 `amount=price * volume`（取本行的 `trade.price` 与 `trade.volume` 局部变量）

### D2 — `avg_price` 守卫仅防 `traded_volume == 0` 除零
**理由**：当前 `if trade.price and trade.volume:` 在 broker price=0 异常笔下不更新 avg_price 但累计金额照常——导致均价口径"历史均价 + 异常笔金额"加权偏离，与"当前累计成交均价"语义脱节
**替代方案**：用 `(Σ amount) / (Σ volume)` 全局重算替代累计——需要遍历所有 trades，性能与正确性都不优于当前累计 + 移除守卫
**实现**：`server/services/push/trd.py:85-86` 改为 `if (order.traded_volume or 0) > 0:` 单条除零守卫；`avg_price = traded_amount / traded_volume`

### D3 — DELETE 成功时 R1 抹平 `cancelled_volume = volume`
**理由**：broker 推回 orig 的 ord_cfm 的时机不可控（可能数秒到数分钟）；DELETE 端点是本地代理，能立即把"已撤"语义写到 orig 字段，前端不用等 broker 兜底
**替代方案**：保留 broker 累加逻辑（之前选项 b）—— 失去本地立即反馈；用户最终选择 a 抹平
**实现**：`server/api/orders/cancel.py` ack_code==0 分支 INSERT cancel-trade 后 `orig.cancelled_volume = orig.volume` + commit

### D4 — place.py 拒单时 R2a 抹平 `cancelled_volume = volume`
**理由**：本地下单被柜台拒（ack.code != 0）写入 `status=55` 视作"废单"——业务语义等价于"整笔撤销"；前端 cancel-row 占位是用户主动触发，但本地拒单是 broker 拒绝，必须把 cancelled_volume 反映出来
**替代方案**：拒绝依赖 status=55 反推——但前端 ws payload 字段不保证带 cancelled_volume，状态反推有 race
**实现**：`server/api/orders/place.py:113-115` ack_code != 0 分支增 `order.cancelled_volume = order.volume`

### D5 — broker ord_cfm 推回废单时 R2b 兜底抹平
**理由**：用户最终选定"信 broker 推的"——这是 broker 的 cancelled_volume 已累加的部分。但 broker 可能只推 `status=拒单类` 而不推 cancelled_volume 字段（如老 broker 版本 / 协议字段不全）；本地兜底抹平避免这种 corner case 下 cancelled_volume 缺失
**替代方案**：纯信 broker 累加（不兜底）—— corner case 下前端 stale，options b 选了"信 broker 推的"是默认，R2b 仅在"broker 未推"时介入
**实现**：`server/services/push/ord.py:62-72` 累加循环之后、`_infer_order_status` 之前插入：检测 broker_status ∈ {拒单类} 与 `order.cancelled_volume < order.volume`，则补 = volume

### D6 — 前端独立累计（applyTradePush）
**理由**：服务端的累计是 DB 权威；前端 ws push payload 字段可能不全（broker 不推某些列 / 服务端 broadcast 手写 payload 缺字段）。让前端在缓存层从单笔 trade 增量独立累加，可以：
1. 不依赖服务端 payload 字段完整
2. 不依赖服务端算法正确性
3. 与服务端算法镜像，可作为服务端 bug 早发现的"独立验证信号"
**替代方案**：信服务端 payload + 周期 refresh 兜底 —— refresh 间隔窗内 stale
**实现**：`client/src/stores/holdings_push.js:98-132` applyTradePush 改为：
- `trades` 数组按 `trade_id` 去重 + 写入 `amount=price*volume`
- 找到对应 `order_no` 的 order 行
- 增量：traded_volume += trade.volume / traded_amount += trade.amount / avg_price = amt/vol
- 调 `inferOrderStatus` 推断 status
- 替换 orders.value[idx] 触发响应式重渲染

### D7 — 前端 applyOrderPush 只读 PK + 元数据
**理由**：用户明确"不要关注推送信息里面的状态信息"——前端完整信任 ref 内部的计算字段（traded_volume / traded_amount / avg_price / cancelled_volume / status），ws payload 的这些列即便有也只是"冗余 / 旁路"，不采纳
**替代方案**：折中方案是 merge 时按字段分类（cancelled_volume 取 max 等）—— 用户最终选择"前端完全独立"，故不引入合并规则
**实现**：
```js
function applyOrderPush(row) {
  if (Number(row.order_flag) === 1) {
    // cancel-row：写入 cancel-row 自身 + 反向抹平原委托 cancelled_volume
    const cIdx = orders.value.findIndex(o => o.order_no === row.order_no)
    if (cIdx >= 0) orders.value[cIdx] = { ...orders.value[cIdx], ...row }
    else orders.value.unshift(row)

    const userDef = String(row.user_def || '')
    if (userDef.startsWith('CANCEL:')) {
      const origOrderNo = userDef.slice('CANCEL:'.length)
      const oIdx = orders.value.findIndex(o => o.order_no === origOrderNo)
      if (oIdx >= 0) {
        const orig = orders.value[oIdx]
        orders.value[oIdx] = { ...orig, cancelled_volume: Number(orig.volume) || 0 }
      }
    }
    return
  }

  // 普通 row: 仅覆盖 PK + 元数据
  const idx = orders.value.findIndex(o => o.order_no === row.order_no)
  if (idx >= 0) {
    const ref = orders.value[idx]
    orders.value[idx] = {
      ...ref,                                          // 计算字段全部保留
      order_id: row.order_id ?? ref.order_id ?? '',
      user_def: row.user_def ?? ref.user_def ?? '',
      order_time: row.order_time ?? ref.order_time ?? '',
      stock_code: row.stock_code ?? ref.stock_code ?? '',
      order_type: row.order_type ?? ref.order_type ?? '',
      price_type: row.price_type ?? ref.price_type ?? 0,
      price: Number(row.price ?? ref.price ?? 0),
      volume: Number(row.volume ?? ref.volume ?? 0),
      status_msg: row.status_msg ?? ref.status_msg ?? '',
    }
  } else {
    orders.value.unshift({
      order_no: row.order_no,
      trd_date: row.trd_date,
      ...row,                                          // 初始 base
      traded_volume: 0, traded_amount: 0,
      avg_price: 0, cancelled_volume: 0,
      status: '48',
    })
  }
}
```

### D8 — 前端 bootstrap / refresh 时用 row 累计字段作初始值
**理由**：bootstrap 是初始化阶段，不存在"既有 ref"被覆盖的风险；用 row.traded_volume / row.traded_amount / row.cancelled_volume 作初始值能立即呈现正确状态（用户已确认）
**替代方案**：bootstrap 完全不用 row 累计字段，全靠 `applyTradePush` 重跑 —— 性能差且失去 row 字段的"权威初始"
**实现**：`client/src/stores/holdings_apply_results.js:41-115` 中：
- `applyOrdersResult/Refresh`：map 时保留 row 累计字段，重算 `avg_price / status`（`inferOrderStatus`）
- `applyTradesResult/Refresh`：map 时 `amount = price × volume` 覆写

### D9 — 前端 helper 集中在 `utils/orderCalc.js`
**理由**：用户要求"前后端独立去计算"——前端需要一份与后端 helper 字段对齐的纯函数集；拆出独立 utils 模块避免把核心逻辑藏在 stores 里，便于单测与潜在的复用
**实现**：
```js
// client/src/utils/orderCalc.js

export function normalizeTrade(trade) {
  return {
    ...trade,
    amount: (Number(trade.price) || 0) * (Number(trade.volume) || 0),
  }
}

export function recomputeOrderFromTrade(order, trade) {
  const tv = (Number(order.traded_volume) || 0) + (Number(trade.volume) || 0)
  const ta = (Number(order.traded_amount) || 0) + ((Number(trade.price) || 0) * (Number(trade.volume) || 0))
  const avg = tv > 0 ? ta / tv : 0
  const next = {
    ...order,
    traded_volume: tv,
    traded_amount: ta,
    avg_price: avg,
  }
  next.status = inferOrderStatus(next, null)
  return next
}

export function metaMerge(row, ref = {}) {
  return {
    ...ref,
    order_no: row.order_no || ref.order_no || '',
    trd_date: row.trd_date || ref.trd_date || '',
    order_id: row.order_id ?? ref.order_id ?? '',
    user_def: row.user_def ?? ref.user_def ?? '',
    order_time: row.order_time ?? ref.order_time ?? '',
    stock_code: row.stock_code ?? ref.stock_code ?? '',
    order_type: row.order_type ?? ref.order_type ?? '',
    price_type: row.price_type ?? ref.price_type ?? 0,
    price: Number(row.price ?? ref.price ?? 0),
    volume: Number(row.volume ?? ref.volume ?? 0),
    status_msg: row.status_msg ?? ref.status_msg ?? '',
  }
}
```

## Risks / Trade-offs

**[R1] — ws 重连丢包场景下前端 ref 长期 stale** → 服务端 dispatch 单条 push 完整字段，客户端有 ws_heartbeat 重连机制；重连成功后 bootstrap 走一次 `GET /api/orders` 兜底（无需新增代码，bootstrap 路径已存在）

**[R2] — broker 重发陈旧 ord_cfm 时前端 spread 不被信** → D7 保证前端完全不读 row 的 status/cumulative 字段；broker 重发只更新 order_id / user_def / status_msg 等元数据，cumulative 字段不被 row 覆盖

**[R3] — DELETE 端点 orig 与 cancel-row 两条 broadcast 到达顺序与 R1 时序 race** → DELETE 端点同步 commit 写 `orig.cancelled_volume = volume`，但 ws broadcast 仍只推 cancel-row（不推 orig）—— 这是已知设计：orig 的 cancelled_volume 由前端 cancel-row 反向抹平（按 user_def 关联）+ 服务端 R1 commit。任一路径触发即正确；如果两条都触发，最多只会把 cancelled_volume 设为 volume（幂等）

**[R4] — 历史 trades 表 amount 与 price × volume 不一致** → 在 task list 加一个 dry-run SQL 脚本对照评估；如有差异，提供一次性 `UPDATE trades SET amount = price * volume WHERE 1=1` 写法但 **不在线执行**，等用户决策

**[R5] — 前端 applyOrderPush 在 INSERT 新单时只用 row 字段做 base，与后端字段顺序耦合** → D7 实现里 row 的 PK + 元数据都被作为 ref 初始；cumulative / status 字段强制写 0 / '48'，与后端 INSERT 默认值一致

**[R6] — 前端 `applyTradePush` 在 trd_cfm 后到对应 order 不存在的情况（罕见）** → 服务端 `push/trd.py:82-94` 已 warn 日志"no order for trade_id={}"，不抛异常；前端若未找到对应 order 也只是 warn 日志，不抛错；下一次 trd_cfm / bootstrap 拉取会校正

**[R7] — 双源算法漂移（前端 helper 与后端 helper 不一致）** → 给前端 normalizeTrade / recomputeOrderFromTrade 写 2 类单测，必须与后端 helper 字段语义对齐；CI 时一并跑前后端测试覆盖同一组 fixture 数据

## Migration Plan

1. **代码就绪**：
   - 后端 4 处修改按 commit 顺序：`push/trd.py`（独立）→ `api/orders/cancel.py` + `api/orders/place.py`（同一组）→ `push/ord.py`（独立）
   - 前端 1 新建 + 3 改动按 commit 顺序：先建 `utils/orderCalc.js`（独立）→ 改 `holdings_helpers.js` re-export（同一组）→ 改 `holdings_apply_results.js`（bootstrap/refresh 入口）→ 改 `holdings_push.js`（ws push 入口）
2. **Spec 同步**：
   - `data-model/spec.md` §1 §2 注释合并在第一个后端 commit 或单开 spec commit
   - `frontend/spec.md` REQ-FE-009.9 合并在前端 commit 内
3. **测试就绪**：
   - 后端 4 类测试可与代码同 PR
   - 前端 2 类测试可与代码同 PR
4. **历史数据 dry-run**：
   - 单开 issue（不在本 change 范围），跑 `SELECT COUNT(*) FROM trades WHERE ABS(amount - price * volume) > 0.01` 评估
5. **回滚策略**：
   - 后端修改点都在 push 推送 / REST 端点内部，单 PR revert 可回滚
   - 前端修改在 stores / utils 内，单 PR revert 可回滚
   - 双源镜像下，前后端独立回滚不会导致算法永久偏离（下一步会重新 sync）

## Open Questions

- **Q1**：trd_cfm 处理后是否同步推 `order_update`（让前端在 `applyTradePush` 后还能收到一次 order 行的 ws），还是仅 `_broadcast_trade_cfm` 自己推 trade + order 两条？当前 `_broadcast_trade_cfm` 同时推两条（`dispatcher.py:114, 120`），不需要调整
- **Q2**：现有 `applyOrdersResult/Refresh` 保留 row 的 `traded_volume / traded_amount / cancelled_volume` 字段是否需要逐条 warn / 验证？用户未明确，决定不加 warn（信任服务端响应作为 bootstrap 初始值）
- **Q3**：是否需要在 ws 重连（`ws_dispatch.js` 的 heartbeat 失败）后强制 `holdings.refreshAll()`？当前 `bootstrap` 是登录后跑一次，重连时不一定再跑。用户未明确，本 change 不引入
