# 2026-08-10-reconcile-report-json-longtext — reconcile_report JSON 列 TEXT→LONGTEXT

## Why

手动日初（POST /api/admin/sys-status/init）返回 **500**，后端日志：

```
pymysql.err.DataError: (1406, "Data too long for column 'local_positions_json' at row 1")
```

`do_reconcile(reconcile_kind='init')` 会把本地全部持仓快照序列化写入 `reconcile_report.local_positions_json`（server/services/reconcile.py:129）。全市场 2197 只持仓的 JSON 达数百 KB，而实际 DB 列是 `TEXT`（上限 64KB）→ 溢出 → 500。

排查发现这是**三处漂移**：代码（orm.py / schema.yml / tables 自动生成）已声明 `LONGTEXT`，**实际 DB 列是 `TEXT`**，而 data-model spec 也错误地写着 `Text`。即 schema 从未按代码落到 DB（历史 `sync_schema.py apply` 前的存量表），init 首次写大快照即触发。

## What Changes

### 知识库（data-model spec 修正）

`openspec/specs/data-model/spec.md` 中 `reconcile_report` 的 5 个 JSON 列：
`diffs_json` / `broker_asset_json` / `local_asset_json` / `broker_positions_json` / `local_positions_json`
类型从 `Text` 修正为 `LONGTEXT`（与 orm.py / schema.yml / tables 一致）。

### DB 迁移（对齐代码类型）

新增 `server/migrations/2026-08-10-reconcile-report-json-longtext.py`：
`ALTER TABLE reconcile_report MODIFY <列> LONGTEXT` 共 5 列。

- 幂等：先查 INFORMATION_SCHEMA.COLUMNS，仅当列当前为 `varchar`/`char`/`text`/`mediumtext`（非 `longtext`）时才 MODIFY；已是 `longtext` 则跳过
- 验证：改后打印 5 列新类型
- **不动** `sync_schema.py apply`（diff 显示它还会 ADD 已删的 strategy 死表等无关变更）

> **2026-08-12 追加（修复实际 500）**：迁移提交后 evtrade_dev 上 **`POST /api/admin/sys-status/init` 仍 500**（`Data too long for column 'broker_positions_json'`）。
> 实际 DB 前态与最初假设不同，为两处漂移：
> - `evtrade_dev`（运行服务器连接库）：5 列是 **`varchar(255)`** — 原守卫 `text`/`mediumtext` REFUSE，迁移对 dev 无效
> - `evtrade`（生产库）：5 列是 **`text`**（64KB），对 broker 快照（≈6KB）够、但对 local 全量快照（数百 KB）溢出
> 故把守卫放宽为 `varchar`/`char`/`text`/`mediumtext` → LONGTEXT，并已对 evtrade_dev 实际执行（5 列全部 `varchar→longtext`，verify 通过）。
> 另注：`server/tables/reconcile_report.py`（codegen 元数据）实际声明 `text` 而非 LONGTEXT，与 orm.py 不一致——仅元数据/type-hint，不影响运行，未在本次修改。

### 不做的事

- ❌ 不改 orm.py / schema.yml / data-model spec（已正确声明 LONGTEXT）
- ❌ 不改 do_reconcile 写入逻辑（列容量足够后无需裁剪快照）
- ❌ 不在本 change 内处理 `sync_schema.py diff` 暴露的其它漂移（strategy 死表残留 schema.yml 条目等）

## 时序

```
init POST → do_reconcile(init) 写 reconcile_report
  local_positions_json(2197 持仓 ≈ 数百 KB)
  └─ 迁移前: TEXT(64KB) 溢出 → 500
  └─ 迁移后: LONGTEXT(4GB) 正常落库
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 知识库 | `openspec/specs/data-model/spec.md` | reconcile_report 5 JSON 列 `Text` → `LONGTEXT` |
| 迁移 | `server/migrations/2026-08-10-reconcile-report-json-longtext.py` | 新增，ALTER 5 列 → LONGTEXT（幂等） |
| 知识库 | `openspec/changes/2026-08-10-reconcile-report-json-longtext/` | proposal.md + spec-delta + tasks.md |

## 关联

- 上游：`data-model/spec.md` §9 `reconcile_report` 表
- 触发：`init-push-gate`（2026-08-10）验证 init 流程时暴露的存量 schema 漂移
