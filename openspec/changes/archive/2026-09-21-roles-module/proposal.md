# rbac-roles-module（角色管理 + 页面权限）— 2026-09-21

## 解决什么

EvTrade 现有 RBAC 粒度过粗：
- **后端** `users.role` 单值字段（admin/trader/viewer 硬编码字符串），`server/services/guards.py` 只判 `role in ('admin','trader')`
- **前端** router meta 仅支持 `requiresAdmin` / `requiresTrader` 两个静态标记，admin 看所有页面、trader 看交易页、viewer 只读——无法自定义
- 各 API 端点各自硬编码 `require_admin` 装饰器

需求：
1. 在**系统管理**下、`用户管理`**上面**新增**角色管理**页面
2. 在角色管理创建/编辑/删除**角色**，给角色配**页面权限**（多选前端路由 page_key）
3. **用户管理**给用户**一个或多个**角色
4. 用户登录后，前端用集合并集判定：用户拥有的所有角色任一含该 page_key → 可访问；前端 router 守卫 + 后端 API `require_page_key` 双层

## 设计

### 数据模型

新建 3 表（migration 用 `CREATE TABLE`，不 DROP/TRUNCATE）：

| 表 | 列 | 说明 |
|---|---|---|
| `roles` | `id` PK auto / `name` unique String(64) / `display_name` String(128) / `description` String(255) nullable / `is_builtin` TinyInt default 0 / `created_at` / `updated_at` | 角色定义，is_builtin=1 不可删（super_admin/admin/trader/viewer） |
| `user_roles` | `user_id` FK→users.id / `role_id` FK→roles.id / `granted_at` / `granted_by` FK→users.id nullable / PK(user_id, role_id) | 多对多：一个用户多个角色 |
| `role_permissions` | `role_id` FK→roles.id / `page_key` String(64) / `granted_at` / PK(role_id, page_key) | 角色→页面授权 |

### 预置角色（migration seed）

| name | display_name | 默认 page_keys | is_builtin |
|---|---|---|---|
| `super_admin` | 超级管理员 | `*`（全部页面） | 1 |
| `admin` | 管理员 | 除需 super_admin 之外的 admin/数据补全/查询页 | 1 |
| `trader` | 交易员 | dashboard / trade / t0-trade / strategy-order / script-dev / script-task / stkpool / asset / cache-orders / cache-trades | 1 |
| `viewer` | 观察者 | dashboard / asset / cache-orders / cache-trades / cache-positions | 1 |

### 向后兼容

- `users.role` 字符串字段保留（不删，**禁清表硬规**）
- seed migration：把现有 `users.role='admin'` 自动 grant 一份 `roles.name=super_admin`（用 `INSERT IGNORE INTO user_roles`，幂等可重跑）
- `guards.py` 的 `current_user.role in ('admin','trader')` 既存逻辑**保留**作 fallback，新逻辑在它之上叠加：`if (user_roles 命中 super_admin) or has_page_key(page_key) → 通过`
- 前端 router 守卫：保留 `requiresAdmin/Trader` 旧 meta，新逻辑用 `requiresPage` meta（未提供则 fallback requireAdmin 行为）

### 前端集成

1. `client/src/router/index.js`：
   - 给每条路由加 `meta.page_key`（系统自动从 path 派生 `@/views/...` 名）
   - 新增 `meta.requiresPage: ['trade.t0']` 或更简单 `meta.requiresRole: 'admin'`（高级写法）
   - guards: `auth.hasPageKey(page_key)` → 查 auth store user 的 role 集合并集

2. `client/src/stores/auth.js`：
   - 增加 `userRoles` ref（`[{id, name, display_name, permissions: [page_key, ...]}, ...]`）
   - `hasPageKey(key)` computed
   - `fetchUserInfo` 增加 `roles` 字段

3. `client/src/views/Roles.vue`（新）：
   - 左：角色列表（CRUD，含 4 个预置不可删标记）
   - 右：选中角色的详情 / 页面权限多选（按 page_key 分组：交易 / 策略 / 管理 / 系统）

4. `client/src/views/Users.vue`：
   - 行详情 / 编辑 dialog 增加"角色"多选（按 role.name 数组提交，替代/并存 users.role 字符串）
   - `users.role` 字段显示第一个角色名（兼容）

## 影响面

| 层 | 影响 | 说明 |
|---|---|---|
| 后端 schema | +3 表 (roles/user_roles/role_permissions) | ADD/CREATE only，禁清表 |
| 后端 API | + `server/api/roles.py` (CRUD + permissions) | 全部 require_admin |
| 后端 services | + `server/services/rbac.py` (helpers) | `get_user_page_keys(user_id) -> set[str]` |
| 后端 guards | `server/services/guards.py` | 加 `require_page_key(key)` dep |
| 后端 tables | + `server/tables/rbac.py` 或 追加到 `tables/base.py` | 3 ORM-like dataclass |
| migration | alembic 2 个 migration | (a) 创建 3 表 (b) seed 4 预置 role + grant 现有用户 |
| 前端 router | `client/src/router/index.js` | 加 page_key 守卫 |
| 前端 store | `client/src/stores/auth.js` | userRoles + hasPageKey |
| 前端 view | `client/src/views/Roles.vue` | 新 |
| 前端 view | `client/src/views/Users.vue` | 改用户编辑 |
| 前端 view | `client/src/views/Sidebar.vue` / `BottomNav.vue` | 权限 filter 用 hasPageKey |
| 前端 api | `client/src/api/roles.js` | 新 |
| 知识库 | `知识库/前端/路由与权限.md` + `知识库/后端服务/角色管理.md`（如无） | 新 + 同步 |

## 风险

| 风险 | 缓解 |
|---|---|
| **禁清表硬规**：现有 admin 账号用户丢失权限锁死 | seed migration 用 `INSERT IGNORE`，幂等；保留 users.role 字符串字段 fallback |
| 后端无 page_key 检查被绕过 | 逐步迁移：先做后端 `require_page_key` + 守卫；前端 guard 仅做 UX 不做安全 |
| super_admin 用户配错权限锁死自己 | `*` 是个特殊 page_key，guard 直接通过；UI 单独标星不允许取消 |
| 大量路由需加 page_key | meta 上加 `pageKey` 常量映射（page_key → 显示名），routes 加一行元即可 |

## 不在范围

- 按钮/字段级细粒度权限（只做页面级）
- 角色继承（role hierarchy）
- 多租户
- 临时提权 / 权限申请流
