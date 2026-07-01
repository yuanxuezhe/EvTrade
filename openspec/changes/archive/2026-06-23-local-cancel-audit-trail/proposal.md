# local-cancel-audit-trail — 撤单委托流水 + 撤单成交记录

> MED 级 / M 工作量。新功能：本地代理撤单留痕（撤单委托 + 撤单成交）。

## 1. Why

### 1.1 现状问题

- **完全无撤单审计**：DELETE `/api/orders/{order_no}` 只调 `rpc.cancel_ord`，**不写任何本地记录**，完全靠 broker `ord_cfm` push 把原委托 `cancelled_volume` 累加 + 改 `status`。
- **缺「撤单委托」概念**：一笔买单/卖单的取消动作不留任何 audit 痕迹，运营/合规无法复盘「几点几分用户试过撤单」。
- **trades 表无撤单成交**：撤单成功时 broker 不推 `trd_cfm`（QMT 协议约定），所以 trades 表完全没有「撤单成交」流水。

### 1.2 用户原话

> 撤单的时候，在委托表增加撤单委托记录，raw_order_no 字段记录被撤委托的 order_no，在委托表增加 order_flag，用来区分正常委托和撤单委托。
> 成交表增加成交类型字段，正常成交和撤单成交，记录撤单成功的记录，成交数量就是撤单撤掉的数量。
> 我需要记录撤单的时间等记录撤单的流水信息。前端发起撤单委托的时候，就将委托记录写道委托表，broker 应答或者推送来的时候，再去更新这个记录。

### 1.3 关键架构约束

- `cancel_ord` RPC **只接 `order_id`**，没有 `remark` 字段
- broker `ord_cfm` 的 `remark` 永远等于**原买单/卖单**的 `order_no`，**不会回带**我们新 cancel-row 的 `order_no`
- 因此 cancel-row 是**纯本地**——`handle_ord_cfm` 永远不会 match 到它，DELETE 端点必须手动 `ws_manager.broadcast` 给前端

### 1.4 改动思路

1. DB schema: `orders.order_flag` + `trades.trade_type` 字段
2. DELETE 端点重写：5 步流程（pre-check → INSERT cancel-row → RPC → 分支 → WS broadcast）
3. ORM + Pydantic 透传新字段
4. 前端 holdings 短路 cancel-row 状态重算；视图加「类型」列 + 过滤

## 2. What Changes

### 2.1 DB schema

`orders` 加 `order_flag`、`trades` 加 `trade_type`：

| 表 | 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `orders` | `order_flag` | Integer | NO | 0 | **0=normal 1=cancel-order**（v9 新增：DELETE 端点生成的撤单委托占位行） |
| `trades` | `trade_type` | Integer | NO | 0 | **0=normal 1=cancel-fill**（v9 新增：撤单成功时生成的撤单成交占位行） |

迁移策略：仿 `migrate_cancelled_volume.py` 写 `migrate_cancel_flag.py`（idempotent ALTER，列存在则 skip）。

### 2.2 ORM 改 `server/models/orm.py`

- `Order` 加 `order_flag = Column(Integer, nullable=False, default=0)`，注释「0=normal 1=cancel-order」
- `Trade` 加 `trade_type = Column(Integer, nullable=False, default=0)`，注释「0=normal 1=cancel-fill」

### 2.3 Pydantic schema

- `OrderOut`: 加 `order_flag: int = 0`
- `TradeOut`: 加 `trade_type: int = 0`
- `CancelResponse`: 加 `cancel_order: Optional[OrderOut] = None`

### 2.4 DELETE 端点改 `server/api/orders.py` 5 步流程

**5 步**：

1. **Pre-checks**（status ∈ {48,49,50}、order_id 存在）：不插行，直接返 `code=NO_CANCELABLE / NO_ORDER_ID`
2. **INSERT cancel-row**（commit 立即落库）：
   - `order_no = next_order_no(db)`
   - `user_def = "CANCEL:{orig_order_no}"`（关联原委托的本地指针）
   - `stock_code / order_type / price_type / price` 镜像
   - `volume = 0`，其他归零
   - `order_flag = 1`，`status = "48"`（待发 sentinel）
3. **Call RPC**：`await rpc_cancel_order(order_id=orig.order_id)`（try/except 捕获网络异常）
4. **分支**：
   - `ack.code == 0` → `cancel_row.status = "53"`,`status_msg = "已撤"`,**同时** INSERT cancel-trade（`volume = orig.volume - orig.traded_volume`,`price = orig.avg_price or orig.price`,`trade_type = 1`,`trade_id = f"CANCEL-{order_no}-{int(time.time())}"`）,commit
   - `ack.code != 0` → `cancel_row.status = "55"`,`status_msg = ack.msg or "撤单失败"`,**不**插 cancel-trade,commit
   - RPC 抛异常 → 同上 status=55,`status_msg = str(e)`
5. **WS broadcast**（broker 不推 cancel-row）：
   - 始终推 `order_update` payload（含 `order_flag: 1, user_def, status, status_msg, ...`）
   - 仅成功时推 `trade_update` payload（含 `trade_type: 1, ...`）

