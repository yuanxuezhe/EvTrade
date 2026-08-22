"""
Password hashing + JWT token utilities.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

# ---- Secret key ----------------------------------------------------------
# Persisted in a file so tokens survive restarts; auto-generated on first use.
_SECRET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")


def _load_or_create_secret() -> str:
    env = os.environ.get("EVTRADE_SECRET")
    if env:
        return env
    if os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_urlsafe(64)
    try:
        with open(_SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass
    return key


SECRET_KEY = _load_or_create_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# 技能包 hermes agent 固定授信 token (REQ-AUTH-011 / REQ-AUTH-013)。
# grant 端点与 WS 直连共用单一事实源; WS 直连时 decode 失败若 token 等于该值 → 视为 admin(id=6)。
HERMES_AGENT_TOKEN = "hermesagent"


# ---- Password hashing ----------------------------------------------------
def hash_password(plain: str) -> str:
    """Hash a plain password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash. Returns False on errors."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---- JWT helpers ---------------------------------------------------------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token with iat/exp claims."""
    to_encode = dict(data)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"iat": now, "exp": now + expires_delta})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode/verify a JWT token; returns claims dict or None if invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
