# futex 僵死根因修复（v52）

## Why

v51 已落 `pool_timeout=10` 预防（限爆炸半径），但根因未根治：登录端点 (`POST /api/auth/login`) 是 sync def + bcrypt.checkpw（CPU bound, rounds=12 ~250ms）阻塞 Starlette anyio threadpool 默认 40 线程，触发以下死锁链：

```
sync login endpoint
  → bcrypt.checkpw (~250ms, blocks Starlette thread)
  → 其他 sync endpoint 也抢同一池（fetch_user / load_trades）
  → DB session 在 handler 内 db.commit() 后未归还
  → Pool 5+10=15 耗尽
  → 新请求 30s 等连接
  → 部分 session 泄漏
  → 任何 io 触发 futex_wait_queue
  → 主进程永久僵死（socket 仍 LISTEN 但不响应）
```

futex 累计复发 3 次（v46 + v50 + v51），其中 v51 第三次复发确认 pool_timeout 是预防，不是根治。

## What Changes

- **REQ-AUTH-001 follow-up**: login/change-password 端点改 async + bcrypt 走 `fastapi.concurrency.run_in_threadpool`
- **REQ-INFRA-002 follow-up**: `_pool_kwargs` docstring 文档化"根治 vs 预防"分工 + `get_db()` 异常路径加 rollback 兜底

## Impact

- 受影响 spec: `auth`, `infra`
- 改动文件: `server/api/auth.py`, `server/infra/db.py`
- 兼容性: 向后兼容（仅实现细节，API 契约不变）
- 风险: 低（async 化 + threadpool 是 FastAPI 标准模式）