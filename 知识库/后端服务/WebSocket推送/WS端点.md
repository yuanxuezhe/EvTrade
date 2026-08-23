# WS端点

## 对应代码路径

- `server/ws/endpoint.py`（register_ws_endpoint / websocket_endpoint）
- `server/ws/agent_handler.py`（agent_channel 业务消息分发 / send_agent_ready）
- `server/auth/security.py`（decode_token / HERMES_AGENT_TOKEN）
- `server/auth/session.py`（touch）
- `server/repo/quote_snapshots.py`（get_latest_multi / to_dict）
- `server/tables/users.py`（sync_update admin 校验查库）

## 功能概述

`/ws/{channel}` WebSocket 端点：`?token=JWT` 鉴权（也接受固定 hermesagent token 视为 admin），按 channel 接入 ws_manager；单向心跳（客户端 30s ping、服务端只回 pong、10 分钟无消息踢线）+ 订阅协议（subscribe/unsubscribe，仅 quote_update 频道）+ subscribe_ack 立即回最新快照。推送是单向 server→client，客户端其他消息仅作心跳续约。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/ws/endpoint.py | 端点注册、鉴权、心跳 idle_checker、订阅消息处理 |
| server/ws/manager.py | 被调用的 subscribe/unsubscribe/disconnect |

## 核心实现

### 模块常量
- `WS_IDLE_TIMEOUT = 600`（秒，无任意消息最大容忍；测试可 monkey-patch 小值）
- `WS_CHANNELS_REQUIRE_ADMIN = {"sync_update"}`（admin 专属频道，查 DB 实时 role）

### 鉴权（_resolve_ws_user）
1. `decode_token(token)`：合法 JWT → claims。
2. `token == HERMES_AGENT_TOKEN`：返回 `{"sub":"6","id":6,"role":"admin","username":"admin"}`（hermes agent 直连，硬编码 admin 凭证，回收需改代码）。
3. 否则 None → close 4001 "Invalid token"；无 token → close 4001 "Unauthorized"。

sync_update 频道额外用 SessionLocal 查 `users.role`（避免 JWT 缓存旧 role），非 admin → close 4003 "Admin required"。

### 心跳（单向 idle）
- 客户端每 30s 发 `{"type":"ping","ts":...}` → 服务端立即回 `{"type":"pong","ts":<回显>}`，并重置 `last_recv`。
- 服务端**不**主动 ping；`idle_checker` 协程每 30s 检查，`now - last_recv > 600s` → close 4001 "idle timeout"（前端看 4001 跳登录、停止重连）。
- ping handler 调 `session_touch(token)`，WS 活着则 HTTP session 持续续期（touch 幂等，token 不在 cache 时静默返回）。WS 鉴权本身只 decode_token，不调 session.is_valid。
- 非 JSON 消息当心跳续约忽略（last_recv 已刷新）。

### 订阅协议（仅 channel == "quote_update"）

请求（客户端 → 服务端）：
```json
{"type": "subscribe", "stock_codes": ["000001.SZ", "SZ", ""]}
```
`stock_codes` 是 pattern 列表（子串匹配：`''`=全市场、`'SZ'`=市场、`'000001.SZ'`=精确）。

应答 subscribe_ack：
```json
{
  "type": "subscribe_ack", "code": 0, "msg": "",
  "stock_codes": ["000001.Sz"...排序后接受的 pattern],
  "snapshots": {"000001.SZ": {…22 字段快照…}},
  "has_wildcard": true,
  "snapshot_count": 1
}
```
- code 400：stock_codes 非 list；code 429：超 `MAX_SUBSCRIPTIONS_PER_WS=200`（ValueError 文案透传）。
- 快照只对"精确 pattern"（含 `.` 且长度 ≥6，如 `000001.SZ`）查 `quote_snapshots` 表（repo.get_latest_multi 取最新 1 行，无记录不返）；宽泛 pattern（SZ/SH/''/片段）靠后续 tick 推送，`has_wildcard` 告知前端。
- 快照查询、订阅诊断日志（写 `%TEMP%/ws_subscribes.log`，用 tempfile.gettempdir 兼容 Windows）均 try/except 包裹，失败绝不打断连接。
- 事件日志内容：ts、remote、accepted、sub_total（subscription_index 大小）、active（quote_update 连接数）。

unsubscribe：
```json
请求 {"type":"unsubscribe","stock_codes":[...]}
应答 {"type":"unsubscribe_ack","code":0,"msg":"","stock_codes":[已移除的...]}
```

### 主循环与清理
`while True: receive_text()` → 刷新 last_recv → json 解析 → 分发 ping / subscribe / unsubscribe；其他消息忽略。finally 中 cancel idle_task + `ws_manager.disconnect(websocket, channel)`（清订阅索引）。

### agent_channel 的 ready 语义（REQ-ARCH-008，2026-08-23 修复）

- `channel == "agent_channel"`（AI 助手，第 6 个 channel）：连接建立后（`ws_manager.connect` 之后）**立即**推 `{"type":"ready","session_id":...}`（`send_agent_ready`），不等第一条 `user_message`。
- **为什么必须连上即发**：前端 `AgentWSClient.connect()` 以收到 `ready` 事件为连接成功标志，在此之前**不会**发出首条 `user_message`。若后端等第一条 `user_message` 才发 `ready` → 前后端互相等待，首条消息永远发不出去（实际故障 2026-08-23「AI 对话框点击发送没用」）。
- 业务消息（`user_message` / `confirmation`）分发到 `server/ws/agent_handler.handle_agent_channel_message`；该 handler **不**再重复推 `ready`。
- `session_id` 为连接级标识（`u<user_id>-<uuid>` 前缀）；hermes run 的 run session 在 `_handle_user_message` 内另行生成。

### 注册方式
`register_ws_endpoint(app)` 在 main.py 的 startup 之前调用，内部 `@app.websocket("/ws/{channel}")` 装饰器注册；端点闭包绑定模块级 ws_manager 单例。

## 依赖关系
- 上游：前端 /ws/{channel}?token=...、main.py 注册
- 下游：auth/security、auth/session、ws_manager、repo/quote_snapshots、tables/users（sync_update 校验）

## 修改指南
- **agent_channel 的 ready 必须连上即发，不能挪到第一条 user_message**（前后端互相等待死锁，2026-08-23 实际故障）。改 `_handle_user_message` 时不要加回 `ready` 推送。
- 新增客户端消息类型：在主循环 `msg_type` 分支追加；保持"失败只 send 错误 ack、不打断连接"原则（一处未捕获异常曾导致连接静默死亡无限重连）。
- 新增 admin 频道：加入 `WS_CHANNELS_REQUIRE_ADMIN`。
- 调整 idle 阈值：改 `WS_IDLE_TIMEOUT`（与前端 30s ping 周期配套）。
- 鉴权策略变更注意 hermesagent 硬编码 token 的回收风险（需改代码下线）。
