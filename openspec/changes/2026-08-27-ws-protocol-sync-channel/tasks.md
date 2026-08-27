# Tasks: ws-protocol-sync-channel (2026-08-27)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 本 change 只有 **1 个 commit**（纯文档）。

## Commit 拆解

- [ ] **commit 1**: `docs(openspec): ws-protocol 补 sync_update channel (admin-only) (GAP-002 + 2026-08-27 实测)`
  - 修正 L5 顶部："6 个 WebSocket channel" → "7 个 WebSocket channel"
  - 修正 REQ-WS-001 表：新增 `sync_update` 行（admin-only，stocks 同步进度）
  - 修正 REQ-WS-002 payload 协议：`channel` enum 列表增加 `sync_update`
  - 修正 S-WS-001 启动连接段：6 channel → 7 channel（admin 路径）

## 验证 (v6 完成自查)

- [ ] `grep -cE "\| \`[a-z_]+_update\` \|" openspec/specs/ws-protocol/spec.md` → 7
- [ ] `git diff --stat` 显示改动**仅** `openspec/specs/ws-protocol/spec.md`
- [ ] 归档：`mv openspec/changes/2026-08-27-ws-protocol-sync-channel openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] 不 drop / truncate / delete from
