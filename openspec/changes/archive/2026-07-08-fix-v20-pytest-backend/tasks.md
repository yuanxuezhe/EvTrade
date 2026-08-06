# v20 Tasks

## 1. Backend 回归 (A1/A2)
- [x] A1: 复测 backend API 9/10 200 + `/api/admin/users` 404 (admin 表缺)
- [x] A2: `server/infra/db.py:142` admin engine 独立 pool_kwargs
  - 提交: `74fdde0 fix(infra): admin engine 重算 pool_kwargs (避免 SQLite check_same_thread 误传给 MySQL)`
- [x] 手动 `init_db()` 重建 17 张表 + seed admin/trader/observer

## 2. e2e 市场时段感知 (B1)
- [x] B1: `test_t0_tasks_e2e.py` 加 `check(skip=...)` + `_skip` 字段
  - 提交: `6f4e72a test(e2e): trading_session 时段敏感测试加 skip (收市后 503 是正常业务行为)`
  - 验证: 15/15 PASS + 2 SKIP (exit 0)

## 3. pytest fixture 重设计 (C1)
- [x] C-1: `server/main.py` PYTEST_CURRENT_TEST env 跳过 RPC + quote_consumer
- [x] C-2: `test_api.py` fixture 拆 module-init + per-test 软清
  - 提交: `5eb3610 test(server): pytest fixture 软清 + main.py 跳过真 RPC`
  - 验证: 9/10 + admin login 200 (业务用户保留)

## 4. v18 衍生 bug (D)
- [x] D: `T0TaskList.vue` + `stores/t0_tasks.js` 扁平字段对齐
  - 提交: `378249a fix(client): T0TaskList 改用后端扁平 overview 字段`

## 5. 验收
- [ ] /opsx:verify 2026-07-08-fix-v20-pytest-backend
- [ ] push 全部 v20 commits (74fdde0 + 6f4e72a + 5eb3610 + v20 openspec)
- [ ] 本地 e2e/test_api 套件全绿
  - 注: 所有代码已验证落地（commit 74fdde0, 6f4e72a, 5eb3610, 378249a 均已存在；db.py/main.py/test_api.py/e2e/T0TaskList.vue/t0_tasks.js 均已确认）

## 6. v21 backlog (NOT in v20)
- [ ] backend segfault on `trd_cfm` push (libc.so.6 AVX)
- [ ] MySQL 业务用户 `EvTrade@%` DDL 权限回收
- [ ] 17 张表 fixture 白名单收敛为配置
- [ ] e2e 真 RPC mock (取代 skip)