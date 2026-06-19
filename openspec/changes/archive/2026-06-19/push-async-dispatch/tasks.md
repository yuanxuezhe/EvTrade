# Tasks

- [x] proposal.md + spec-deltas/push.md
- [x] spec.md 新增 REQ-PUSH-006（异步落库）+ S-PUSH-004 场景
- [ ] server/rpc/client.py：抽 `_run_handle_push` helper（同步，新建 SessionLocal + handle_push + commit）
- [ ] server/rpc/client.py：_listen_pushs 内 push 落库改 `await asyncio.to_thread(_run_handle_push, func, row, ts)`
- [ ] server/test_push_async.py：4 用例（mock to_thread + 不阻塞验证 + 异常透传 + 签名兼容）
- [ ] pytest server/test_push_async.py 全绿 + 现有 test_push_handlers.py 不挂
- [ ] archive → openspec/changes/archive/2026-06-19/push-async-dispatch/

## Out-of-scope

- AsyncSession 全栈 async（独立 change）
- push handler 并发控制（现状安全：单条 commit + 短事务）