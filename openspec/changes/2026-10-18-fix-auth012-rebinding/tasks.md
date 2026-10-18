# Tasks: fix-auth012-rebinding

## C1 — OpenSpec change 工件（1 commit）

- [x] 立项：`openspec/changes/2026-10-18-fix-auth012-rebinding/proposal.md`
- [x] tasks.md（本文件）
- [x] spec-deltas/auth.md（diff 草案：heartbeat 段 012 → 015 + AUTH-014 段加追溯注记 + KNOWLEDGE_GAP_AUDIT.md 同步）

## C2 — spec.md 改号 + 追溯注记（1 commit）

- [ ] `openspec/specs/auth/spec.md` 第 195 行：`### REQ-AUTH-012: POST /heartbeat` → `### REQ-AUTH-015: POST /heartbeat`
- [ ] `openspec/specs/auth/spec.md` 第 139 行 `REQ-AUTH-014` RBAC 段底部加追溯注记：
  > 本能力立项时编号为 REQ-AUTH-012（见 archive/2026-09-21-roles-module/tasks.md），
  > spec 合并时（commit fc49b15）改号 REQ-AUTH-014，对应 8 个 RBAC 代码 commit 沿用 `(REQ-AUTH-012)`。
  > 原 `REQ-AUTH-012` heartbeat 段已改号 `REQ-AUTH-015` 让出号段（变更见 fix-auth012-rebinding）。
- [ ] `openspec/specs/KNOWLEDGE_GAP_AUDIT.md`：原 `REQ-AUTH-012 (/heartbeat token touch)` → `REQ-AUTH-015 (/heartbeat token touch)`

## 验证（不产生 commit）

- [ ] `grep -nE "REQ-AUTH-012[^:0-9]" openspec/specs/` 仅剩 RBAC spec merge commit / 8 RBAC 代码 commit 历史（commit message 不动，符合预期）
- [ ] `grep -nE "REQ-AUTH-015" openspec/specs/` 命中 heartbeat 段 + KNOWLEDGE_GAP_AUDIT.md 各 1 处
- [ ] `pytest server/tests/ -q` 仍 58/58/0（不动代码，不破坏基线）

## C3 — git push（用户拍板后）

- [ ] `git push origin master`
- [ ] 验证 origin 收到 C1 + C2 两个 commit
