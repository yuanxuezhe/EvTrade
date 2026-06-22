# 修 t0_aggregate.py Python 3.6 兼容性 + evctl.py 诊断窗口

## 1. Why

2026-06-22 用户报 `python scripts\evctl.py restart` 失败：evctl 输出
`[OK] backend started (pid=25836, ...)` 然后 `[WARN] backend health check failed`，
但端口 8000 没监听、`/api/health` curl 不通。

手动跑 `python -u -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload` 才看到真正的栈：

```
File ".\api\t0_aggregate.py", line 66, in T0ExposureOut
    positions: list[ExposurePositionOut]
TypeError: 'type' object is not subscriptable
```

**根因**：`server/api/t0_aggregate.py` 三处用了 **PEP 585 内建泛型**（`list[T]`），
此语法需要 **Python 3.9+**。但 `dev-process-control/spec.md` 明确约束
"Python 3.6.8 兼容"，`.python-version = 3.6.81`。

引入处：`changes/archive/2026-06-19/t0-exposure-and-aggregate/proposal.md` ——
proposal 全文未检查 Python 版本兼容约束。

**次根因（evctl 诊断窗口太窄）**：uvicorn `--reload` 模式下，父进程（Popen 拿到的 PID）
spawn 后立刻打印 `Uvicorn running on ...`，然后才 fork 出子进程去 `import main:app`。
本次子进程在 `import` 中段崩（`list[T]` 语法），父进程**延迟**才感知到（"Stopping reloader"
是在子进程死后才打）。`evctl.py` 的 0.5s `pid_alive` 检查只看父进程，仍然 alive → 误报成功。
等到 `wait_health` 走 10 次失败（约 10s）用户才知道有事。

参考：`changes/archive/2026-06-16-consolidate-evctl-script/tasks.md:77` 已知类似事件
（`No module named uvicorn`），但那次是 0.1s 秒挂场景，0.5s 检查能抓到。本场景是
"父进程晚感知"型失败，0.5s 不够。

## 2. What

### 2.1 修 t0_aggregate.py（主修）

`server/api/t0_aggregate.py`：
- 第 10 行 `from typing import Optional` → `from typing import List, Optional`
- 第 66 行 `positions: list[ExposurePositionOut]` → `positions: List[ExposurePositionOut]`
- 第 109 行 `by_day: list[AggregateByDayOut]` → `by_day: List[AggregateByDayOut]`
- 第 110 行 `by_stock: list[AggregateByStockOut]` → `by_stock: List[AggregateByStockOut]`

仅类型注解，运行期等价（Pydantic v1 在两种写法下行为一致）。

### 2.2 evctl.py spawn 存活检查窗口加长（次修）

`scripts/evctl.py`：
- `_post_spawn_survival_check` 概念引入：spawn 后 0.5s / 1.5s / 3.0s 三次 poll
  （间隔 0.5/1.0/1.5），任一时刻 `not pid_alive(p.pid)` 即触发 `_tail_log` 报错
- 当子进程死时，stderr 已通过 `subprocess.STDOUT` 重定向到 log_f，所以 `_tail_log`
  必然能拿到 traceback（已实现，但本次事件中**未被调用**，因为 pid_alive 误判父进程活着）

不改后端 uvicorn 重启逻辑（`_WIN_DETACHED_FLAGS`、`spawn_detached` 行为不变）。

### 2.3 加防回归 grep（预防性约束）

`scripts/check_py36_compat.sh` （可选 / 后续 change）：
- `grep -rn -E ': (list|dict|tuple)\[[A-Z][a-zA-Z]*\]' server/`
- 命中即非零退出
- 接入 CI 或 pre-commit

本次 change 不实施 2.3，留 follow-up。

### 2.4 修 asyncio.create_task（Py3.6.8 不兼容，扩张范围）

**触发**：2026-06-22 实施 2.1/2.2 后，`python scripts\evctl.py restart` 通过 import 链，
backend 启动到 ws 路由时再次崩：

```
File ".\main.py", line 174, in websocket_endpoint
    sender_task = asyncio.create_task(heartbeat_sender())
AttributeError: module 'asyncio' has no attribute 'create_task'
```

