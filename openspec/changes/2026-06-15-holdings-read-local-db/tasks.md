# Tasks: Holdings reads local DB

## Phase 1: 代码改动

- [ ] **T1.1** 修改 `server/api/holdings.py`
  - 删除 `from rpc.client import qry_positions`
  - 加 `from db import get_db` / `from models.orm import Position`
  - 加 `from services.guards import resolve_default_trd_date, require_trading_day_for_query`
  - 改 `list_holdings` 签名：增 `stock_code: Optional[str]` / `trading_day: Optional[str]` / `db: Session = Depends(get_db)`
  - 改实现：DB 查询 → PositionOut 6 字段映射
  - 用 `require_trading_day_for_query` 屏障

## Phase 2: 测试

- [ ] **T2.1** 新建 `server/test_holdings_api.py`
  - `test_holdings_returns_positions_from_db`：seed 2 行 Position → 调 API → 返 2 行
  - `test_holdings_filter_by_stock_code`：seed 3 行 → `?stock_code=600000` → 返 1 行
  - `test_holdings_empty_db_returns_empty_list`：空 DB → 返 0 行 code=0
  - `test_holdings_503_when_no_active_day`：未做日初 → 返 503 + TRADING_DAY_NOT_INIT
  - `test_holdings_field_mapping`：DB 字段 last_vol/volume 不存在 → 用 initial_position/total
- [ ] **T2.2** 跑 `pytest server/test_holdings_api.py -v` 全绿
- [ ] **T2.3** 跑 `pytest server/test_positions_api.py -v`（确保不破旧的）
- [ ] **T2.4** 跑全测 `pytest server/test_models.py test_guards.py test_reconcile.py test_t0.py test_push_handlers.py test_orders_api.py test_holdings_api.py` 全绿

## Phase 3: 验证

- [ ] **T3.1** 删 `server/evtrade.db` → restart
- [ ] **T3.2** curl `/api/holdings`（未做日初）→ 503 + TRADING_DAY_NOT_INIT
- [ ] **T3.3** admin 调 `/api/admin/trading-day/init` 激活 20260601
- [ ] **T3.4** curl `/api/holdings` → 200 + 空 list（DB 没数据，因没真 RPC）
- [ ] **T3.5** 前端 holdings store bootstrap 仍能跑（看 Network 200）

## Phase 4: 归档

- [ ] **T4.1** commit: `feat(holdings): 改读本地 positions 表（v4 漏改端点）`
- [ ] **T4.2** 把 spec-delta 合并到 `specs/positioning/spec.md`
- [ ] **T4.3** `mv openspec/changes/2026-06-15-holdings-read-local-db openspec/changes/archive/`
- [ ] **T4.4** 更新 `openspec/AGENTS.md` 活跃 change 表格

## Out of Scope (deferred)

- 合并 /api/holdings 和 /api/positions（破坏前端）
- 改 holdings store 前端解析
- user_id 字段（v4 已知缺失）

## Risks

- holdings store bootstrap 失败时前端仪表盘持仓 0（设计正确）
- DB 空时返空 list（不是 bug）
