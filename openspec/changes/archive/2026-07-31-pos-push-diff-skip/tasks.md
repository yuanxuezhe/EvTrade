# Tasks

- [x] 1. 在 `openspec/specs/push/spec.md` 新增 `REQ-PUSH-034`：pos_push 无变化时跳过落库与广播（diff 字段 = {last_vol, vol, avl_vol, cost_price}）
- [x] 2. 在 `openspec/specs/positioning/spec.md` `REQ-POS-003` 数据来源段加注 pos_push diff 行为
- [x] 3. 在 `server/services/push/pos.py` `handle_pos_push` 入口加 `_fields_unchanged` 守门；新增本地辅助函数
- [x] 4. 新增 `server/tests/push/test_pos_push_diff.py`：3 个用例（无变化→None / 字段变化→UPDATE / 新建行不走 diff）
- [x] 5. pytest 跑通（`pytest server/tests/push/ -v`）
- [x] 6. ws 实测：连 broker → 重复同值 pos_push → 前端 ws frame 不新增
- [x] 7. 归档：proposal.md + tasks.md 完成 + spec.md 已合并 → `opsx:archive`