`asyncio.create_task` 是 Python 3.7+ API；`.python-version = 3.6.81` 下不可用。
本次实施过程中用户当场报问题 → 扩入本 change 一起处理。

**根因**：v10 加 WS 双向心跳（commit 未列）时引入，未检查 Py3.6.8 兼容。
`server/rpc/client.py:137-138` 已正确用 `asyncio.ensure_future(...)`，本批代码漏改。

**4 处需修**（生产 1 + 测试 3）：

| 文件 | 行 | 现状 |
|---|---|---|
| `server/main.py` | 174 | `asyncio.create_task(heartbeat_sender())`（生产，崩 WS 连接） |
| `server/test_push_async.py` | 111 | `asyncio.create_task(asyncio.to_thread(...))` |
| `server/test_push_async.py` | 115 | `[asyncio.create_task(fake_reply()) for _ in range(10)]` |
| `server/test_rpc_link.py` | 190 | `asyncio.create_task(client.call("qry_ast", timeout=2.0))` |

**修法**：4 处统一 `asyncio.create_task(coro)` → `asyncio.ensure_future(coro)`。

**等价性论证**：
- 4 处均在 running loop 中调用（`async def` 协程内 / `pytest-asyncio` 的 async 测试函数内）
- `asyncio.ensure_future(coro)` 在 running loop 中返回 `Task` 对象，**与 `create_task` 等价**：
  支持 `.cancel()` / `.done()` / `.result()` / `.exception()`
- `main.py:192` `sender_task.cancel()`、`test_rpc_link.py:213` `call_task.cancel()` 均不受影响
- `asyncio.gather(...)`（`test_push_async.py:116`）接受 Task / Future 均可

**回退验证**：Python 3.6.8 下 `asyncio.ensure_future` 一直存在（3.4+），本次修复不引入新依赖。

## 3. 影响面

- `server/api/t0_aggregate.py` — 4 行（3 处类型 + 1 处 import）
- `scripts/evctl.py` — `start_service` 中 spawn 后存活检查逻辑（约 10 行）
- `server/main.py` — 1 行（line 174 `asyncio.create_task` → `asyncio.ensure_future`）
- `server/test_push_async.py` — 2 行（line 111, 115）
- `server/test_rpc_link.py` — 1 行（line 190）
- `openspec/specs/dev-process-control/spec.md` — 新增 3 个 Scenario（S-DPC-005/006/007）
- `openspec/specs/trading/spec.md` — REQ-TRADE-006 schema 部分引用 `List[ExposurePositionOut]` 写法
- **测试**：`pytest server/test_t0_aggregate.py` + `test_push_async.py` + `test_rpc_link.py` 全绿
- **CI/hook**：本 change 不动；2.3 留给后续

## 4. Spec Deltas

- `dev-process-control/spec.md`：
  - 新增 Scenario S-DPC-005 "spawn 后存活检查"：WHEN spawn 进程 0.5s/1.5s/3.0s 任何时刻检测到 pid 已死，THEN 报错并打日志最后 15 行
  - 新增 Scenario S-DPC-006 "import 链兼容 Python 3.6.8"（PEP 585 禁 `list[T]` 等）
  - 新增 Scenario S-DPC-007 "asyncio.create_task 不出现在 server/"（强制 `ensure_future`）
- `trading/spec.md`：
  - REQ-TRADE-006 schema 字段类型注释统一改 `List[T]`（仅注释，代码已 2.1 修好）

## 5. 不在本 change 范围

- 升级 Python 版本到 3.9+（与 `dev-process-control` 约束冲突）
- `check_py36_compat.sh` 防回归脚本（留 follow-up）
- evctl.py 的 port-based PID 关联（孤儿 vite 接管已实现，本次不重复）
- 任何前端改动

## 6. 归档条件

- `pytest server/test_t0_aggregate.py` + `test_push_async.py` + `test_rpc_link.py` 全绿
- 手动 `python scripts\evctl.py restart` 输出 `backend healthy`
- `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`
- WS 心跳连接 smoke：连接 `/ws/position_update?token=JWT` 不再 AttributeError