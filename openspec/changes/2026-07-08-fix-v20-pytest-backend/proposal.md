# Proposal — v20 修复套件 (pytest + backend + MySQL 网络)

## Why

v19 push 后回归测试发现三类问题，集中在测试基础设施 + 跨网访问 + 业务接口回归:

### A. Backend API 回归 + DB 连接池污染
- **A1** 后端 9/10 endpoint 200 OK，但 `/api/admin/users` 404 —— 路由正常但表无 admin 用户
- **A2** MySQL 容器接受 `localhost:33066` 外部访问，但**业务用户**`EvTrade@%`连不上 —— `infra/db.py:142` 把 SQLite 的 `check_same_thread` 错传给 MySQL admin engine，admin 连接创建失败

### B. e2e RPC 测试受市场时段约束
- **B1** `test_t0_tasks_e2e.py` 2 case 写死 `pytest.raises` 期待下单/撤单成功，但 15:00 收市后 `require_trading_session` 装饰器返 503，e2e 失败
- 真实业务行为（收市后禁单）不是 bug，**测试不应绑死非交易时段**

### C. pytest 41 ERROR（环境性，非业务）
- **C-1** `main.py` startup 启 RPC client + quote consumer，TestClient 触发真 RabbitMQ/WS 连接 → **SSL read timeout 30s+**
- **C-2** `fresh_db` fixture `drop_all + init_db` 漏 import `user.py` / `strategy_models`，重建 6 张表（17 应有），admin 用户丢失 → 9/10 → 8/10

### 衍生
- **D** v18 T0TaskList 渲染报 `Cannot read properties of undefined (reading 'realized_pnl')` —— 前端模板用 `{ overall: {...} }` 嵌套，后端实际返回扁平字段

## What Changes

### A. Backend + DB
- `server/infra/db.py` admin engine 独立 `pool_kwargs` 计算（**不**复用 SQLite kwargs）
- 已 seed admin/trader/observer 默认用户（init_db 全量 import）

### B. e2e 市场时段感知
- `test_t0_tasks_e2e.py` 加 `check(skip=...)` + `_skip` 字段：交易时段敏感 case 在非交易时段 pytest.skip 而非 fail
- e2e 当前 15/15 PASS + 2 SKIP（exit 0）

### C. pytest fixture 重设计
- `server/main.py` startup 检查 `PYTEST_CURRENT_TEST` env，**跳过 RPC/WS init**
- `test_api.py` fixture 拆为：
  - `module_init_db(scope="module", autouse=True)` —— 每 module 跑一次 `drop_all + init_db`
  - `fresh_db(autouse=True)` —— 每 test **软清**数据（白名单保留 `users`/`sys_status`/`trading_session`/`fee_config`/`reconcile_config`/`reconcile_report`/`quote_snapshots`/`order_no_seq`/`strategy_audit`）

### D. v18 T0TaskList 字段对齐
- 前端 `T0TaskList.vue:35/40/45/139` 改用后端扁平字段 `total_realized_pnl` / `active_task_count` / `avg_win_rate`
- `stores/t0_tasks.js` 默认值改 `{}`（替换 `{ overall: {}, by_stock: [] }`）

## Backward Compatibility

- e2e skip 是**测试基础设施**调整，业务代码不变
- pytest fixture 软清**保留** admin/trader 用户 + system_status 状态，**不**破坏现有测试预期
- 前端字段对齐是**修复**，行为不变
- DB pool_kwargs 分离**对生产无影响**（生产用 MySQL，原本 admin engine 就该独立 kwargs）

## Impact

| 文件 | 影响 |
|---|---|
| `server/infra/db.py` | admin engine `pool_kwargs` 重算 |
| `server/main.py` | startup 检查 `PYTEST_CURRENT_TEST` env |
| `server/services/t0/test_t0_tasks_e2e.py` | 加 `check(skip=...)` |
| `server/tests/strategy/test_api.py` | fixture 拆 module-init + per-test 软清 |
| `client/src/components/trade/T0TaskList.vue` | 字段扁平化 |
| `client/src/stores/t0_tasks.js` | overviewData 默认值 |

## Scope Boundaries

✅ **本 change 范围**:
- A1/A2 backend + DB 池修复
- B1 e2e 市场时段感知
- C-1/C-2 pytest fixture 重设计
- D v18 T0TaskList 字段对齐

❌ **不在本 change**（v21 backlog）:
- **backend segfault on trd_cfm push** —— libc.so.6 段错误（疑似 msgpacket C 扩展 AVX 指令触发，IP 0x...819 出现 `c5 f9 ef c0` 类指令；100% 复现于收到 trd_cfm 后 ~20 秒）
- MySQL 业务用户 `EvTrade@%` DDL 权限回收（DDL-only 用 root）
- 17 张表的 fixture 收敛到白名单 list（自动化）
- e2e 真 RPC mock（取代 skip）