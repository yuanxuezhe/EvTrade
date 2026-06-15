# trading spec delta

## REQ-TRADE-002（下单）— 改写

新增段落：
- **v5 幂等 / 路由定位**：
  - `client_order_id` 客户端幂等号
  - `order_no` 本地生成 8 位序号（保证当日 + 全局唯一）
  - 下单时 `order_no` 透传到柜台 RPC 的 `remark` 字段
  - 委托表复合主键 `(trd_date, order_id)`；初始 `order_id` 占位 `PENDING-{order_no}`，broker ack 后用真实 `order_id` 替换

## REQ-TRADE-003（撤单）— 改写

- 路径：`DELETE /api/orders/{order_id}` → **`DELETE /api/orders/{order_id}?trd_date=YYYYMMDD`**
- 复合主键定位
- **新增** v5 改写要点：本服务**不本地改 status**，由 ord_cfm push 异步回写

## Orders 表字段（新增章节）

| 字段 | 类型 | 说明 |
|---|---|---|
| `trd_date` | VARCHAR(8) | 交易日，复合主键之一 |
| `order_id` | VARCHAR(64) | 柜台号 / `PENDING-{order_no}` 占位，复合主键之一 |
| `client_order_id` | VARCHAR(64) | 客户端幂等号（与 trd_date UNIQUE） |
| `order_no` | VARCHAR(8) | 本地序号（与 trd_date UNIQUE，全局 UNIQUE） |
| `stock_code` | VARCHAR(16) | 股票代码 |
| `order_type` / `price_type` | VARCHAR(8) / INT | 方向 / 价格类型 |
| `price` / `volume` | DECIMAL / INT | 价格 / 数量 |
| `traded_volume` / `traded_amount` / `avg_price` | — | 成交累计 |
| `status` | VARCHAR(8) | 柜台状态 48-57 / 255 |
| `status_msg` | VARCHAR(256) | 废单 / 撤单原因 |
| `order_time` / `created_at` / `updated_at` / `pushed_at` | — | 时间戳 |

**删除**：`id`（自增 PK）、`order_remark`（与 broker 字段重名）

## Trades 表字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `trd_date` | VARCHAR(8) | 交易日，复合主键之一 |
| `trade_id` | VARCHAR(64) | 柜台成交流水号，复合主键之一 |
| `order_id` | VARCHAR(64) | 关联委托号 |
| `stock_code` / `order_type` / `price` / `volume` / `amount` | — | 成交明细 |
| `trade_time` / `created_at` | — | 时间戳 |

**删除**：`id`（自增 PK）；`TRD_DATE` → `trd_date`（小写）
