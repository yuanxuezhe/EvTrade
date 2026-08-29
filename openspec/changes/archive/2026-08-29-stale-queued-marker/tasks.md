# Tasks: stale-queued-marker (2026-08-29)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进，P3 不在本 change 范围。

## P0 — 前端纯视觉标记（核心）

- [ ] **commit 1 — BatchTasksTable stale 标记**
  - 改 `client/src/components/strategy/BatchTasksTable.vue`:
    - 加 `isStaleQueued(row)` computed function: `row.status==='queued' && !row.started_at && (row.progress==null || row.progress?.phase==='queued') && (Date.now() - new Date(row.created_at)) >= 24*3600*1000`
    - 状态列 stale 时：保留原 tag + 追加 `<el-tag type="warning" size="small">已超时</el-tag>`
    - 行加 `:class="{ 'bf-row-stale': isStaleQueued(row) }"`
    - 行 hover tooltip 加 "卡 N 小时，建议重测或联系 admin"
    - 加 `<el-checkbox v-model="showStaleOnly">只看超时任务</el-checkbox>` 顶部工具栏
    - computed `filteredTasks` = showStaleOnly ? tasks.filter(isStaleQueued) : tasks
  - 加 CSS:
    - `.bf-row-stale { background: var(--bg-secondary, #f7f8fa); opacity: 0.85; }`
    - `.bf-row-stale td { color: var(--text-secondary); }`
  - 编译: `cd client && npm run build` 无报错

- [ ] **commit 2 — ScriptTask.vue banner + checkbox 联动**
  - 改 `client/src/views/ScriptTask.vue`:
    - 新 ref `showStaleOnly = ref(false)`
    - `BatchTasksTable` 加 prop `:show-stale-only.sync="showStaleOnly"`（或 v-model:showStaleOnly）
    - 批次列表 card 顶部条件显示 `<el-alert v-if="staleQueuedCount > 0" type="warning" :closable="true" :title="`批次内 ${staleQueuedCount} 个任务卡 queued > 24h，建议重测或联系 admin`">`
    - computed `staleQueuedCount` = 当前 batchTasks.filter(isStaleQueued).length
    - 工具栏加 `BatchTasksTable` 的 checkbox 同步
  - 编译: `cd client && npm run build` 无报错

## P1 — 后端辅助接口（轻量）

- [ ] **commit 3 — server helper + API**
  - 改 `server/services/script_strategy/batches.py`:
    - 新 function `list_stale_queued_tasks(strategy_id, threshold_hours=24) -> List[Dict]`
    - SQL: `SELECT id, batch_no, created_at, TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS age_min FROM strategy_task WHERE strategy_id=:sid AND status='queued' AND started_at IS NULL AND (progress IS NULL OR JSON_EXTRACT(progress, '$.phase')='queued') AND created_at < NOW() - INTERVAL :h HOUR`
    - 返 [{task_id, batch_no, age_min, created_at}]
  - 改 `server/api/script_strategy/strategies.py`:
    - 新 endpoint `GET /strategies/{strategy_id}/stale-queued` (admin only)
    - 返 `{strategy_id, stale_count, stale_tasks: [...]}`
  - 改 schema: 新 `StaleQueuedOut` Pydantic
  - 不影响现有端端

- [ ] **commit 4 — server 单测**
  - 新文件 `server/tests/strategy/test_stale_queued.py`:
    - monkeypatch list_stale_queued_tasks → fake 返回
    - 测 endpoint: admin OK + 非 admin 403
    - 测 SQL helper: boundary cases（24h 内/外、有 progress 无 progress）
  - 基线: `pytest server/tests/strategy/test_stale_queued.py -v`

## P2 — 文档同步 + 归档

- [ ] **commit 5 — spec-delta merge + 归档 change**
  - 改 `openspec/specs/frontend/spec.md` REQ-FE-546 增加 stale-queued 场景段
  - 改 `openspec/specs/strategy/spec.md` 如有 stale 相关段
  - 归档: `mv openspec/changes/2026-08-29-stale-queued-marker openspec/changes/archive/`

- [ ] **commit 6 — 知识库同步**
  - 改 `知识库/前端/页面/策略开发与运行.md` § 进度可视化增加 stale marker 描述
  - 改 `知识库/策略服务/架构概览.md` 如有 stale task 相关说明

## 验证（v6 完成自查）

- [ ] pytest server/tests/strategy/test_stale_queued.py → 0 fail
- [ ] pytest server/tests/ → 66+ 不退化
- [ ] pytest tests/strategy_exec/ → 45 不退化
- [ ] cd client && npm run build → 无报错
- [ ] git diff --stat 每 commit 单目的
- [ ] 不动 MySQL 任何表/列/行
- [ ] 测试不创建老 queued 任务 fixture（仅 mock / fake）