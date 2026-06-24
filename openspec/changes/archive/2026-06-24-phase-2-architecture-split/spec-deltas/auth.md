# REQ-AUTH-006..010: auth spec 扩（profile + 改密）

## ADDED Requirements

### REQ-AUTH-006: 个人资料查看

- **位置**：`/api/auth/me` GET → 返回当前用户 `{id, username, role, created_at, last_login_at}`
- **view**: `client/src/views/Profile.vue`
- 详见 `auth/spec.md` REQ-AUTH-006

### REQ-AUTH-007: 修改密码（自己）

- **位置**：`/api/auth/change-password` POST `{old_password, new_password}`
- **view**: `client/src/components/ChangePasswordDialog.vue`
- 详见 `auth/spec.md` REQ-AUTH-007

### REQ-AUTH-008: 管理员重置密码

- **位置**：`/api/auth/admin/reset-password` POST `{user_id, new_password}` (admin only)
- **view**: `client/src/components/users/UserResetPwdDialog.vue`
- 详见 `auth/spec.md` REQ-AUTH-008

### REQ-AUTH-009: 管理员创建/编辑用户

- **位置**：`/api/users` POST/PUT (admin only)
- **view**: `client/src/components/users/UserEditDialog.vue`
- 详见 `auth/spec.md` REQ-AUTH-009

### REQ-AUTH-010: 用户列表 + 角色管理

- **位置**：`/api/users` GET (admin only) → 返回用户列表 + 角色
- **view**: `client/src/views/Users.vue`
- 详见 `auth/spec.md` REQ-AUTH-010

详见归档 `archive/2026-06-24-phase-2-architecture-split/`
