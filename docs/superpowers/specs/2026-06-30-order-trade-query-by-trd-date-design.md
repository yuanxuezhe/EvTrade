# 委托 / 成交按 trd_date 查询与展示设计

> **设计稿**，未经评审前不要直接动代码。

## 1. 背景与目标

### 1.1 现状问题

`Orders.vue` / `Trades.vue` 当前通过 `holdings` store 缓存展示数据，但有几个缺口：

| 缺口 | 位置 | 现状 | 用户诉求 |
|---|---|---|---|
| 当日委托查询 | `Orders.vue` | 仅展示「激活日」数据（`/api/orders` 默认 trd_date = 激活日） | 明确「只看当天下的单」语义 |
| 委托查询（不过滤日期） | 无独立入口 | `/api/orders/history` 必须显式传 trd_date | 一个无日期过滤的查询入口 |
| 成交排序 | `/api/trades` | `ORDER BY created_at DESC`（DB 入库时间，不是成交时间） | 按成交时间倒序 |
| trd_date 列 | `Orders.vue` / `Trades.vue` 表头 | 无 | 三类视图都需展示交易日期 |

### 1.2 设计目标

1. **后端**：`GET /api/orders` / `GET /api/trades` 支持 `start_date` / `end_date` 区间查询（向后兼容，缺省时维持现状），trades 排序改为 `trade_time DESC`
2. **前端缓存**：holdings store bootstrap 拉取一个日期窗口（默认 30 天），缓存该窗口内的全量 orders/trades
3. **前端筛选**：新增独立的 `client/src/utils/trdDateFilter.js` 工具模块，三个 view 共用一个纯函数做区间筛选
4. **前端视图**：`Orders.vue` 加 Tab「仅当日 / 全部」；`Trades.vue` 加 trd_date 列并按 trade_time 倒序；两个表都新增 trd_date 列

### 1.3 非目标（YAGNI）

- 不动 `/api/orders/place`、`DELETE /api/orders/{order_no}`、`/api/orders/history`
- 不重做 holdings store 整体架构（仍是 orders / trades 两个 ref）
- 不引入日期范围选择器（用户目前只要求「当日 / 全部」二选一）
- 不改 server/services/* 中的对账、推送逻辑

## 2. 后端改动

### 2.1 `GET /api/orders` 新增 query 参数

文件：`server/api/orders/query.py::list_orders`

新增两个可选 query 参数（带 FastAPI pattern 校验）：

```python
from fastapi import Query

start_date: Optional[str] = Query(None, pattern=r"^\d{8}$", description="起始交易日 YYYYMMDD（含）")
end_date:   Optional[str] = Query(None, pattern=r"^\d{8}$", description="结束交易日 YYYYMMDD（含）")
```

过滤规则：
- 两者都缺省 → 维持现状：`trd_date = 激活日`（`SysStatus.status='active'`）
- 仅 `start_date` → `trd_date >= start_date`
- 仅 `end_date` → `trd_date <= end_date`
- 两个都给 → `trd_date BETWEEN start_date AND end_date`

排序维持：`ORDER BY order_time DESC`（已正确）。

### 2.2 `GET /api/trades` 新增 query 参数 + 改排序

文件：`server/api/trades.py::list_trades`

新增同上的 `start_date` / `end_date`（与 orders 完全一致的 Query 签名 + pattern 校验）。

**排序修改**：`ORDER BY created_at DESC` → `ORDER BY trade_time DESC, trade_id DESC`

- `trade_time` 形如 `HH:MM:SS`（来自 broker 推送），无日期部分；同一秒内多条成交用 `trade_id` 二级稳定排序
- `created_at` 是 DB 入库时间，与 broker 成交时刻有毫秒级漂移（push handler → SQLAlchemy commit），按它排序不准

### 2.3 参数校验

- `start_date` / `end_date` 必须是 8 位数字字符串（`^\d{8}$`），否则 FastAPI 422
- `start_date <= end_date` 由 SQLAlchemy 直接处理；不写额外校验（范围为空时自然返回空集）

### 2.4 兼容性

- 所有现有调用方（bootstrap、place 响应的 list 风格、admin reconcile）不传新参数 → 行为完全不变
- v8 `ListOrdersResponse` / `TradesListResponse` schema 字段不变；`OrderOut.trd_date` / `TradeOut.trd_date` 已在

## 3. 前端改动

### 3.1 新增 `client/src/utils/trdDateFilter.js`（职责单一，纯函数模块）

```js
/**
 * 按 trd_date 过滤委托/成交数组（纯函数，view 层使用）
 * @param {Array<{trd_date: string}>} items
 * @param {Object} range
 * @param {string} [range.start]    起始日期 YYYYMMDD（含）
 * @param {string} [range.end]      结束日期 YYYYMMDD（含）
 * @param {string} [range.exact]    精确匹配某日（与 start/end 互斥，优先级最高）
 * @returns {Array} 过滤后数组（不修改原数组）
 */
