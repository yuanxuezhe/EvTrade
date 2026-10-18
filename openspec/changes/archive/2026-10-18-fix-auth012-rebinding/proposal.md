# fix-auth012-rebinding（REQ-AUTH-012 编号冲突处理）— 2026-10-18

## 解决什么

`REQ-AUTH-012` 在项目内存在**两个独立段的编号冲突**：

| 段位 | 占用方 | 内容 |
|---|---|---|
| `openspec/specs/auth/spec.md` 第 195 行 | heartbeat（2026-08-04 立）| `POST /api/auth/heartbeat` — Token 保活 |
| RBAC 8 个 commit 的 commit message | RBAC 后端 service / api / guard / 前端 store / 路由守卫 / 用户管理 UI / Sidebar-BottomNav filter | 全部用了 `(REQ-AUTH-012)` |

冲突历史：
1. `openspec/changes/archive/2026-09-21-roles-module/tasks.md` 立项时用 `REQ-AUTH-012 角色管理与细粒度权限`
2. spec 合并 commit `fc49b15 docs(openspec): rbac-roles-module spec merge + change 归档` 把 RBAC 段从 `012` 改叫 `014`（因 `AUTH-014` 被先前 `a17937a docs(auth): REQ-AUTH-011 扩展 + 新 REQ-AUTH-014 (AI 助手授信通路)` 占过、且 `81bbe0b` revert 该提交后腾出的号——RBAC 段被合并进 `AUTH-014`）
3. 8 个代码 commit 的 commit message **未跟随 spec merge 改号**，仍标 `(REQ-AUTH-012)`
4. 结果：spec 里 `AUTH-012` 段 = heartbeat；commit 引用 `AUTH-012` = RBAC。同号两份独立段内容。

## 影响面

- 仅 spec.md / KNOWLEDGE_GAP_AUDIT.md 文字编排
- 不改 commit history（零 force push / 零 rebase）
- 不改代码、不改 API 契约、不改数据库、不改 migration
- 不需要服务重启

## 修复方案（最小破坏）

| 编号 | 内容 | 调整 |
|---|---|---|
| `REQ-AUTH-012` | heartbeat | **改号** → `REQ-AUTH-015`（挪到下一个空号） |
| `REQ-AUTH-014` | RBAC（spec 段内文）| 保留号，**加追溯注记**说明 commit 沿用 `012` 的来龙去脉 |
| RBAC 8 个代码 commit `(REQ-AUTH-012)` commit message | 不动 | 在 spec `AUTH-014` 段加注记即可溯源 |

理由：
- heartbeat 段就 1 段老段（2026-08-04 立），改名影响最小
- 8 个代码 commit 不 rewrite（避免 force push + 历史重写）
- `AUTH-014` RBAC 段内容已合规，新增注记只是追溯说明

## 阶段 commit（与 CLAUDE.md § 五 v6 一致）

| # | 内容 | 类型 |
|---|---|---|
| C1 | 新增 `openspec/changes/2026-10-18-fix-auth012-rebinding/` 三件套（proposal + tasks + spec-delta）| `docs(openspec): …` |
| C2 | `openspec/specs/auth/spec.md` heartbeat 段 `012 → 015` + `AUTH-014` 段加追溯注记 + `KNOWLEDGE_GAP_AUDIT.md` 同步 | `docs(spec): …` |
| C3 | `git push origin master`（C1+C2 一并推送；非自动 push，按用户拍板） | 网络操作 |

中间验证：
- `git grep -nE "REQ-AUTH-012[^:0-9]"` 在改后**只**应剩 RBAC 8 commit 历史（commit message 不动，符合预期）
- `git grep -nE "REQ-AUTH-015"` 应匹配 heartbeat 段 + KNOWLEDGE_GAP_AUDIT.md 一处
- pytest server 58/58 基线不动（无代码改动）

## 不做什么

- ❌ 不 force push
- ❌ 不 rebase 8 个 RBAC commit
- ❌ 不改 RBAC 段号 `014 → 012`（spec merge commit fc49b15 已合并，reverse 风险高）
- ❌ 不删任何 commit
- ❌ 不动任何代码 / 测试 / migration / KB 业务文档
