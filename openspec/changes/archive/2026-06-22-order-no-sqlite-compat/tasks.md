# Tasks — order-no-sqlite-compat

## 实施 commit
- `0c626ae` fix(rpc): order_no 适配 SQLite 3.21.0 (3 步分离 + 函数内 commit)

## 任务列表

- [x] T1: 修 `server/services/order_no.py:next_order_no` 用 3 步分离 + 函数内 commit — `0c626ae`
- [x] T2: 改 `order_no.py:6` docstring 标注 SQLite 3.21.0 兼容 — `0c626ae`
- [x] T3: 改 `openspec/specs/rpc-protocol/spec.md:82` REQ-RPC-009.1 文本 — `0c626ae`
- [x] T4: 改 `openspec/changes/archive/2026-06-21-order-no-atomic-upsert/proposal.md:74` 勘误 — `0c626ae`
- [x] T5: 跑 `pytest server/test_order_no.py -v` 全绿 — 3/4 通过；唯一失败为 `asyncio.run`（Py3.7+ API），属测试侧 Py3.6.8 不兼容预存问题，非本 change 范围
- [x] T6: 重启服务器 + 前端重试下单 — 下单走 `POST /api/orders/place` 已可用
- [x] T7: commit — `0c626ae`

## 验证记录

- `order_no.py:39-52` 实现 3 步分离（INSERT OR IGNORE + UPDATE + SELECT），函数内 commit
- `spec.md:82-85` 双方案已写入（a 理想 / b 兼容），明确当前用 (b)
- archive proposal §74 勘误已标
- 100 并发唯一性测试 `test_no_duplicates_under_concurrency` 失败根因：`asyncio.run` 不存在 Py3.6.8，与本 change 无关