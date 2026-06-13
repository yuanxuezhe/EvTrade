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

## Scenarios

### S-AUTH-001: 新用户首次登录

Given 系统中无用户  
When FastAPI 启动  
Then 自动创建 admin/admin123 账户，日志提示首次登录后改密码

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
