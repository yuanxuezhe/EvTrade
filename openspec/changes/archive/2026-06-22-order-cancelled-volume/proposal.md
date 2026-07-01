# order-cancelled-volume — 委托表加撤单数量字段 + 重写状态推断

> MED 级 / M 工作量。新功能：记录撤单数量、按 cum_traded + cum_cancelled 推断 status。

## 1. Why

### 1.1 现状问题

- **撤单后状态错**：用户报"撤单变成了已成"——撤单后 broker 推 `status=53/54`，但 `traded_volume=0`，被前端误判（之前靠 `broker_status in (52,53,54)` 触发撤单分支，但 broker 推得不准时漏判）
- **缺"部成部撤"区分**：`status=56` 含义"部成部撤"（既有成交又有撤单）当前无法推断——只靠 broker 推 broker_status=56 兜底，broker 不一定推
- **缺审计数据**：撤单数量（多少股被撤）目前没有字段，运营/合规无法分析

### 1.2 用户原话

> 表和缓存委托表需要增加一个撤单数量字段，记录撤单数量。
> 如果撤单数量 = 委托数量，状态是已撤。
> 若撤单数量 > 0 且成交数量 > 0 ，部成部撤。

### 1.3 改动思路

1. DB schema: `orders` 加 `cancelled_volume` Integer 字段
2. handle_ord_cfm 累加 `cancelled_volume`（broker 推 `cancelled_volume` / `cancel_volume` / `withdrawn_volume` 任一）
3. _infer_order_status 改规则：以 cancelled_volume 为主，traded_volume 为辅
4. OrderOut schema 加字段
5. 前端 _recomputeStatus 用同样规则

## 2. What Changes

### 2.1 DB schema

`openspec/specs/data-model/spec.md` orders 表加字段：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `cancelled_volume` | Integer | NO | 0 | 累计撤单数量（broker 推送累加） |

迁移策略：现有库用 `ALTER TABLE orders ADD COLUMN cancelled_volume INTEGER NOT NULL DEFAULT 0`；新表由 `Base.metadata.create_all` 自动建（已有 schema 不重建，需要 sqlite 手动 ALTER）。

### 2.2 ORM 改 `server/models/orm.py`

```python
cancelled_volume = Column(Integer, nullable=False, default=0)
```

加在 `traded_volume` 之后。

### 2.3 push handler 改 `server/services/push_handlers.py`

**handle_ord_cfm**：
- 累加 `cancelled_volume`：从 row 取 `cancelled_volume` / `cancel_volume` / `withdrawn_volume` 任一字段名（broker 多版本兼容），累加到 `order.cancelled_volume`
- 不直接读 broker 推的 status 推断终态（仅在 cancelled_volume 累加后由 _infer_order_status 统一算）

**_infer_order_status** 重写规则：
```python
# 输入: order (含 traded_volume / cancelled_volume / volume / status)
# 输出: 49/50/51/53/56

current = order.status or '48'
# 1. 终态保持
if current in TERMINAL_STATUSES:
    return current

cum_traded = order.traded_volume or 0
cum_cancelled = order.cancelled_volume or 0
vol = order.volume or 0
unfilled = vol - cum_traded - cum_cancelled  # 未成交未撤的剩余

# 2. 撤单主轴
if cum_cancelled >= vol:           return '53'  # 已撤
if cum_cancelled > 0 and cum_traded > 0:  return '56'  # 部成部撤
if cum_cancelled > 0:             return '53'  # 部分撤单(无成交) → 也算已撤(运营角度)

# 3. 成交主轴
if cum_traded == 0:               return '49'  # 已报
if cum_traded < vol:              return '50'  # 部成
return '51'  # 已成
```

**注意**：原 `broker_status in (52, 53, 54)` 撤单类信号分支**保留**（v6 兼容，但优先级低于 cancelled_volume 累加逻辑）。

### 2.4 API schema 改 `server/api/orders.py` OrderOut

```python
class OrderOut(BaseModel):
    ...
    cancelled_volume: int = 0
    ...
```

`_to_order_out` 转换时透传。

### 2.5 前端改 `client/src/utils/format.js`

`inferOrderStatus` 重写为同一规则：
- current 在 TERMINAL_STATUSES → 保持
- cum_cancelled >= vol → 53
- cum_cancelled > 0 && cum_traded > 0 → 56
- cum_cancelled > 0 → 53
- cum_traded == 0 → 49
- cum_traded < vol → 50
- cum_traded == vol → 51

### 2.6 前端 holdings.js `_recomputeStatus`

`o.cancelled_volume` 也参与（不只是 traded_volume / volume）。

### 2.7 Trade.vue 加列

"已撤"列：`{{ row.cancelled_volume || 0 }}`

## 3. Capabilities

### Modified Capabilities
- `data-model`: REQ-ORD-007 cancelled_volume 字段
- `push`: REQ-PUSH-005 状态推断改用 cancelled_volume
- `frontend`: REQ-FE-006 inferOrderStatus 加 cancelled_volume 入参
- `trading`: REQ-TRADE-002 推断规则修订

## 4. 影响面

- 后端：orm.py / push_handlers.py / orders.py
- DB：orders 表加 1 列（需 ALTER 迁移）
- 前端：format.js / holdings.js / Trade.vue
- 测试：test_push_handlers / test_orders_api 加新 case

## 5. 不在本 change 范围

- 改 broker RPC 协议——不在项目内
- 改 trd_cfm 处理——不变
- 改 terminal 状态集合（51/52/53/54/55/56）——保持

## 6. Tasks

- [ ] T1: `server/models/orm.py` Order 加 `cancelled_volume` 字段
- [ ] T2: `server/services/push_handlers.py` 累加 cancelled_volume + 改 _infer_order_status
- [ ] T3: `server/api/orders.py` OrderOut 加 `cancelled_volume` + `_to_order_out` 透传
- [ ] T4: DB 迁移脚本（ALTER TABLE）
- [ ] T5: `client/src/utils/format.js` inferOrderStatus 加 cancelled_volume 推断
- [ ] T6: `client/src/stores/holdings.js` _recomputeStatus 透传 cancelled_volume
- [ ] T7: `client/src/views/Trade.vue` 加"已撤"列
- [ ] T8: 更新 `openspec/specs/data-model/spec.md` orders 表
- [ ] T9: 更新 `openspec/specs/push/spec.md` REQ-PUSH-005
- [ ] T10: 更新 `openspec/specs/frontend/spec.md` REQ-FE-006
- [ ] T11: 更新 `openspec/specs/trading/spec.md` REQ-TRADE-002
- [ ] T12: 跑测试 + 浏览器验证
- [ ] T13: commit
