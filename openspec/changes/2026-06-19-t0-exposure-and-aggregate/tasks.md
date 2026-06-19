# Tasks

> 任务粒度 2-5 分钟。每条 commit 一个独立单元。
> Commit 风格：feat / fix / refactor / test / docs(openspec)

- [x] 1. docs(openspec): 更新 spec.md + 添加 REQ-TRADE-006（已完成，commit 1）
- [x] 2. feat(services): 新增 t0_aggregate.py 聚合算法（calc_realized_pnl / calc_net_exposure / aggregate_by_stock / aggregate_by_day / aggregate_summary）
- [x] 3. fix(services): t0.py 注释 + commission 取 min_commission 兜底（注释已更新，兜底交给 t0_aggregate）
- [x] 4. feat(api): 新增 t0_aggregate.py 端点（t0-exposure + t0-aggregate）
- [x] 5. fix(api): t0_stats.py realized_pnl 算式改真实算法
- [x] 6. test: 新增 test_t0_aggregate.py（16 用例全绿）+ 既有 test_t0.py 兼容
- [x] 7. feat(frontend): t0_stats.js 新增 getExposure + getAggregate
- [x] 8. feat(frontend): useT0Balance.js 新增 exposureList / aggregate
- [x] 9. feat(frontend): T0Trade.vue 加 T0ExposureTable + T0AggregateCard + 一键配平
- [x] 10. docs(frontend): frontend/spec.md 加 REQ-FE 规则（spec-deltas/frontend.md 已写）
- [x] 11. test: 全量 pytest + 手动 UI 验证（冒烟通过）+ 归档
