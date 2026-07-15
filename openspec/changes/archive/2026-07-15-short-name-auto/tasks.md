# Tasks: short_name 自动生成 + ST 前缀保留 (v46+ short-name-auto)

> **对照 proposal.md 执行** — 每完成一项勾选 [x]

---

## Phase 1: OpenSpec 工件（前置）

- [ ] **t.1** 建 changeset 目录 `openspec/changes/2026-07-15-short-name-auto/{spec-deltas}`
- [ ] **t.2** 写 `proposal.md`（背景 + 目标 + 非目标 + 影响面 + 风险表 + 待拍板清单）
- [ ] **t.3** 写 `tasks.md`（本文档，5 阶段 26 子任务）
- [ ] **t.4** 写 `spec-deltas/stocks.md`（REQ-STOCK-007 自动生成 + ST 规则）
- [ ] **t.5** 写 `spec-deltas/frontend.md`（REQ-FE-STOCK-HIDE 隐藏 short_name 编辑界面）

---

## Phase 2: 后端实施

- [ ] **t.6** 新建 `server/services/short_name.py`
  - 导出 `to_short_name(stock_name: str) -> str`
  - ST 前缀检测：`*ST` / `ST`（4 种大小写组合）
  - 拼音首字母转大写
  - 16 字符上限
  - 失败/空字符串返回 ""

- [ ] **t.7** 重构 `server/scripts/backfill_short_name.py`
  - 删除本地 `to_short_name()` 函数副本
  - 改为 `from server.services.short_name import to_short_name`
  - 脚本行为不变（v25 已 backfill 过，仅重构）

- [ ] **t.8** 改 `server/api/stocks.py`
  - `StockCreateRequest` Pydantic **删除 short_name 字段**
  - `StockUpdateRequest` Pydantic **删除 short_name 字段**
  - 更新顶部 docstring（v25 7 字段白名单 → v46+ 6 字段自动生成）
  - 更新 endpoint docstring

- [ ] **t.9** 改 `server/repo/stocks.py`
  - `create_by_admin()` **不再接受 short_name**，自动调 `to_short_name(stock_name)` 写入
  - `update_by_admin()` 检测 stock_name 字段是否在 payload 里
    - 如果在，调 `to_short_name()` 重算 short_name
    - 如果不在（仅改其他字段），保留旧 short_name
  - 更新顶部 7 字段白名单注释为 6 字段自动生成

---

## Phase 3: 前端实施

- [ ] **t.10** 改 `client/src/views/AdminStockConfig.vue`
  - 删"首字母"列（第 109-113 行）
  - 删编辑 dialog 中 short_name input（第 165-167 行）
  - 删添加 dialog 中 short_name input（第 219-221 行）
  - 删 form 默认值 short_name: ''（第 307 行）
  - 删 form 校验规则 short_name: [{...}]（第 329 行）
  - 删提交函数中 short_name: ...（第 353 行）
  - **保留**客户端搜索 keyword 二次过滤用 short_name（第 388 行）
  - 更新顶部注释（第 7/14 行，移除 short_name 提到）

---

## Phase 4: 测试与验证

- [ ] **t.11** 单元测试 `to_short_name()` 函数
  - 平安银行 → PAYH
  - 贵州茅台 → GZMT
  - *ST实达 → *STSD
  - ST华微 → STHW
  - *st康佳 → *STKJ（大小写不敏感）
  - st美丽 → STMЛ
  - 空字符串 / None → ""
  - 数字开头的混合（如 ST12测试）→ ST... (字母优先)

- [ ] **t.12** 后端 curl 测试
  - POST /api/stocks {stock_name: "*ST测试股"} → 201 + short_name=*STCSG
  - PATCH 改 stock_name → short_name 自动重算
  - PATCH 改 sector 但不改 stock_name → short_name 保持不变
  - 旧版本带 short_name 字段的请求 → 422 Pydantic 忽略（extra=forbid）

- [ ] **t.13** 浏览器实测
  - 访问 /admin/stock-config 看"首字母"列已隐藏
  - 打开添加对话框看没有 short_name 输入
  - 打开编辑对话框看没有 short_name 输入
  - 添加一只 "ST测试股" → 表格显示 stock_name="ST测试股"，但已查不到 short_name 列

---

## Phase 5: 归档与提交

- [ ] **t.14** commit.1 - backend (4 files: services/short_name.py + scripts/backfill_short_name.py + api/stocks.py + repo/stocks.py)
- [ ] **t.15** commit.2 - frontend (1 file: AdminStockConfig.vue)
- [ ] **t.16** 应用 spec-deltas 到 `openspec/specs/{stocks,frontend}/spec.md`
- [ ] **t.17** 归档 changeset 到 `openspec/changes/archive/2026-07-15-short-name-auto/`
- [ ] **t.18** commit.3 - docs(spec) + 归档
- [ ] **t.19** push 3 commits 到 origin/master
- [ ] **t.20** 汇报交付总结

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 现有 short_name 数据错（如 ST→SHW）| 不重算，保留现状 |
| ST 前缀大小写变体漏判 | 4 种大小写组合都查 |
| 前端残留 short_name 引用导致 404 | 提交前 grep 验证 |
| Pydantic extra=forbid 导致旧客户端请求 422 | 前端同步删字段 |
| commit 跨多文件难 review | 按 backend / frontend / spec 拆 3 commit |
