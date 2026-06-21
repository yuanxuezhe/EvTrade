# Data model knowledge base (single source of truth for schema)

## Why

11 张本地 SQLite 表（orders / trades / positions / assets / sys_status / trading_session / fee_config / reconcile_config / reconcile_report / quote_snapshots / order_no_seq）的 schema 散落在 `server/models/orm.py` 注释里，没有独立 spec：

- 想改 schema（加列、调类型、改 PK）的人不知道字段语义、PK 规则、约束、默认值
- 不知道某列是不是被前端依赖、是不是被 push handler 写入
- v5 重构（`2026-06-15-schema-refactor`）已经改过 6 张表的 schema，但变更没沉淀到独立 spec，下个人改的时候没有参考
- 后端表 ↔ 前端 store ↔ WS 推送字段的映射在多份注释里反复出现，没有 single source of truth

## What Changes

### 1. 新建 capability `data-model`

- 路径：`openspec/specs/data-model/spec.md`
- 内容：
  - 11 张表的完整字段表（字段、类型、可空、默认、说明）
  - 主键 / Unique / Index / Check 约束
  - 业务规则（写入方、读出方、推送到字段映射）
  - 单行表的多行访问约定
  - 跨表引用（如 `sys_status.trd_date` ↔ `orders.trd_date`）

### 2. 同步现有 4 个 cap spec 引用 data-model

- `trading/spec.md` 引用 data-model 第 1 / 2 / 4 节（orders / trades / assets）
- `positioning/spec.md` 引用 data-model 第 3 节（positions）
- `push/spec.md` 引用 data-model 第 1 / 2 / 3 / 4 节（落库字段映射）
- `frontend/spec.md` 引用 data-model 全文（前端 store 与 DB schema 校对）

### 3. `server/models/orm.py` 注释与 data-model 同步

- ORM 类的 docstring 顶部加「详见 `openspec/specs/data-model/spec.md` 第 N 节」
- diff 检查项：每次改 ORM 必同步 spec，反之亦然

## Capabilities

### New Capabilities
- `data-model`: 11 张表结构 + 业务规则

### Modified Capabilities
- `trading` / `positioning` / `push` / `frontend`: 加引用链接

## Impact

- `openspec/specs/data-model/spec.md` — 新建
- `server/models/orm.py` — 顶部注释 + 各 class docstring 改 11 处（每张表 1 处）
- 4 个现有 spec 加 1 行 cross-reference
- 无运行时影响（纯文档）

## Verification

1. `openspec/specs/data-model/spec.md` 存在，包含 11 张表
2. `grep -l "详见.*data-model" server/models/orm.py` 应找到 11 个 class
3. 4 个 cap spec 都有引用 data-model 的链接
4. 无代码变更；现有 `pytest server/` 全绿

## Spec Deltas

本 change 不需要 spec-deltas（新建 cap，spec 内容已直接放在 `specs/data-model/spec.md`）。
