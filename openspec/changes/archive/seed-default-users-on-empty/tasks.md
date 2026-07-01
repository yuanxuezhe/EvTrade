# Tasks — seed-default-users-on-empty

## 实施 commit
- `ba8b364` fix: Python 3.6.8 兼容性 + 默认账号问题
  - H7: `on_startup` 同时种 admin + trader 两个默认账号
  - 现场补 admin 行（手动 insert，让 admin/admin123 立刻能登录）

## 任务列表

- [x] 1. 改 `server/main.py::on_startup` — `ba8b364`
  - [x] 1.1 `if count == 0:` 块中插入 admin（保留现有逻辑）
  - [x] 1.2 紧跟其后插入 trader（role='trader', full_name='默认交易员'）
  - [x] 1.3 改 `[INIT]` 日志输出两行账号信息
- [x] 2. 现场往 `server/evtrade.db` 插 admin 行（让用户立刻能登录） — `ba8b364` 配套
- [x] 3. 更新 `openspec/specs/auth/spec.md` — `ba8b364`
  - [x] 3.1 S-AUTH-001 措辞改为"自动创建 admin/admin123 和 trader/trader123"
  - [x] 3.2 新增 S-AUTH-006 "wipe 后自动补两个默认账号"
- [x] 4. `python scripts/evctl.py restart` — `ba8b364`
  - [x] `[OK] backend healthy`
  - [x] `curl /api/auth/login -d 'username=admin&password=admin123'` → 200 + JWT
- [x] 5. commit — `ba8b364`
- [x] 6. tracking `current-issues/proposal.md` 标记 H7 Done — `dd5c761`

## 验证

- [x] admin/admin123 登录 → 200 + JWT（user.role='admin', must_change_password=true）
- [x] wipe users 表 → 重启 → 日志见 `[INIT] Created default accounts`，DB 里有 admin + trader
- [x] trader/trader123 登录 → 200 + JWT
- [x] pytest 18/N 全绿（无回归）
- [x] `git log --oneline -1` 显示 `ba8b364`

## 备注

- on_startup 逻辑后来被 `d35e2a7 refactor(server): main.py 拆 lifecycle.seed + ws.endpoint` 移到 `server/lifecycle/seed.py`，bug fix 行为保留
- "若 trader1 存在但 admin 不存在，admin 永远不会被种" 这一深层 bug **未在本 change 修复**（用户接受的修复语义是"首启动同时种两个 + 手动补 admin 行"）；如需 idempotent 修复可另起 change