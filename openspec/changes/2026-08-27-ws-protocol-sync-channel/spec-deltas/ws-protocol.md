# ws-protocol — Spec Delta (2026-08-27)

## 修改类型

MODIFIED — 补登 `sync_update` channel（admin-only）+ 修正顶部 channel 数 6 → 7

## 变更内容

### § L5 顶部 channel 数声明

**Before**: "6 个 WebSocket channel"

**After**: "7 个 WebSocket channel"

### § §Purpose 段 — 新增 1 行 channel 描述

**新增**:
- 1 个**同步进度 channel**（`sync_update`）走**后端**，admin-only，由 `server/services/sync/manager.py` 推送 stocks 同步进度（仅 admin 角色可订阅）

### § REQ-WS-001 表 — 新增 1 行

**新增**:
| `sync_update` | `{proto}://{host}/ws/sync_update?token={jwt}` | JWT (query) + role=admin | `server/services/sync/manager.py` 推 stocks 同步进度 |

### § REQ-WS-002 payload 协议 — `channel` enum 增加 `sync_update`

**Before**: `"channel": "order_update" | "trade_update" | "position_update" | "asset_update" | "quote_update" | "system_update" | "task_progress_update"`

**After**: `"channel": "order_update" | "trade_update" | "position_update" | "asset_update" | "quote_update" | "system_update" | "task_progress_update" | "sync_update"`

### § S-WS-001 启动连接段

**Before**: "Then 6 个 channel 各自创建 WebSocket"

**After**: "Then 7 个 channel 各自创建 WebSocket（admin 角色多连 `sync_update`）"

## 影响面

- spec ↔ 代码一致性 +1：ws-protocol spec 现在覆盖所有 7 个真实 channel
- 后续 admin 后台集成 sync_update 时有 spec 依据
- 关闭 GAP-002 audit

## 不修改

- 不动 `server/ws/endpoint.py`（已正确实现 admin gate at WS_CHANNELS_REQUIRE_ADMIN）
- 不动 `server/ws/manager.py`（broadcast 已存在）
- 不动 DB（用户硬规则 2026-08-27）
