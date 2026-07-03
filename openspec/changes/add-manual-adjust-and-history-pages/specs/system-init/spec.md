## ADDED Requirements

### Requirement: day-init reconcile 全表覆盖语义（v12 强化）

`do_reconcile` MUST 把 `positions` / `assets` 表**全表覆盖**为 broker 端权威数据。manual adjust 值在 reconcile 后会被全表覆盖抹掉 —— 这是预期的、不持久化的语义。

#### Scenario: reconcile 覆盖 manual adjust

- **WHEN** admin 上午 10:00 调平 `Position.vol += 100`（broker 期权行权但 trd_cfm 未来得及推）
- **AND** admin 下午 14:00 触发手动 `do_reconcile`（极端场景）
- **THEN** `Position.vol` 被 broker 真实值覆盖，100 delta 丢失
- **AND** UI 提示 admin"reconcile 已执行，原 manual adjust 已按柜台数据全表覆盖"

#### Scenario: 调平不影响 sys_status

- **WHEN** admin 调平 `Position.vol += 100`
- **THEN** `sys_status` 表不变（active 状态不受影响）
- **AND** `reconcile_report` 表不写（用户明确不留 audit row）

### Requirement: reconcile 不会自动叠加 manual adjust（v12）

`do_reconcile` MUST NOT 把 manual adjust 值叠加到 broker 全量结果之上。manual adjust 是 reconcile 之间的临时补丁。

#### Scenario: reconcile 清零 manual 标记

- **WHEN** `do_reconcile` 执行
- **THEN** `Position.synced_from = "rpc_full"`（覆盖原 `"manual"`）
- **AND** `Asset.synced_from = "rpc_full"`

#### Scenario: UI reconcile 后允许再次手动调平

- **WHEN** reconcile 后 broker 仍未对账的偏差仍存在
- **THEN** admin 可以再次调平
- **AND** 再次调平后 `synced_from = "manual"` 取代 `"rpc_full"`
- **AND** 下次 reconcile 又会被覆盖 — 形成自然循环
