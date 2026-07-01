# push delta — status 推送契约补注

## MODIFIED Requirements

### REQ-PUSH-005: status 字段契约 — 双层语义说明

**Before:**
- 委托 `status` 字段语义单一（= 本地推断终态码）

**After:**
- **WS payload 层**：broker 原始 `status` 透传（`server/rpc/client.py:_listen_pushs:236` `enriched_row = {**row, "trd_date": ...}`，保留 `row.status` 原值）
- **DB 持久化层**：后端 `_infer_order_status` 推断后写 `Order.status`（commit 时覆盖 broker 原始值）
- **前端展示层**：以本地 `inferOrderStatus` 防御性重算为准（详见 `frontend/spec.md` REQ-FE-006）
- 三层语义不同源：WS 透传 broker / DB 存推断值 / 视图重算重防御

**Why:**
- broker ord_cfm `status="50"`（broker 端"已报"），与本地 50=部成 语义不一致
- 三层解耦允许：协议层不变（broker 协议越界不动）、DB 层安全（保证查询一致）、视图层鲁棒（防 broker 协议漂移）

## Cross-References

- `frontend/spec.md` REQ-FE-006（前端防御性重算契约）
- 实施 commit: `a6b4f76`（原始 fix）/ `640419a`
