# Strategy Dev Page Optimize — 任务清单

> **范围**：前端策略开发页面 + 对应后端逻辑
> **拍板**：待用户回答 Q1-Q3 后填入
> **本文档是模板**，Q 拍板后冻结任务边界

---

## 阶段 0 — 决策拍板

- [ ] **Q1** 范围：Batch 1（仅清理） / Batch 1+2（+前端拆 composable） / Batch 1+2+3（+后端 batches.py 拆） / +Batch 4（架构）
- [ ] **Q2** 实施：派 subagent 走 sandbox-cc / 主 agent 自己写（不推荐）/ 跳过
- [ ] **Q3** 是否走完整 OpenSpec 流程

---

## 阶段 1 — 静态扫描基线（必做，无论 Q1 选哪个）

> 这是事实收集阶段，不改代码。所有 subagent 主 agent 必做。耗时 ~10 分钟。

- [ ] **1.1** 跑 `pytest server/strategy/tests/ server/tests/script_strategy/ -v` 记录基线 (pass/fail 数)
- [ ] **1.2** 跑 `cd client && npm run build` 记录基线 (build 时间 + warning 数)
- [ ] **1.3** 跑 `cd client && npm run lint` 记录基线 (error/warning 数)
- [ ] **1.4** 跑 `curl http://127.0.0.1:8000/api/script-strategy/scripts -H "Authorization: Bearer $JWT"` 确认 200
- [ ] **1.5** 写出《扫描基线报告》附到 proposal 末尾
- [ ] **1.6** `git checkout .` 确认无污染基线（如有则 commit 后再继续）

## Batch 1 — 清理（最低风险，推荐先做）

> 涉及：删未使用 import、长函数抽 helper、schemas.py 拆分、_convert.py 注释
> 估时：30 分钟 / 估提交：3-5 个 commit（每个 fix 一个 commit）

- [ ] **B1.1** 删 `api/script_strategy/strategy_orders.py` 未使用 import `STATUS_RUNNING`
- [ ] **B1.2** 在 `services/script_strategy/_convert.py` 顶部加注释说明"内部模块，不要外部 import"，并修文件名（建议 `_convert.py` → `_strategy_convert.py` 避免 IDE 折叠）
- [ ] **B1.3** 跑 `python -c "from server.api.script_strategy import router; print(len(router.routes))"` 确认 endpoints 数不变
- [ ] **B1.4** commit batch 1（每 fix 一 commit，按 EvTrade v6 commit 规范）
- [ ] **B1.5** 重跑基线测试确认无回归

## Batch 2 — 前端 ScriptDev.vue 拆 composable（覆盖 80% 收益）

> 涉及：ScriptDev.vue 668 行 → ~380 行
> 估时：1.5 小时 / 估提交：3-4 个 commit

- [ ] **B2.1** 抽 `client/src/composables/useScriptEditor.js`
  - 入参：当前 user id
  - 出参：scripts / selectedId / selectedUserId / currentScript / draft / loading / saving / filterMode / isReadonly + 行为：loadScripts / onSelect / onCreate / onSave / onDelete / onCompile / onTestBacktest
- [ ] **B2.2** 抽 `client/src/composables/useParamsSchema.js`
  - 入参：form ref
  - 出参：addRow / removeRow / onValuesStrChange / validateSchema
- [ ] **B2.3** ScriptDev.vue 改用上述两个 composable
- [ ] **B2.4** 写 `useScriptEditor.test.js`（用 vitest，vitest 是 Vite 默认测试 runner）
- [ ] **B2.5** 跑 `npm run build` + `npm run lint` + 手工点测核心流程（新建 / 编辑 / 保存 / 编译 / 回测）
- [ ] **B2.6** commit batch 2

## Batch 3 — 后端 batches.py 长函数拆分（最复杂）

> 涉及：`batches.py` create_backtest_batch (103 行) + retest_batch (84 行)
> 估时：1.5 小时 / 估提交：2-3 个 commit

- [ ] **B3.1** 写 `server/services/script_strategy/_batch_grid.py` 抽 `grid_expand()` 函数（笛卡尔积生成）
- [ ] **B3.2** 写 `_batch_persist.py` 抽 `bulk_insert_tasks()` 函数
- [ ] **B3.3** `create_backtest_batch` 主调度只保留 orchestration，单函数 ≤ 50 行
- [ ] **B3.4** `retest_batch` 同理拆 `deprecate_old_batch()` + `rebuild_tasks()`
- [ ] **B3.5** 写 `tests/services/script_strategy/test_batches.py` 单测覆盖拆分后的 helper
- [ ] **B3.6** 跑基线测试确认无回归
- [ ] **B3.7** commit batch 3

---

## 风险与禁忌

1. **不改数据库 schema**（任何 batch）
2. **不开新 endpoint**
3. **不重写算法**（仅抽函数，行为不变）
4. **不在 sandbox 镜像装新依赖**（前端 node_modules 已齐全，后端 venv 已齐全）
5. **不开新 npm 包**
6. **抽 composable 必须保留原 props/事件契约**，ScriptDev.vue 父级用法不变
7. **每个 batch 完成后必须跑完整基线测试**，无回归才能进下一 batch
8. **不开新 PyPI 包**

## 必跑的二次验证（EvTrade CLAUDE.md §12）

每个 batch 完成后主 agent 必做：

- [ ] `git diff --stat <changed files>` 看改动范围单一功能
- [ ] `git status -s` 仅预期文件
- [ ] `pytest` 全绿
- [ ] `npm run build` 成功
- [ ] 手工 curl 端点确认行为不变

## 不做的事

- 不动 hqserverd / strategy_exec（不在范围）
- 不重写 BacktestEngine
- 不换前端 UI 框架
- 不改数据库 schema
- 不引入新依赖
- 不改 CLAUDE.md / 知识库（除非代码同步要求；本 change 不涉及）

---

## 完成后归档

1. `git mv openspec/changes/2026-08-27-strategy-dev-page-optimize openspec/changes/archive/2026-08-27-strategy-dev-page-optimize`
2. proposal.md 加 [ARCHIVED 2026-MM-DD] 标记
3. tasks.md 全勾完成
4. 知识库 `知识库/前端/策略开发/` 和 `知识库/后端服务/策略引擎/` 同步更新（如有架构变化）
