## MODIFIED Requirements

### Requirement: REQ-STRAT-003 — 4 张表（原「4 张 ORM 表」，改为「4 张表，Core Table 定义」）

`server/services/strategy/models.py` 的 7 个 strategy ORM 类删除后，4 张策略表
（`Strategy` / `StrategyRegime` / `StrategyGrid` / `StrategyAudit`）的表定义归
`server/tables/strategy*.py`（codegen 生成，SQLAlchemy Core `Table` 对象注册到
`Base.metadata`）。另有 3 张脚本策略表（`StrategyScript` / `StrategyTask` /
`StrategyScriptAudit`）同样归 `tables/`。

#### 变更前（spec 现状）

spec L42「### REQ-STRAT-003: 4 张 ORM 表」+ L43-46 列出字段定义。

#### 变更后

- 标题改为「### REQ-STRAT-003: 4 张表（Core Table 定义）」
- 字段定义不变（schema 未变，只是 ORM declarative → Core Table）
- 表结构真源改为 `server/tables/strategy*.py`（codegen 生成），不再引用
  `server/services/strategy/models.py`

#### Scenario: strategy 表定义来自 tables/

- **WHEN** 维护者需要查看 `Strategy` 表的字段定义
- **THEN** 查看 `server/tables/strategy.py`（codegen 生成）或
  `openspec/specs/data-model/spec.md` §4
- **AND** `server/services/strategy/models.py` 不存在

#### Scenario: flags/payload getter/setter 为 Row 纯函数

- **WHEN** 业务代码需要读写 `StrategyRegime.required_flags`（JSON 字段）
- **THEN** 调用 `services/strategy/repository.py`（或 flags.py）的纯函数：
  `get_required_flags(regime_row)` / `set_required_flags(regime_row, [...])`
- **AND** 函数操作 `Row` 对象的 `_data['required_flags']`，序列化用 `json.dumps`
- **AND** 不再有 `regime.get_required_flags()` 实例方法（ORM 类已删）

#### Scenario: strategy 表的 metadata 注册

- **WHEN** alembic autogenerate 或 `init_db()` 扫描表结构
- **THEN** `import server.tables` 触发 `Table("strategy", Base.metadata, Column(...), ...)`
  注册到 `Base.metadata`
- **AND** 不再依赖 `from server.services.strategy import models` 触发注册
