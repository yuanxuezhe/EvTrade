# Test Auth & Default Admin Seed

## Why

v4 实施期间曾因 `main.py` 改动顺序问题把 `db.py` 改坏，被迫 `git checkout` 回滚至 `cc7b67a`。
回滚时 `main.py` 的"用户表为空 → seed 默认 admin 账户"逻辑未单独留测试，导致后续 `965a76d` v5 commit 时担心这逻辑被再次冲掉。

本次任务的"增加用户表 + 登录从用户表验证 + admin/admin123 默认 seed"功能**实际已实现**（`models/user.py` 11 张表之一、`api/auth.py:55-60` 已查表验证、`main.py:34-46` 启动 seed），但**无专项测试覆盖**，回归保护不足。

## What

新建 `server/test_auth.py`，覆盖 4 个场景：

1. **`test_login_with_default_admin`**：清空 users 表 → 触发 startup seed → POST `/api/auth/login` with `admin/admin123` → 200 + JWT
2. **`test_login_with_invalid_password`**：seed admin → POST 错密码 → 401
3. **`test_login_with_nonexistent_user`**：空 users 表 + 错用户名 → 401（验证不会绕过用户表）
4. **`test_login_updates_last_login_at`**：seed admin → 登录 → 查 users 表 `last_login_at` 非空

**不新增代码**，只新增测试。

## 设计决策

- **直接 import `from main import app`** 触发 `@app.on_event("startup")` 在 fixture 里跑（不重新跑进程）
- **不依赖运行中 backend**（fixture 起 TestClient，pyproject `evtrade.db` 隔离）
- **不修 v4 已知 `Position.market_value` bug**（在 `holdings-read-local-db` change 中已用 `cost × total` 代理）

## 风险

- 触发 startup seed 会创建 admin，可能污染测试 DB → 用 fresh_db fixture（drop_all + create_all）+ startup handler 后置
- `init_db()` 会 idempotent，不会重复 seed

## 影响面

- 新增：`server/test_auth.py`（~150 行）
- 不改任何业务代码
- 测试覆盖度：+4 测试
