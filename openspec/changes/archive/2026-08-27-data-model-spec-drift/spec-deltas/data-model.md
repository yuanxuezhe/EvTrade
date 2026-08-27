# data-model — Spec Delta (2026-08-27)

## 修改类型

MODIFIED — 重写 Tables Overview 11→19 张表 + 修文件路径引用

## 变更内容

### § 顶部文件路径引用修正 (L6)

**Before**:
```
ORM 注释（`server/models/orm.py` 自动生成）必须与本 spec 保持一致（diff 检查项之一）。
```

**After**:
```
ORM 注释（`server/tables/base.py` + 各 `server/tables/<表名>.py`，由 `scripts/gen_tables.py` 自动生成）必须与本 spec 保持一致（diff 检查项之一）。

DB 引擎实现在 `server/infra/db.py`（v20 起，MySQL-only）。
```

### § 顶部表数声明 (L5)

**Before**:
> 15 张表（业务 6 + 策略/脚本 3 + 系统/用户 4 + 对账/序列 2）

**After**:
> 19 张表（业务 6 + 策略/脚本 9 + 系统/用户 4 + 对账/序列 2 + 鉴权 1）
> （注：v130 schema governance 实施后准确值为 19 张，本 spec 同步）

### § Tables Overview — 重写为 19 张

**Before**: 11 张表登记

**After**: 完整 19 张表登记，按业务域分组

### § 设计原则 — 新增一条

**新增**:
- **spec ↔ 代码一致性**: 新增/删表时必须同时改本 spec + 跑 `sync_schema.py export` 更新 `server/schema.yml`。spec 是 schema 描述的 SoT（详见 `evtrade-schema-governance` skill）。

## 影响面

- 文档一致性 +1：spec 描述与 `server/tables/*.py` 真实 19 张表对齐
- 后续 GAP-001 audit 闭环
- 下一刀 P0-3 同类修复 ws-protocol（5→7 channel）

## 不修改

- 不动 `server/tables/*.py`（已正确）
- 不动 `server/schema.yml`（已正确）
- 不动 DB 数据（用户硬规则 2026-08-27）
- 不跑 `sync_schema.py apply`
