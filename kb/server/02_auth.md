# Server · 02 · 鉴权与权限（Auth & RBAC）

> 实现文件：`server/auth/security.py` + `server/auth/deps.py`
> 角色三档：`admin` / `trader` / `viewer`，权限矩阵见 `cross/03_role_matrix.md`。

## 1. 密码与 Token

### 1.1 哈希算法
- `bcrypt`，`gensalt(rounds=12)`，`hashpw(plain.encode("utf-8"), salt).decode("utf-8")`
- 验证：`bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))`
- 任何异常（如空串、解析失败）一律返回 `False`

### 1.2 JWT
- 算法：`HS256`
- 默认有效期：`ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 = 1440`（24h）
- Payload：`{ "sub": str(user.id), "role": user.role, "iat": now, "exp": now + delta }`
- 库：`python-jose`

### 1.3 密钥管理（`SECRET_KEY`）
- 来源优先级：
  1. 环境变量 `EVTRADE_SECRET`（最高）
  2. 持久化文件 `server/auth/.secret_key`（`secrets.token_urlsafe(64)`）
  3. 自动生成新密钥并落盘（OSError 时仅内存使用）
- 持久化目的：让 JWT 跨进程重启仍可校验

## 2. 依赖注入（`auth/deps.py`）

### 2.1 `oauth2_scheme`
```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
```
- `auto_error=False` 让无 token 时由我们自己抛 401 + `WWW-Authenticate: Bearer` 头

### 2.2 `get_current_user(token, db) -> User`
- 无 token → `401 未登录或登录已过期`
- token 解析失败 → `401 无效或过期的令牌`
- `sub` 缺失 / 非整数 → `401 令牌缺少/用户标识无效`
- 用户不存在 → `401 用户不存在`
- `is_active=False` → `403 账号已禁用，请联系管理员`
- 成功 → 返回 `User` 实例（自动加载 role / is_active 等）

### 2.3 `require_admin(user) -> User`
- `user.role != "admin"` → `403 需要管理员权限`
- 否则返回原 user

### 2.4 `require_trader(user) -> User`
- `user.role not in ("admin", "trader")` → `403 只读账号无法执行此操作`
- 否则返回原 user

> **注意**：FastAPI 中应使用 `Depends(require_trader)`，但 `orders.py` 中是 `_=Depends(require_trader)`，变量名带下划线表示不使用返回值。

## 3. 角色权限矩阵（业务层）

| 路由 / 操作 | viewer | trader | admin |
|-------------|:------:|:------:|:-----:|
| 查看 Dashboard / Position / Asset / Orders / Trades | ✅ | ✅ | ✅ |
| 查看 Profile / 修改个人资料 / 修改自己密码 | ✅ | ✅ | ✅ |
| 路由 `/trade`（下单页） | ❌（被重定向 `/`） | ✅ | ✅ |
| 委托：POST `/api/orders/place`、`POST /api/orders`、`DELETE /api/orders/{id}` | ❌ | ✅ | ✅ |
| 持仓：POST `/api/positions/{code}/init` | ❌ | ✅ | ✅ |
| 路由 `/users`（用户管理页） | ❌ | ❌ | ✅ |
| `GET/POST/PATCH/DELETE /api/users/*` | ❌ | ❌ | ✅ |
| 重置任意用户密码 | ❌ | ❌ | ✅ |
| 启停任意用户（自己除外） | ❌ | ❌ | ✅ |
| 最后一个 admin 的降级 / 禁用 / 删除 | ❌ | ❌ | 系统拦截 |

## 4. 前端守卫（`client/src/router/index.js`）

`router.beforeEach` 顺序：
1. 设置 `document.title`
2. 公共路由（`meta.layout === 'blank'`，如 `/login`）→ 已登录跳 `/`，否则放行
3. 未登录 → 跳 `/login?redirect=...`
4. `meta.requiresAdmin` 且非 admin → 跳 `/`
5. `meta.requiresTrader` 且非 trader/admin → 跳 `/`
6. 全局 401 处理器：`setUnauthorizedHandler(() => auth.clear(); router.replace('/login?redirect=...'))`

## 5. 修改密码流程

```
Profile.vue / AppHeader.vue
  └─ <ChangePasswordDialog v-model="visible"/>
       ├─ 表单: old_password, new_password, confirm
       ├─ 校验两次输入一致 + 长度 ≥ 6
       └─ authStore.changePassword(old, new)
              └─ authApi.changePassword() → POST /api/auth/change-password
                    └─ 成功 → 弹成功 → 800ms 后 logout + 跳 /login
```

## 6. Token 存储约定

| 位置 | key | 内容 |
|------|-----|------|
| `localStorage` | `evtrade-token` | JWT |
| `localStorage` | `evtrade-user` | `{ id, username, role, ... }` JSON |
| `localStorage` | `evtrade-remember-username` | 上次登录用户名（仅前端体验） |
| `localStorage` | `evtrade-theme` | `light` / `dark` |
| `localStorage` | `evtrade-sidebar` | `1` / `0` |

## 7. 错误响应规范

后端统一使用 FastAPI `HTTPException(status_code, detail, headers)`：

| 场景 | 状态码 | 中文 detail |
|------|--------|------------|
| 缺 / 失效 token | 401 | 未登录或登录已过期 / 无效或过期的令牌 |
| 用户不存在 / 标识错 | 401 | 用户不存在 / 令牌用户标识无效 |
| 账号禁用 | 403 | 账号已禁用 |
| 角色不足 | 403 | 需要管理员权限 / 只读账号无法执行此操作 |
| 业务校验失败 | 400 | 具体原因（见各接口） |
| 资源不存在 | 404 | 用户不存在 |
| 资源冲突 | 409 | 用户名已存在 |
| 内部错误 | 500 | str(e)（多为 RPC / DB 异常） |
