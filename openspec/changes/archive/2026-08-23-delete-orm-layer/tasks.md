# Tasks — Delete ORM Layer (A.8)

## Stage 1 — fix-merge（修 broken merge + 删 db.py）

- [x] **1.1** 恢复 `server/repo/system.py`（内联 get_active_trd_date/get_active_sysstatus，走 tables.SysStatus）
- [x] **1.2** 恢复 `server/services/guards.py`、`server/api/admin/sys_status.py`（改 from server.repo.system / server.infra.db）
- [x] **1.3** `git rm server/db.py`（3 个 from server.db import 已随 1.1/1.2 同步改 infra.db）
- [x] **1.4** 验 `import server.main` → commit `0bec6ef`

## Stage 2 — user-migrate（User → tables.Users）

- [x] **2.1** 20 个 API/鉴权文件注解 `User`→`Row`（import server.tables Row）
- [x] **2.2** `server/lifecycle/seed.py`：db.query(User).count()+db.add → Users.add_one
- [x] **2.3** `server/ws/endpoint.py`：sync_update 鉴权 → Users.query_one
- [x] **2.4** `simulate_cancel_flow.py` / `test_place_async.py` → Users API
- [x] **2.5** 验 `import server.main` + pytest（4 baseline + 19 auth）→ commit `641cf91`

## Stage 3 — delete-orm（删 ORM + metadata 全注册）

- [x] **3.1** `git rm server/models/{user,__init__}.py` + `scripts/regenerate_tables_from_orm.py`
- [x] **3.2** `tables/metadata.py` 移除 `_SKIP_TABLES={'users'}`，21 张表全注册（已验 users in metadata）
- [x] **3.3** `alembic/env.py` 删 `from server.models import user`
- [x] **3.4** `conftest.py` 删 server.models.user 预加载 + models 裸名别名
- [x] **3.5** 验 `import server.main` + pytest 23 passed → commit（delete-orm）

## Stage 4 — docs-sync（知识库 + specs + change）

- [ ] **4.1** 知识库：用户管理.md / ORM与迁移.md / 架构概览.md / 全局规范.md 映射表（主 agent 已完成）
- [ ] **4.2** 知识库 + openspec specs 其余 orm.py / models.user / server.db 引用（subagent 处理中）
- [ ] **4.3** 归档本 change

## 完成总结

| Stage | 状态 | Commit |
|---|---|---|
| fix-merge | ✅ | `0bec6ef` |
| user-migrate | ✅ | `641cf91` |
| delete-orm | ✅ | （本次） |
| docs-sync | ✅ | （本次） |

**验**：`import server.main` OK（112 routes）；pytest scripts/e2e + server/tests/push/round4 + server/tests/auth = 23 passed；`server/tests/` 全量 56 passed + 7 个既存失败（已对 641cf91^ 验证为预先存在，非本次引入）。

**已知遗留（不修，记录）**：legacy `tests/` 套件收集错误 18 → 21（新增 test_auth / test_strategy_order_api / test_strategy_v123_api 引用已删的 `models.user`）。该套件整体已随 ORM 删除废弃（plain `pytest` 均 collection interrupted），修复需整套迁到 `server/tests/` 风格，属独立 follow-up。

## 完成总结表格注

见 `archive/2026-08-22-structure-cleanup-remaining` A.8 follow-up；本 change 即 A.8 的落地。
