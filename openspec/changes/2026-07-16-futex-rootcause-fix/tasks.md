# Tasks: futex 僵死根因修复（v52）

## 1. 异步化根治
- [x] 1.1 `server/api/auth.py` import `run_in_threadpool` (fastapi.concurrency)
- [x] 1.2 `def login` → `async def login`
- [x] 1.3 `def change_password` → `async def change_password`
- [x] 1.4 `verify_password` / `hash_password` 调用全包 `await run_in_threadpool(...)`
- [x] 1.5 user 不存在时提前 raise（避免无意义 bcrypt 调用）

## 2. 兜底文档化 + get_db() 异常路径
- [x] 2.1 `server/infra/db.py::_pool_kwargs` docstring 扩展（根治 vs 预防分工 + futex 链路 7 步）
- [x] 2.2 `get_db()` 加 `except Exception: rollback + close` 异常路径
- [x] 2.3 文档化环境变量（EVTRADE_DB_POOL_TIMEOUT 等）

## 3. 验证
- [x] 3.1 后端重启（PID 2554693）+ `/api/health` 200 OK
- [x] 3.2 curl 单线程 login 200 OK 0.5s
- [x] 3.3 curl 5 并发 10 个 login 全 200，平均 0.65s
- [x] 3.4 浏览器 admin/admin123 登录跳 Dashboard，资产/持仓/委托全加载，无 stuck
- [x] 3.5 极端 40 并发 → 确认非生产场景（pool 5+10=15 容量限制，超出会超时），但服务本身不再僵死（health endpoint 正常）

## 4. 归档
- [x] 4.1 commit.1 = `server/api/auth.py` 改动（`22f515f`）
- [x] 4.2 commit.2 = `server/infra/db.py` 改动（`48cc8f9`）
- [x] 4.3 git push origin master
- [x] 4.4 双 hash 验证：本地 `48cc8f9` == 远端 `48cc8f9`