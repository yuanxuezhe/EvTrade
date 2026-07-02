# Tasks — Server 交互日志

按 memory 拆 5 commit（utils + middleware + rpc + ws + tests/docs）：

## 1. Commit 1: utils/logflow.py 统一日志入口 ✅ Done

新建 `server/utils/__init__.py` + `server/utils/logflow.py`：

- [x] 函数 `log_interaction(direction, summary, *, data=None, elapsed_ms=None, level="info")`
- [x] 4 个常量：`DIR_FRONT_TO_SVC = "front->svc"` / `DIR_SVC_TO_RPC = "svc->rpc"` / `DIR_SVC_FROM_RPC = "svc<-rpc"` / `DIR_SVC_TO_FRONT = "front<-svc"`
- [x] 内部用 `format_ts()` (v10 工具) 打时间戳
- [x] 内部用 `_truncate_data(data, max_bytes=4096)` 截断 body
- [x] 失败安全：序列化失败 → 用 `repr()` 兜底

## 2. Commit 2: FastAPI HTTP 请求/响应中间件 ✅ Done

新建 `server/middleware/__init__.py` + `server/middleware/request_logging.py`：

- [x] `RequestLoggingMiddleware(BaseHTTPMiddleware)` 或 `@app.middleware("http")` 风格
- [x] 进入：记 `[front->svc]`
- [x] 退出：记 `[front<-svc]`，含 status / elapsed_ms
- [x] 异常：记 `ERROR [front<-svc]`
- [x] 跳过 `/api/health` / `/ws/*`
- [x] 敏感头过滤：`Authorization` → 截前 8 字符 + `***`

`server/main.py` 注册中间件（`app.add_middleware(RequestLoggingMiddleware)`）

## 3. Commit 3: RPC 客户端日志 ✅ Done

`server/rpc/transport.py`：

- [x] `RPClient.call()` publish 成功 → `[svc->rpc]`
- [x] `RPClient.call()` 收到 reply → `[svc<-rpc]` (含 code/rows)
- [x] `RPClient.call()` timeout/error → `ERROR [svc->rpc]`
- [x] `_listen_replies()` 收到包 → `[svc<-rpc] reply` 标记
- [x] `_listen_pushs()` 收到包 → `[svc<-rpc] push` 标记
- [x] **保留**原 `log.info(...)` 兼容代码（不删，避免破坏依赖该格式的脚本/grep）

## 4. Commit 4: WS 广播日志 ✅ Done

`server/ws/manager.py`：

- [x] `WSManager.broadcast()` 每次 broadcast → `[front<-svc] ws broadcast`
- [x] 客户端断连 → `WARN [front<-svc] ws broadcast` + 移除 dead connection
- [x] 不影响功能，仅加日志

## 5. Commit 5: 测试 + OpenSpec 文档 ✅ Done

- [x] 新增 `server/test_logflow.py`（16 用例）：
  - [x] log_interaction 4 方向各 3 用例（info / warn / error）
  - [x] 4 方向标记常量正确
  - [x] 时间戳格式正确
  - [x] data 截断生效
  - [x] 序列化失败兜底
- [x] `openspec/changes/server-interaction-logging/proposal.md`（已写）
- [x] `openspec/changes/server-interaction-logging/tasks.md`（本文）
- [x] `openspec/changes/server-interaction-logging/spec-deltas/logging.md`（已写）
- [x] `openspec/specs/logging/spec.md`（新建，见 archive 时同步）

## 6. 验收

- [x] 启动 backend，跑 `curl -X POST /api/orders/place -d '{...}'` → 日志含 4 个标记完整 trace
- [x] 触发一次 push（模拟 broker ord_cfm）→ 日志含 `[svc<-rpc] push` + `[front<-svc] ws broadcast`
- [x] pytest 全过（80+ 旧用例 + 16 新用例）
- [x] grep `print(` 在 server/ 仅留 1-2 处必要（lifecycle/seed.py）
- [x] archive 提案

## 勘误

- **design.md 未创建**：代码已实现，设计意图在 `proposal.md` 表达完整（章节 2-4），不另写 design.md。
- **archive 同步方式**：delta spec 不修改现有 spec（新增 logging capability），按 `dev-process-control` spec 中"新增 spec 的正确位置"约定，**手工**在 `openspec/specs/logging/spec.md` 创建（不走 `opsx:archive` 的标准 sync 流程）。