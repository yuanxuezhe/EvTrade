# Fix: ws-protocol spec 漏登 `sync_update` channel（admin-only）

> 用户拍板 2026-08-27：按 P0 顺序修第三刀。Why 详见 `openspec/specs/KNOWLEDGE_GAP_AUDIT.md` GAP-002 + 2026-08-27 实测补漏。

## Why

`openspec/specs/ws-protocol/spec.md` 是 WebSocket 推送协议的**单一事实源**。当前 spec 已部分修订（v117 起登记了 `system_update` + `task_progress_update`），但**漏登** `sync_update` channel（admin-only）：

- **实测调用方**：`server/services/sync/manager.py:118` 调 `ws_manager.broadcast("sync_update", payload)` 推 stocks 同步进度
- **admin-only**：`server/ws/endpoint.py:45` `WS_CHANNELS_REQUIRE_ADMIN = {"sync_update"}`（其他 channel 不需要 admin 角色）
- **spec 现状**：REQ-WS-001 表里只列 6 个 channel，没有 sync_update；REQ-WS-002 payload 协议也没列 `sync_update` channel 名
- **客户端是否订阅**：尚未发现前端订阅此 channel，但 WS endpoint 已暴露，前端 admin 后台集成时可能用到

**影响**：
- AI 助手按 spec 实现 admin 后台 → 漏 `sync_update` 频道，前端拿不到同步进度
- spec 与代码不一致（spec 6 channel vs 代码 7+ channel）

## What

**单 commit 单目的**（按 v6 规范）：纯文档修复，零代码改动。

1. **修正 L5 顶部声明**：6 → 7 channel（增加 sync_update）
2. **修正 REQ-WS-001 表**：新增 `sync_update` 行（admin-only，stocks 同步进度）
3. **修正 REQ-WS-002 payload 协议**：`channel` 列表增加 `sync_update`
4. **修正 S-WS-001 启动连接 6 channel** → 7 channel（admin 路径单独连）

## 不做什么

- 不动 `server/ws/endpoint.py`（已正确实现 admin gate）
- 不动 `server/ws/manager.py`（broadcast 已存在）
- 不动前端 store（admin 后台未集成此 channel）
- 不动 DB（用户硬规则）

## 验证 (v6 完成自查)

- [ ] `grep -cE "\| \`[a-z_]+_update\` \|" openspec/specs/ws-protocol/spec.md` → 7 行（REQ-WS-001 表）
- [ ] `grep -cE "\`[a-z_]+_update\`" openspec/specs/ws-protocol/spec.md` → 8 命中（channel 名 in 7 行表 + 1 行 enum）
- [ ] `git diff --stat` 显示改动**仅** `openspec/specs/ws-protocol/spec.md`
- [ ] commit message: `docs(openspec): ws-protocol 补 sync_update channel (admin-only) (GAP-002 + 2026-08-27 实测)`
- [ ] 归档：`mv openspec/changes/2026-08-27-ws-protocol-sync-channel openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- 不动 MySQL 任何表/列/行
- 不 drop / truncate / delete from
- 不重建 schema、不跑 `sync_schema.py apply`
