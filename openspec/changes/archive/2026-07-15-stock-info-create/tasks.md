# Tasks: 证券信息设置支持添加证券

> **对照 proposal.md 执行** — 每完成一项勾选 [x]

---

## Phase 1: OpenSpec 工件（前置）

- [ ] **t.1** 建 changeset 目录 `openspec/changes/2026-07-15-stock-info-create/{spec-deltas}`
- [ ] **t.2** 写 `proposal.md` (why / what / how / risks / out-of-scope / test plan)
- [ ] **t.3** 写 `tasks.md` (本文件)
- [ ] **t.4** 写 `spec-deltas/stocks.md` (REQ-STOCK-006)
- [ ] **t.5** 写 `spec-deltas/frontend.md` (REQ-FE-STOCK-CREATE)

---

## Phase 2: 后端实现（commit 1）

- [ ] **b.1** `server/repo/stocks.py` 新增 `create_by_admin(db, payload) -> Optional[Stock]`
  - 先 `db.query(Stock).filter_by(stock_code=code).first()` 检查存在
  - 不存在 → `Stock(stock_code=code, **payload)` + `db.add()` + `db.commit()` + 返回 ORM 对象
  - 存在 → 返回 None（API 层抛 409）
- [ ] **b.2** `server/api/stocks.py` 新增 `class StockCreateRequest` Pydantic
  - 8 字段：`stock_code: str` (regex 校验), `stock_name: str`, `sector: Optional[str]`, `short_name: Optional[str]`, `is_t0_able: bool = False`, `min_buy_qty: int = 100`, `trade_unit: int = 1`
  - `class Config: extra = "forbid"`
- [ ] **b.3** `server/api/stocks.py` 新增 `@router.post("", status_code=201, dependencies=[Depends(require_admin)])`
  - 调 `repo.create_by_admin`，返回 None 抛 409 Conflict
  - 成功 → `{code:0, msg:"ok", data: to_dict(stock)}`
- [ ] **b.4** 验证 patch 后 Python 语法（`python -c "import ast; ast.parse(open('...').read())"`）
- [ ] **b.5** git diff --stat 确认改动范围
- [ ] **b.6** git add + commit: `feat(api): POST /api/stocks admin 添加证券`

---

## Phase 3: 前端实现（commit 2）

- [ ] **f.1** `client/src/api/stocks.js` 新增 `stocksApi.create(payload)`
  - `http.post('/stocks', payload)` → 返回 data
- [ ] **f.2** `client/src/stores/stocks.js` 新增 `createStock(payload) -> {ok, msg, data?}`
  - 调 `stocksApi.create`
  - 成功：`cache.value.unshift(data)` + `total.value += 1` + `pageRows.value.unshift(data)`
  - 失败：返回 `{ok: false, msg: error message}`
- [ ] **f.3** `client/src/views/AdminStockConfig.vue` 在 panel-header 加"添加证券"按钮（Primary type）
- [ ] **f.4** `client/src/views/AdminStockConfig.vue` 新增 `<el-dialog>` 用于"添加证券"
  - 标题："添加证券信息"
  - 8 字段表单: stock_code (必填, regex 校验) / stock_name / sector / short_name / is_t0_able (switch) / min_buy_qty / trade_unit
  - 提交按钮调 `store.createStock` + 提示 + 关闭 dialog
  - 与编辑 dialog 独立（用独立 ref `createDialogVisible`）
- [ ] **f.5** 验证 patch 后 Vue SFC 结构（`<template>/<script setup>/<style scoped>` 平衡）
- [ ] **f.6** git diff --stat 确认改动范围
- [ ] **f.7** git add + commit: `feat(client): 证券信息设置支持添加证券`

---

## Phase 4: 验证

- [ ] **v.1** 后端重启（kill + nohup uvicorn）
- [ ] **v.2** curl 测试 POST `/api/stocks`
  - 正常: admin token + 完整 payload → 201
  - 重复 stock_code → 409
  - 缺 stock_name → 422
  - 非 admin token → 401/403
- [ ] **v.3** 浏览器实测: admin 登录 → /admin/stock-config → 点"添加证券" → 填表单 → 提交 → 看新行
- [ ] **v.4** 缓存验证: 刷新页面 → 新加的 stock 仍在（说明 cache 持久化到后端 DB）

---

## Phase 5: 同步 spec + 归档 + push（commit 3）

- [ ] **s.1** patch `openspec/specs/stocks/spec.md` 追加 REQ-STOCK-006 + 4 scenario
- [ ] **s.2** patch `openspec/specs/frontend/spec.md` 追加 REQ-FE-STOCK-CREATE + 3 scenario
- [ ] **s.3** `git mv openspec/changes/2026-07-15-stock-info-create → openspec/changes/archive/2026-07-15-stock-info-create`
- [ ] **s.4** git commit: `chore(archive): 归档 stock-info-create changeset（端到端验证通过）`
- [ ] **s.5** git push origin master
- [ ] **s.6** 双确认: 本地 HEAD = 远端 HEAD
- [ ] **s.7** 总结交付

---

## 总耗时预估

| 阶段 | 任务数 | 预估时间 |
|---|---|---|
| Phase 1 | 5 | 5 分钟 |
| Phase 2 | 6 | 10 分钟 |
| Phase 3 | 7 | 15 分钟 |
| Phase 4 | 4 | 10 分钟 |
| Phase 5 | 7 | 8 分钟 |
| **合计** | **29** | **48 分钟** |