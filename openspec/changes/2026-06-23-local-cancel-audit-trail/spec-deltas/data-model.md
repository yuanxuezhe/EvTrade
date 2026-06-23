# data-model delta — v9 撤单审计 schema

## MODIFIED Requirements

### §1 orders 表

#### Schema 变更
- 新增字段：`order_flag`（`Integer`，nullable=False，default=0）

#### 新字段表

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `order_flag` | Integer | NO | 0 | **0=正常委托，1=撤单委托**（DELETE 端点 INSERT 的本地代理行，broker 不返回推送） |

#### 业务规则新增
- `order_flag=1` 的行（cancel-row）由 DELETE 端点全权管理 `status`：RPC 成功 → `53`，RPC 失败 → `55`
- broker `ord_cfm` 永远不会 match 到 cancel-row（broker `remark` 永远是原委托 `order_no`，不是 cancel-row 的 `order_no`）
- cancel-row 字段填充：`stock_code/order_type/price_type/price` 镜像原委托；`volume=0`；`user_def="CANCEL:{orig_order_no}"`；`status` 起步 `48`

### §2 trades 表

#### Schema 变更
- 新增字段：`trade_type`（`Integer`，nullable=False，default=0）

#### 新字段表

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `trade_type` | Integer | NO | 0 | **0=正常成交，1=撤单成交**（DELETE 端点撤单成功时同步生成，volume=剩余可撤） |

#### 业务规则新增
- cancel-fill 由 DELETE 端点 INSERT，**不**由 broker `trd_cfm` 写入（broker 撤单成功时**不**推 `trd_cfm`）
- cancel-fill 字段填充：`volume = orig.volume - orig.traded_volume`（剩余可撤股数）；`price = orig.avg_price or orig.price`；`trade_id = "CANCEL-{cancel_order_no}-{unix_ts}"` 合成；`order_no` 关联 cancel-row（不是原委托）

## Migration

- `migrate_cancel_flag.py`：idempotent `ALTER TABLE`，列存在则 skip
- 新部署：`Base.metadata.create_all` 自动建（含 NOT NULL DEFAULT 0，无需回填）