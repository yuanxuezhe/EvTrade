# Tasks — fix-t0-aggregate-py36-compat

## 实施步骤

- [ ] 1. 改 `server/api/t0_aggregate.py`：
  - [ ] 1.1 `from typing import Optional` → `from typing import List, Optional`
  - [ ] 1.2 第 66 行 `list[ExposurePositionOut]` → `List[ExposurePositionOut]`
  - [ ] 1.3 第 109 行 `list[AggregateByDayOut]` → `List[AggregateByDayOut]`
  - [ ] 1.4 第 110 行 `list[AggregateByStockOut]` → `List[AggregateByStockOut]`
- [ ] 2. 改 `scripts/evctl.py::start_service`：
  - [ ] 2.1 把单次 `time.sleep(0.5)` + 单次 `pid_alive` 改成 3 次轮询（0.5/1.5/3.0s）
  - [ ] 2.2 任一时刻检测到 pid 已死 → 调 `_tail_log`（已存在），同时打明确错误信息
  - [ ] 2.3 三次都活着才打 `[OK] X started`
- [ ] 3. 更新 `openspec/specs/dev-process-control/spec.md`：
  - [ ] 3.1 新增 Scenario S-DPC-005 "spawn 后存活检查"（3 次轮询 + tail log）
  - [ ] 3.2 新增 Scenario S-DPC-006 "import 链兼容 Py3.6.8"（PEP 585 禁 `list[T]` 等）
  - [ ] 3.3 新增 Scenario S-DPC-007 "asyncio.create_task 不出现在 server/"（强制 `ensure_future`）
- [ ] 4. 更新 `openspec/specs/trading/spec.md` REQ-TRADE-006 schema 注释（`list[T]` → `List[T]`）
- [ ] 5. `pytest server/test_t0_aggregate.py` 全绿
- [ ] 6. 手动 `python scripts\evctl.py restart`：
  - [ ] `[OK] backend started` 后 ~3s 内出现 `[OK] backend healthy`
  - [ ] `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`
- [ ] 7. 修 `server/main.py:174`：`asyncio.create_task(heartbeat_sender())` → `asyncio.ensure_future(heartbeat_sender())`
- [ ] 8. 修 `server/test_push_async.py`：
  - [ ] 8.1 line 111 `asyncio.create_task(...)` → `asyncio.ensure_future(...)`
  - [ ] 8.2 line 115 列表推导式内 `asyncio.create_task(...)` → `asyncio.ensure_future(...)`
- [ ] 9. 修 `server/test_rpc_link.py:190`：`asyncio.create_task(client.call(...))` → `asyncio.ensure_future(client.call(...))`
- [ ] 10. `pytest server/test_push_async.py server/test_rpc_link.py` 全绿（Py3.6.8 下不再 AttributeError）
- [ ] 11. WS 连接 smoke：`wscat` 或 curl-upgrade 连 `/ws/position_update?token=JWT` 不再 500
- [ ] 12. commit: `fix(server): t0_aggregate PEP 585 + asyncio.create_task → ensure_future (Py3.6 compat) + evctl spawn 存活检查窗口`
- [ ] 13. 把 `current-issues/proposal.md` H4/H5 后的"待修"区追加 H8 一行指向本 change（asyncio.create_task）

## 验证

- [ ] `pytest server/test_t0_aggregate.py test_push_async.py test_rpc_link.py -v` 全绿
- [ ] `python scripts\evctl.py restart` 看到 `[OK] backend healthy`
- [ ] `curl http://127.0.0.1:8000/api/health` 返回 200
- [ ] WS 连接：`wscat` 或客户端连 `/ws/{channel}?token=...` 不再 AttributeError
- [ ] `git log --oneline -1` 显示新 commit
- [ ] grep `asyncio\.create_task server/` 仅剩 `server/rpc/client.py` 同款（已 ensure_future）和测试注释