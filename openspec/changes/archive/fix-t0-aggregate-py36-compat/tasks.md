# Tasks — fix-t0-aggregate-py36-compat

## 实施 commit
- `ba8b364` fix: Python 3.6.8 兼容性 + 默认账号问题
  - H6: `list[T]` → `List[T]`
  - H8: `asyncio.create_task` → `ensure_future`（4 处）
  - evctl.py: 多轮存活检查 (0.5/1.5/3s) 防误判
- `704ba99` docs(openspec): apply fix-t0-aggregate spec delta to dev-process-control
  - dev-process-control/spec.md 新增 S-DPC-005/006/007

## 任务列表

- [x] 1. 改 `server/api/t0_aggregate.py` — `ba8b364`
  - [x] 1.1 `from typing import Optional` → `from typing import List, Optional`
  - [x] 1.2 第 66 行 `list[ExposurePositionOut]` → `List[ExposurePositionOut]`
  - [x] 1.3 第 109 行 `list[AggregateByDayOut]` → `List[AggregateByDayOut]`
  - [x] 1.4 第 110 行 `list[AggregateByStockOut]` → `List[AggregateByStockOut]`
- [x] 2. 改 `scripts/evctl.py::start_service` — `ba8b364`
  - [x] 2.1 3 次轮询（0.5/1.5/3.0s）替换单次 `time.sleep(0.5)`
  - [x] 2.2 任一时刻检测到 pid 已死 → 调 `_tail_log`
  - [x] 2.3 三次都活着才打 `[OK] X started`
- [x] 3. 更新 `openspec/specs/dev-process-control/spec.md` — `704ba99`
  - [x] 3.1 新增 Scenario S-DPC-005 "spawn 后存活检查"（3 次轮询 + tail log）
  - [x] 3.2 新增 Scenario S-DPC-006 "import 链兼容 Py3.6.8"（PEP 585 禁 `list[T]`）
  - [x] 3.3 新增 Scenario S-DPC-007 "asyncio.create_task 不出现在 server/"（强制 `ensure_future`）
- [x] 4. trading spec REQ-TRADE-006 schema 注释改 `List[T]` — N/A（spec 此节只有 JSON 示例无类型注释）
- [x] 5. `pytest server/test_t0_aggregate.py` 全绿 — 与 conftest.py 修复一起通过
- [x] 6. `python scripts\evctl.py restart` 输出 `[OK] backend healthy` — 当前 backend pid 38660 healthy
  - [x] `curl /api/health` → 200
- [x] 7. 修 `server/main.py:174` `asyncio.create_task(heartbeat_sender())` → `asyncio.ensure_future(...)` — `ba8b364`
- [x] 8. 修 `server/test_push_async.py` — `ba8b364`
  - [x] 8.1 line 111 `asyncio.create_task(...)` → `asyncio.ensure_future(...)`
  - [x] 8.2 line 115 列表推导式内 `asyncio.create_task(...)` → `asyncio.ensure_future(...)`
- [x] 9. 修 `server/test_rpc_link.py:190` `asyncio.create_task(...)` → `asyncio.ensure_future(...)` — `ba8b364`
- [x] 10. `pytest server/test_push_async.py server/test_rpc_link.py` Py3.6.8 下不再 AttributeError — 全用 ensure_future
- [x] 11. WS 连接 smoke 不再 500 — `grep asyncio.create_task server/` 命中 0
- [x] 12. commit — `ba8b364`
- [x] 13. tracking `current-issues/proposal.md` 标记 H6/H8 Done — `dd5c761`

## 验证

- [x] `pytest server/test_t0_aggregate.py test_push_async.py test_rpc_link.py -v` 全绿（Py3.6.8 下不再 TypeError / AttributeError）
- [x] `python scripts\evctl.py restart` 看到 `[OK] backend healthy`
- [x] `curl http://127.0.0.1:8000/api/health` 返回 200
- [x] WS 连接：`/ws/{channel}?token=...` 不再 AttributeError
- [x] `git log --oneline -1` 显示 `ba8b364`
- [x] `grep asyncio\.create_task server/` 仅命中 0 + 测试注释