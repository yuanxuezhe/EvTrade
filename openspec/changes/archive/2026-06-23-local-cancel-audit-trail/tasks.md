# Tasks — local-cancel-audit-trail

## 实施 commits
- `4bf640b` feat(orders): 加 order_flag + trade_type 字段 (v9 撤单流水基础)
- `cfc16ee` feat(orders): DELETE 端点重写 - 本地代理 cancel-row + cancel-trade
- `44b61a5` test(push) v9 cancel-row 隔离测试
- `ae17415` feat(client) v9 撤单审计前端展示

## 任务列表

- [x] T1: `server/models/orm.py` 加 `order_flag / trade_type` — `4bf640b`
- [x] T2: `server/api/orders.py` Pydantic schema + inline builder — `4bf640b`, `cfc16ee`
- [x] T3: `server/api/trades.py` Pydantic schema — `4bf640b`
- [x] T4: `server/api/orders.py` DELETE 端点重写（5 步）— `cfc16ee`
- [x] T5: `migrate_cancel_flag.py` 脚本（idempotent ALTER）— `4bf640b`，脚本已落到 `openspec/changes/2026-06-23-local-cancel-audit-trail/migrations/`
- [x] T6: `server/test_orders_api.py` 测试（4 改 + 4 增）— `cfc16ee`
- [x] T7: `server/test_push_handlers.py` 1 增测试 — `44b61a5`
- [x] T8: `client/src/stores/holdings.js` 短路 + 透传 — `ae17415`
- [x] T9: `client/src/views/Trade.vue` 类型列 + 过滤 + 守卫 — `ae17415`
- [x] T10: `client/src/views/Orders.vue` + `Trades.vue` 类型列 + 计数排除 — `ae17415`
- [x] T11: 4 个 spec 文件更新（已应用）：
  - `data-model/spec.md:55,75-77,102,114-116` — order_flag / trade_type schema + 业务规则
  - `trading/spec.md:62-76` — DELETE 端点 5 步契约
  - `push/spec.md:105-113` — REQ-PUSH-008 broker ord_cfm 不匹配 cancel-row
  - `frontend/spec.md:171-193` — REQ-FE-009.5 cancel-row 短路 + 视图契约
- [x] T12: `migrate_cancel_flag.py` + 重启后端 — backend 当前 pid 38660 已运行；schema 在生产 DB 已落
- [x] T13: 端到端验证 — `trade_update` payload 含 `trade_type=1` + 前端 holdings 短路 cancel-row 实测正常
- [x] T14: `git push origin master` — 已推送 `cfc16ee / ae17415 / 4bf640b / 44b61a5`

## 验证记录

- 后端 orm.py：Order.order_flag / Trade.trade_type 字段已加，迁移幂等
- DELETE 端点 5 步流程已实施（pre-check → INSERT cancel-row → RPC → 分支 → WS broadcast）
- 前端 holdings.applyOrderPush 短路 cancel-row
- 视图层：Trade/Orders/Trades 三页均加「类型」列 + 守卫 + 计数排除

## 备注

- pytest 整体跑通被 `Base 重复注册` 阻塞（已在 `conftest.py` 修复）；44b61a5 测试本身在 conftest 修复后可通过