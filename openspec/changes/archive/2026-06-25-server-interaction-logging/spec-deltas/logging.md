# logging spec — Server 端交互日志（新增）

## ADDED Requirements

### REQ-LOG-001: 4 个方向标记

所有 server 端交互日志必须使用以下 4 个方向标记之一：

| 标记 | 含义 | 触发位置 |
|---|---|---|
| `[front->svc]` | 前端 HTTP 请求 → server | FastAPI middleware (请求阶段) |
| `[svc->rpc]` | server 调 broker (发送 REQ) | `RPClient.call()` publish 前 |
| `[svc<-rpc]` | server 收到 broker 消息 (REPLY 或 PUSH) | `_listen_replies` / `_listen_pushs` 收到包时 |
| `[front<-svc]` | server → 前端 (HTTP 响应 / WS 广播) | FastAPI middleware (响应阶段) / `ws_manager.broadcast` |

每条日志**必须**包含方向标记，缺一不可。

### REQ-LOG-002: 统一时间戳格式

所有交互日志时间戳格式：**`YYYY-MM-DD HH:MM:SS.fff`** (23 字符，毫秒精度)
- 复用 v10 `format_ts()` / `format_db_dt()` 工具
- 业务时间戳用本地时间，系统时间戳用 UTC
- 禁止使用 `isoformat()` / `time.time()` / 紧凑 14 位串 等其他格式

### REQ-LOG-003: 4 类交互必须打日志

| 场景 | 标记 | 数据 |
|---|---|---|
| 任意 HTTP 请求 | `[front->svc]` | method / path / query / body |
| 任意 HTTP 响应 | `[front<-svc]` | status / method / path / body / elapsed_ms |
| 任意 RPC 请求 (publish) | `[svc->rpc]` | func / msg_id / values |
| 任意 RPC 应答 (receive reply) | `[svc<-rpc]` | func / msg_id / code / rows / elapsed_ms |
| 任意 broker 推送 (receive push) | `[svc<-rpc]` | func / wire_len |
| 任意 WS 广播 | `[front<-svc]` | channel / clients / data |

### REQ-LOG-004: body 截断

为防止日志爆炸：
- HTTP request/response body 截断 **4KB**（单条上限）
- RPC values / rows 截断 **2KB**（单条上限）
- 截断后追加 `[truncated, total=XX bytes]`

### REQ-LOG-005: 错误日志规范

- 系统异常（5xx / 内部错误）→ `log.exception()` 自动带 stack trace
- 业务异常（HTTPException 4xx / RPC code != 0）→ `log.warning()` 或 `log.error()`（按严重度）
- **禁止**用 `print()` 替代 logging（lifecycle/seed.py 的初始配置 print 除外）

### REQ-LOG-006: 统一入口

所有交互日志必须通过 `server.utils.logflow.log_interaction()` 入口打印，**禁止**直接 `log.info("[front->svc] ...")` 拼接（保证格式一致 + 未来易扩展）。

## 勘误历史

- 2026-06-25 新增：v10 field-align 实施中发现排查 RPC 推送链路时日志散落、方向不明、格式不统一，提议统一
