# Server 端交互日志（front ↔ svc ↔ rpc 全链路）

## 1. Why

当前 server 日志散落各处（`transport.py` / `push_handler_*.py` / `main.py`），
排查问题时需要：
- 关联前端某次 HTTP 请求触发了哪些 RPC 调用
- 关联某次 RPC 应答是否被前端实际收到
- 复盘 push 链路（broker → server → DB → WS 广播）
- 抓一次完整 trace 看数据流转

但目前日志：
- 格式不统一（`RPClient.call >>>` / `RPClient.push <<<` / `RPClient <<< reply` 等多种箭头）
- 无统一时间戳格式（混用 ISO 8601 / 紧凑 14 位 / `time.time()`）
- HTTP 请求体 / 响应体几乎不打印
- WS 广播无日志
- 错误日志混在 info 里，不易过滤

**根因**：v5 重构、v6 order-pk、v7 user_def、v8 cancelled-volume、v9 cancel-row、v10 field-align 各阶段只补局部，
无人统一规划日志体系。

## 2. What

### 2.1 统一方向标记（4 个）

| 标记 | 含义 | 触发位置 |
|---|---|---|
| `[front->svc]` | 前端 HTTP 请求 → server | FastAPI middleware (请求阶段) |
| `[svc->rpc]` | server 调 broker (发送 REQ) | `RPClient.call()` publish 前 |
| `[svc<-rpc]` | server 收到 broker 消息 (REPLY 或 PUSH) | `_listen_replies` / `_listen_pushs` 收到包时 |
| `[front<-svc]` | server → 前端 (HTTP 响应 / WS 广播) | FastAPI middleware (响应阶段) / `ws_manager.broadcast` |

每条日志格式：
```
[2026-06-25 10:30:00.123] [front->svc] POST /api/orders/place body={"stock_code":"600030.SH",...} (3.2ms)
[2026-06-25 10:30:00.456] [svc->rpc] call func=qry_ast msg_id=abc-123 values={} (0.1ms)
[2026-06-25 10:30:00.580] [svc<-rpc] reply func=qry_ast msg_id=abc-123 code=00000 rows=1 (124ms)
[2026-06-25 10:30:00.581] [front<-svc] 200 GET /api/asset body={...} (125ms)
[2026-06-25 10:30:01.200] [svc<-rpc] push func=ord_cfm wire_len=234 (push q)
[2026-06-25 10:30:01.201] [front<-svc] ws broadcast channel=order_update data={...} (push)
```

### 2.2 实施细节

#### 2.2.1 工具模块 `server/utils/logflow.py`（新增）

```python
def log_interaction(direction: str, summary: str, *,
                    data: dict = None, elapsed_ms: float = None,
                    level: str = "info") -> None:
    """统一日志入口 (direction ∈ front->svc / svc->rpc / svc<-rpc / front<-svc)
    
    格式: [YYYY-MM-DD HH:MM:SS.fff] [<direction>] <summary> [(<elapsed_ms>ms)]
          └─ 当 data 不为空时, 缩进 2 字符换行打印
    """
```

特性：
- 单一函数，4 个方向复用
- 自动处理序列化（dict/list → JSON, 截断超长）
- 失败安全（logging.exception 捕获，不影响业务）

#### 2.2.2 FastAPI 中间件（[server/main.py](server/main.py) 新增）

注册 `RequestLoggingMiddleware`：
- 请求进入：记 `[front->svc] <METHOD> <path> body=... query=...`
- 响应返回：记 `[front<-svc] <status> <METHOD> <path> body=... (<elapsed>ms)`
- 异常路径：记 `ERROR [front<-svc] <METHOD> <path> <exc_type>: <msg>`
- 过滤敏感头（`Authorization` 只截前 8 字符 + `***`）
- 跳过 `/api/health` / `/ws/*`（WS 由单独日志管）
- body 截断：单条 4KB 上限（避免日志爆炸）

#### 2.2.3 RPC 客户端（[server/rpc/transport.py](server/rpc/transport.py) 改造）

- `RPClient.call()`:
  - publish 成功 → `[svc->rpc] call func=... msg_id=... values={...}`
  - 收到 reply 解析成功 → `[svc<-rpc] reply func=... msg_id=... code=... rows=... (<elapsed>ms)`
  - 超时/异常 → `ERROR [svc->rpc] TIMEOUT func=... msg_id=... (<elapsed>ms)`
- `_listen_replies()` 收到包 → 调 `_log_svc_from_rpc(direction='reply', ...)`
- `_listen_pushs()` 收到包 → 调 `_log_svc_from_rpc(direction='push', ...)`
- **保留**原 `log.info("RPClient.call >>> ...")` 兼容（用 [REQ-LOG-002] 标注）

#### 2.2.4 WS 广播（[server/ws/manager.py](server/ws/manager.py) 改造）

- `WSManager.broadcast()` 改为每次 broadcast 记一条 `[front<-svc] ws broadcast channel=... clients=N data={...}`
- 失败/断连 → `WARN [front<-svc] ws broadcast channel=... 1 client disconnected`

#### 2.2.5 错误日志增强

- 所有 catch 块必须 `log.exception()` 或 `log.error()`（不能 print 替代）
- 业务异常（HTTPException 4xx）→ `WARN` 级别
- 系统异常（5xx / 内部错误）→ `ERROR` 级别

### 2.3 不在范围

- 日志聚合 / ELK 接入（当前 stdout + 文件已够用）
- 日志级别动态切换（沿用 Python `logging` 配置）
- 性能埋点（elapsed_ms 仅做轻量记录，不做聚合分析）
- 行情 hqserver 日志（走独立端口 :8765，独立进程）

## 3. 影响面

**新增文件**：
- `server/utils/__init__.py`（新建 utils 包）
- `server/utils/logflow.py`（统一日志入口）
- `server/middleware/__init__.py`（新建 middleware 包，备未来扩展）
- `server/middleware/request_logging.py`（HTTP 请求/响应日志中间件）
- `server/test_logflow.py`（16 用例覆盖 4 方向 + 错误路径）
- `openspec/changes/server-interaction-logging/proposal.md`（本文件）
- `openspec/changes/server-interaction-logging/tasks.md`
- `openspec/changes/server-interaction-logging/spec-deltas/data-model.md`（暂不需要，可省）
- `openspec/changes/server-interaction-logging/spec-deltas/logging.md`（新增 spec）

**修改文件**：
- `server/main.py` — 注册中间件
- `server/rpc/transport.py` — call/监听处加日志
- `server/ws/manager.py` — broadcast 加日志
- `server/api/order_place.py` — 已有 print/log 替换为新入口（可选）

**测试影响**：
- 现有 80+ 测试大部分不依赖日志格式（断言 API 响应而非日志），不应破
- 需新增 1 个 test_logflow.py（测试 logflow 函数本身）

## 4. Spec Deltas

`logging/spec.md`（新增）：
- REQ-LOG-001: 4 个方向标记（[front->svc] / [svc->rpc] / [svc<-rpc] / [front<-svc]）
- REQ-LOG-002: 时间戳格式 "YYYY-MM-DD HH:MM:SS.fff" (复用 v10 format_ts)
- REQ-LOG-003: 4 类交互都必须打日志
- REQ-LOG-004: body 截断 4KB 上限
- REQ-LOG-005: 错误日志必须用 log.exception 或 log.error

## 5. Tasks

见 `tasks.md`。
