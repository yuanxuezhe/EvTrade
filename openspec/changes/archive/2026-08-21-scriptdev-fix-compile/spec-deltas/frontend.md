# Spec Deltas — Frontend（ScriptDev 视觉修复 + 编译按钮）

> 追加于：`openspec/specs/frontend/spec.md` 末尾
> Change: 2026-08-21-scriptdev-fix-compile

---

### REQ-FE-SCRIPTDEV-001: ScriptDev 删除按钮视觉规范（2026-08-21）

The system SHALL render `client/src/views/ScriptDev.vue` 底栏的"删除"按钮为 **el-button 实底（无 `plain`）**，`type="danger"`，确保文字色与背景对比度 ≥ 4.5:1（WCAG AA），避免 plain 模式下文字被压成浅色导致用户看不见。

#### Scenario: 删除按钮文字可见

- **GIVEN** user 在 `/script-dev` 页面编辑一个已存在的脚本
- **WHEN** 底栏渲染
- **THEN** 删除按钮 MUST NOT 含 `plain` 属性
- **AND** 删除按钮文字 MUST 视觉清晰（背景红色 + 白色文字）
- **AND** `:disabled="isReadonly"` 仍生效（只读场景下按钮变灰）

#### Scenario: 只读脚本不显示删除

- **GIVEN** user 在看一个他人公开脚本（`isReadonly = true`）
- **WHEN** 底栏渲染
- **THEN** 删除按钮 MUST NOT 出现在 DOM（因 `v-if="form.id"` 已确保，但 `isReadonly` 也要保证按钮置灰）

---

### REQ-FE-SCRIPTDEV-002: ScriptDev 编译按钮 UX（2026-08-21）

The system SHALL provide a "编译" button in `ScriptDev.vue` 底栏，位于"测试回测"按钮左边。点击后调 `POST /api/script-strategy/scripts/{id}/compile`，根据返回结果展示成功消息或错误弹窗。

#### Scenario: 编译按钮渲染条件

- **GIVEN** user 在 `/script-dev` 页面
- **WHEN** `form.id` 已存在（已保存的脚本）
- **THEN** "编译"按钮 MUST 可见且可点击
- **WHEN** `form.id` 为 null（新建草稿未保存）
- **THEN** "编译"按钮 MUST NOT 可点击（`disabled`），或点击后弹 `ElMessage.warning('请先保存脚本')`

#### Scenario: 编译成功

- **GIVEN** 脚本 code 语法正确
- **WHEN** user 点击"编译"按钮
- **THEN** 前端调 `compileScript(form.id)`
- **AND** 后端返 `{"ok": true}`
- **AND** 前端展示 `ElMessage.success('语法 OK')`

#### Scenario: 编译失败 — 语法错误

- **GIVEN** 脚本 code 含 `SyntaxError`（如 `def foo(` 漏右括号）
- **WHEN** user 点击"编译"按钮
- **THEN** 前端调 `compileScript(form.id)`
- **AND** 后端返 `{"ok": false, "error": {"line": 1, "col": 9, "msg": "unexpected EOF while parsing"}}`
- **AND** 前端展示 `ElMessageBox.alert(error.msg, '语法错误 (line 1, col 9)')`

#### Scenario: 编译中 loading 态

- **GIVEN** user 点击"编译"按钮
- **WHEN** 请求 in-flight
- **THEN** 编译按钮 MUST 显示 loading 态（`:loading="compiling"`）
- **AND** 其他按钮 MUST 保持可点击状态（不阻塞"保存"等其他操作）