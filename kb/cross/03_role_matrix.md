# Cross · 03 · 角色权限矩阵（Role × Route × API）

> 角色三档：`admin` / `trader` / `viewer`
> 实现：
> - 后端 `server/auth/deps.py:require_admin / require_trader`
> - 前端 `client/src/stores/auth.js` 计算属性 + `client/src/router/index.js` 守卫
> - UI `client/src/components/Sidebar.vue` 菜单

## 1. 角色定义

| 角色 | 含义 |
|------|------|
| `admin` | 系统管理员：可管理用户、查看/操作全部业务 |
| `trader` | 交易员：可下单、撤单、查看全部数据，**不能**管用户 |
| `viewer` | 只读账号：仅能查看数据，**不能**下单 / 改持仓 / 管用户 |

## 2. 路由守卫

| 路由 | 守卫 | viewer | trader | admin |
|------|------|:------:|:------:|:-----:|
| `/login` | `public` | ✅ | ✅ | ✅ |
| `/` (Dashboard) | 需登录 | ✅ | ✅ | ✅ |
| `/positions` | 需登录 | ✅ | ✅ | ✅ |
| `/orders` | 需登录 | ✅ | ✅ | ✅ |
| `/trades` | 需登录 | ✅ | ✅ | ✅ |
| `/asset` | 需登录 | ✅ | ✅ | ✅ |
| `/profile` | 需登录 | ✅ | ✅ | ✅ |
| `/trade` | `requiresTrader` | ❌ 跳 `/` | ✅ | ✅ |
| `/users` | `requiresAdmin` | ❌ 跳 `/` | ❌ 跳 `/` | ✅ |
| `/:pathMatch(.*)*` | redirect `/` | — | — | — |

> 守卫失败一律 `replace` 到 `/`，不带提示。

## 3. 菜单可见性（Sidebar）

```js
const base = [
  Dashboard, Position, Trade, Orders, Trades, Asset
]
if (authStore.isAdmin) {
  base.push({ path: '/users', label: '用户管理', icon: UserFilled, divider: true })
}
```
- 普通菜单：6 项
- admin 追加 `用户管理`（带 divider 分隔）

## 4. API 权限

| 接口 | viewer | trader | admin | 实现 |
|------|:------:|:------:|:-----:|------|
| `POST /api/auth/login` | ✅ | ✅ | ✅ | 公开 |
| `GET /api/auth/me` | ✅ | ✅ | ✅ | 需登录 |
| `PATCH /api/auth/me` | ✅ | ✅ | ✅ | 需登录 |
| `POST /api/auth/change-password` | ✅ | ✅ | ✅ | 需登录 |
| `POST /api/auth/logout` | ✅ | ✅ | ✅ | 需登录 |
| `GET /api/asset` | ✅ | ✅ | ✅ | 需登录 |
| `GET /api/positions` | ✅ | ✅ | ✅ | 需登录 |
| `POST /api/positions/{code}/init` | ❌ 403 | ✅ | ✅ | `require_trader` |
| `GET /api/orders` | ✅ | ✅ | ✅ | 需登录 |
| `POST /api/orders` | ❌ 403 | ✅ | ✅ | `require_trader` |
| `POST /api/orders/place` | ❌ 403 | ✅ | ✅ | `require_trader` |
| `DELETE /api/orders/{id}` | ❌ 403 | ✅ | ✅ | `require_trader` |
| `GET /api/trades` | ✅ | ✅ | ✅ | 需登录 |
| `GET /api/users` | ❌ 403 | ❌ 403 | ✅ | `require_admin` |
| `POST /api/users` | ❌ 403 | ❌ 403 | ✅ | `require_admin` |
| `PATCH /api/users/{id}` | ❌ 403 | ❌ 403 | ✅ | `require_admin` |
| `POST /api/users/{id}/reset-password` | ❌ 403 | ❌ 403 | ✅ | `require_admin` |
| `DELETE /api/users/{id}` | ❌ 403 | ❌ 403 | ✅ | `require_admin` |
| `GET /api/health` | ✅ | ✅ | ✅ | 公开 |

## 5. 业务硬约束（不依赖角色）

| 约束 | 实现 |
|------|------|
| 不能删除自己 | `users.py:delete_user` → `400 不能删除当前登录账号` |
| 不能禁用自己 | `users.py:update_user` → `400 不能禁用当前登录账号` |
| 必须保留至少 1 个 admin | `users.py:update_user / delete_user` |
| 最后一个启用的 admin 不能被禁用 | `users.py:update_user` |
| 用户名格式 `^[A-Za-z0-9_\-\.]{3,32}$` | `users.py:_validate_username` |
| 密码 ≥ 6 位 | `users.py:_validate_password` + `auth.py:change_password` |
| 角色 ∈ {admin, trader, viewer} | `users.py:VALID_ROLES` |

## 6. 跨端一致性

| 维度 | 后端 | 前端 |
|------|------|------|
| 角色枚举值 | `users.py:VALID_ROLES` | `Profile.vue / Users.vue` 中 `ROLE_LABEL` 字典 |
| 角色显示中文 | 无 | `管理员 / 交易员 / 只读用户` |
| 角色色阶 | 无 | `linear-gradient` 三套（`--brand-gradient / --color-up-gradient / linear-gradient(135deg, #5fa8ff...)`） |
| 业务硬约束 | 服务端校验 | UI 上按钮 disabled（如 `Users.vue` 操作列 `row.id === authStore.user?.id`） |

> UI 的 disabled 是**体验优化**，**不替代**服务端校验。

## 7. 角色切换 / 升级路径

```
无角色（未登录） ──login──> 任意
viewer     ──admin 改 role──> trader
viewer     ──admin 改 role──> admin
trader     ──admin 改 role──> admin
trader     ──admin 改 role──> viewer
admin      ──admin 改 role──> trader（前提：还有其它启用的 admin）
```

`update_user` 中 admin_count 保护逻辑（关键代码片段）：
```python
if user.role == "admin" and payload.role != "admin":
    admin_count = db.query(User).filter(
        User.role == "admin", User.is_active == True
    ).count()
    if admin_count <= 1:
        raise HTTPException(400, "必须至少保留一个管理员")
```

## 8. 种子

`server/main.py on_startup`：
- `count == 0` 时插入 `admin / admin123 / admin / 系统管理员 / is_active=true`
- 控制台打印请修改密码