export function filterByTrdDate(items, range = {}) {
  // 三种模式：exact > [start,end] > 无过滤（返回原数组副本）
  // 字符串比较在 YYYYMMDD 格式下天然字典序 = 时间序，无需 parse
}
```

**入参约束**：
- `exact` 与 `start/end` 互斥；同时给 `exact` 时优先 `exact`，忽略 `start/end`（符合「当日委托查询」语义）
- 任一参数未传视为无下/上界
- 缺省 `range = {}` 时返回 `items.slice()`（不污染调用方引用）

**导出策略**：单函数模块，按项目硬约束保留 `export function` 单公开入口；文件不超 40 行。

### 3.2 `client/src/stores/holdings_bootstrap.js` 改 bootstrap 拉取窗口

文件：`client/src/stores/holdings_bootstrap.js`

新增一个本地常量（文件顶部）：

```js
const BOOTSTRAP_WINDOW_DAYS = 30
```

`bootstrap()` 与 `refreshAll()` 中，调用 `api.getOrders()` / `api.getTrades()` 改为：

```js
const endDate = activeTrdDate.value  // 来自已 _resolveActiveDay()
const startDate = shiftDateStr(endDate, -BOOTSTRAP_WINDOW_DAYS)
api.getOrders({ start_date: startDate, end_date: endDate })
api.getTrades({ start_date: startDate, end_date: endDate })
```

`shiftDateStr(yyyymmdd, deltaDays)` 是新增的日期工具函数（放在 `client/src/utils/date.js`，避免污染 `trdDateFilter.js`）。

**WS 推送守门不受影响**：push handler 的守门逻辑用 `trd_date === activeTrdDate.value` 单值比较，与拉取窗口解耦；store 里 orders/trades 仍是单一 ref。

### 3.3 `client/src/views/Orders.vue` 改造

#### 3.3.1 顶部新增 Tab 切换

在 `stats-row` 上方新增（沿用项目 `<el-tabs>` 风格）：

```
[ 仅当日 ] [ 全部 ]
```

- 缺省 Tab = 仅当日（与当前激活日数据一致，零回归）
- 「全部」Tab 展示 holdings store 全量（已含 bootstrap 拉的 30 天窗口）

#### 3.3.2 表头新增 trd_date 列

在「时间」列前新增 `<el-table-column prop="trd_date" label="交易日" width="100" />`。

#### 3.3.3 computed `filteredOrders` 改造

在现有 `filters.keyword/order_type/status` 之上叠加 trd_date 过滤：

```js
const filteredOrders = computed(() => {
  const trdRange = activeTab.value === 'today'
    ? { exact: activeTrdDate.value }
    : {}  // 全部 = 不过滤
  return filterByTrdDate(orders.value, trdRange).filter(/* 现有 keyword/status 过滤 */)
})
```

`activeTrdDate` 来自 `useHoldingsStore().activeTrdDate`（store 已持有）。

#### 3.3.4 CSV 导出表头与文件名

表头加 `交易日`；文件名 `委托查询_当日_${date}.csv` / `委托查询_全部_${date}.csv`。

### 3.4 `client/src/views/Trades.vue` 改造

#### 3.4.1 表头新增 trd_date 列

与 Orders 对齐：`<el-table-column prop="trd_date" label="交易日" width="100" />`。

#### 3.4.2 排序

后端已按 `trade_time DESC` 返回；前端 `<el-table>` `default-sort` 设 `prop: 'trade_time', order: 'descending'`。

#### 3.4.3 CSV 导出

表头加 `交易日`。

### 3.5 不动 `CacheOrders.vue` / `CacheTrades.vue`

（仅做存根 / 兼容旧路由，本次不动）

## 4. 数据流

### 4.1 启动序列（改后）

```
App bootstrap
  → _resolveActiveDay()               # GET /api/system/active-day → activeTrdDate
  → Promise.all([
      getAsset(),
      getHoldings(),
      getOrders({start_date, end_date}),     # ← 新增区间
      getTrades({start_date, end_date}),     # ← 新增区间 + 后端排序改
    ])
  → holdings store.orders = resp.list  # 单 ref，存 30 天窗口
  → holdings store.trades = resp.list  # 同上
