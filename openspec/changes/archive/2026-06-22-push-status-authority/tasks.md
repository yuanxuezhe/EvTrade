# Tasks — push-status-authority

- [x] T1: `client/src/stores/holdings.js` 加 `_recomputeStatus` helper（commit `a6b4f76` + 重构至 `holdings_helpers.js::recomputeStatus`，commit `73fc901`）
- [x] T2: bootstrap + refresh 列表赋值用 `.map(_recomputeStatus)`（commit `640419a` + `bcf5811` refactor `holdings_apply_results.js`）
- [x] T3: `applyOrderPush` 改用 `_recomputeStatus(row)`，**不传 brokerStatus**（commit `a6b4f76`）
- [x] T4: 改 `openspec/specs/frontend/spec.md` REQ-FE-006
- [x] T5: 改 `openspec/specs/push/spec.md` REQ-PUSH-005 加注
- [x] T6: 用户端验证：traded_volume=0 → 显示"已报"
- [x] T7: commit
