"""
Auth API: login, current user info, change password.

v81 tables-migration (strict user-pseudocode 风格):
  - ORM 残留全部清掉: 无 Depends(get_db), 无 sqlalchemy.orm.Session, 无 server.db.get_db.
  - 严格按 MIGRATION_GUIDE.md:
      单字段非主键查 → Users.query_by('username', form.username, limit=1)
      主键查       → Users.query_one(id=...)
      对象更新     → 走 Row.update(cls, id=obj.id) (login 流程)
                  或 Users.update_one({...}, id=obj.id) (me / change-password, 因 current_user
                  仍可能来自 deps.get_current_user 的 ORM User, Row 字段赋值+update 即可)
  - 兼容期: deps.get_current_user 仍返 ORM User. _row_to_user_dict 用 getattr 同时
    支持 Row 与 ORM 对象, 保证 me 端点读得到 created_at/last_login_at 等 datetime 字段.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from server.tables.users import Users
from server.utils.time import format_db_dt
from server.auth.security import (
    verify_password, hash_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
)
from server.auth import session  # REQ-AUTH-IDLE-001: 登录注册到 token cache, logout 撤销
from server.auth.deps import get_current_user, oauth2_scheme

router = APIRouter()


# ──────────────────────────── helper ────────────────────────────
def _row_to_user_dict(row) -> dict:
    """把 tables Row (或 ORM User) 转为与 User.to_dict() 字段一致的 dict。

    主要差异: datetime 字段 (created_at / updated_at / last_login_at)
    ORM 版本用 _format_db_dt(...) if self.created_at else None, 这里复用
    server.utils.time.format_db_dt + None 守卫保持行为一致。

    入参 row: 支持 tables.base.Row (query_one/query_by 返回) 或
    server.models.user.User (deps.get_current_user 仍是 ORM, 兼容期).
    两者字段名一致 (id/username/email/...), 用 getattr 兼容.
    """
    def _g(name):
        return getattr(row, name, None)

    return {
        "id": _g("id"),
        "username": _g("username"),
        "email": _g("email"),
        "full_name": _g("full_name"),
        "role": _g("role"),
        "is_active": _g("is_active"),
        "must_change_password": _g("must_change_password"),
        "created_at": format_db_dt(_g("created_at")) if _g("created_at") else None,
        "updated_at": format_db_dt(_g("updated_at")) if _g("updated_at") else None,
        "last_login_at": format_db_dt(_g("last_login_at")) if _g("last_login_at") else None,
    }


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserInfoResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    must_change_password: bool = False
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    # v_next: 不限制旧密码 / 新密码长度 — 用户可自由修改
    new_password: str


class UpdateProfileRequest(BaseModel):
    email: str = None
    full_name: str = None


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
):
    """Username + password → JWT token.

    async + run_in_threadpool: bcrypt.checkpw 是 CPU bound (rounds=12 ~250ms)，
    在 sync endpoint 会阻塞 Starlette threadpool（40 线程）→ 与 DB pool 形成
    复合死锁（threadpool 满 → DB session 不归还 → futex_wait_queue 僵死）。
    run_in_threadpool 把 bcrypt 扔到 anyio threadpool，不阻塞 event loop 与
    DB session 释放。

    v81 tables-migration (严格伪代码):
      原: db.query(User).filter(User.username == ...).first()
      改: Users.query_by('username', form.username, limit=1)
    """
    matched = Users.query_by("username", form.username, limit=1)
    user = matched[0] if matched else None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    # bcrypt in threadpool (CPU bound, blocking)
    ok = await run_in_threadpool(verify_password, form.password, user.password_hash)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已禁用")
    # Record last login — 严格用户伪代码: obj.xx = val; obj.update(cls, id=obj.id)
    # user 是 Row (来自 query_by), Row.update(Users, id=user.id) 直接生效
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.update(Users, id=user.id)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    # REQ-AUTH-IDLE-001: token 注册到 session cache (10min idle + restart 失效)
    session.register_token(token, user_id=user.id, role=user.role)
    user_dict = _row_to_user_dict(user)
    # v_next: 系统级开关 — 关掉后首次登录不再强制改密
    from server.services.sysconfig import get
    required = bool(get("must_change_password_required", 1))
    user_dict["must_change_password_required"] = required
    user_dict["must_change_password_effective"] = (
        bool(user_dict.get("must_change_password")) and required
    )
    return TokenResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_dict,
    )


@router.get("/me", response_model=UserInfoResponse)
def me(current_user=Depends(get_current_user)):
    # v81: current_user 仍可能来自 deps.get_current_user 的 ORM User;
    # _row_to_user_dict 用 getattr 兼容两者.
    return UserInfoResponse(**_row_to_user_dict(current_user))


@router.patch("/me", response_model=UserInfoResponse)
def update_profile(
    payload: UpdateProfileRequest,
    current_user=Depends(get_current_user),
):
    """v81 tables-migration:
      原: db.commit() / db.refresh()
      改: Users.update_one({...}, id=current_user.id)
    注意: current_user 兼容期仍是 ORM User, ORM 属性赋值 + Users.update_one(dict)
    是无 ORM 残留的合法迁移模式 (update_one 走主键 UPDATE, 不需要 db.commit).
    """
    data = {}
    if payload.email is not None:
        data["email"] = payload.email.strip() or None
    if payload.full_name is not None:
        data["full_name"] = payload.full_name.strip() or None
    if data:
        Users.update_one(data, id=current_user.id)
        # 回读 (原 db.refresh(current_user) 等价)
        refreshed = Users.query_one(id=current_user.id)
        if refreshed is not None:
            current_user = refreshed
    return UserInfoResponse(**_row_to_user_dict(current_user))


@router.post("/grant", response_model=TokenResponse)
async def grant(payload: dict):
    """技能包授信: 固定 token "hermesagent" -> 永久 JWT (exp 2099).

    仅当 EVTRADE_ALLOW_GRANT_TOKEN=1 才启用, 默认 admin (user_id=6) 身份.
    """
    import os
    from datetime import datetime, timezone, timedelta
    if os.environ.get("EVTRADE_ALLOW_GRANT_TOKEN", "0") != "1":
        raise HTTPException(status_code=403, detail="grant endpoint disabled (set EVTRADE_ALLOW_GRANT_TOKEN=1)")
    token_str = payload.get("token", "")
    from server.auth.security import HERMES_AGENT_TOKEN
    if token_str != HERMES_AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="invalid grant token")
    data = {"sub": "6", "id": 6, "role": "admin", "username": "admin"}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires = now + timedelta(days=365 * 30)
    to_encode = dict(data)
    to_encode["iat"] = now
    to_encode["exp"] = expires
    from server.auth.security import SECRET_KEY, ALGORITHM
    from jose import jwt
    permanent_token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    # 注册到 session cache (否则 is_valid 失败 → 401)
    from server.auth.session import register_token
    register_token(permanent_token, user_id=6, role="admin")
    return {
        "access_token": permanent_token,
        "token_type": "bearer",
        "expires_in": int((expires - now).total_seconds()),
        "user": {"id": 6, "username": "admin", "role": "admin"},
    }


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
):
    """Change password — 不校验旧密码 / 不限制新密码长度 / 不限制不能与旧密码相同。

    初始化时 admin 密码是 admin/admin123 (seed.py), 用户可自由修改, 不加任何限制。
    hash_password rounds=12 更慢 (~300ms)，必走 threadpool。

    v81 tables-migration:
      原: current_user.password_hash = ... ; db.commit()
      改: Users.update_one({...}, id=current_user.id)  # 无 ORM 残留, 主键 UPDATE
    """
    new_hash = await run_in_threadpool(hash_password, payload.new_password)
    Users.update_one(
        {
            "password_hash": new_hash,
            "must_change_password": False,
        },
        id=current_user.id,
    )
    return {"success": True, "message": "密码修改成功"}


@router.post("/heartbeat")
def heartbeat(current_user=Depends(get_current_user)):
    """token keepalive: 前端每 N 分钟调用一次, 重置 last_seen_at

    REQ-AUTH-IDLE-001 (2026-08-04 追加):
    - idle 超 10min token 失效
    - 前端静止时如不发请求, token 会过期
    - 解决: 前端每 5 分钟调一次 /heartbeat, 让 token touch
    - get_current_user 内部已经 is_valid + touch, 这里只需返 OK
    """
    from server.auth.session import IDLE_TIMEOUT_SECONDS
    user_id = getattr(current_user, "id", None)
    if user_id is None and isinstance(current_user, dict):
        user_id = current_user.get("id")
    return {
        "ok": True,
        "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
        "user_id": user_id,
    }


@router.post("/logout")
def logout(
    current_user=Depends(get_current_user),
    token: Optional[str] = Depends(oauth2_scheme),
):
    """Logout: 主动撤销 server session cache 中的 token (立即失效)。

    REQ-AUTH-IDLE-001: 即便前端 localStorage 还在, 后端 cache 已无该 token,
    下次请求 deps.get_current_user 会返 401, 前端 axios 拦截器自动跳 /login。

    兼容: 若 token 为 None (header 缺失), 仍然返 success=True (审计用)
    """
    if token:
        session.revoke(token)
    return {"success": True}