**事务边界**：`db.commit()` 在 step 2 和 step 4 各一次；WS broadcast 在 commit 之后。

### 2.5 前端改 `client/src/stores/holdings.js`

- `applyOrderPush`: 加**短路** `if (Number(row.order_flag) === 1) { merge + return }`（volume=0 会被 `_recomputeStatus` 推算成 49 污染显示）
- `applyTradePush`: 透传 `trade_type` 字段，`trade_type=1` 时记「撤单审计」日志

### 2.6 前端视图

- `Trade.vue`: 加「类型」列（el-tag「撤单」），过滤选项新增 `allWithAudit`，`canCancel(row)` 加 `order_flag === 1` 守卫
- `Orders.vue`: 加「委托类型」列（区别于 price_type「类型」），`countByStatus` / `getFillRate` 排除 cancel-row
- `Trades.vue`: 加「类型」列，`buyCount/sellCount/buyAmount/sellAmount` 排除 `trade_type === 1`

## 3. Capabilities

### Modified Capabilities
- `data-model`: orders 加 `order_flag`、trades 加 `trade_type` 字段
- `trading`: REQ-TRADE-003 重写 DELETE 端点契约
- `frontend`: REQ-FE-009.x cancel-row 展示/过滤契约
- `push`: REQ-PUSH-007 broker ord_cfm 不匹配 cancel-row 隔离说明

## 4. 影响面

- 后端：`models/orm.py`、`api/orders.py`、`api/trades.py`
- DB：orders + trades 各加 1 列（需 ALTER 迁移）
- 前端：`stores/holdings.js`、`views/Trade.vue`、`views/Orders.vue`、`views/Trades.vue`
- 测试：`test_orders_api.py` 改 4 + 增 4；`test_push_handlers.py` 增 1

## 5. 不在本 change 范围

- 改 broker RPC 协议（`cancel_ord` 不接 remark）——不在项目内
- 改 broker `ord_cfm` 处理原委托的逻辑——保持
- 改 terminal 状态集合——保持
- 改 `next_order_no` 分配器——复用

## 6. 关键设计决策（已与用户确认）

| 维度 | 选择 |
|---|---|
| order_flag 语义 | `0`=正常委托，`1`=撤单委托 |
| trade_type 语义 | `0`=正常成交，`1`=撤单成交 |
| cancel-order 字段填充 | `stock_code/order_type/price_type/price` 镜像；`volume=0`；其他归零 |
| cancel-trade 字段填充 | `volume = (原 volume - 原 traded_volume)`；`price = orig.avg_price or orig.price`；`trade_id = CANCEL-{order_no}-{unix_ts}` |
| cancel-order 状态 | RPC 成功 → `53` 已撤；RPC 失败 → `55` 废单 |
| cancel-trade 生成 | 仅 RPC 成功时生成；失败时不生成 |
| RPC 失败行为 | 更新 cancel-row 为 status=55，不删行，不插 cancel-trade |

## 7. Edge Cases

1. **快速双击撤单**：两次各获新 `order_no`，都插 cancel-row；broker 第二次可能拒（orig 已 53），cancel-row.status=55。前端看到两次尝试，无数据损坏
2. **broker ord_cfm 抢先到**：`remark=原 order_no` 更新原 row，cancel-row 完全不被触及，无需特殊处理
3. **完全成交时撤单** (`orig.traded_volume == orig.volume`)：cancelled_qty=0 → 仍插 cancel-row(status=53) 但**不**插 cancel-trade
4. **T0 统计污染**：cancel-row `user_def="CANCEL:..."` ≠ `"T0"`，自然被 T0 过滤逻辑排除
5. **`holdings.applyOrderPush` 状态污染**：必须短路 cancel-row（volume=0 会被 `inferOrderStatus` 重算成 49）——已处理
6. **`Orders.vue` `getFillRate` NaN**：cancel-row volume=0 → `0/0 = NaN`，已加 `order_flag === 1` 守卫直接返 100

## 8. Tasks

- [x] T1: `server/models/orm.py` 加 `order_flag / trade_type`
- [x] T2: `server/api/orders.py` Pydantic schema + inline builder
- [x] T3: `server/api/trades.py` Pydantic schema
- [x] T4: `server/api/orders.py` DELETE 端点重写（5 步）
- [x] T5: `migrate_cancel_flag.py` 脚本
- [x] T6: `server/test_orders_api.py` 测试（4 改 + 4 增）
- [x] T7: `server/test_push_handlers.py` 1 增测试
- [x] T8: `client/src/stores/holdings.js` 短路 + 透传
- [x] T9: `client/src/views/Trade.vue` 类型列 + 过滤 + 守卫
- [x] T10: `client/src/views/Orders.vue` + `Trades.vue` 类型列 + 计数排除
- [ ] T11: 4 个 spec 文件更新
- [ ] T12: 跑 `migrate_cancel_flag.py` + 重启后端
- [ ] T13: 端到端 curl 验证 + 前端手动验证
- [ ] T14: `git push origin master`