# Tasks: 日初全流程 E2E

## Phase 1: ORM 唯一约束

- [ ] 1.1 `server/models/orm.py:127` TradingDay 加 `UniqueConstraint("current_date", name="uq_trading_day_current_date")`

## Phase 2: 注释 + 文档

- [ ] 2.1 `server/services/reconcile.py:170` 切日块加 docstring 说明 upsert 语义

## Phase 3: E2E 测试

- [ ] 3.1 `server/test_reconcile_e2e.py` 新建
  - [ ] `test_e2e_full_flow`: mock 4 RPC 返数据 → do_reconcile → 验 4 表 + TradingDay active
  - [ ] `test_upsert_same_day`: 同日 2 次 init → TradingDay 1 行
  - [ ] `test_init_switch_day`: 切日 → 老的 closed + 新的 active
  - [ ] `test_apply_manual_mode`: manual 模式不写本地
  - [ ] `test_query_local_only`: do_reconcile 后 GET /api/asset 200 + DB 数据
  - [ ] `test_rpc_failure_all`: 4 RPC 全失败 → 503 + 不切日
  - [ ] `test_rpc_partial`: 2 失败 → partial + 503 + 不切日
  - [ ] `test_trading_day_unique_constraint`: 直接 INSERT 重复 current_date → IntegrityError

## Phase 4: 验证

- [ ] 4.1 `rm -f server/evtrade.db && bash scripts/restart.sh` 重建 DB
- [ ] 4.2 `pytest server/test_reconcile_e2e.py -v` 全绿

## Phase 5: Commit

- [ ] 5.1 `docs(openspec): 起草 trading-day-e2e-flow change`
- [ ] 5.2 `feat(reconcile): 切日 upsert 注释 + TradingDay unique 约束`
- [ ] 5.3 `test(reconcile): e2e 覆盖全流程 + upsert + query 本地`
- [ ] 5.4 `git push origin master`
