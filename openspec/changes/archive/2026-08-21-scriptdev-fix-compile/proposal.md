# Proposal — ScriptDev 视觉修复 + 编译按钮（2026-08-21）

## Why

现状：
- `client/src/views/ScriptDev.vue` L198 删除按钮 `<el-button type="danger" plain>删除</el-button>` 在浅色主题下**文字色与背景对比度不足**，用户反馈"字看不见"
- 脚本策略代码编辑后**无静态校验入口**，只能"保存 → 去测试回测"，跑整段回测才发现语法错误，**首版调试成本高**

缺口：
1. 删除按钮 plain 样式**文字色对比度**未做主题适配
2. 缺**编译/语法检查按钮**（后端无 `/api/script-strategy/scripts/{id}/compile` 类端点，前端也无对应 UI）

## What Changes

新增 2 项小功能：

1. **删除按钮视觉修复** — `ScriptDev.vue` 底栏"删除"按钮去掉 `plain`（保留 `type="danger"`），强制实底+文字高对比，**同时**支持 dark/light 主题
2. **编译按钮 + 后端编译端点**
   - 前端 `ScriptDev.vue` L196-205 底栏新增 **"编译"** 按钮（`type="warning"` + `DocumentChecked` 图标）
   - 调后端 `POST /api/script-strategy/scripts/{id}/compile`（仅语法静态检查，不回测）
   - 后端用 Python `ast.parse(code)` 校验 → 返 `{ok: bool, error?: {line, col, msg}, warnings?: [...]}`（warnings 暂不实现，留空列表）
   - 编译失败 → `ElMessageBox.alert` 弹窗显示行号+错误信息
   - 编译成功 → `ElMessage.success('语法 OK')`

### 影响范围
| 文件 | 改动 |
|---|---|
| `client/src/views/ScriptDev.vue` | 删除按钮去 `plain`；新增"编译"按钮 + onCompile handler；compile 结果弹窗 |
| `client/src/api/script_strategy.js` | 新增 `compileScript(id)` 方法 |
| `server/api/script_strategy.py` | 新增 `POST /scripts/{id}/compile` 端点（读 DB 取 code → ast.parse → 返结果） |
| `openspec/specs/frontend/spec.md` | 新增 REQ-FE-SCRIPTDEV-001（删除按钮视觉规范）+ REQ-FE-SCRIPTDEV-002（编译按钮 UX） |
| `openspec/specs/strategy/spec.md` | 新增 REQ-STRAT-018（compile 端点契约） |

## Backward Compatibility

- 删除按钮**保持功能不变**（`onDelete` handler、confirm 弹窗、API 调用都不变），**仅样式调整**
- 编译按钮**纯新增**，不影响现有"保存"/"测试回测"/"删除"按钮
- 后端 compile 端点**只读不写**（不修改 DB），可安全反复调
- 已归档 change 不影响

## Decisions（拍板记录）

> 用户拍板模式：**批模式（§8）** — 用户回复"全按默认"视作全部批准默认推荐。
>
> | # | 决策点 | 默认推荐 | 用户选择 |
> |---|---|---|---|
> | Q1 | 删除按钮修复方案 | 去 `plain`（最简、对比度立即达 4.5:1） | 默认 |
> | Q2 | 编译后端实现 | `ast.parse` 静态检查（不跑回测，快 < 200ms） | 默认 |
> | Q3 | 编译按钮位置 | 底部按钮栏，"测试回测"按钮左边 | 默认 |
> | Q4 | 编译失败展示 | `ElMessageBox.alert` 行号+消息（不入 ElNotification） | 默认 |
> | Q5 | compile 是否要求已保存 | 是（必须 form.id 存在；无 id → ElMessage.warning 提示先保存） | 默认 |

## Impact

| 文件 | 改动 |
|---|---|
| `client/src/views/ScriptDev.vue` | 改 1 行（删 plain）+ 加 1 个按钮（~15 行 template + ~20 行 script handler）|
| `client/src/api/script_strategy.js` | +1 方法（5 行）|
| `server/api/script_strategy.py` | +1 端点（~20 行：取 code + ast.parse + 返 dict）|
| `openspec/specs/frontend/spec.md` | +2 REQ |
| `openspec/specs/strategy/spec.md` | +1 REQ |

## Risks

- **M2.7 subagent 写代码风险**（按 opsx-field-notes 反例）：M2.7 在"无 tool access 时会闭卷瞎写"，且已知写 Vue/FastAPI 项目代码时 4 处架构瞎编。
- **缓解**：实施阶段 commit 拆分粒度极细（按"文件"拆），每 commit 后必 sed/grep/wc 验证（见 opsx-field-notes §3 §10）；compile 后端逻辑保持 < 30 行避免 M2.7 大段发挥。
- **Vue 3 + Element Plus 组件** 若 M2.7 引入已弃用 API（如 `el-button` 的 `icon` slot 而非 `:icon` prop），主 agent 会 commit 前 sed 检查并回退。