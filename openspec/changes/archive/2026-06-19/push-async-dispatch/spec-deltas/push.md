# spec-deltas/push

## 改动

`openspec/specs/push/spec.md` 新增：

- **REQ-PUSH-006 异步落库（v8）**：push listener 调用 `handle_push` 必须走 `asyncio.to_thread` 包裹，禁止在 event loop 内同步执行 SQLAlchemy。原因：push 密集到达时阻塞 event loop → reply 队列延迟。实现：`await asyncio.to_thread(_run_handle_push, func, row, ts)`，helper 在新线程开 SessionLocal + handle_push + commit。错误透传给 listener。**`handle_push` 同步签名不变**（向后兼容 test_push_handlers.py）。
- **S-PUSH-004**：验证场景——push 落库期间 reply 消费延迟 < 5ms。

## 影响范围

仅 `server/rpc/client.py`：

- 新增 `_run_handle_push(func, row, ts)` 同步 helper
- `_listen_pushs()` 内 12 行同步块 → 3 行 `await asyncio.to_thread(...)`

无业务 API / handler / model 改动。

## 测试

`server/test_push_async.py` 新增 4 用例，mock to_thread + 异常透传 + 签名兼容。