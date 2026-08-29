# Stale Queued Marker — 老 queued 任务视觉标记提案 (2026-08-29)

> 用户拍板 2026-08-29：按 P0→P1→P2→P3 顺序推进。
> 解决 ScriptTask 批次表格内老 queued 任务（卡 > 24h）与新任务混淆，无任何状态指示的 UX 问题。

## Why

**实测现场**（2026-08-29 SQL 查 strategy_task，仍有 5 条老任务）：

| id | sid | batch  | status  | age_min | started | finished | progress |
|----|-----|--------|---------|---------|---------|----------|----------|
| 14 | 12  | 10000009 | queued | 8540  | None | None | None |
| 6  | 5   | 10000001 | queued | 11060 | None | None | None |
| 5  | 3   | 10000004 | queued | 19174 | None | None | None |
| 4  | 3   | 10000003 | queued | 24553 | None | None | None |
| 3  | 3   | 10000002 | queued | 24553 | None | None | None |

**前端体验问题**：
- 用户打开 ScriptTask 页看到「5/5 完成」「排队中」混合的批次表格，分不清哪些 task 是当前批次活跃、哪些是历史孤儿
- 老 queued 任务 status 跟新提交未起跑的 task 视觉一致（都是 info 蓝 tag "排队中"）
- `started_at` 为 None + `progress` 为 None 表示从未被 strategy_exec 调度过，与正常 queued 无法区分

**用户硬规则**：
- 禁清表数据（`策略服务/信号推送.md` § 数据安全 + `测试体系.md` § fixture 卫生）
- 不主动改 status / delete / reset（老 task 数据不可侵犯）
- 只能**视觉标记**（UI 提示，不动 DB）

## What

### P0 — 前端纯视觉标记

1. **判定逻辑**（前端纯计算，无后端改动）：
   - `status === 'queued' && !started_at && !progress`
   - **OR** `status === 'queued' && (now - created_at) > 24h`（兜底 started/progress 已被清的老任务）
2. **视觉表现**（BatchTasksTable.vue）：
   - 行加灰色背景（`var(--bg-secondary)` 或 `rgba(0,0,0,0.04)`）
   - 「状态」列保留原 tag 后面追加 `<el-tag type="warning" size="small">已超时</el-tag>`
   - 行 hover tooltip 提示「卡 N 小时，建议重测或联系 admin」
3. **可观测性**（前端工具栏 + 批次列表）：
   - 批次列表顶部加一个 `st-batch-warn` banner：「X 个任务卡 queued > 24h，建议重测或联系 admin」
   - 仅当批次内含 ≥1 stale queued task 时显示，可关闭（dismiss）
4. **过滤**（可选）：
   - `BatchTasksTable` 顶部加 `<el-checkbox v-model="showStaleOnly">只看超时任务</el-checkbox>`
   - 默认 false；勾选后只显示 stale queued 行（其余隐藏）

### P1 — 后端辅助接口（轻量）

1. **`GET /api/script-strategy/strategies/{strategy_id}/stale-queued`**
   - 返 `{strategy_id, stale_count, stale_tasks: [{task_id, batch_no, age_min}]}`
   - 单 SQL：`SELECT id, batch_no, TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS age_min FROM strategy_task WHERE strategy_id=? AND status='queued' AND started_at IS NULL AND (progress IS NULL OR JSON_EXTRACT(progress, '$.phase')='queued') AND created_at < NOW() - INTERVAL 24 HOUR`
   - 仅 admin 可调（不暴露给 owner 隐私）
   - 前端 banner 数据源

2. **测试覆盖**：
   - `server/tests/strategy/test_stale_queued.py` — 测 SQL 边界（stale/非 stale 区分）
   - 不写 fixture 数据，用 conftest.TEST_TRD_DATE 不行（strategy_task 无 trd_date 字段），改用 monkeypatch + fake session

### P2 — 文档同步

- `openspec/specs/frontend/spec.md` REQ-FE-546 增加 stale-queued 视觉标记场景
- `openspec/specs/strategy/spec.md`（如果有 stale task 相关）补 1 段
- `知识库/前端/页面/策略开发与运行.md` § 进度可视化增加 stale marker 描述

### P3 — (可选) admin 操作

**本 change 不做**，留给后续 change：
- admin 强制 abandon stale queued task 端点
- 自动检测 cron + email / wechat 通知
- 用户拍板后另开 change

## 不做什么

- **不动 MySQL 任何表/列/行**（用户硬规则 2026-08-27）
- 不 drop / truncate / delete from
- 不重建 schema，不跑 sync_schema.py apply
- 不改 strategy_task.status / 不主动 abandon 老 task（数据归属 owner/admin 决策）
- 不动 ws 推送逻辑（stale 标记纯前端衍生，与 task_progress_update 解耦）
- 不动 strategy_exec（与运行引擎无关）
- 不动老 5 条 queued task 的 status（即便看到也是 readonly 视觉）

## 影响面

| 模块 | 影响 |
|---|---|
| client/src/components/strategy/BatchTasksTable.vue | stale 行灰色背景 + tag + tooltip + 过滤 checkbox |
| client/src/views/ScriptTask.vue | banner + checkbox 联动 |
| server/api/script_strategy/strategies.py | 新端点 `/strategies/{id}/stale-queued`（admin only） |
| server/services/script_strategy/batches.py | 新 helper `list_stale_queued_tasks(strategy_id)` |
| server/tests/strategy/test_stale_queued.py | 新测试 |
| openspec/specs/frontend/spec.md | REQ-FE-546 补 stale-queued 场景 |
| openspec/specs/strategy/spec.md | 补 stale-queued 概念段（如有） |
| 知识库/前端/页面/策略开发与运行.md | 同步 stale marker |

## Commit 拆解 (v6)

```
1. feat(client): BatchTasksTable stale-queued 视觉标记 (灰色 + tag + 过滤)
2. feat(client): ScriptTask.vue banner + 过滤 checkbox
3. feat(server): list_stale_queued_tasks helper + API 端点
4. test(server): stale_queued SQL 边界单测
5. docs(openspec): frontend spec-delta + merge + 归档
6. docs(knowledge): 知识库 同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema，不跑 sync_schema.py apply
- [ ] 测试不写 fixture 老任务数据（不污染生产 trd_date）

## 验证 (v6 完成自查)

- [ ] pytest server/tests/strategy/test_stale_queued.py → 0 fail
- [ ] pytest server/tests/ → 不退化 (基线 66 passed)
- [ ] pytest tests/strategy_exec/ → 不退化 (基线 45 passed)
- [ ] cd client && npm run build → 无报错
- [ ] 实测：开 ScriptTask 页面 → 老 5 条 queued 行显示灰色 + 「已超时」tag
- [ ] git diff --stat 每 commit 单目的