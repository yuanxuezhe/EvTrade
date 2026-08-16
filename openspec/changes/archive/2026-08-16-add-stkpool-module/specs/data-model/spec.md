## ADDED Requirements

### Requirement: stkpool 主表（证券池）

The system SHALL 提供 `stkpool` 表存储用户/策略自定义的股票分组主表。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | INT | NO | AUTO_INCREMENT | 行主键，自增 |
| `name` | VARCHAR(64) | NO | — | 池名（唯一） |
| `remark` | VARCHAR(255) | NO | `''` | 备注 |
| `created_at` | DATETIME | NO | `CURRENT_TIMESTAMP` | 创建时间 |

**约束**：

- `PRIMARY KEY (id)`
- `UNIQUE KEY uk_stkpool_name (name)` — 池名唯一
- `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='证券池主表'`

**业务规则**：

- 主表**无** `user_id` 字段（决策 2：全局共享，不分用户）
- `name` 字段不得为空（Pydantic `min_length=1`）
- `name` 重复插入必须返回 409 `POOL_NAME_DUPLICATE`（应用层校验 + UK 兜底）
- `created_at` 必须保留（决策 3），用于审计 / 列表排序

#### Scenario: 主表创建（name 唯一）

- **WHEN** `POST /api/stkpool {"name": "白马组合", "remark": "高股息大盘"}` 收到
- **THEN** MySQL `INSERT INTO stkpool (name, remark) VALUES ('白马组合', '高股息大盘')` 成功
- **AND** 返回 201 + Row `{id: 1, name: '白马组合', remark: '高股息大盘', created_at: '2026-08-16 10:00:00'}`

#### Scenario: name 重复返回 409

- **WHEN** `POST /api/stkpool {"name": "白马组合"}` 收到，但 `stkpool` 已存在 `name='白马组合'`
- **THEN** MySQL `INSERT` 触发 `uk_stkpool_name` 唯一约束冲突
- **AND** API 捕获并返回 409 `{detail: "POOL_NAME_DUPLICATE: '白马组合'"}`

#### Scenario: 列表按 id ASC

- **WHEN** `GET /api/stkpool` 收到
- **THEN** 返回 `stkpool` 全表，按 `id ASC` 排序（TableBase.query_all 默认）

#### Scenario: 删池 CASCADE 自动清明细

- **WHEN** `DELETE /api/stkpool/5` 收到
- **THEN** MySQL `DELETE FROM stkpool WHERE id=5` 成功
- **AND** `stkpooldetail` 中所有 `id=5` 的行被 MySQL ON DELETE CASCADE 机制自动删除
- **AND** 业务代码 MUST NOT 显式 DELETE 明细表（CASCADE 已涵盖）

### Requirement: stkpooldetail 明细表（复合 PK + share-id）

> **关键决策（决策 1）**：明细表 `id` 字段**不自增**，与主表 `stkpool.id` 共享（物理聚簇）。复合 PK `(id, stock_code)` 天然去重。删除主表行通过 MySQL `ON DELETE CASCADE` 自动清明细。

The system SHALL 提供 `stkpooldetail` 表存储证券池与股票的明细关联。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | INT | NO | — | **共享主表 id（不自增）** |
| `stock_code` | VARCHAR(16) | NO | — | 股票代码 |

**约束**：

- `PRIMARY KEY (id, stock_code)` — 复合 PK
- `KEY ix_stkpooldetail_id (id)` — id 单字段索引（虽然 PK 包含 id，单独查询更高效）
- `FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE` — 删池自动清
- `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='证券池明细: share PK id + stock_code'`

**业务规则**：

- `id` 字段 MUST NOT 设 `AUTO_INCREMENT`（share-id 模式）
- `id` 字段写入时由应用层显式指定 = `stkpool.id`
- `stock_code` 字段 MUST 匹配 `^\d{6}\.(SH|SZ|BJ)$`（与 `stocks` 表 stock_code 校验对齐）
- 明细表 MUST NOT 含 `stock_name` 字段（决策：名称从 `useStocksStore.cache` 前端读）
- 同 `(id, stock_code)` 重复插入走 `upsert_one` 幂等（MySQL `ON DUPLICATE KEY UPDATE` 不报错）

#### Scenario: 复合 PK 写入

- **WHEN** 池 5 加入 600519.SH
- **THEN** MySQL `INSERT INTO stkpooldetail (id, stock_code) VALUES (5, '600519.SH')` 成功
- **AND** `(5, '600519.SH')` 成为复合 PK 唯一记录

#### Scenario: 重复明细 idempotent

- **WHEN** `(5, '600519.SH')` 已存在，再次调用 `POST /api/stkpool/5/detail {"stock_code": "600519.SH"}`
- **THEN** MySQL `INSERT ... ON DUPLICATE KEY UPDATE` 走 UPDATE 分支
- **AND** API 返回 200（既不是 201 也不是 409，复用现有行）
- **AND** 业务上无副作用（stock_code 字段值未变）

#### Scenario: 同 id 多 stock_code 物理聚簇

- **WHEN** 池 5 加入 50 只股票
- **THEN** `stkpooldetail` 中有 50 行 `id=5`（不同 stock_code）
- **AND** 物理存储聚簇（同 InnoDB 区段）
- **AND** `SELECT * FROM stkpooldetail WHERE id=5` 走 PK 范围扫，无次索引

#### Scenario: 删池级联删明细

- **WHEN** `DELETE FROM stkpool WHERE id=5` 成功
- **THEN** MySQL FK 约束触发 `DELETE FROM stkpooldetail WHERE id=5`
- **AND** 50 行明细全部自动清除
- **AND** 业务代码 MUST NOT 显式查/清明细

#### Scenario: 池不存在 → 404

- **WHEN** `POST /api/stkpool/999/detail {"stock_code": "600519.SH"}` 收到，但 `stkpool.id=999` 不存在
- **THEN** API 业务校验先查 `Stkpool.query_one(id=999)` 返 None
- **AND** 返回 404 `{detail: "POOL_NOT_FOUND: id=999"}`
- **AND** **不会** INSERT `stkpooldetail`（避免孤儿行）

### Requirement: stkpool 视图 vs 现状

The system SHALL 在 `data-model` 知识库 Tables Overview 表中添加 `stkpool` 与 `stkpooldetail` 两项（同步 spec 增量），保持文档与 DB 一致。

#### Scenario: Tables Overview 登记

- **WHEN** 同步 `openspec/specs/data-model/spec.md` Tables Overview
- **THEN** 在"业务核心"分组添加：
  - `stkpool` — 业务 — `id` 自增 — 否 — `server/api/stkpool.py`
  - `stkpooldetail` — 业务 — `(id, stock_code)` 复合 — 否 — `server/api/stkpool.py`
- **AND** Tables Overview 总表数从 15 → 17

## MODIFIED Requirements

无（本次为全新模块，不修改现有表）。
