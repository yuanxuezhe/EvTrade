# 2026-08-10-ws-keepalive-ping-slack — 放宽 backend uvicorn WS keepalive ping 探测阈值

## Why

浏览器 WS 每 ~2.3min 断开重连（quote_update 通道），页面走公网时伴随 502（openresty）。实测定位：

- **探测逻辑本体**：backend uvicorn 以默认 `ws_ping_interval=20s / ws_ping_timeout=20s` 启动（`evctl.py` 未覆盖）。服务端每 20s 发 native WS ping，20s 内收不到 pong → 关连接 `1011 "keepalive ping timeout"`。
- **为什么浏览器中招**：quote_update 全市场订阅（`''`）下，浏览器每 ~140s 收 ~176,810 帧（≈1260 帧/s），渲染主线程处理 quote.js `update()` 跟不上 → 浏览器对 socket 施加 backpressure → native ping/pong 处理被推迟 → pong 超 20s 没回 → 探测误断。
- **证据**：裸 socket 客户端不回 pong → 默认配置 40s 被关（1011）；同一客户端换成 `ws_ping_timeout=60` → 80s 才关（3 倍余量）。正常自动 pong 的 Python 客户端走相同 vite→backend 路径、订阅相同全市场 → 140s 存活（收 176,810 帧），证明服务器/vite/数据均正常，问题只在探测阈值太紧。
- **先例**：`hq/hqserver.py` 2026-07-09 已踩同坑并修（`ping_interval=15, ping_timeout=60`，注释："ping_interval=20/ping_timeout=20 默认值在 tick 短暂停顿时被误判断连(1011)"）。本次是对齐该先例到 backend uvicorn。

## What Changes

### backend uvicorn WS keepalive 探测阈值放宽（`scripts/evctl.py`）

`evctl.py` backend 服务启动命令加：

```
--ws-ping-interval 20 --ws-ping-timeout 60
```

- 保留服务端探测（不死连接仍会被踢），仅把 pong 容忍窗口从 20s 放宽到 60s
- 与 hqserver `ping_timeout=60` 对齐；浏览器 pong 延迟 ~20-30s 时不再被误断
- 附中文注释说明 why（含诊断结论 + hqserver 先例）

**不在范围**：
- ❌ 不改 WS 协议 / 前端代码 / quote.js（用户已确认"和行情没关系"，数据链路本身正常）
- ❌ 不关掉 uvicorn native ping（`--ws-ping-interval 0`）——应用层已有 30s JSON ping + 300s/600s 兜底，但"探测处理正常"应保留探测本身
- ❌ 不改远程 openresty（外部设施，本仓库无配置；502 由重连风暴缓解后自然减少）

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 知识库 | `openspec/changes/2026-08-10-ws-keepalive-ping-slack/` | proposal + spec-delta + tasks |
| 知识库 | `openspec/specs/dev-process-control/spec.md` | 新增 Requirement：backend uvicorn WS keepalive 探测阈值 |
| 脚本 | `scripts/evctl.py` | backend uvicorn 命令加 `--ws-ping-interval 20 --ws-ping-timeout 60` + 注释 |

## 落地约束

- ✅ 与 OpenSpec 工作流一致：先补 spec → 再写代码
- ✅ 不新增依赖 / 不引入新模块，改动收敛在 evctl.py 一处
- ✅ 验证：`evctl.py restart backend` 后裸 socket 不回 pong 复测 → 应 ~80s 才关（原 40s）
- ✅ 不自动 push（用户硬性偏好）
