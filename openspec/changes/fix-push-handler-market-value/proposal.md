# Fix push handler writing non-existent market_value

## 1. Why

`server/services/push_handlers.py:222` 写入了：
```python
pos.market_value = _float(row.get('market_value', 0))
```

但 `Position` ORM 没有 `market_value` 列，触发 `AttributeError`。这是设计层面的问题：

- `market_value` 应由**前端根据行情实时计算**（已有 `holdings.js:86-97` 的 `liveMarketValue` computed 属性实现）
- 后端不需要也不可能实时反映市值
- `positions.py` 和 `holdings.py` 注释已明确了这一点（`cost * total` 只是临时代理）

## 2. What

### 2.1 修复 push handler

1. 从 `handle_pos_cfm` 中删除 `pos.market_value = ...` 行
2. 同步检查 `handle_ast_cfm` 中 `asset.market_value = ...` 是否正常（Asset ORM 有 `market_value` 列，无需修改）

### 2.2 清理残骸

1. `server/api/positions.py:70` 和 `server/api/holdings.py:60` 中 `market_value = round(cost * total, 2)` 的临时代理保持不变（作为前端行情未到的 fallback）
2. 删除或更新这两处 NOTE 注释，说明代理值逻辑为有意设计

## 3. 影响面

- `server/services/push_handlers.py:222` — 删除 `pos.market_value` 赋值
- `server/api/positions.py` — 更新注释
- `server/api/holdings.py` — 更新注释
- 前端不受影响

## 4. Spec Deltas

`positioning/spec.md`:
- 补充说明：`market_value` 由前端计算，后端不存不传

## 5. Tasks

- [ ] 删 `push_handlers.py:222` 中 `pos.market_value = ...` 行
- [ ] 更新 positions.py NOTE 注释
- [ ] 更新 holdings.py NOTE 注释
- [ ] 更新 positioning/spec.md
- [ ] pytest 全绿
- [ ] commit
