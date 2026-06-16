# trading delta — v7 schema 修订

## MODIFIED Requirements

### REQ-TRADE-002: 下单 — v7 schema 调整

**Before (v6)**:
- `client_order_id: String(64)` 必传，DB 层 UNIQUE(client_order_id, trd_date) 约束幂等

**After (v7)**:
- 删除 `client_order_id` 字段
- 新增 `user_def: String(255) = ""` 字段（外部自定义信息透传）
- 幂等由 `order_no` 单调递增保证（同 ord_stk RPC 第二次调用方会被 broker 拒绝）
- DB 不再有 UNIQUE 约束依赖 client_order_id

#### `PlaceOrderRequest` 字段变更
| 字段 | 类型 | 必传 | 变更 |
|---|---|---|---|
| ~~`client_order_id`~~ | ~~String(64)~~ | ~~必传~~ | **删除** |
| `user_def` | String(255) | 否 | **新增**（默认 ""，透传到 orders 表） |

#### `OrderOut` 字段变更
| 字段 | 类型 | 变更 |
|---|---|---|
| ~~`client_order_id`~~ | ~~str~~ | **删除** |
| `user_def` | str | **新增**（默认 ""） |

#### `place_order` 幂等逻辑变更

**Before**:
```python
cid = req.client_order_id or f"cid-{...}"
existing = db.query(Order).filter_by(client_order_id=cid, trd_date=trd_date).first()
if existing:
    return existing  # 重复 cid 返回原单
order_no = next_order_no(db)
new_order = Order(client_order_id=cid, ...)
```

**After**:
```python
order_no = next_order_no(db)  # 应用层单调递增保证唯一
new_order = Order(order_no=order_no, user_def=req.user_def, ...)
# broker 端重复 remark/order_no 时返回错误，由 ord_cfm 落库失败兜底
```

## ADDED Requirements

无新增。

## REMOVED Requirements

无整段删除（只是字段调整）。

## Cross-References

- `data-model/spec.md` §1 orders 表
- `push/spec.md` REQ-PUSH-001（trd_cfm 落库改用 order_no）
