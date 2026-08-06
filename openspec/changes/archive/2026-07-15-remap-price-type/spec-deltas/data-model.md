# spec-deltas / data-model — remap-price-type

> 本 change 已直接合并到 `openspec/specs/data-model/spec.md`。

## §13 orders 表第 52 行（price_type 列）

**Before**:
```
| `price_type` | Integer | NO | 11 | 5/11/14/44 详见 trading spec |
```

**After**:
```
| `price_type` | Integer | NO | 0 | 0/1/2 详见 trading spec（v__: 与 xtconstant 柜台协议 1:1 对齐） |
```

## 影响

- `server/models/orm.py::Order.price_type` 列 default = `0`（was 11）
- 历史数据迁移：`server/migrations/2026-07-15-remap-price-type.py` 幂等 UPDATE (11/14→0, 5→1, 44→2)