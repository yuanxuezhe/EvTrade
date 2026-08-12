# Tasks — broker 持仓成本统一 4 位小数

> 先知识库后代码。用户已确认方案：仅边界四舍五入（复用 `_round4`），不迁移 DB 列。
> 改动分 3 个 commit 便于 review/回滚。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [ ] 1.2 主 spec 落地：`openspec/specs/data-model/spec.md` positions.cost_price
      - [ ] 补「统一 4 位小数」约定（写路径 reconcile/pos_push 落库前 `_round4`，读取序列化同口径）
      - [ ] 修正写源描述：cost_price 由「仅 do_reconcile 写入」改为「do_reconcile + pos_push」
- [ ] 1.3 commit: `docs(spec): positions.cost_price 统一 4 位小数口径 (cost-price-round4)`

## 2 — 写路径：reconcile 落库补 _round4

- [ ] 2.1 `reconcile.py:224` cost_price 套 `_round4`（import `server.services.push.helpers._round4`）
- [ ] 2.2 回归测试（reconcile 边界 round 4 位，见 §4）
- [ ] 2.3 commit: `fix(reconcile): positions.cost_price 落库前 _round4, 对齐 v130+ 4 位口径 (cost-price-round4)`

## 3 — 读路径：WS 序列化补 _round4

- [ ] 3.1 `push/helpers._position_to_out_dict` cost_price `_float` → `_round4`
- [ ] 3.2 回归测试（`_position_to_out_dict` 输出 cost_price 4 位）
- [ ] 3.3 commit: `fix(push): position_update cost_price 序列化 _round4, 对齐读取口径 (cost-price-round4)`

## 4 — 验证

- [ ] 4.1 server 端新测试 + `test_pos_push_diff.py` 等既有测试全绿（无新 regression）
