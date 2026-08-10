# Tasks — reconcile_report JSON 列 TEXT→LONGTEXT（修复 init 500）

> 先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-delta：`data-model.md`（REQ-DM-041）
- [x] 1.3 主 spec 落地：`openspec/specs/data-model/spec.md` reconcile_report 5 JSON 列 `Text` → `LONGTEXT`
- [x] 1.4 commit: `docs(spec): reconcile_report JSON 快照列 Text→LONGTEXT (reconcile-report-json-longtext)` `63934a6`

## 2 — DB 迁移

- [x] 2.1 新增 `server/migrations/2026-08-10-reconcile-report-json-longtext.py`：ALTER 5 列 → LONGTEXT（幂等：仅 text/mediumtext 时 MODIFY）+ 验证打印列类型
- [x] 2.2 执行迁移 → 确认 5 列变为 longtext
- [x] 2.3 commit: `feat(migrations): reconcile_report JSON 列扩容 LONGTEXT 修复 init 500 (reconcile-report-json-longtext)` `78c8a98`

## 3 — 验证

- [x] 3.1 `py_compile` 迁移脚本
- [x] 3.2 回归：push 测试 7/7 通过 + 100KB 写入 local_positions_json 成功（OVERFLOW_TEST_OK）
- [ ] 3.3 用户实测：重试 POST /api/admin/sys-status/init → 200（不再 500）
