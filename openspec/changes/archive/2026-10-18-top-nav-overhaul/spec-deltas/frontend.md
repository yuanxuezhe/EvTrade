# REQ-FE-555: 前端顶部导航改版 (top-nav-overhaul 2026-10-18)

## 改什么

### 改动 1：新增 `## REQ-FE-555` 段（追加到 frontend/spec.md 末段）

`openspec/specs/frontend/spec.md` 末尾追加：

```markdown
## REQ-FE-555: 前端顶部导航改版 (top-nav-overhaul 2026-10-18)

EvTrade 前端从「桌面左 Sidebar + 顶部 AppHeader + 手机 BottomNav 三套混合」
改为「桌面顶部 TopNav 5 组下拉 + 手机 BottomNav（保留）」形态。
参考 OKX 顶部导航（Logo → 5 列分组下拉 → 右侧工具区）。

### 布局

```
[ EvTrade Logo ] [ 交易▾ ] [ 资金▾ ] [ 策略▾ ] [ 管理▾ ] [ 系统▾ ] ...... [ AppHeader 右侧工具区 ]
```

### 5 组下拉内容

| 组 | 子菜单 |
|---|---|
| 交易 | 自选池 (stkpool-view) / 交易下单 (trade) / 快速做T (t0-trade) |
| 资金 | 账户资金 (asset) |
| 策略 | 策略开发 (script-dev) / 策略运行 (script-task) / 策略下单母单 (strategy-order) |
| 管理 | 用户管理 (users) / 角色管理 (roles) / 证券池 (stkpool) |
| 系统 | 系统初始化 (system-init) / 系统配置 (system-config) / 证券信息设置 (admin-stock-config) / 历史行情补全 (data-completion-history-quote) |

### 行为约束

- 5 组菜单在 RBAC 下走 `authStore.hasPageKey` filter（与 Sidebar 同语义）
- 全部 pageKey 不通过时该组不渲染
- `PAGE_NAV_TREE` 仍是单一事实源；TopNav 直接消费同一棵树
- AppHeader 右侧工具区（RPC 状态 / 行情状态 / 总资产 / 主题切换 / 用户下拉）原样保留
- 移动端（< 768px）TopNav 隐藏，BottomNav 仍工作

### 组件生命周期

- 新建 `client/src/components/TopNav.vue`
- 删除 `client/src/components/Sidebar.vue`（旧左导航，297 行）
- 删除孤儿 `client/src/components/NavBar.vue`（10 行占位文件，无引用）
- 保留 `client/src/components/AppHeader.vue` 不动内部逻辑，只删除 `sidebarCollapsed` 引用
- 保留 `client/src/components/BottomNav.vue` 不动
- `client/src/stores/ui.js` 删除 `sidebarCollapsed` state 与 `toggleSidebar` action

### 不做什么

- ❌ 不改 router / pageKey / RBAC 模型
- ❌ 不改 12 个 view 的业务代码
- ❌ 不动底部 BottomNav
- ❌ 不动 AppHeader 的主要逻辑
```

### 改动 2：`## REQ-FE-547`（标的组件全站统一）等不动的段位 — 旧 Sidebar 段如存在，加废止注记

如果 spec.md 里有 Sidebar 段（暂未确认），加块引用注记：

```markdown
> **废止注记（2026-10-18 top-nav-overhaul）**：本段描述的桌面左 Sidebar 已废弃，
> 由 REQ-FE-555 顶部 TopNav 取代。详见 change `2026-10-18-top-nav-overhaul`。
```

## 不改什么

- 任何业务 view / router / RBAC
- 任何后端
- 任何 KB 业务文档（KB 引用会在 C7 合并后再统一修）
