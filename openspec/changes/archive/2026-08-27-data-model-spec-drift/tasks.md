# Tasks: data-model-spec-drift (2026-08-27)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 本 change 只有 **1 个 commit**（纯文档）。

## Commit 拆解

- [ ] **commit 1**: `docs(openspec): 重写 data-model Tables Overview 11→19 张表 + 修文件路径引用 (GAP-001/GAP-006)`
  - 修正 L6 文件路径：`server/models/orm.py` → `server/tables/base.py` + 各 `server/tables/*.py`；`server/db.py` → `server/infra/db.py`
  - 顶部 "11 张表" → "19 张表"
  - 重写 Tables Overview 完整 19 张表登记
  - 新增 §15-§19 段补登 8 张历史遗漏表
  - 在"设计原则"段加一条 "spec 与代码一致性" 原则

## 验证 (v6 完成自查)

- [ ] `grep -E "server/models/orm.py|server/db.py" openspec/specs/data-model/spec.md` → 0 命中
- [ ] `grep -cE "^\| \`[a-z_]+\` " openspec/specs/data-model/spec.md` → 19 行
- [ ] `git diff --stat` 显示改动**仅** `openspec/specs/data-model/spec.md`
- [ ] commit message 单行 `-m`
- [ ] 归档：`mv openspec/changes/2026-08-27-data-model-spec-drift openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema、不跑 `sync_schema.py apply`
- [ ] 不动 `server/schema.yml`（已是正确 SoT）
