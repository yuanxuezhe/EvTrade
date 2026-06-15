# Tasks — fix-push-handler-market-value

## 实施步骤

- [ ] 1. 读 `server/services/push_handlers.py:222` 确认问题
- [ ] 2. 删除 `pos.market_value = ...` 行（保留其他 pos 字段更新）
- [ ] 3. 更新 `server/api/positions.py` NOTE 注释：说明 market_value 由前端计算
- [ ] 4. 更新 `server/api/holdings.py` NOTE 注释：同上
- [ ] 5. `pytest server/test_push_handlers.py` 全绿
- [ ] 6. commit: `fix(push): 删除 pos.market_value 赋值（前端实时计算市值）`

## 验证

- [ ] `pytest server/` 全绿
- [ ] pos_cfm push 过来不再触发 AttributeError
- [ ] 前端持仓页市值仍正常显示（前端 `liveMarketValue` 不受影响）
