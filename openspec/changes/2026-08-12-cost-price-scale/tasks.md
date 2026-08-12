# Tasks — 持仓成本按证券 scale 保留精度

> 先知识库后代码。取代 cost-price-round4 的固定 4 位口径。改动分 2 commit 便于 review/回滚。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [ ] 1.2 主 spec 落地：`openspec/specs/data-model/spec.md` positions.cost_price
      - [ ] 精度口径「统一 4 位小数」→「按 stocks.scale 保留精度（A股 2/ETF 3，兜底 2）」
      - [ ] 写路径清单补 trd 建仓（买入自动建 Position 也写 cost_price）
- [ ] 1.3 commit: `docs(spec): positions.cost_price 按 stocks.scale 保留精度 (cost-price-scale)`

## 2 — 工具函数 helpers

- [ ] 2.1 `push/helpers.py`：删 `_round4`，新增 `_round_scale(v, scale)`（round + scale>6 兜底 2）
- [ ] 2.2 `_position_to_out_dict` cost_price 按 `get_stock_scale` round
- [ ] 2.3 commit: `refactor(push): cost_price 精度 _round4 → _round_scale(scale) (cost-price-scale)`

## 3 — 3 条写路径按 scale

- [ ] 3.1 `reconcile.py:225` cost_price 按 scale（import 更新）
- [ ] 3.2 `push/pos.py:68` cost_price 按 scale
- [ ] 3.3 `push/trd.py:147` 建仓 cost_price 按 scale（补漏）
- [ ] 3.4 commit: `fix(push): 3 条写路径 cost_price 按 stock.scale 保留精度 (cost-price-scale)`

## 4 — 测试

- [ ] 4.1 `test_cost_price_round4.py` 改 scale-aware（scale=2/3 两组断言 + 序列化）
- [ ] 4.2 `test_pos_push_diff.py` fixture 补 `get_stock_scale` monkeypatch（hermetic）
- [ ] 4.3 验证：新测试全绿 + push 目录其余失败为预存（无新 regression）
