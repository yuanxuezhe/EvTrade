# Cross · 02 · 订单状态映射（Order Status Mapping）

> 涉及文件：
> - `server/api/orders.py:_map_status`（11 档 XtQuant 码 → 前端 key）
> - `client/src/utils/format.js:STATUS_LABEL / STATUS_TYPE / STATUS_TONE / STATUS_ICON_NAME / STATUS_PULSE / STATUS_OPTIONS`
> - `client/src/components/OrderStatusBadge.vue`（渲染）
> - `server/services/trading.py:Order.status` 默认 `pending`（旧内存订单）

## 1. 完整状态机

```
                    ┌──────────────────────┐
                    │      unreported      │ (未报)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │    pending_report    │ (待报)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │       reported       │ (已报)
                    └─────┬───────┬────────┘
              ┌──────────┘       └────────────┐
              ▼                               ▼
   ┌────────────────────┐         ┌──────────────────┐
   │  reported_cancel   │         │      partial     │ (部成)
   └─────────┬──────────┘         └────────┬─────────┘
             ▼                             │
   ┌────────────────────┐                 │ ┌────────────────────────────┐
   │      cancelled     │ (已撤) ◀──────┐ └─▶ partial_pending_cancel    │ (部成待撤)
   └────────────────────┘              │    └─────────────┬─────────────┘
                                      │                  ▼
   ┌────────────────────┐              │      ┌──────────────────────┐
   │      cancelled     │ ◀────────────┼──────│  partial_cancelled    │ (部撤)
   └────────────────────┘              │      └──────────────────────┘
                                      │
   ┌────────────────────┐              │
   │       filled       │ (已成) ◀────┤
   └────────────────────┘              │
                                      │
   ┌────────────────────┐              │
   │      rejected      │ (废单) ◀────┘
   └────────────────────┘
```

## 2. XtQuant 码 ↔ 前端 key

| XtQuant 常量 | 数值 | 字符串字面量 | 前端 key | 含义 | STATUS_TYPE | STATUS_TONE |
|--------------|------|--------------|----------|------|-------------|-------------|
| `ORDER_UNREPORTED` | 48 | `"48"` | `unreported` | 未报 | info | pending |
| `ORDER_WAIT_REPORTING` | 49 | `"49"` | `pending_report` | 待报 | info | pending |
| `ORDER_REPORTED` | 50 | `"50"` | `reported` | 已报 | primary | pending |
| `ORDER_REPORTED_CANCEL` | 51 | `"51"` | `reported_cancel` | 已报待撤 | warning | terminal |
| `ORDER_PARTSUCC_CANCEL` | 52 | `"52"` | `partial_pending_cancel` | 部成待撤 | warning | working |
| `ORDER_PART_CANCEL` | 53 | `"53"` | `partial_cancelled` | 部撤 | info | terminal |
| `ORDER_CANCELED` | 54 | `"54"` | `cancelled` | 已撤 | info | terminal |
| `ORDER_PART_SUCC` | 55 | `"55"` | `partial` | 部成 | warning | working |
| `ORDER_SUCCEEDED` | 56 | `"56"` | `filled` | 已成 | success | done |
| `ORDER_JUNK` | 57 | `"57"` | `rejected` | 废单 | danger | terminal |
| `ORDER_UNKNOWN` | 255 | `"255"` | `unknown` | 未知 | info | pending |

## 3. 兼容旧 key `pending`

- 内存订单（`POST /api/orders`）默认 `status="pending"`
- 旧版本 RPC 报文可能返回 `"pending"`
- 前端 `STATUS_LABEL.pending = "已报"`，渲染同 `reported`
- `STATUS_TYPE.pending = primary`，`STATUS_TONE.pending = pending`，`STATUS_PULSE.pending = true`

## 4. 可撤单状态

`Trade.vue` 中 `canCancel(status)`：
```js
return [
  'unreported', 'pending_report', 'reported', 'reported_cancel',
  'partial', 'partial_pending_cancel', 'pending'
].includes(status)
```

不可撤：`cancelled / partial_cancelled / filled / rejected / unknown`

## 5. 5 大聚合分组（用于 Dashboard `orderStats`）

```js
const groups = [
  { key:'done',     label:'已成交',    color:'#16b572', statuses:['filled'] },
  { key:'working',  label:'部分成交',  color:'#ffa726', statuses:['partial','partial_pending_cancel','partial_cancelled'] },
  { key:'pending',  label:'已报/待报',  color:'#5fa8ff', statuses:['reported','pending_report','unreported','pending'] },
  { key:'terminal', label:'已撤单',    color:'#a0aec0', statuses:['cancelled','reported_cancel'] },
  { key:'rejected', label:'废单',      color:'#e85d75', statuses:['rejected'] }
]
```

## 6. 状态值同步 checklist

修改任何状态时**必须同步**：

1. **后端** `server/api/orders.py:_map_status`
2. **前端常量** `client/src/utils/format.js`
   - `STATUS_LABEL`（中文文案）
   - `STATUS_TYPE`（el-tag type）
   - `STATUS_TONE`（徽章色调）
   - `STATUS_ICON_NAME`（Element Plus 图标）
   - `STATUS_PULSE`（是否脉冲）
   - `STATUS_OPTIONS`（下拉选项）
3. **前端聚合** `Dashboard.vue` `orderStats` + `Orders.vue` `countByStatus`
4. **前端可撤单** `Trade.vue` `canCancel`
5. **KB** `cross/02_order_status.md`（本文件）

## 7. RPC 报文兼容（`rpc/client.py:_parse_orders`）

```python
status = pkt.get_value_str("order_status") or pkt.get_value_str("status") or ""
```
会同时读 `order_status`（XtQuant 字段）与 `status`（自定义）两个 key。
