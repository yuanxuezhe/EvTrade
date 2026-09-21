# Tasks — 2026-09-18-position-table-sortable

## P0 — DataTableView 扩展 sortFn

- [ ] `client/src/components/DataTableView.vue` 列定义结构注释加 `sortFn: (row) => any` 字段
- [ ] `client/src/components/DataTableView.vue` Props 头部文档加 `sortFn` 说明
- [ ] `client/src/components/DataTableView.vue` `sortCompare` + `sortedData` 优先用 sortFn，缺省回退 row[prop]
- [ ] `client/tests/components/dataTableView_sort.test.js` 新建：3 case 覆盖 sortFn 优先 / 缺省回退 / null 兜底

## P1 — HoldingsPanel 4 列开启 sortable

- [ ] `client/src/components/trade/HoldingsPanel.vue` 市值列 `sortable: false → 'custom'` + 加 sortFn
- [ ] 同上，当日盈亏列
- [ ] 同上，浮动盈亏列
- [ ] 同上，收益率列
- [ ] 行情驱动：确保 sortFn 调用 getter 时 quoteTickTrigger 触发响应式（已有 `void quoteTickTrigger.value` 模式可复用）

## P2 — 验证

- [ ] `cd client && npx vitest run client/tests/components/dataTableView_sort.test.js` 通过
- [ ] `cd client && npm run build` 通过（vue-tsc + vite build）
- [ ] `cd .. && pytest server/tests/ -v` 基线 58/58 不破

## P3 — 知识库 + spec 同步

- [ ] `知识库/前端/页面/资产与持仓.md` § 持仓实时市值 后追加排序能力小节
- [ ] `openspec/specs/frontend/spec.md` 末尾新增 REQ-FE-540: HoldingsPanel 4 列 sortable

## P4 — 归档

- [ ] `git add` 前 `git diff --stat` 看改动单一性（前端 + 知识库 + spec，零后端）
- [ ] 按 v6 拆 2 个 commit：① 代码（DataTableView + HoldingsPanel + test） ② 知识库 + spec merge
- [ ] `mv openspec/changes/2026-09-18-position-table-sortable openspec/changes/archive/`
- [ ] `openspec/AGENTS.md` 当前活跃 change 表追加 1 行（待归档后改✅）
