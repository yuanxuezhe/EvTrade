# Fix: data-model spec Tables Overview 11→19 张表 + 错误文件路径

> 用户拍板 2026-08-27：按 P0 顺序修第一刀。Why 详见 `openspec/specs/KNOWLEDGE_GAP_AUDIT.md` GAP-001 + GAP-006（🔴 致命级）。

## Why

`openspec/specs/data-model/spec.md` 是项目数据库表结构的**单一事实源**（v20 起强制 MySQL-only），但严重过期：

1. **Tables Overview 写 11 张，实际 19 张**（已通过 2026-08-23 delete-orm-layer 实施完毕）。**缺登 8 张**：
   - `users` / `sys_config` / `stocks`（系统/用户/证券基础表）
   - `t0_tasks` / `stkpool` / `stkpooldetail` / `quote_snapshots`（业务侧补齐）
   - `strategy` / `strategy_task` / `strategy_grid` / `strategy_regime` / `strategy_audit` / `strategy_script` / `strategy_script_audit` / `strategy_order` / `token_sessions`（策略 + 鉴权）

2. **L6 引用错误文件路径**：声称 ORM 在 `server/models/orm.py` + `server/db.py`，**这两个文件都不存在**。实际：
   - ORM 已迁到 `server/tables/base.py` + 各 `server/tables/<表名>.py`（v81 ORM→tables 迁移）
   - DB 引擎在 `server/infra/db.py`（v20 起）

**影响**：
- AI 助手按 spec 写代码会漏 8 张表（特别是 `users` / `strategy_task` / `token_sessions` 等关键表）
- 新人 onboarding 按 spec 看 schema，少 8 张上手就漏掉 strategy/用户/认证模块
- spec 自身失信 → 后续 audit 类工作（CI drift check）无依据

## What

**单 commit 单目的**（按 v6 规范）：纯文档修复，零代码改动，零数据风险。

1. **修正 L6 文件路径引用**：
   - `server/models/orm.py` → `server/tables/base.py` + 各 `server/tables/*.py`
   - `server/db.py` → `server/infra/db.py`
   - 顶部 "11 张表" 改为 "19 张表"（v130 schema governance 实施后准确值）

2. **重写 Tables Overview**：从 11 张 → **19 张表完整登记**，每张表保留：表名 / 分类 / 主键 / 单行约束 / 业务入口文件

3. **新增 §15-§19 段**登记 8 张历史遗漏表：
   - §15 鉴权（`users` + `token_sessions`）
   - §16 证券基础（`stocks`）
   - §17 配置（`sys_config`）
   - §18 策略全套（`strategy` + `strategy_task` + `strategy_grid` + `strategy_regime` + `strategy_audit` + `strategy_script` + `strategy_script_audit` + `strategy_order`）
   - §19 业务扩展（`t0_tasks` + `stkpool` + `stkpooldetail` + `quote_snapshots`）

4. **建立 "spec 与代码一致性" 原则**（在设计原则段加 1 条）：新增/删表时必须同时改本 spec + 跑 `sync_schema.py export` 更新 `server/schema.yml`。

## 不做什么

- **不动** `server/tables/*.py`（已正确，19 张表 ORM 都在）
- **不动** `server/schema.yml`（已正确，yml 是 schema SoT）
- **不动** DB（用户硬规则 2026-08-27：禁止清表数据，本次纯文档修复）
- **不**重构 spec 结构（H2 编号 / H1 标题等小瑕疵留到 P3-2 spec 索引重建时统一处理）

## 验证 (v6 完成自查)

- [ ] `grep -E "server/models/orm.py|server/db.py" openspec/specs/data-model/spec.md` → 0 命中
- [ ] `grep -cE "^\| \`[a-z_]+\` " openspec/specs/data-model/spec.md` → 19 行（11 业务+8 补登）
- [ ] `diff <(grep -oE '\`[a-z_]+\`' server/tables/*.py | sort -u | grep -v base | grep -v init | grep -v _applied) <(grep -oE '\`[a-z_]+\`' openspec/specs/data-model/spec.md | sort -u)` → 集合一致
- [ ] `git diff --stat` 显示改动**仅** `openspec/specs/data-model/spec.md`（不混入其它文件）
- [ ] commit message: `docs(openspec): 重写 data-model Tables Overview 11→19 张表 + 修文件路径引用 (GAP-001/GAP-006)`
- [ ] 归档：`mv openspec/changes/2026-08-27-data-model-spec-drift openspec/changes/archive/`

## 关联

- 上游审计：`openspec/specs/KNOWLEDGE_GAP_AUDIT.md` § GAP-001 + GAP-006
- 同类待修：GAP-002（ws-protocol 5→7 channel）— 下一刀 P0-3
- 远期：GAP-005（auth spec 漏 /grant + /heartbeat）/ GAP-003（strategy spec 漏 script-strategy）— P1 队列

## 不修改的数据

- 任何 MySQL 表、列、行数据全部不动（用户硬规则 2026-08-27）
- 不 drop / truncate / delete from 任何表
- 不重建 schema、不跑 `sync_schema.py apply`
- 不动 `server/schema.yml`（已是正确 SoT）
