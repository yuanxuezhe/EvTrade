# Tasks — seed-default-users-on-empty

## 实施步骤

- [ ] 1. 改 `server/main.py::on_startup`：
  - [ ] 1.1 `if count == 0:` 块中插入 admin（保留现有逻辑）
  - [ ] 1.2 紧跟其后插入 trader（role='trader', full_name='默认交易员'）
  - [ ] 1.3 改 `[INIT]` 日志输出两行账号信息
- [ ] 2. 现场往 `server/evtrade.db` 插 admin 行（让用户立刻能登录；用 `inspect_users.py` 同款脚本，加 insert）
- [ ] 3. 更新 `openspec/specs/auth/spec.md`：
  - [ ] 3.1 S-AUTH-001 措辞改为"自动创建 admin/admin123 和 trader/trader123"
  - [ ] 3.2 新增 S-AUTH-006 "wipe 后自动补两个默认账号"
- [ ] 4. `python scripts/evctl.py restart`：
  - [ ] `[OK] backend healthy`
  - [ ] `curl /api/auth/login -d 'username=admin&password=admin123'` → 200
- [ ] 5. commit: `feat(server): on_startup seed admin+trader when users table empty`
- [ ] 6. 把 `current-issues/proposal.md` 现有 H6 之后或单独加一行指向本 change

## 验证

- [ ] admin/admin123 登录 → 200 + JWT（user.role='admin', must_change_password=true）
- [ ] wipe users 表 → 重启 → 日志见 `[INIT] Created default accounts`，DB 里有 admin + trader
- [ ] trader/trader123 登录 → 200 + JWT
- [ ] pytest 18/N 全绿（无回归）
- [ ] `git log --oneline -1` 显示新 commit