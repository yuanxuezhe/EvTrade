# Tasks: Fix Position.market_value Field

## Phase 1: ORM + API

- [ ] T1.1 `server/models/orm.py:83-102` 加 `market_value = Column(Float, nullable=True)`
- [ ] T1.2 `server/api/positions.py:64` 去掉代理, 改回 `r.market_value`
- [ ] T1.3 `server/api/holdings.py` 去掉代理, 改 `r.market_value or r.cost * r.total` (兜底)
- [ ] T1.4 `server/services/push_handlers.py:222` 去掉 try/except 吞错, 直用 `pos.market_value`

## Phase 2: Tests

- [ ] T2.1 `server/test_holdings_api.py` 恢复 `market_value` 字段 seed (3 个 seed 行)
- [ ] T2.2 `server/test_holdings_api.py::test_holdings_market_value_proxy` 改名为 `test_holdings_market_value_from_db`
- [ ] T2.3 新建 `server/test_positions_api.py` 覆盖 `/api/positions` 端点 (至少 3 测试)

## Phase 3: Verify + Commit

- [ ] T3.1 `rm -f server/evtrade.db && pytest server/test_holdings_api.py server/test_positions_api.py -v` 全绿
- [ ] T3.2 `restart.sh restart` 拉起 backend, 前端验证
- [ ] T3.3 `git diff` 预览
- [ ] T3.4 commit "fix(position): 加 market_value 字段 + 去掉代理"
- [ ] T3.5 `git -c http.proxy=http://127.0.0.1:10809 push origin master`
- [ ] T3.6 归档 change → `openspec/changes/archive/2026-06-15-fix-position-market-value-field/`
- [ ] T3.7 `openspec/changes/archive/2026-06-15-holdings-read-local-db/IMPLEMENTATION.md` 追加 "后续 fix" 章节
