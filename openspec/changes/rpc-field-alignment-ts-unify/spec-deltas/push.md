# push delta — push handler 字段映射表（broker 原字段名）

## MODIFIED Requirements

### REQ-PUSH-001 ord_cfm 字段映射表（v10 修订）

**原文本**（`openspec/specs/push/spec.md`）：

> `ord_cfm` 字段映射（push_handler_ord.py 读取）
> - `order_id` → Order.order_id
> - `remark` → 匹配本地 Order（= order_no）
> - `status` → 喂给 `_infer_order_status`
> - `status_msg` → Order.status_msg
> - `cancelled_volume` / `cancel_volume` / `withdrawn_volume` → Order.cancelled_volume 累加

**新文本**：

> ### REQ-PUSH-001.1: ord_cfm 字段映射（v10 broker 原字段名）
>
> | broker 字段（xtquant 协议） | server 字段 | 备注 |
> |---|---|---|
> | `order_id` | `Order.order_id` | 柜台真实委托号 |
> | `stock_code` | 透传 | 不写库（Order 已有） |
> | `order_status` | 喂给 `_infer_order_status` | broker 原字段名，**不 alias `status`** |
> | `order_volume` | `Order.volume` 覆盖 | broker 改单后真实 volume |
> | `traded_volume` | **不写**（trd_cfm 累计） | v6 决策 |
> | `price` / `traded_price` | **不写** | trd_cfm 累计算 avg |
> | `strategy_name` | 透传 | 暂不入库 |
> | `remark` | 匹配本地 Order | broker 透传回来的 order_no |
> | `order_time` | `Order.order_time` | v10 起写库（标准格式 23 字符） |
> | `cancelled_volume` / `cancel_volume` / `withdrawn_volume` | `Order.cancelled_volume` 累加 | v8 决策，多字段名兼容 |

### REQ-PUSH-002 trd_cfm 字段映射表（v10 修订）

**原文本**：

> `trd_cfm` 字段映射（push_handler_trd.py 读取）
> - `trade_id` → Trade.trade_id
> - `order_id` → 兜底定位 Order
> - `remark` → 匹配本地 Order（= order_no）
> - `stock_code` / `order_type` / `price` / `volume` / `amount` / `trade_time` → Trade 字段

**新文本**：

> ### REQ-PUSH-002.1: trd_cfm 字段映射（v10 broker 原字段名）
>
> | broker 字段（xtquant 协议） | server 字段 | 备注 |
> |---|---|---|
> | `traded_id` | `Trade.trade_id` | broker 原字段名（**不 alias `trade_id`**） |
> | `order_id` | 兜底定位 Order | broker 真实委托号 |
> | `remark` | 匹配本地 Order | broker 透传回来的 order_no |
> | `stock_code` | `Trade.stock_code` | |
> | `order_type` | `Trade.order_type` | 23/24 |
> | `traded_price` | `Trade.price` | broker 原字段名（**不 alias `price`**） |
> | `traded_volume` | `Trade.volume` | broker 原字段名（**不 alias `volume`**） |
> | `traded_amount` | `Trade.amount` | broker 原字段名（**不 alias `amount`**） |
> | `traded_time` | `Trade.trade_time` | broker 原字段名（**不 alias `trade_time`**） |
> | `account_id` | 透传 | 暂不入库 |
> | `strategy_name` | 透传 | 暂不入库 |

### REQ-PUSH-003 pos_cfm 字段映射表（v10 修订）

**新增**：

> ### REQ-PUSH-003.1: pos_cfm 字段映射（v10 broker 原字段名）
>
> | broker 字段（xtquant 协议） | server 字段 | 备注 |
> |---|---|---|
> | `stock_code` | `Position.stock_code` (PK) | |
> | `volume` | `Position.vol` | 总持仓 |
> | `avl_amt` | `Position.avl_vol` | broker 原字段名（**不 alias `available`**） |
> | `avg_price` | `Position.cost_price` | broker 原字段名（**不 alias `cost_price`**） |
> | `market_value` | 透传 / 推 WS | v5 决策：DB 不存 market_value（前端用行情实时算） |
> | `last_vol` | 透传 | 对账时设 |

### REQ-PUSH-004 ast_cfm 字段映射表（v10 修订）

**新增**：

> ### REQ-PUSH-004.1: ast_cfm 字段映射（v10 broker 原字段名）
>
> | broker 字段（xtquant 协议） | server 字段 | 备注 |
> |---|---|---|
> | `total_asset` | `Asset.total_asset` | |
> | `cash` | `Asset.cash` | |
> | `frozen_cash` | `Asset.frozen_cash` | broker 原字段名（**不 alias `frozen`**） |
> | `market_value` | `Asset.market_value` | |
> | `account_id` | 透传 | 暂不入库 |

## 勘误历史

- 2026-06-25 修订：push handler 之前用内部命名（`status`/`trade_id`/`price` 等）覆盖 broker 原字段名，导致与 parsers 层字段不一致；改为 broker 原字段名 + DB 字段显式映射（与 parsers 对齐）
