# Tasks — 放宽 backend uvicorn WS keepalive ping 探测阈值（ws-keepalive-ping-slack）

> 先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-delta：`dev-process-control.md`（Requirement: backend uvicorn WS keepalive 探测阈值）
- [x] 1.3 主 spec 落地：`openspec/specs/dev-process-control/spec.md` 新增 Requirement
- [x] 1.4 commit: `docs(spec): backend uvicorn ws_ping_timeout 60 探测阈值 (ws-keepalive-ping-slack)` `48d7a70`

## 2 — evctl.py 启动参数

- [x] 2.1 `scripts/evctl.py` backend uvicorn 命令加 `--ws-ping-interval 20 --ws-ping-timeout 60` + 中文注释
- [x] 2.2 commit: `feat(evctl): backend uvicorn ws_ping_timeout 60 防浏览器 pong 延迟误断 (ws-keepalive-ping-slack)` `21c2e5e`

## 3 — 验证

- [x] 3.1 `evctl.py restart backend`，确认新参数生效（[OK] backend healthy）
- [x] 3.2 裸 socket 不回 pong 复测：直连 backend 20s ping + 60s timeout → **80s 才关**（1011 keepalive ping timeout），原默认 40s。新参数已生效
- [ ] 3.3 观察浏览器是否停止每 ~2.3min 重连（ws_subscribes.log 不再每 ~140s 新增）—— 当前无活跃浏览器连接（system_update clients=0），待浏览器回到全市场订阅后观察
