# 2026-06-19-push-async-dispatch — push 落库改为异步（to_thread）

## Problem

`server/rpc/client.py` `_listen_pushs()` 在 event loop 中**同步**执行 SQLAlchemy 操作（handle_push + commit + close），阻塞 50–200ms。

rpc-link-topology change 排查时列为 P3（参见 archive 2026-06-19/rpc-link-topology/proposal.md "Out-of-scope"）。本 change 顺手补齐。

**症状**：push 消息密集到达时（每秒 5+ 条成交回报）reply 队列消费被推迟 200ms+ → RPC 超时率上升；WebSocket 推送也卡。

## Solution

最小改动 `server/rpc/client.py`：

### A. 抽 helper `_run_handle_push`

```python
def _run_handle_push(func: str, row: Dict[str, Any], ts: str):
    """同步 helper：开 SessionLocal → handle_push → commit，to_thread 内部跑。"""
    db = SessionLocal()
    try:
        handle_push(db, func, row, ts)
        db.commit()
    except Exception as e:
        db.rollback()
        raise  # 让 to_thread 把异常传到 await 处
    finally:
        db.close()
```

### B. push listener 改成 `await asyncio.to_thread(_run_handle_push, ...)`

替换现在的同步调用块（约 12 行 → 3 行）。try/except 仍在 listener 内捕获异常 + log。

### 不改 `handle_push` 签名

- 4 个 `_cfm` 函数继续同步 SQLAlchemy（每个新 thread 一个 SessionLocal，安全）
- `test_push_handlers.py` 11 用例**零改动**继续通过
- 业务行为完全等价

## Risks

| 风险 | 缓解 |
|------|------|
| 多线程共享 ORM session | helper 内部 `SessionLocal()` 每次新建，跟现状一致 |
| 异常吞掉 | to_thread 重新抛，listener 已有 try/except log |
| 顺序错乱 | push 来自同队列 broker 端有序，但落库顺序不保证 = **现状**（单线程跑也是单条 commit）|

## Out-of-scope

- 全栈 async（AsyncSession + aiosqlite）：改动太大，独立 change
- push handler 内部并发控制

## Tests

新增 `server/test_push_async.py`：

1. `test_handle_push_runs_in_thread` — patch `asyncio.to_thread`，断言被调用且参数对
2. `test_listener_does_not_block_event_loop` — patch `_run_handle_push` 为 sleep(0.2) 同步，listener 在 await 期间 main loop 能处理 reply
3. `test_to_thread_exception_propagates` — `_run_handle_push` 抛错时 listener 捕获 + log
4. `test_handle_push_signature_unchanged` — 反射验证 handle_push 仍是同步函数（向后兼容）

按 v7 纪律不跑无关测试。

## Tasks

参见 tasks.md。