# Tasks: top-nav-overhaul

## C1 — OpenSpec change 工件（1 commit）

- [x] proposal.md
- [x] spec-deltas/frontend.md（REQ-FE-555 段加 + 旧 Sidebar 段废止注记）
- [x] tasks.md

## C2 — spec merge（1 commit）

- [ ] `openspec/specs/frontend/spec.md` 加 `## REQ-FE-555: 前端顶部导航改版（top-nav-overhaul 2026-10-18）` 段
- [ ] 5 组分组语义 + RBAC 单源 + 不动 BottomNav 写明

## C3 — TopNav 实现 + App.vue layout（1 commit）

- [ ] 新建 `client/src/components/TopNav.vue`：
  - `<el-menu mode="horizontal">` + 5 个 `el-sub-menu` 包裹 `el-menu-item`
  - 标题 = 从 import 进来的固定分组（`groupLabels = { trading: '交易', asset: '资金', strategy: '策略', admin: '管理', system: '系统' }`）
  - 子菜单项 = 通过 pageKey 反查 router meta.title（用 router.resolve）
- [ ] `client/src/App.vue`：
  - 删 `<Sidebar>` import + `<aside class="sidebar-wrap">` 块
  - 新增 `<TopNav>` import + 顶部 slot
  - 保留 `<AppHeader>` 不动
  - 保留 `<BottomNav>` 不动
- [ ] `client/src/styles/` 相关：sidebar 容器 CSS / 折叠按钮 CSS 可清理（保留以防兜底，commit 时不删）

## C4 — ui store 清理（1 commit）

- [ ] `client/src/stores/ui.js`：
  - 删 `sidebarCollapsed` state
  - 删 `toggleSidebar` action
- [ ] 验证全仓 `sidebarCollapsed` 引用清零：
  - `grep -rE "sidebarCollapsed" client/src/` 应 0 命中
  - （AppHeader 的 `uiStore.isMobile / uiStore.toggleTheme` 保留）

## C5 — 删 Sidebar.vue + NavBar.vue（1 commit）

- [ ] `git rm client/src/components/Sidebar.vue`
- [ ] `git rm client/src/components/NavBar.vue`（孤儿占位）
- [ ] 验证 `npm run build` 不报 missing import

## C6 — 验证（不 commit）

- [ ] `npm run build` 通过
- [ ] `vite dev` 桌面 chrome 实测：
  - 5 组下拉点击展开子菜单
  - RBAC：viewer 用户看不到"管理 / 系统"组（hasPageKey filter）
  - 路由跳转正常（自选池 / 交易下单 / 快速做T / 角色管理 都点得到）
- [ ] mobile chrome 实测：
  - BottomNav 仍工作
  - TopNav 在 mobile (<768) 隐藏（按 el-menu mode="horizontal" + 显式 hide-on-mobile CSS）

## C7 — 合并回 master（用户拍板后）

- [ ] `git push origin feature/top-nav-overhaul`
- [ ] `git checkout master`
- [ ] `git merge --no-ff feature/top-nav-overhaul -m "Merge feature/top-nav-overhaul — 前端顶部导航改版"`
- [ ] `git push origin master`
- [ ] 删除 feature 分支（`git branch -d feature/top-nav-overhaul` + `git push origin --delete feature/top-nav-overhaul`）
