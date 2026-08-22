# 认证与JWT

## 对应代码路径

| 文件 | 说明 |
|---|---|
| `server/api/auth.py` | 登录/me/grant/改密/心跳/登出 REST（273 行） |
| `server/auth/deps.py` | FastAPI 鉴权依赖 get_current_user / require_admin / require_trader（80 行） |
| `server/auth/security.py` | JWT 签发校验 + bcrypt 工具（77 行） |
| `server/auth/session.py` | token session cache（进程内 dict + RLock，140 行） |

## 功能概述

认证体系 = **JWT（HS256）+ bcrypt 密码 + 进程内 token session cache + RBAC 三级**：

- **登录**（`POST /api/auth/login`）：OAuth2PasswordRequestForm（username/password 表单）→ bcrypt 校验（threadpool，rounds=12 约 250ms）→ 签发 24h JWT → `session.register_token` 注册进内存 cache
- **双因子校验**（每个受保护请求，deps.get_current_user）：
  1. `decode_token`（JWT 签名 + exp 校验）
  2. `session.is_valid(token)`（内存 cache 存在且 idle ≤ 10 分钟）
  3. 通过后 `session.touch(token)` 重置 idle 计时
- **心跳保活**（`POST /api/auth/heartbeat`）：前端静止时每 5 分钟调一次，让 token touch 不过期（IDLE_TIMEOUT_SECONDS=600）
- **登出**（`POST /api/auth/logout`）：`session.revoke(token)` 立即失效（即便前端 localStorage 还存着 token）
- **重启失效语义**：cache 是进程内 dict，后端重启 = 所有 token 失效（用户期望行为）
- **技能包授信**（`POST /api/auth/grant`）：环境变量 `EVTRADE_ALLOW_GRANT_TOKEN=1` 时，固定 token "hermesagent" 可换永久 JWT（exp 2099，admin id=6）
- **RBAC 三级**：admin > trader > viewer；`require_admin`（仅 admin）、`require_trader`（admin+trader，viewer 403）

## 文件清单

| 文件 | 行数 | 核心内容 |
|---|---|---|
| `server/api/auth.py` | 273 | login / me(PATCH) / grant / change-password / heartbeat / logout |
| `server/auth/security.py` | 77 | SECRET_KEY 加载、hash_password、verify_password、create_access_token、decode_token |
| `server/auth/session.py` | 140 | register_token / touch / is_valid / revoke / sweep_expired / sweep_loop |
| `server/auth/deps.py` | 80 | oauth2_scheme / get_current_user / require_admin / require_trader |

### 关键常量

| 常量 | 值 | 位置 |
|---|---|---|
| ALGORITHM | HS256 | security.py |
| ACCESS_TOKEN_EXPIRE_MINUTES | 60×24（24h） | security.py |
| HERMES_AGENT_TOKEN | "hermesagent" | security.py |
| IDLE_TIMEOUT_SECONDS | 600（10min） | session.py |
| SWEEP_INTERVAL_SECONDS | 60 | session.py |
| bcrypt rounds | 12 | security.py |

## 核心实现

### 1. Secret key 持久化（security.py）

```python
_SECRET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")

def _load_or_create_secret() -> str:
    env = os.environ.get("EVTRADE_SECRET")          # 1. 环境变量优先
    if env: return env
    if os.path.exists(_SECRET_PATH):                # 2. 文件复用（token 跨重启有效的前提）
        ...
    key = secrets.token_urlsafe(64)                 # 3. 首次生成并写文件
    ...
SECRET_KEY = _load_or_create_secret()
```

### 2. JWT 与 bcrypt

```python
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(plain, hashed) -> bool:         # 异常返回 False 不抛
    try: return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError): return False

def create_access_token(data: dict, expires_delta=None) -> str:
    to_encode = dict(data)                          # {"sub": "6", "role": "admin"}
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC（DB 无时区）
    to_encode.update({"iat": now, "exp": now + (expires_delta or timedelta(minutes=1440))})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:     # 无效/过期返回 None
    try: return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError: return None
```

### 3. 登录端点（api/auth.py）

```python
@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    matched = Users.query_by("username", form.username, limit=1)   # tables 层
    user = matched[0] if matched else None
    if not user: raise HTTPException(401, detail="用户名或密码错误")
    # bcrypt 是 CPU bound — 必须 run_in_threadpool，否则阻塞 Starlette threadpool(40线程)
    # → 与 DB pool 复合死锁（threadpool 满 → session 不归还 → futex 僵死）
    ok = await run_in_threadpool(verify_password, form.password, user.password_hash)
    if not ok: raise HTTPException(401, detail="用户名或密码错误")
    if not user.is_active: raise HTTPException(403, detail="账号已禁用")

    user.last_login_at = utcnow_naive()
    user.update(Users, id=user.id)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    session.register_token(token, user_id=user.id, role=user.role)   # 注册进 cache

    user_dict = _row_to_user_dict(user)
    required = bool(sysconfig_get("must_change_password_required", 1))   # 系统级开关
    user_dict["must_change_password_required"] = required
    user_dict["must_change_password_effective"] = bool(user_dict.get("must_change_password")) and required
    return TokenResponse(access_token=token, expires_in=ACCESS_TOKEN_EXPIRE_MINUTES*60, user=user_dict)
```

