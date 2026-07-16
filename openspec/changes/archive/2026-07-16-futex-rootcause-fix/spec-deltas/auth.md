## REQ-AUTH-001 follow-up: 登录端点必须 async

### 背景

futex 僵死事件复盘（v52）：
- 旧 `POST /api/auth/login` 是 `def login`（sync），bcrypt.checkpw（CPU bound, rounds=12 ~250ms）阻塞 Starlette anyio threadpool
- 40 并发 login 即可耗光 threadpool → 其他 sync endpoint (fetch_user/load_trades) 抢同一池 → DB session 不归还 → Pool 5+10=15 耗尽 → 新请求 30s 等连接 → 部分 session 泄漏 → futex_wait_queue → 主进程永久僵死

### 约束

#### Scenario: bcrypt 不阻塞 event loop
**Given** 用户在浏览器点击登录按钮  
**When** 前端 POST `/api/auth/login` form-data username=admin&password=admin123  
**Then** 后端 `await run_in_threadpool(verify_password, ...)` 释放 event loop  
**And** DB session 在 handler 异常时通过 get_db() finally 归还  
**And** 5 并发 login 平均响应 ≤ 0.7s（实测 0.65s）

#### Scenario: change-password 同样 async
**Given** 用户已登录  
**When** POST `/api/auth/change-password`  
**Then** `hash_password` 也走 threadpool（rounds=12 ~300ms，CPU bound）  
**And** 不阻塞 event loop

### 验收

- [x] `def login` 改 `async def login`
- [x] `def change_password` 改 `async def change_password`
- [x] bcrypt 调用全包 `await run_in_threadpool(...)`
- [x] 5 并发实测 200 OK，无 5xx，无 stuck
- [x] 浏览器 admin/admin123 登录成功，Dashboard 正常加载

### 关联

- 根治: commit `22f515f` (auth.py)
- 预防: commit `51fcb9c` (v51 pool_timeout=10)
- 关联 REQ: REQ-AUTH-001 (登录端点契约)