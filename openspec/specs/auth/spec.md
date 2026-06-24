# auth — 身份认证与权限

## Purpose

EvTrade 是多用户交易平台，必须区分：
- **普通用户**（viewer）：看资产/委托/成交
- **交易员**（trader）：能下单/撤单
- **管理员**（admin）：能管用户、修改任意人密码

任何敏感操作都必须经过 JWT 鉴权。

## Requirements

### REQ-AUTH-001: 登录

`POST /api/auth/login` 接收 `username + password`，返回 JWT。
- 失败：401，msg 形如"用户名或密码错误"（不区分两种错误，防枚举）
- 成功：200，返回 `{access_token, token_type: "bearer", user: UserInfo}`
- 密码用 bcrypt 哈希，存 SQLite

### REQ-AUTH-002: 路由守卫

- 未登录访问受保护路由 → 重定向 `/login?redirect=<原路径>`
- 已登录访问 `/login` → 重定向 `/`
- 访问 `requiresAdmin` 路由但不是 admin → 重定向 `/`
- 访问 `requiresTrader` 路由但不是 trader/admin → 重定向 `/`

### REQ-AUTH-003: Token 续期 / 失效

- JWT 过期时间由 `JWT_EXPIRE_MINUTES` 控制（默认 60min）
- 401 响应时前端 axios 拦截器应清 localStorage + 跳 `/login`
- ❌ 当前**未实现 refresh token**，过期必须重新登录

### REQ-AUTH-004: 用户管理（admin only）

- `GET /api/users` — 列表
- `POST /api/users` — 创建
- `PATCH /api/users/{id}` — 修改角色/状态/姓名
- `POST /api/users/{id}/reset-password` — 重置密码
- `DELETE /api/users/{id}` — 禁用（不物理删除）

### REQ-AUTH-005: 自我管理

- `GET /api/auth/me` — 当前用户信息
- `PATCH /api/auth/me` — 改自己姓名
- `POST /api/auth/change-password` — 改自己密码
- ❌ `POST /api/auth/logout` 当前**是空实现**（JWT 是无状态的，logout 应仅前端清 localStorage）

### REQ-AUTH-006: GET /me — 当前用户信息

- 端点：`GET /api/auth/me`，依赖 `get_current_user`（任意登录角色可调）
- 响应：`UserInfoResponse`（`id` / `username` / `email` / `full_name` / `role` / `is_active` / `must_change_password` / `created_at` / `last_login_at`）
- **不**返回 `password_hash`（任何时候都不可外泄）
- 用途：前端 store 启动时拉一次 user 信息（auth.js `fetchUserInfo`）
- 实现位置：`server/api/auth.py::me`（line 78）

### REQ-AUTH-007: PATCH /me — 修改邮箱 / 姓名

- 端点：`PATCH /api/auth/me`，body `{email?: str, full_name?: str}`
- 行为：
  - 字段为 `null` → **不改**该字段（区分"未传"和"传 null 清空"）
  - 空字符串 → 存为 `None`（清空邮箱 / 姓名）
  - `strip()` 去除前后空格
  - 邮箱格式校验**当前未实现**（仅 strip），未来应在 schema 层加 `EmailStr`
- 不允许改 `username` / `role` / `password`（这些走 REQ-AUTH-004 admin 端点或 REQ-AUTH-008 改密）
- 响应：更新后的 `UserInfoResponse`
- 实现位置：`server/api/auth.py::update_profile`（line 83）

### REQ-AUTH-008: POST /change-password — 修改自己密码

- 端点：`POST /api/auth/change-password`，body `{old_password, new_password}`
- 校验：
  1. `old_password` 必须与 `current_user.password_hash` 匹配（bcrypt verify）→ 400 "原密码错误"
  2. `len(new_password) >= 6` → 400 "新密码长度需至少 6 位"
  3. `new_password != old_password` → 400 "新密码不能与原密码相同"
- 成功行为：
  - `password_hash = hash_password(new_password)`（bcrypt 重算）
  - `must_change_password = False`（首次登录强改密提示清除）
  - 返回 `{success: true, message: "密码修改成功"}`
- **不**主动失效旧 token（JWT 是无状态的，过期前仍可用 — 这是一个 Known Issue，参见下方）
- 实现位置：`server/api/auth.py::change_password`（line 98）

### REQ-AUTH-009: must_change_password 强改密流程

- 触发：seed 时 `admin` / `trader` 默认账号 `must_change_password=true`（首登录必须改）
- 后端：无强校验（不强制下次请求前必须改密，依赖前端拦截）
- 前端契约（`client/src/views/Login.vue` / `client/src/stores/auth.js`）：
  - 登录响应 `user.must_change_password === true` → 跳强制改密页（不走正常首页）
  - 改密成功后 `must_change_password=false` 才允许访问业务路由
- 已知缺口：后端 API（除 `/change-password` 外）**不**主动校验该标志 — 拿到 token 后仍可调 `/api/orders/place`（属于 Known Issue）

### REQ-AUTH-010: POST /logout — 无状态退出

- 端点：`POST /api/auth/logout`，依赖 `get_current_user`（必须已登录）
- 行为：返回 `{success: true}`（无副作用）
- 设计取舍：
  - JWT 是无状态的，**真正的 logout = 前端清 localStorage + 跳 `/login`**
  - 端点保留仅为审计（admin 看到调用日志、客户端一致调用）
  - 不需要 clear server-side session / token blacklist
- 未来若改有状态（refresh token + 黑名单）需重构本端点
- 实现位置：`server/api/auth.py::logout`（line 116）

## Scenarios

### S-AUTH-001: 新用户首次登录

Given users 表为空（count == 0；首启动 / 开发期 wipe / 全新 DB）
When FastAPI 启动
Then 自动创建两个默认账号：

| username | password | role | must_change_password |
|---|---|---|---|
| admin | admin123 | admin | true |
| trader | trader123 | trader | true |

And 日志提示首次登录后必须改密码

### S-AUTH-006: 开发期 wipe users 表后重启

Given 用户通过 SQLite 工具手动 `DELETE FROM users`（清空 users 表但保留 schema）
When FastAPI 重启
Then `on_startup` 检测到 `count == 0`，自动补 admin 和 trader 两个默认账号
And `[INIT] Created default accounts` 日志出现
And 不影响其他表（orders / trades / positions 等）的数据

### S-AUTH-002: 401 拦截

Given 用户 token 过期  
When 前端调任意 `/api/*` 受保护接口  
Then 后端返回 401，前端 axios 拦截器清 token + 跳 `/login`

### S-AUTH-003: trader 越权

Given 用户角色是 viewer  
When 调 `POST /api/orders/place`  
Then 后端返回 403（require_trader 依赖拒绝）

## Data Model

```python
class User:
    id: int (PK)
    username: str (unique, indexed)
    password_hash: str
    role: str  # 'admin' | 'trader' | 'viewer'
    full_name: str
    is_active: bool
    created_at: datetime
```

## Known Issues (from analysis)

- 🟡 `POST /api/auth/logout` 是空 stub（JWT 无状态，前端清 token 即可，但 stub 接口应明确返回 204 或删除）
- 🟢 `client/src/api/index.js` 的 401 处理已实现，但**没有**针对 403 的统一提示
