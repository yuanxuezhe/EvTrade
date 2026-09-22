# tasks — rbac-roles-module

> 编程更新规则：拆 2-5 分钟粒度细任务，每完成一项立即汇报

## P0 — spec / 开 spec change

- [x] 创建 `openspec/changes/2026-09-21-roles-module/`
- [x] proposal.md（解决什么 + 设计 + 风险）
- [x] tasks.md（本文件）
- [ ] spec-deltas/auth.md（REQ-AUTH-012 角色管理与细粒度权限）
- [ ] spec-deltas/frontend.md（REQ-FE-548 page_key 路由守卫）
- [ ] spec-deltas/data-model.md（3 张表 schema）
- [ ] 用户拍板 spec，merge 进 specs/

## P1 — 后端 schema + tables

- [ ] `server/schema.yml` 加 3 张表定义 (roles / user_roles / role_permissions)
- [ ] `server/tables/base.py` 或新建 `server/tables/rbac.py`，3 个 dataclass
- [ ] 跑 `python scripts/sync_schema.py` 同步
- [ ] alembic migration：(a) CREATE TABLE 3 表 (b) seed 4 预置 role + INSERT IGNORE grant 现有 users.role
- [ ] 验证：`pytest server/tests/services/rbac/` 新增空 pass（占位，给后续 test 跑）

## P2 — 后端 services + api

- [ ] `server/services/rbac.py`：`get_user_page_keys(user_id) -> set[str]`、`get_user_roles(user_id) -> list[role]`
- [ ] `server/services/guards.py`：加 `require_page_key(key: str)` FastAPI dep
- [ ] `server/api/roles.py`：CRUD + grant/revoke permissions
- [ ] `server/main.py`：注册 router
- [ ] test：`test_rbac.py` 单测 guard + helpers（**禁清表**——直读 INSERT 的 4 预置 role，临时 grant t_ 前缀 test user）

## P3 — 前端 router + store

- [ ] `client/src/router/index.js`：加每路由 `meta.pageKey`，guards 用 hasPageKey
- [ ] `client/src/stores/auth.js`：userRoles / hasPageKey computed / fetchUserInfo 加 roles
- [ ] `client/src/api/roles.js`：CRUD + permissions

## P4 — 前端视图

- [ ] `client/src/views/Roles.vue`：左角色列表 + 右权限多选
- [ ] `client/src/router/index.js`：注册路由（meta.pageKey='roles'）/ Sidebar nav 列表项（admin 下）
- [ ] `client/src/components/Sidebar.vue` + `BottomNav.vue`：filter 用 hasPageKey
- [ ] `client/src/views/Users.vue`：用户编辑加多角色多选
- [ ] `client/src/components/users/UserEditDialog.vue`：多角色

## P5 — 验证

- [ ] 后端：`pytest server/tests/` 全过（**单文件**，永远不跑全套，按规）
- [ ] 前端：`npm run build` 编译零错
- [ ] 双向 import 校验：grep `<RolesView` 没就坏 + `import` 都齐
- [ ] browser E2E（手动）：admin 登录 → 进角色管理 → 建角色配权限 → 给用户赋 → 切该用户登录 → 路由守卫生效

## P6 — 同步

- [ ] `知识库/前端/路由与权限.md`：加 REQ-FE-548 路由 page_key 守卫
- [ ] `知识库/后端服务/`：新增 `角色管理.md`
- [ ] OpenSpec AGENTS.md 活跃 change 表追新一行

## 进度汇报

每完成一阶段立即汇报当前状态 + 改了哪些文件 + 跑测试结果，绝不连做（避免大改后无法定位）。
