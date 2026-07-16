## REQ-INFRA-002 follow-up: futex 僵死 "根治 vs 预防" 分工

### 根治 vs 预防（v52 复盘后明确）

| 维度 | 根治 (v52 commit 22f515f) | 预防 (v51 commit 51fcb9c) |
|---|---|---|
| 落点 | sync endpoint → async + bcrypt 走 threadpool | pool_timeout=10s + pool_pre_ping=true |
| 目标 | 释放 Starlette threadpool → DB session 立即归还 | 极端情况下快速 5xx，不让主进程僵死 |
| 失败模式 | 不适用（结构性消除） | 超时即失败 → 客户端快速重试 → 服务可恢复 |
| 必要性 | ✅ 必做（已复发 3 次） | ✅ 必做（兜底保险） |

### 约束

#### Scenario: 文档化 futex 死锁链
**Given** 新工程师接触 `server/infra/db.py::_pool_kwargs`  
**When** 阅读 docstring  
**Then** 看到完整 futex 死锁链路（7 步）+ v52 修复路径 + 预防兜底语义

#### Scenario: get_db 异常路径兜底
**Given** sync endpoint 异常抛出 HTTPException  
**When** FastAPI 调用 get_db() finally  
**Then** `db.rollback()` + `db.close()` 双步执行，避免半挂 session  
**And** 即便未来再误用 sync 阻塞 endpoint，也不会触发 session 泄漏

### 验收

- [x] `_pool_kwargs` docstring 含 futex 链路 + 根治 vs 预防分工
- [x] `get_db()` 加 `except Exception: rollback + close`
- [x] 环境变量 `EVTRADE_DB_POOL_TIMEOUT` 默认 10s，可调

### 关联

- commit `48cc8f9` (infra/db.py)
- v51 commit `51fcb9c` (pool_timeout=10 预防)
- 关联 REQ: REQ-INFRA-001 (DB pool 配置), REQ-INFRA-002 (异常路径兜底)