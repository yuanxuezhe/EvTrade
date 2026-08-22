# Proposal — Delete ORM Layer (A.8 follow-up)

## Why

`2026-08-22-structure-cleanup-remaining` partial-archive 的 A.8 follow-up：数据访问层重写（v81 → v132）最后一步——删除残留的 ORM 兼容层。此前 orm.py 已删（`267bef8`），但 merge `cb30676` 取回了 Phase B 侧的旧 import（`server.models.orm`）导致服务无法启动；`server/models/user.py` + `server/db.py` 仍是兼容垫片，24+ 个业务文件仍 import ORM `User`。

本次把 `server/models/` 与 `server/db.py` 彻底删除，`server/tables/` 成为数据访问唯一入口（含 users 表 metadata 注册）。

## What Changes

| Stage | 改动 |
|---|---|
| **fix-merge** | 恢复 3 个被 merge 覆盖的文件（repo/system.py 内联 get_active_* helper；guards / admin/sys_status 改 `from server.repo.system` / `from server.infra.db`）；`git rm server/db.py` |
| **user-migrate** | 25 个 `from server.models.user import User` 引入方迁移：20 个仅类型注解 `User`→`Row`；seed.py / ws/endpoint.py / simulate_cancel_flow.py / test_place_async.py 的真实 ORM 读写改 `tables.Users` API |
| **delete-orm** | `git rm server/models/{user,__init__}.py` + `scripts/regenerate_tables_from_orm.py`（加载已删 orm.py 的死代码）；`tables/metadata.py` 移除 `_SKIP_TABLES={'users'}`（21 张表全注册）；`alembic/env.py` 删 `from server.models import user`；conftest.py 删 models 裸名别名；相关注释同步 |
| **docs-sync** | 知识库（用户管理 / ORM与迁移 / 架构概览 / 全局规范映射表 / WS端点 / 日初初始化 / 测试体系 / 数据库迁移与Schema）+ openspec specs 中 orm.py / models.user / server.db 引用清理 |

## Backward Compatibility

- fix-merge：`import server.main` 恢复可启动；`server/db.py` 删除后无 `from server.db import` 残留（已验证）
- user-migrate：`get_current_user` 本已返 tables `Row`，`User`→`Row` 注解是语义修正，行为不变；auth/ws/seed 已过 pytest
- delete-orm：`tables.metadata` 验证 `Base.metadata` 注册 21 张表含 users；legacy `tests/`（引用已删 orm.py）为既存不可收集，非新增回归

## Risks

- **alembic 未安装**：`alembic/env.py` 无法直接 import 验证，但文件 AST 通过、metadata 注册路径已独立验证
- **legacy `tests/` 目录**：18 个文件引用已删 orm.py/user.py，pytest 收集报错（`testpaths = tests`）；非本 change 引入，暂不迁移

## Decisions

| # | 决策点 | 结果 |
|---|---|---|
| Q1 | current_user 注解类型 | `Row`（get_current_user 实际返回 tables.base.Row） |
| Q2 | `server/models/` 空目录 | 连同 __init__.py 整体删除 |
| Q3 | legacy `tests/` 18 文件 | 保持既存失败，不迁移（ORM 已删，需整套重写） |
| Q4 | `regenerate_tables_from_orm.py` | 删除（加载已删 orm.py，由 gen_tables.py 取代） |

## Reference

- 知识库/后端服务/数据层/ORM与迁移.md
- 知识库/后端服务/用户鉴权/用户管理.md
