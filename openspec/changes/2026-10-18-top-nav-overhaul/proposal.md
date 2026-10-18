# top-nav-overhaul — 前端顶部导航改版 (2026-10-18)

## 解决什么

当前前端采用 **"桌面左侧 Sidebar 297 行 + AppHeader 头部右侧 / 手机底部 BottomNav 105 行"** 的混合 3 套导航结构。要改成 **"桌面顶部 TopNav 5 组下拉 + 手机底部 BottomNav（保留）"** 形态，参照 OKX 顶部导航结构（Logo → 5 列分组下拉 → 右侧工具区）。

注意：
- 这不是视觉调整，是**布局重构** —— 涉及新增 `TopNav.vue`、删除 `Sidebar.vue`、调整 `App.vue`、清理 `stores/ui.js` 的 `sidebarCollapsed` 状态
- 不改 router，不改 pageKey，不改 RBAC 模型（仍走 `PAGE_NAV_TREE` 单一事实源 + `authStore.hasPageKey` filter）
- 不改 view 本身（12 个 view 业务代码零改动）

## 现状

| 组件 | 行数 | 角色 |
|---|---|---|
| Sidebar.vue | 297 | 桌面左导航，可折叠 |
| AppHeader.vue | 555 | 顶部右侧（RPC 状态 / 行情状态 / 总资产 / 主题切换 / 用户下拉）|
| BottomNav.vue | 105 | 手机端底部 5 个 tab |
| NavBar.vue | 10 | **孤儿文件**（无引用，占位 el-menu，早期残留）|

## 目标态

```
[ EvTrade Logo ] [ 交易▾ ] [ 资金▾ ] [ 策略▾ ] [ 管理▾ ] [ 系统▾ ] .............. [ AppHeader 右侧工具区整体搬过来 ]
```

### 5 组下拉内容

| 组 | 子菜单 | 来源 router pageKey |
|---|---|---|
| **交易** | 自选池 / 交易下单 / 快速做T | `stkpool-view` / `trade` / `t0-trade` |
| **资金** | 账户资金 | `asset` |
| **策略** | 策略开发 / 策略运行 / 策略下单母单 | `script-dev` / `script-task` / `strategy-order` |
| **管理** | 用户管理 / 角色管理 / 证券池 | `users` / `roles` / `stkpool` |
| **系统** | 系统初始化 / 系统配置 / 证券信息设置 / 历史行情补全 | `system-init` / `system-config` / `admin-stock-config` / `data-completion-history-quote` |

不含（路由保留但不属于 TopNav 显式分组）：
- **仪表盘 `/`**（默认页，TopNav 不直接列）
- **个人资料 `/profile`**（走 AppHeader 用户下拉）
- **交易查询 cache-asset / cache-positions / cache-orders / cache-trades**（admin 内部工具，保留 router 不上 TopNav —— 走 /admin/cache/* 旧链接访问）
- **登录页 `/login`**（public）
- **403 Forbidden**（public）

### 组件生命周期

| # | 内容 | 类型 |
|---|---|---|
| 1 | 删 `Sidebar.vue` | `chore(frontend): rm` |
| 2 | 删孤儿 `NavBar.vue` | `chore(frontend): rm` |
| 3 | 新建 `TopNav.vue`（5 组下拉、el-menu 横向 + el-sub-menu）| `refactor(frontend): add TopNav` |
| 4 | `App.vue` 拆 Sidebar → TopNav + 删除 uiStore.sidebarCollapsed 引用 | `refactor(frontend): App.vue layout` |
| 5 | `stores/ui.js` 删除 sidebarCollapsed 字段 + toggleSidebar action | `refactor(frontend): ui store cleanup` |
| 6 | 跑 `npm run build` 验证通过 | 验证 |
| 7 | 桌面 chrome 实测 5 组下拉 + RBAC filter 生效 | 验证 |

### 移动端

**保留 BottomNav** — 105 行不动。手机端屏幕宽度放 5 组下拉顶 nav 不现实，BottomNav 5 个 tab 是行业通用做法。
不动 `client/src/components/BottomNav.vue`。
不动 `client/src/components/AppHeader.vue` 的 mobile hamburger 逻辑（mobile chip / Hamburger button）。

### 关键设计约束

1. **PAGE_NAV_TREE 是 RBAC 角色管理 UI 的单一事实源**（Roles.vue 用其渲染「页面权限」多选）—— 本次不改。
2. **TopNav 5 组是独立的信息架构**（仅菜单展示层），不复用 PAGE_NAV_TREE 的 6 业务域结构。
   TopNav 自己定义 `pageKey → group` 映射（5 组），与 PAGE_NAV_TREE 共用同一套 pageKey 命名（数据维度一致）。
   跟 OKX 顶部 nav 一样是独立的视觉聚合——同行业实践。
3. **router meta.pageKey 守卫不动**——rbac-roles-module 已立。
4. **AppHeader 内部逻辑不动**——右侧工具区内容（RPC 状态/总资产/主题切换/用户下拉）原样留在 AppHeader；
   TopNav 在 AppHeader 之上，AppHeader 仍是右侧工具区唯一拥有者。
5. **TopNav 不显示 hidden pageKey**：跟 Sidebar 一样，过滤后空组不渲染。
6. **mobileSidebarOpen / 移动端 drawer 全部废弃**——重构后桌面用 TopNav、手机用 BottomNav，无需抽屉。

## 不做什么

- ❌ 不改 router、pageKey、RBAC 模型
- ❌ 不改 view 业务代码（12 个 view）
- ❌ 不改 BottomNav（保留移动端底 tab）
- ❌ 不动 AppHeader 内部逻辑，只删除 sidebarCollapsed 相关
- ❌ 不动 AuthStore / PAGE_NAV_TREE
- ❌ 不强制清表 / 删 migration / 改后端

## 分支 / tag

- 起点 tag: `baseline-pre-layout-overhaul-2026-10-18`
- branch: `feature/top-nav-overhaul`（基于 tag）
- 完成合并: 暂定 merge 回 master（非 fast-forward 保留拓扑）

## 风险

- ⚠️ 改 App.vue 拆 layout 会触发 `npm run build` 失败的可能（侧栏宽度调整 / 老 CSS）。commit 前必验 `npm run build`。
- ⚠️ TopNav 的 el-menu mode="horizontal" 与 el-sub-menu 在深色主题下渲染样式不一致；需要测试 dark/light 两套。
- ⚠️ 用户已习惯折叠的 Sidebar；重构后无折叠动作（顶部 nav 不折叠），需要文档 / 用户通知。