### 4. 鉴权依赖链（deps.py）

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(token=Depends(oauth2_scheme)) -> User:
    if not token: raise HTTPException(401, "未登录或登录已过期")
    claims = decode_token(token)
    if not claims: raise HTTPException(401, "无效或过期的令牌")
    if not session.is_valid(token):          # 内存 cache 检查（10min idle + 重启失效）
        session.revoke(token)                # 顺手清理
        raise HTTPException(401, "登录已过期，请重新登录")
    session.touch(token)                     # 重置 idle 计时
    user_id = int(claims.get("sub"))         # 异常 401
    user = Users.query_one(id=user_id)       # tables 层
    if not user: raise HTTPException(401, "用户不存在")
    if not getattr(user, 'is_active', True): raise HTTPException(403, "账号已禁用")
    return user

def require_admin(current_user=Depends(get_current_user)):
    if current_user.role != "admin": raise HTTPException(403, "需要管理员权限")
    return current_user

def require_trader(current_user=Depends(get_current_user)):
    if current_user.role not in ("admin", "trader"): raise HTTPException(403, "只读账号无法执行此操作")
    return current_user
```

### 5. token session cache（session.py，单进程实现）

```python
IDLE_TIMEOUT_SECONDS = 600; SWEEP_INTERVAL_SECONDS = 60
_TOKEN_CACHE: dict = {}                     # PK = SHA256(token) hex（不存原文）
_TOKEN_LOCK = threading.RLock()             # RLock 允许重入（is_valid 内 touch）

def register_token(token, user_id, role):   # 登录/grant 时调用；幂等覆盖
    _TOKEN_CACHE[_hash_token(token)] = {"user_id": ..., "role": ...,
                                        "created_at": time.time(), "last_seen_at": time.time()}
def touch(token):                           # 每个鉴权请求调用；不存在静默 no-op
    entry["last_seen_at"] = time.time()
def is_valid(token) -> bool:
    return (time.time() - entry["last_seen_at"]) <= IDLE_TIMEOUT_SECONDS
def revoke(token):  _TOKEN_CACHE.pop(_hash_token(token), None)   # logout
def sweep_expired() -> int:                 # 清 idle 超时条目
async def sweep_loop():                     # lifespan 启动的后台协程，60s 一轮
```

现状：**单进程** + 进程内 dict（多 worker 下 dict 不共享会跨进程 401，MySQL MEMORY 表方案曾有抖动）（微秒级、无锁竞争、重启清空语义保留）。**部署禁止 `--workers N`。**

### 6. grant 永久 token（api/auth.py）

```python
@router.post("/grant", response_model=TokenResponse)
async def grant(payload: dict):
    if os.environ.get("EVTRADE_ALLOW_GRANT_TOKEN", "0") != "1":
        raise HTTPException(403, "grant endpoint disabled")
    if payload.get("token") != HERMES_AGENT_TOKEN: raise HTTPException(401, "invalid grant token")
    data = {"sub": "6", "id": 6, "role": "admin", "username": "admin"}
    expires = now + timedelta(days=365*30)                      # ~2099
    permanent_token = jwt.encode({**data, "iat": now, "exp": expires}, SECRET_KEY, algorithm=ALGORITHM)
    register_token(permanent_token, user_id=6, role="admin")    # 必须注册，否则 is_valid 401
```

WS 直连时 decode 失败但 token == HERMES_AGENT_TOKEN 也视为 admin(id=6)（同一事实源）。

### 7. 其余端点

- `GET/PATCH /api/auth/me`：读/改自己 email/full_name（`Users.update_one(data, id=...)` 后回读）
- `POST /api/auth/change-password`：**不校验旧密码、不限长度**（admin/admin123 seed 场景）；hash 走 threadpool；成功后 `must_change_password=False`
- `POST /api/auth/heartbeat`：get_current_user 内已 touch，直接返回 `{ok, idle_timeout_seconds, user_id}`
- `POST /api/auth/logout`：token 缺失也返回 success（审计兼容）

## 依赖关系

- **依赖**：python-jose（JWT）、bcrypt、pypinyin 无关；server.tables.Users；server.services.sysconfig（must_change_password_required）；FastAPI run_in_threadpool
- **被依赖**：几乎所有业务路由（get_current_user/require_admin/require_trader）；WS endpoint.py（touch 续期）；main.py lifespan 启动 `session.sweep_loop()` 与停止
- **前端契约**：401 → axios 拦截器跳 /login；TokenResponse.user 携带 must_change_password_effective 驱动首登改密页

## 修改指南

- **改 idle 超时**：改 session.py 的 `IDLE_TIMEOUT_SECONDS`（heartbeat 响应会自动带回新值）；同时调整前端心跳间隔（当前 5min < 10min 超时）
- **改 JWT 有效期**：改 `ACCESS_TOKEN_EXPIRE_MINUTES`；注意它只是上限，实际失效由 idle 10min 先触发（活跃用户靠 touch 续命）
- **新增角色**：users 表 role 列 + `VALID_ROLES`（users.py）+ deps.py 加 `require_xxx` guard
- **多进程部署**：必须先解决 session cache 共享（Redis 或 SQL 共享方案），否则跨 worker 401
- **换 secret**：删 `server/auth/.secret_key` 或改 EVTRADE_SECRET 环境变量；**所有已发 token 立即失效**
- **grant 收紧**：HERMES_AGENT_TOKEN 常量与 WS endpoint 的兜底判断是两处引用，改值需同步
- **登录加图形验证码等**：加在 login 端点 bcrypt 校验之前；保持 401 文案统一（"用户名或密码错误"）防止用户名枚举
