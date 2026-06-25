# data-model delta — 时间戳列格式（order_time / trade_time 23 字符规则）

## MODIFIED Requirements

### §1 orders 表

#### Schema 变更
- `order_time` 字段类型：`String(8)` → `String(23)`，格式 `"YYYY-MM-DD HH:MM:SS.fff"`（v10 起）

| 字段 | 类型（原） | 类型（v10） | 说明 |
|---|---|---|---|
| `order_time` | `String(8)` `"HH:MM:SS"` | `String(23)` `"YYYY-MM-DD HH:MM:SS.fff"` | 含日期 + 毫秒，便于跨日委托归属 / 排序 |

#### 业务规则新增
- `order_time` 写入时由 `parse_broker_ts(broker_order_time, order.trd_date, tz='local')` 统一转换
- 创建 Order 时（`order_place.py`）使用 `format_ts(tz='local')` 生成当前时间字符串
- DB 迁移脚本：`UPDATE orders SET order_time = trd_date || ' ' || order_time || '.000' WHERE length(order_time) = 8`（把已有 8 字符补齐为 23 字符）

### §2 trades 表

#### Schema 变更
- `trade_time` 字段类型：`String(8)` → `String(23)`，格式 `"YYYY-MM-DD HH:MM:SS.fff"`（v10 起）

| 字段 | 类型（原） | 类型（v10） | 说明 |
|---|---|---|---|
| `trade_time` | `String(8)` `"HH:MM:SS"` | `String(23)` `"YYYY-MM-DD HH:MM:SS.fff"` | 含日期 + 毫秒 |

#### 业务规则新增
- `trade_time` 写入时由 `parse_broker_ts(broker_traded_time, trade.trd_date, tz='local')` 统一转换
- DB 迁移脚本：`UPDATE trades SET trade_time = trd_date || ' ' || trade_time || '.000' WHERE length(trade_time) = 8`

## 备注

- `trd_date` 保持 `String(8)` `"YYYYMMDD"` 不变（是交易日 PK 的语义标识，不含时分秒）
- `created_at` / `updated_at` / `pushed_at` / `synced_at` 保持 `DateTime` 类型（DB 内部 UTC，便于索引/范围查询）
- 上述 DateTime 列在 API 响应序列化时由 `format_db_dt(dt)` 转 `"YYYY-MM-DD HH:MM:SS.fff"` 字符串

## 勘误历史

- 2026-06-25 修订：原 `String(8)` 仅能存 "HH:MM:SS"，无法区分同日重复委托 / 跨日数据迁移；升级为 23 字符完整时间戳
