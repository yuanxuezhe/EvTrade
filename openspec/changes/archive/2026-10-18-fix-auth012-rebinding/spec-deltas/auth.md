# REQ-AUTH-012 编号冲突处理 — spec delta

## 改什么

### 改动 1：heartbeat 段挪号 `012 → 015`

`openspec/specs/auth/spec.md` 第 195 行段标题：

```diff
- ### REQ-AUTH-012: POST /heartbeat — Token 保活（idle 防过期）
+ ### REQ-AUTH-015: POST /heartbeat — Token 保活（idle 防过期）
```

段正文不动。

### 改动 2：REQ-AUTH-014 RBAC 段加追溯注记

`openspec/specs/auth/spec.md` 第 139 行 `REQ-AUTH-014` 段末尾追加一段引用块：

```diff
  #### 测试

  `server/tests/services/rbac/test_rbac.py` — 23 case (helpers + 整体覆盖 + 派生)
+
+ > **编号追溯注记（2026-10-18 fix-auth012-rebinding）**：
+ > 本能力（RBAC 角色管理）立项时编号为 `REQ-AUTH-012`
+ > （见 `archive/2026-09-21-roles-module/tasks.md`）。spec 合并
+ > commit `fc49b15` 时改号为 `REQ-AUTH-014`，但对应 8 个 RBAC
+ > 代码 commit 的 commit message 沿用 `(REQ-AUTH-012)`。
+ > 原 `REQ-AUTH-012` heartbeat 段已改号 `REQ-AUTH-015`
+ > （见 change `2026-10-18-fix-auth012-rebinding`）。
+ > 读者：spec 检索请走 `AUTH-014`；git log 检索请走 `(REQ-AUTH-012)`。
```

### 改动 3：KNOWLEDGE_GAP_AUDIT.md 同步

`openspec/specs/KNOWLEDGE_GAP_AUDIT.md` 行内一处：

```diff
- | **修复建议** | 新增 REQ-AUTH-011 (`/grant` 永久 token，env 控制) + REQ-AUTH-012 (`/heartbeat` token touch) |
+ | **修复建议** | 新增 REQ-AUTH-011 (`/grant` 永久 token，env 控制) + REQ-AUTH-015 (`/heartbeat` token touch) |
```

## 不改什么

- 任何代码 / test / migration / SQL
- 任何 KB 业务文档（已 grep `知识库/` 0 命中 REQ-AUTH-012）
- commit history（无 rebase / 无 force push）
