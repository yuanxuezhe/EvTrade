# Spec Delta — fix-t0-aggregate-py36-compat → dev-process-control

## MODIFIED Requirements

### Requirement: Python 3.6.8 兼容（强化）

原 Scenario 描述 evctl.py 自身 import 无 SyntaxError 即可。本次 BUG（2026-06-22）表明：
仅 evctl.py 自身兼容**不够**，还须保证 `uvicorn main:app` import 链整体兼容。

#### Scenario S-DPC-005: spawn 后存活检查（新增）

- **WHEN** evctl.py spawn 一个服务后 0.5s / 1.5s / 3.0s 任一时刻检测到 PID 已死
- **THEN** 报错并打 `scripts/.logs/<svc>.log` 最后 15 行（uvicorn 子进程的 stderr 通过
  `subprocess.STDOUT` 重定向已写入该日志，因此 traceback 必然可见）
- **AND** 返回 False 让 start_all 增加 fails 计数

#### Scenario S-DPC-006: import 链兼容 Python 3.6.8（新增）

- **WHEN** developer run `python scripts\evctl.py start backend` 在 Python 3.6.8 下
- **THEN** `uvicorn main:app` 整个 import 链不能出现 `TypeError: 'type' object is not subscriptable`
  （PEP 585 内建泛型 `list[T]` / `dict[T,U]` 在 3.6.8 下不可用）
- **AND** 若 import 失败，traceback 应在 `scripts/.logs/backend.log` 中可读

#### Scenario S-DPC-007: asyncio.create_task 不出现在 server/（新增）

- **WHEN** 项目代码（生产 + 测试）需要在 running loop 中调度协程
- **THEN** 必须使用 `asyncio.ensure_future(coro)` 而非 `asyncio.create_task(coro)`
  （后者 Python 3.7+ 才可用，本项目 `.python-version = 3.6.81`）
- **AND** 两种调用在 running loop 中均返回 `Task`，支持 `.cancel()` / `.done()` / `.result()`
- **AND** `scripts/check_py36_compat.sh`（follow-up）应 grep `asyncio\.create_task` 命中即非零退出