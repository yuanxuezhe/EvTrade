# Tasks — 2026-08-23-ai-strategy-assistant

> 按 CLAUDE.md § 五 v6 拆 commit：每完成 1 项 = 1 commit。

## C0 调研 + 写 change（已完成）

- [x] 调研 ScriptDev.vue 文件位置 + hermes serve 端口 + scripts.py API
- [x] 写 proposal.md + tasks.md + spec-deltas/

## C1 spec delta（待做）

- [ ] `openspec/specs/strategy/spec.md` 加 REQ-STRAT-018 AI 助手契约
- [ ] `openspec/specs/frontend/spec.md` 加 REQ-FE-018 ScriptDev AI 抽屉
- [ ] `openspec/specs/server-architecture/spec.md` 加 REQ-SRV-018 hermes RPC 客户端

## C2 后端 hermes RPC 客户端（待做）

- [ ] `server/services/hermes_client.py` — JSON-RPC over HTTP 封装（hermes serve 9119）
- [ ] `_extract_python_code(text: str) -> str | None` — 正则提取 ```python ... ``` 代码块
- [ ] 单测 `server/tests/test_hermes_client.py`（mock HTTP）

## C3 后端 /api/ai-strategy 端点（待做）

- [ ] `server/api/ai_strategy.py` — POST `/api/ai-strategy` 接收 `{description, current_code?}`
- [ ] 调 hermes_client.chat(prompt=模板注入 description + current_code + 策略模板)
- [ ] 校验 LLM 输出 → 仅返代码块字符串
- [ ] 错误处理：hermes 未起 → 503；LLM 超时 → 504；输出无代码块 → 422
- [ ] 单测 `server/tests/test_ai_strategy.py`（mock hermes_client）

## C4 前端 AI 抽屉（待做）

- [ ] `client/src/api/ai_strategy.js` — axios 客户端
- [ ] `client/src/views/ScriptDev.vue` — 顶部「AI 助手」按钮 + 右侧 el-drawer
- [ ] 抽屉内：el-input(v-model=aiPrompt) + 「生成」按钮 + 历史列表
- [ ] 生成成功 → el-message-box.confirm → 注入 `form.code`
- [ ] 只读模式不渲染抽屉

## C5 e2e + 归档（待做）

- [ ] `scripts/e2e/test_ai_strategy_e2e.py` — e2e 测试（可选，mock LLM）
- [ ] pytest hq/ server/tests/ 全跑（基线 64 passed 不降）
- [ ] 跑 npm run build 验证前端
- [ ] 跑 evctl status + /api/health 验证服务健康
- [ ] 归档：spec merge + mv openspec/changes/2026-08-23-ai-strategy-assistant → archive/

## 验证清单（commit 前必做）

- [ ] `git diff --stat` 改动单一目的
- [ ] `git log -1` hash 校验
- [ ] pytest 跑过
- [ ] npm run build 跑过（前端 commit）
- [ ] 知识库同步（`openspec/specs/...`）
