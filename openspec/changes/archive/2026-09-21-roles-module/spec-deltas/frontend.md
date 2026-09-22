# REQ-FE-548: router page_key 守卫 (rbac-roles-module 2026-09-21)

## 路由 meta

每条路由加 `meta.pageKey` 字段 (与 RBAC role.page_key 对齐):

| 路由 | pageKey |
|---|---|
| `/` | `dashboard` |
| `/stkpool-view` | `stkpool-view` |
| `/trade` | `trade` |
| `/asset` | `asset` |
| `/profile` | `profile` |
| `/t0-trade` | `t0-trade` |
| `/system-config` | `system-config` |
| `/system-init` | `system-init` |
| `/users` | `users` |
| `/roles` | `roles` |
| `/admin/cache/asset` | `cache-asset` |
| `/admin/cache/positions` | `cache-positions` |
| `/admin/cache/orders` | `cache-orders` |
| `/admin/cache/trades` | `cache-trades` |
| `/admin/stock-config` | `admin-stock-config` |
| `/data-completion/history-quote` | `data-completion-history-quote` |
| `/stkpool` | `stkpool` |

## router.beforeEach 守卫优先级

1. `meta.public` → return true (含 /login + /forbidden)
2. 未登录 → 跳 `/login?redirect=原路径`
3. `meta.pageKey` 存在 + `user.roles` 数组非空 (`hasRbac=true`) → `hasPageKey(pageKey)` 判定, 否则跳 `/forbidden`
4. `meta.requiresAdmin` → `isAdmin` 否则跳 `/`
5. `meta.requiresTrader` → `isTrader` 否则跳 `/`

## 死循环防护

- 严禁 `return { path: '/' }` —— vue-router 4 检测 from===to=/= 报 infinite redirect
- 替代: 跳 `/forbidden` (name: 'Forbidden', meta.public=true)
- 老 store 无 `user.roles` 字段 → `hasRbac=false` → 宽松 fallback 到老 requiresAdmin/Trader, 防新 user 升级过渡期死锁

## hasPageKey 双层判定 (stores/auth.js)

- 新 user (有 `roles` 字段): RBAC 角色集合并集, 任一 role 含 `'*'` 通配 → true
- 老 user (fallback): `isAdmin` 全通; `isTrader` 命中 TRADER_KEYS; `isViewer` 命中 VIEWER_KEYS

## 文件清单

| 文件 | 说明 |
|---|---|
| `client/src/router/index.js` | 路由表 (含 pageKey meta) + beforeEach 守卫 |
| `client/src/stores/auth.js` | userRoles/pageKeys/hasPageKey + 老 fallback |
| `client/src/views/Forbidden.vue` | 拒绝页 (el-result + 返回首页按钮) |
| `client/src/utils/pageNavTree.js` | 6 业务域树 (Sidebar/Roles 单源) |

---

# REQ-FE-549: 用户管理 UI 加多角色编辑 (rbac-roles-module 2026-09-21)

## 列表 / 列

- 角色列从单 chip 改为多 `el-tag` (r.is_builtin=1 时 warning 黄)
- 无 RBAC role (老 user) fallback 显示 `users.role` 字符串

## 编辑 dialog (UserEditDialog.vue)

- 新建: 单 radio-group (admin/trader/viewer) (向后兼容 POST /users)
- 编辑: 多 `el-checkbox-group` 拉所有 role; super_admin 对当前 admin 用户禁勾 (防锁死)

## 提交

- `userApi.update(id, {role_names: [...]})` —— 后端整体覆盖 user_roles + 自动派生 users.role

## countByRole 派生

- 优先按 `row.roles` 内 role.name 分桶 (admin 类 → 'admin', 含 trader → 'trader', 否则 viewer)
- fallback 到 `users.role` 字符串 (兼容老 user)