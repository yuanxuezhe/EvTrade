# Tasks — ScriptDev 视觉修复 + 编译按钮（2026-08-21）

按 v6 拆小 commit。每 commit 后必 `git log -1` 校验 hash；不自动 push。

**agent 分工**（按 2026-08-21 用户拍板 + M2.7 已知反例修正）：
- **主 agent（M3.0）**：写工件（proposal/tasks/spec-deltas）+ 验收 + **前端 UI commit**（M2.7 写 Vue 会瞎编，2026-07-08 反例）
- **subagent（M2.7, 走 `delegate_task`）**：后端 compile 端点 commit + 测试 commit + 归档（纯逻辑 + 模板化代码，M2.7 友好场景）

> ⚠️ M2.7 已知反例（2026-07-08 v18 实测：4 处架构瞎编 + L3 慢 20x）。
> 缓解：每 commit 后主 agent 必 grep/sed 验证关键字段；commit 拆到单文件粒度。

## Stage 1（草稿）— 主 agent

- [x] **proposal-1** 写 `proposal.md`（含 Decisions 表 + M2.7 风险章节）
- [x] **spec-A** 写 `spec-deltas/frontend.md`（REQ-FE-SCRIPTDEV-001/002）
- [x] **spec-B** 写 `spec-deltas/strategy.md`（REQ-STRAT-018 compile 契约）
- [x] **proposal-2** 写 `tasks.md`（本文件）

## Stage 2（拍板）— 主 agent 等待用户

- [ ] **用户拍板 Q1-Q5**（proposal §Decisions 表 5 项）
  - 默认推荐全部勾选 → 回"全按默认" = 全部批准
- [ ] 用户确认 OpenSpec 草稿无歧义

## Stage 3（实施）— 派 subagent（M2.7）

### Commit 1：后端 compile 端点 — **subagent**

> 文件：`server/api/script_strategy.py`
> 单文件、新增 1 端点（~20 行）。
> 主 agent 验证：`grep -c "compile_script\|/compile" server/api/script_strategy.py` 应为 2

- [ ] **apply-c1-1** subagent 在 `server/api/script_strategy.py` 加 `compile_script(id)` 函数
  - 取 script `code` 字段
  - `ast.parse(code)` 校验
  - 返 `{"ok": True}` 或 `{"ok": False, "error": {"line": int, "col": int, "msg": str}}`
  - 注册路由 `POST /scripts/{id}/compile`
- [ ] **apply-c1-2** 主 agent sed 验证 + smoke test（curl 本地端口）

### Commit 2：前端 API + UI（删除按钮修复 + 编译按钮 + handler） — **主 agent（M3.0）**

> 文件：`client/src/api/script_strategy.js` + `client/src/views/ScriptDev.vue`
> 2 个文件，串行 patch（按 opsx-field-notes §10：增量 patch 优先 write_file 整文件覆盖）。
> 主 agent 验证：
> - `grep -c "compileScript" client/src/api/script_strategy.js` 应为 1
> - `grep -c 'sd-compile' client/src/views/ScriptDev.vue` 应为 1
> - `wc -l client/src/views/ScriptDev.vue` 应 +15~20 行

- [ ] **apply-c2-1** subagent 改 `client/src/api/script_strategy.js` 加 `compileScript(id)` 方法
- [ ] **apply-c2-2** subagent 改 `client/src/views/ScriptDev.vue`：
  - L198 删除按钮去 `plain` 属性
  - L196-205 底栏新增"编译"按钮（type="warning" + `DocumentChecked` 图标 + `:loading="compiling"` + `@click="onCompile"`）
  - script setup 加 `const compiling = ref(false)` + `async function onCompile()` handler
- [ ] **apply-c2-3** 主 agent sed/wc 验证

### Commit 3：spec 落地（永久 spec.md） — **subagent**

> 文件：`openspec/specs/frontend/spec.md` + `openspec/specs/strategy/spec.md`
> 按 opsx-field-notes §4："Commit 4 (`docs(spec): ...`) 落永久 spec 增量"
> 主 agent 验证：grep `REQ-FE-SCRIPTDEV-001/002` 应为 2 行；grep `REQ-STRAT-018` 应为 1 行

- [ ] **apply-c3-1** subagent 改 `openspec/specs/frontend/spec.md`：
  - 加 `### REQ-FE-SCRIPTDEV-001`（删除按钮视觉规范）
  - 加 `### REQ-FE-SCRIPTDEV-002`（编译按钮 UX）
- [ ] **apply-c3-2** subagent 改 `openspec/specs/strategy/spec.md`：
  - 加 `### REQ-STRAT-018`（compile 端点契约）

### Commit 4：测试 — **subagent**

- [ ] **apply-t4-1** subagent 写测试：
  - 后端：`pytest server/tests/test_script_strategy_compile.py`（3 case：语法 OK / SyntaxError / IndentationError）
  - 前端：手动截图（curl vite 模块 URL 验证 SFC 编译通过）
- [ ] **apply-t4-2** 主 agent 验证 pytest 输出 3/3

## Stage 4（归档）— subagent

- [ ] **archive-1** subagent：
  ```bash
  git log --oneline -5  # 确认 4 commit hash
  git status  # 干净
  git mv openspec/changes/2026-08-21-scriptdev-fix-compile openspec/changes/archive/
  ```
- [ ] **archive-2** 主 agent 最终验证：`ls openspec/changes/archive/` 含 2026-08-21-scriptdev-fix-compile/

## 暂停点（需用户拍板）

- **Pause #1**（Stage 2 拍板后实施前）：用户是否仍按默认推荐推进？
  - 默认建议：是（按 §8 批模式 + §11 增量迭代模式）
  - 若拒绝：拆步骤逐一问
- **Pause #2**（Stage 4 commit 4 后）：是否立刻 push？
  - 默认建议：**否**（按 AGENTS.md v6 "不自动 push"）
  - 若用户拍 push：执行 `git push origin <branch>`（**必须先确认在哪个分支**）

## Report cadence（按 opsx-field-notes §9）

每 sub-task 完成报告：**一行表格 8 列**：
`# / 任务 / 改动 / 文件 / 验证 / 结果 / OpenSpec / Git`