```

### 4.2 查询路径（Orders.vue）

```
用户切 Tab: 仅当日 ↔ 全部
  → filteredOrders = filterByTrdDate(orders, {exact: activeTrdDate})
                    .filter(keyword/status/order_type)
  → el-table 渲染 filteredOrders
```

**全部走本地内存筛选**，不打 API。

### 4.3 WS 推送

`order_update` / `trade_update` 推送守门用 `trd_date === activeTrdDate`，与拉取窗口无关；store 内同一 ref 维持。**新增区间参数不影响推送路径。**

## 5. 错误处理

- 后端 `start_date` / `end_date` 格式错误 → FastAPI 自动 422（依赖 Query 的 `pattern=r'^\d{8}$'`）
- 后端范围过宽（如 5 年）→ 当前表量级可控（自然按交易日截断）；不引入硬上限，超出风险由 ops 监控
- 前端 `shiftDateStr` 解析失败 → 降级到 `endDate`（单日窗口），`log('warn', '缓存', 'bootstrap', 'shiftDateStr 失败, 回退单日窗口')`

## 6. 测试 / 验收

### 6.1 后端单元 / 集成

`server/test_orders_api.py` / `server/test_trades_api.py`（如不存在则新建）：

- `GET /api/orders?start_date=...&end_date=...` 返回区间内全量 orders；不含区间外
- 仅传 `start_date`：返回该日及之后
- 仅传 `end_date`：返回该日及之前
- 两个都不传：返回激活日单日（向后兼容）
- `GET /api/trades?...` 排序按 `trade_time DESC`：构造同 trade_time 多条，验证二级 `trade_id DESC` 稳定

### 6.2 前端验收

手工 + Vitest（项目用 element-plus + Vitest）：

- `filterByTrdDate` 三种模式单元测试（exact / range / 透传）
- `shiftDateStr` 跨月、跨年、闰年
- `Orders.vue` 切 Tab：当日 / 全部 数量正确；trd_date 列展示正确
- `Trades.vue` 表头 trd_date 列展示正确，排序按 trade_time 倒序

### 6.3 回归

- `POST /api/orders/place` 返回 list 仍只含 1 行（默认 `trd_date = active`），不被新参数影响
- holdings store `applyOrderPush` / `applyTradePush` 推送守门正常（仅入 `activeTrdDate` 的行）

## 7. 文件清单

| 文件 | 改动类型 |
|---|---|
| `server/api/orders/query.py` | 改：list_orders 加 start_date/end_date query 参数 |
| `server/api/trades.py` | 改：list_trades 加 start_date/end_date + 改排序 |
| `server/test_orders_api.py` | 改：补区间查询用例 |
| `server/test_trades_api.py` | 改（如存在）：补排序 + 区间用例；不存在则新建 |
| `client/src/utils/trdDateFilter.js` | 新增：纯函数筛选工具 |
| `client/src/utils/date.js` | 新增：`shiftDateStr` 工具 |
| `client/src/stores/holdings_bootstrap.js` | 改：bootstrap 拉 30 天窗口 |
| `client/src/views/Orders.vue` | 改：加 Tab、trd_date 列、过滤逻辑 |
| `client/src/views/Trades.vue` | 改：加 trd_date 列、默认排序 |
| `docs/superpowers/specs/2026-06-30-...md` | 新增：本 spec |

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| bootstrap 拉 30 天窗口首屏慢 | 量级小（个人账户级），单 RPC < 200ms；监控埋点 |
| `trade_time` 形如 `HH:MM:SS` 同秒多条 | 二级 `trade_id DESC` 兜底 |
| 前端 Tab 切换触发大量响应式重算 | `computed` 自动 memo；30 天窗口单账户量级可控 |
| `GET /api/trades` 排序改向后老客户端感知差异 | 老客户端按 `created_at` 顺序展示可能跳序；此接口由本前端独占，外部无调用方 |

回滚：所有改动为新增/局部替换，git revert 单 PR 即可。