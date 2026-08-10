# spec-delta: dev-process-control — backend uvicorn WS keepalive ping 探测阈值

## Requirement: backend uvicorn WS keepalive ping 探测阈值（ws-keepalive-ping-slack 2026-08-10）

The system SHALL launch the backend (port 8000) uvicorn with WebSocket keepalive ping settings that tolerate realistic client pong latency:

- `--ws-ping-interval 20`（服务端每 20s 发 native WS ping）
- `--ws-ping-timeout 60`（pong 容忍窗口 60s，而非 uvicorn 默认 20s）

**Why**：uvicorn 默认 `ws_ping_timeout=20s` 下，浏览器 quote_update 全市场订阅（`''`，≈1260 帧/s）时渲染主线程 backpressure 导致 native pong 延迟 ~20-30s，服务端探测误断 `1011 keepalive ping timeout`，前端每 ~2.3min 重连一次。`hq/hqserver.py` 2026-07-09 已对同款 bug 设 `ping_interval=15, ping_timeout=60`，本次对齐 backend。实测：不回 pong 时默认 40s 被关，`timeout=60` 下 80s 才关；正常自动 pong 客户端 140s 稳定，证明服务器/代理/数据均正常。

**How to apply**：在 `scripts/evctl.py` backend Service 的 uvicorn 命令行显式加两个 flag + 注释；任何其他 backend 启动方式（如生产部署）也应沿用相同或更宽松的 `ws_ping_timeout`。

#### Scenario: 浏览器 pong 延迟 20-30s 不被误断

- **GIVEN** backend 以 `--ws-ping-timeout 60` 启动，浏览器 quote_update 全市场订阅
- **WHEN** 浏览器渲染 backpressure 使 native pong 延迟 ~20-30s
- **THEN** 连接 MUST 保持存活（60s 窗口 > 延迟），不再 `1011 keepalive ping timeout`

#### Scenario: 真正死连接仍被探测踢掉

- **GIVEN** backend 以 `--ws-ping-timeout 60` 启动
- **WHEN** 客户端网络真断且 60s 内完全无 pong
- **THEN** 服务端 MUST 仍关闭该连接（探测功能保留），并触发前端既有重连/兜底

#### Scenario: 启动参数生效

- **GIVEN** `evctl.py restart backend`
- **WHEN** 裸 socket 客户端建立 WS 后故意不回 pong
- **THEN** 连接在 `20s ping + 60s timeout ≈ 80s` 才被服务端关闭（而非默认的 40s）

## Cross References

- `dev-process-control/spec.md`「单一 Python 入口」—— backend uvicorn 命令由 evctl.py 管理
- `ws-protocol/spec.md` REQ-WS-003 双向心跳 —— 应用层 30s JSON ping/pong；本 Requirement 是**传输层** uvicorn native ping，两者互补
- 触发来源：诊断结论（浏览器全市场订阅 pong 延迟 → uvicorn 默认探测误断 1011），见本 change `proposal.md`
