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
- 密码用 bcrypt 哈希，存 MySQL `users.password_hash`
- **v52 起必须 `async def`**（futex 僵死根治）：bcrypt 走 `run_in_threadpool`，不阻塞 Starlette anyio threadpool

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
- **v52 起必须 `async def`**（futex 僵死根治）：bcrypt verify + hash 都走 `run_in_threadpool`
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

### REQ-AUTH-011: POST /grant — 技能包永久 token（env 控制）

**v92 立**（2026-08-04）：技能包授信入口，固定 token "hermesagent" → 永久 JWT（exp 2099）。

**v2026-08-24 扩展**：grant 支持 `role=admin|trader`（白名单），`role=viewer` 拒绝 400；admin id 运行时动态查 users 表（避免硬编码 id 与实际 seed 冲突）。

- 端点：`POST /api/auth/grant`，body `{token: "hermesagent", role?: "admin"|"trader"}`
- 启用条件：**必须** `EVTRADE_ALLOW_GRANT_TOKEN=1` 环境变量；否则 403 "grant endpoint disabled"
- 校验：
  1. `payload.token` 必须等于字符串 `"hermesagent"` → 否则 401 "invalid grant token"
  2. `payload.role` ∈ `{"admin", "trader"}`，默认 `admin`；`viewer`/其他 → 400
- 成功行为：
  - `Users.query_by("role", requested_role, limit=1)` 动态查 user（admin id=1, trader id=2 真实 seed）
  - 生成 JWT `{sub: <user.id>, id: <user.id>, role: requested_role, username: <user.username>, exp: now + 30 年}`
  - 调用 `server.auth.session.register_token(permanent_token, user_id=<user.id>, role=requested_role)` 注册到 session cache
  - **必须注册** — 否则下次请求 `is_valid` 失败 → 401
- 响应：`TokenResponse{access_token, token_type, expires_in, user{id, username, role}}`
- 安全约束：
  - 默认 `EVTRADE_ALLOW_GRANT_TOKEN=0`（环境变量门控，避免生产环境暴露）
  - token 字符串 "hermesagent" 硬编码（技能包白名单，不开放 admin 后台入口）
  - role 白名单：仅 admin/trader 可签（viewer 不授信 — 防止脚本误调只读账号）
  - 不需要任何现有 JWT（grant 端点本身是绕过登录的）
- 实现位置：`server/api/auth.py::grant`（line 179）

### REQ-AUTH-014: AI 助手 / 脚本授信通路（v2026-08-24 立）

**问题**：v92 grant 端点只给 admin，但 AI 助手 / e2e 脚本 / 后台 LLM 默认走 `/api/auth/login`（OAuth2PasswordRequestForm），导致：
- admin 密码明文出现在 shell history / 日志 / 进程 args
- 与 §四"AI 助手严禁走 login"业务铁律冲突

**方案**：
- 后端：`server/api/auth.py::grant` 加 `payload.role` 参数（REQ-AUTH-011 v2026-08-24 扩展）
- 客户端 helper：`scripts/evtrade_grant.py` + `scripts/evtrade_ai.sh`
  - `evtrade_grant.py` Python helper：`auth_header(role="admin"|"trader")` / `get/post/put/patch/delete(path, role=...)`
  - token 按角色分文件缓存：`~/.cache/evtrade/grant_token_<role>.json`（0o600），跨进程复用 + 401 自动重新 grant 重试
  - `evtrade_ai.sh` bash wrapper：AI agent 一行调 `bash scripts/evtrade_ai.sh [role=...] <verb> <path> [json_body]`
- e2e 脚本改造：
  - `test_users_e2e.py` / `test_t0_tasks_e2e.py` / `test_api_tables_e2e.py` / `test_orders_e2e.py`（admin 部分）改走 grant
  - `test_orders_e2e.py` trader 部分保留 OAuth2 login（grant 默认 admin，trader 角色测试业务场景必须）
  - `test_auth_e2e.py` 不动（测的就是 login 本身）
- WS 不变：`server/ws/endpoint.py` 仍只接受 `token=hermesagent` → admin(id=6)（待后续扩展时再考虑 `token=hermesagent:trader` 之类格式）

**安全约束**：
- viewer 角色**不授信** — grant endpoint 拒绝（400）；helper 无 viewer role
- e2e 密码（admin123/trader123）从脚本里逐步退场；reset-password / change-password 测试仍需 OAuth2 流程（验证新密码可用）
- AI 助手 / 自动脚本 / 后台 LLM **严禁走 `/api/auth/login`**（CLAUDE.md §四铁律）；登录仅限 Vue 前端人为交互

**影响面**：
- `scripts/e2e/test_{users,t0_tasks,api_tables,orders}_e2e.py` 4 文件改 `_grant_token(role)` 替代 admin login
- `scripts/init_strategy_exec_env.py:request_grant_token` 也走 grant（之前已支持）
- `scripts/evtrade_grant.py` 新增（commit `2366897`）
- `scripts/evtrade_ai.sh` 新增

**实现位置**：
- 后端：`server/api/auth.py::grant`
- 客户端：`scripts/evtrade_grant.py` + `scripts/evtrade_ai.sh`
- 规则：`CLAUDE.md` §四业务铁律

### REQ-AUTH-013: WS 直连 token=hermesagent — 无条件接受（v129, 2026-08-13）

**v129 立（2026-08-13）**：hermes agent 用 `wss://…/ws/{channel}?token=hermesagent` 直连
WS，不再走 grant 换 JWT 的仪式。**用户决策：无条件接受，不做 env 门控**。

- 行为：WS 鉴权 `decode_token(token)` 返回 None 时，若 `token == "hermesagent"`
  （常量 `server.auth.security.HERMES_AGENT_TOKEN`）→ 视为 admin 身份
  `{sub:"6", id:6, role:"admin", username:"admin"}`；否则 close 4001 "Invalid token"
- 身份与 REQ-AUTH-011 grant 一致（user_id=6 admin），共享同一常量
- 不做 `EVTRADE_ALLOW_GRANT_TOKEN` 门控（区别于 REQ-AUTH-011）
- 影响面：所有 WS channel 鉴权入口；`sync_update` 的 DB admin 校验对 user 6 通过 → 也可进
- 安全风险（已知情登记）：`hermesagent` 成为 WS 上**无法用配置关闭的硬编码 admin 凭证**；
  回收需改代码或补门控
- 实现位置：`server/ws/endpoint.py::_resolve_ws_user`

### REQ-AUTH-012: POST /heartbeat — Token 保活（idle 防过期）

**REQ-AUTH-IDLE-001**（2026-08-04 立）：idle 超 10min token 失效（session cache LRU + TTL）。

- 端点：`POST /api/auth/heartbeat`，依赖 `get_current_user`
- 行为：返回 `{ok: true, idle_timeout_seconds, user_id}`（无副作用）
- 调用链：
  - `get_current_user` 内部已 `is_valid` + `touch`（更新 session cache 的 last_seen_at）
  - 端点本身只需返 OK + 当前 idle timeout 阈值（前端可据此调度）
- 前端调用模式：登录成功后每 **5 分钟**调一次（小于 10 min 超时阈值）
- 不需要返回用户对象（前端 store 已有；省响应体大小）
- 实现位置：`server/api/auth.py::heartbeat`（line 237）

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

Given admin 通过 MySQL 客户端手动 `DELETE FROM users`（清空 users 表但保留 schema）
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
