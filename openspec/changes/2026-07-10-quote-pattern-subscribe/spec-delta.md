# Spec Delta — 2026-07-10 quote-pattern-subscribe

## MODIFIED

### REQ-QUOTE-005: 后端 WS 接入（strategy_trade）

原行为（v15 quote-snapshot-subscribe）:
- 客户端 `{type:"subscribe", stock_codes:["000001.SZ"]}` → 订阅该具体 code
- tick 推送时 `subscription_index.get(code)` O(1) 精确查 ws

升级后（v16 quote-pattern-subscribe, 2026-07-10）:
- 客户端 `{type:"subscribe", stock_codes:["000001.SZ", "SZ", ""]}` 三种 pattern 同时生效
- 精确 pattern → ack 立即返 snapshot
- 宽泛 pattern (`SZ`/`SH`/`数字前缀`/``) → `has_wildcard=true`, 后续 tick 走子串匹配推送
- tick 推送时遍历所有 pattern O(P), 子串匹配命中即合并 ws 集合

### Scenario: subscribe_ack 字段增强

- **NEW FIELD** `has_wildcard: bool` — 订阅里是否有宽泛 pattern
- **NEW FIELD** `snapshot_count: int` — 从 DB 读到的精确 pattern snapshot 数
- 已有字段 `snapshots: Dict[code, dict]` 仅包含精确 pattern 的 snapshot