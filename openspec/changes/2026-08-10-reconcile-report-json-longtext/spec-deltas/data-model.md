# spec-delta: data-model — reconcile_report JSON 列 TEXT→LONGTEXT

## REQ-DM-041（修正）：reconcile_report JSON 快照列 MUST 为 LONGTEXT（reconcile-report-json-longtext 2026-08-10）

`reconcile_report` 表 5 个 JSON 快照列 MUST 声明并落库为 `LONGTEXT`（对齐 orm.py / schema.yml / tables 自动生成代码）：

`diffs_json` / `broker_asset_json` / `local_asset_json` / `broker_positions_json` / `local_positions_json`

**Why**：`do_reconcile(reconcile_kind='init')` 将全市场持仓快照（2197 只 ≈ 数百 KB JSON）写入 `local_positions_json`。历史 DB 列误建为 `TEXT`（上限 64KB）→ init 返回 500（`DataError 1406`）。代码层早已是 `LONGTEXT`，本 delta 修正 spec 与 DB 实际列。

#### Scenario: 日初 init 写入全量持仓快照不溢出

- **GIVEN** DB `reconcile_report.local_positions_json` 列类型为 `LONGTEXT`
- **WHEN** `do_reconcile(reconcile_kind='init')` 写入本地全量持仓 JSON（可 > 64KB）
- **THEN** 落库成功，init 返回 200，不再抛 `DataError 1406`

#### Scenario: 迁移幂等

- **GIVEN** 列已是 `LONGTEXT`
- **WHEN** 重跑 `server/migrations/2026-08-10-reconcile-report-json-longtext.py`
- **THEN** 跳过 MODIFY，不报错

## Cross References

- `data-model/spec.md` §9 `reconcile_report` 表
- 触发来源：`changes/2026-08-10-init-push-gate`（init 流程验证暴露存量漂移）
