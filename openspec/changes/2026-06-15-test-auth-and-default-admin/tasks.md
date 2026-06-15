# Tasks: Test Auth & Default Admin Seed

## Phase 1: Tests

- [ ] T1.1 新建 `server/test_auth.py`
  - import `from main import app`
  - 用 `fresh_db` fixture（drop_all + create_all）
- [ ] T1.2 `test_login_with_default_admin`
  - fresh_db → 触发 startup → POST `/api/auth/login` (admin/admin123) → 200 + token
- [ ] T1.3 `test_login_with_invalid_password`
  - seed admin → POST 错密码 → 401
- [ ] T1.4 `test_login_with_nonexistent_user`
  - 空 users 表 + 错用户名 → 401
- [ ] T1.5 `test_login_updates_last_login_at`
  - seed admin → 登录 → 查 `last_login_at` 非空

## Phase 2: Verify

- [ ] T2.1 `rm -f server/evtrade.db && pytest server/test_auth.py -v` 全绿
- [ ] T2.2 全量 `pytest server/test_*.py -v --tb=line` 累计通过数 +4
- [ ] T2.3 跑 `restart.sh restart` 拉起 backend → 验证 admin/admin123 仍可登录

## Phase 3: Commit

- [ ] T3.1 `git diff server/test_auth.py` 预览
- [ ] T3.2 `git add server/test_auth.py` → commit "test(auth): 覆盖默认 admin seed + 登录用户表验证"
- [ ] T3.3 `git push -c http.proxy=http://127.0.0.1:10809 origin master`
- [ ] T3.4 归档 change → `openspec/changes/archive/2026-06-15-test-auth-and-default-admin/`
