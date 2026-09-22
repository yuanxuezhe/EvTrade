# REQ-AUTH-014: 角色管理与细粒度 RBAC (rbac-roles-module 2026-09-21)

EvTrade 系统从单字段 `users.role` 字符串 (admin/trader/viewer) 升级为多对多角色 + 页面权限配置。

## 数据模型

3 张表 (migration `2026-09-21-add-roles-user-roles-permissions.py` 幂等)：

- `roles (id PK, name UK, display_name, description, is_builtin, created_at, updated_at)`
- `user_roles (user_id FK, role_id FK, granted_at, granted_by) PK(user_id, role_id) CASCADE`
- `role_permissions (role_id FK, page_key VARCHAR(64), granted_at) PK(role_id, page_key) CASCADE; page_key='*' 通配`

## 4 预置 role

| name | display | 默认 page_keys | is_builtin |
|---|---|---|---|
| super_admin | 超级管理员 | `*` (通配) | 1 |
| admin | 管理员 | 13 page (admin/* + cache/*) | 1 |
| trader | 交易员 | 11 page (trade/t0/strategy/script/cache) | 1 |
| viewer | 观察者 | 5 page (dashboard/asset/cache-orders/-trades/-positions) | 1 |

## API 端点 (全 require_admin)

```
GET    /api/roles                          列出所有角色 + 各自 page_keys
GET    /api/roles/{id}                     单角色详情
POST   /api/roles                          新建角色 (name UK + 初始 page_keys)
PATCH  /api/roles/{id}                     改 display_name / description (name + is_builtin 不可改)
DELETE /api/roles/{id}                     删角色 (内置 is_builtin=1 不可删, 400)
GET    /api/roles/{id}/permissions         该角色 page_keys
PUT    /api/roles/{id}/permissions         整体覆盖 page_keys (super_admin 必保留 '*')
GET    /api/roles/users/{user_id}/roles    用户已绑定角色 + page_keys
PUT    /api/roles/users/{user_id}/roles    整体覆盖用户角色
```

## 4 道防锁死

1. 内置 role 不可 DELETE → 400 `BUILTIN_ROLE`
2. super_admin 不能去掉 `'*'` → 400 `SUPER_ADMIN_NEEDS_WILDCARD`
3. 不能解绑最后 super_admin → 400 `LAST_SUPER_ADMIN`
4. role_name 不存在 → 404 `ROLE_NOT_FOUND`

## 向后兼容

- `users.role` 字符串字段保留; PATCH /users/{id} body 加 `role_names` 整体覆盖时自动派生 (`derive_users_role_from_names`)
- 旧 admin/trader/viewer 路由 meta `requiresAdmin/Trader` 保留作 fallback; 新 RBAC 用户走 `meta.pageKey` + `hasPageKey`
- `GET /api/auth/me` 响应加 `roles: [{id,name,display_name,is_builtin,page_keys}]` 字段; 老 user 无 roles 时前端 store 的 `hasPageKey()` 走 isAdmin/isTrader/isViewer 字符串 fallback

## 首次部署

`python3 server/migrations/2026-09-21-add-roles-user-roles-permissions.py` — 幂等 INSERT IGNORE, 已存在不重复.

## 测试

`server/tests/services/rbac/test_rbac.py` — 23 case (helpers + 整体覆盖 + 派生)