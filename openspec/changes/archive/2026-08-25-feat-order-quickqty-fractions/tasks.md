# Tasks — order-quickqty-fractions

- [ ] 1. **建 change 结构** — 创建 `openspec/changes/2026-08-25-feat-order-quickqty-fractions/`（proposal.md + tasks.md + spec-deltas/frontend.md）
- [ ] 2. **stocks store 加 helper** — `client/src/stores/stocks.js` 加 `stockTradeUnit(code)`，签名同 `stockScale`/`stockStktype`，cache miss 兜底 100，导出
- [ ] 3. **OrderForm 快捷按钮改造** — `volumeShortcuts` 改 `[{label:'1/10',value:0.1},...,{label:'1/1',value:1}]`；模板渲染 `{{ fraction.label }}`；点击调 `applyFraction(fraction.value)`；新增 `availableTradeQty` computed 按方向 × trade_unit 算最大可用股数；`applyFraction` 内按方向 × fraction → 整手取整（买 floor / 卖 ceil）
- [ ] 4. **写测试** — 新建 `tests/client/components/OrderForm.test.js`，覆盖：买 1/2 cash/px = 5000, px=10, trade_unit=100 → 250 股；卖 1/2 avl=3000, trade_unit=100 → 1500 股（向上）；买 1/1 cash/px 不足 1 手 → 0；卖 1/10 avl<100 → 0；切换方向重算
- [ ] 5. **跑测试** — `cd client && npm run test -- OrderForm` + `pytest hq/ server/tests/`（无 regression）
- [ ] 6. **KB 同步** — 改 `知识库/前端/页面/交易下单.md`（OrderForm 章节：快捷按钮描述）
- [ ] 7. **合并 spec delta** — `openspec/specs/frontend/spec.md` 新增 REQ-FE-543（分数快捷按钮）+ REQ-FE-544（stockTradeUnit helper）
- [ ] 8. **归档** — `mv openspec/changes/2026-08-25-feat-order-quickqty-fractions openspec/changes/archive/`；更新 `openspec/AGENTS.md` 活跃 change 表
- [ ] 9. **commit** — 按 v6 拆 4 commit（feat / feat / test / docs）；不自动 push

## 验证

- [ ] vitest 5 分数 × 2 方向 = 10 case 全过
- [ ] pytest 81 passed / 7 failed（CLAUDE.md § 八基线持平）
- [ ] 知识库 4 文件 diff 单一功能（OrderForm 快捷按钮改造）
- [ ] 归档后 `openspec/AGENTS.md` 活跃表新增 1 行