# Tasks — 放宽 backend uvicorn WS keepalive ping 探测阈值（ws-keepalive-ping-slack）

> 先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-delta：`dev-process-control.md`（Requirement: backend uvicorn WS keepalive 探测阈值）
- [ ] 1.3 主 spec 落地：`openspec/specs/dev-process-control/spec.md` 新增 Requirement
- [ ] 1.4 commit: `docs(spec): backend uvicorn ws_ping_timeout 60 探测阈值 (ws-keepalive-ping-slack)`

## 2 — evctl.py 启动参数

- [ ] 2.1 `scripts/evctl.py` backend uvicorn 命令加 `--ws-ping-interval 20 --ws-ping-timeout 60` + 中文注释
- [ ] 2.2 commit: `feat(evctl): backend uvicorn ws_ping_timeout 60 防浏览器 pong 延迟误断 (ws-keepalive-ping-slack)`

## 3 — 验证

- [ ] 3.1 `evctl.py restart backend`，确认新参数生效
- [ ] 3.2 裸 socket 不回 pong 复测：应 ~80s 才关（原默认 40s），直连 + vite 各测一次
- [ ] 3.3 观察浏览器是否停止每 ~2.3min 重连（ws_subscribes.log 不再每 ~140s 新增）
