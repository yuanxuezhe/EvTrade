"""
test_auth.py — 验证 v4 用户表登录 + 默认 admin seed

覆盖：
- 默认 admin/admin123 账户被 seed（main.py startup）
- 登录从 users 表验证（不绕过、不硬编码）
- 错密码 / 未知用户 401
- 登录成功更新 last_login_at

v4 实战背景：v4 实施期间 main.py 改动顺序问题曾回退到 cc7b67a，
"启动 seed 默认 admin" 逻辑靠此测试保护。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db import Base, engine, SessionLocal, init_db
from models.user import User
from auth.security import hash_password


@pytest.fixture(autouse=True)
def fresh_db():
    """drop_all + create_all；不触发 startup（TestClient 默认不跑 startup）"""
    Base.metadata.drop_all(bind=engine)
    init_db()
    # v128.2: token_sessions 表是 TableBase (不在 Base.metadata), init_db 不创建
    # 这里手动跑 migration 建表, 保证 session.register_token 能写
    import importlib
    mod = importlib.import_module("server.migrations.2026-08-12-add-token-sessions")
    mod.migrate(engine)
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _seed_admin(db: Session, username="admin", password="admin123", role="admin"):
    """手动 seed admin（不依赖 startup 跑）"""
    # 幂等：清掉再 seed
    db.query(User).filter_by(username=username).delete()
    db.commit()
    u = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        full_name="系统管理员" if role == "admin" else None,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_login_with_default_admin(fresh_db):
    """admin/admin123 → 200 + JWT"""
    _seed_admin(SessionLocal())

    client = TestClient(__import__("main").app)
    res = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"
    assert body["expires_in"] > 0


def test_login_with_invalid_password(fresh_db):
    """错密码 → 401"""
    _seed_admin(SessionLocal())

    client = TestClient(__import__("main").app)
    res = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "wrong_password"},
    )
    assert res.status_code == 401
    assert "用户名或密码错误" in res.json()["detail"]


def test_login_with_nonexistent_user(fresh_db):
    """空 users 表 + 错用户名 → 401（不会绕过用户表）"""
    client = TestClient(__import__("main").app)
    res = client.post(
        "/api/auth/login",
        data={"username": "ghost", "password": "anything"},
    )
    assert res.status_code == 401
    assert "用户名或密码错误" in res.json()["detail"]


def test_login_updates_last_login_at(fresh_db):
    """登录成功 → last_login_at 被更新"""
    admin = _seed_admin(SessionLocal())
    assert admin.last_login_at is None  # seed 后是空

    client = TestClient(__import__("main").app)
    res = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert res.status_code == 200

    # 重新查
    db = SessionLocal()
    try:
        refreshed = db.query(User).filter_by(username="admin").first()
        assert refreshed.last_login_at is not None
    finally:
        db.close()


def test_login_with_inactive_user(fresh_db):
    """is_active=False → 403（即使密码对也不让进）"""
    _seed_admin(SessionLocal())
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username="admin").first()
        u.is_active = False
        db.commit()
    finally:
        db.close()

    client = TestClient(__import__("main").app)
    res = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert res.status_code == 403
    assert "禁用" in res.json()["detail"]
