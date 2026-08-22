# Tasks — ScriptDev 脚本编辑增加"公开/私有"开关

## Stage 1 — OpenSpec change（本次）

- [x] **1.1** proposal.md（引 REQ-STRAT-014）
- [x] **1.2** tasks.md

## Stage 2 — KB 同步

- [ ] **2.1** `知识库/前端/页面/策略开发与运行.md`：ScriptDev 段补"公开/私有开关（表单，保存生效，owner 可改）"
- [ ] **2.2** `知识库/后端服务/策略引擎/脚本策略模块.md`：Script 段确认前端开关

## Stage 3 — 前端实现（ScriptDev.vue）

- [ ] **3.1** `_blankForm()` 加 `is_public: false`
- [ ] **3.2** `onSelect()` 拷 `s.is_public` → form
- [ ] **3.3** `_formToPayload()` 加 `is_public: !!f.is_public`
- [ ] **3.4** 表单加 `el-switch`（公开/私有，`:disabled="isReadonly"`）

## Stage 4 — 验证 + 提交 + 归档

- [ ] **4.1** 前端验证（vite build 或 grep：createScript/updateScript payload 含 is_public）
- [ ] **4.2** commit：前端 1 commit + docs 1 commit
- [ ] **4.3** 归档 change
