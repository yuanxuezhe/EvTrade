## ADDED Requirements

### Requirement: 12. `t0_tasks` 表（v18 新增）

**PK**: `id`（自增 int）

**业务定位**：T0 做 T 任务实体。一份 task = 一只券 + 一个底仓 + 一个目标开仓量 + 一个生命周期（active / closed / archived）。

**单行**：否（一用户多任务；一用户一对多）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer PK autoincrement | NO | — | 主键 |
| `user_id` | Integer FK→users.id | NO | — | owner；与 users 表级联 NOT enforced（手动控） |
| `stock_code` | String(16) | NO | — | 股票代码（不带 `.SH`/`.SZ` 后缀冗余，按既有约定带后缀） |
| `base_volume` | Integer | NO | 0 | 底仓量（"保留部分底仓"语义，>0 时不平到 0） |
| `target_volume` | Integer | NO | 0 | 目标开仓量（区别于现仓位；可为负=净减仓目标） |
| `coefficient` | Float | NO | 1.0 | 配平系数（沿用 REQ-TRADE-005 语义） |
| `status` | Enum('active','closed','archived') | NO | 'active' | 生命周期 |
| `note` | String(255) | YES | NULL | 用户备注 |
| `created_trd_date` | String(8) | NO | — | 创建时所属交易日（业务字段，不用 created_at 倒推） |
| `created_at` | DateTime | NO | now() | 创建时间 |
| `closed_at` | DateTime | YES | NULL | 关任务时间 |

**索引**：
- PK(id)
- INDEX(stock_code) — 按股票过滤
- INDEX(status, created_at) — 列表按状态 + 时间排序
- INDEX(user_id, status) — 按用户权限过滤

**与其他表关系**：
- `orders.task_id` → `t0_tasks.id`（nullable FK；不强制外键约束以保留历史 user_def='T0' 单的兼容）
- 不级联删除：删 task 时仅置 orders.task_id = NULL（保留审计）

#### Scenario: 建表迁移幂等

- **WHEN** migration `add-t0-tasks.py` 跑
- **THEN** `CREATE TABLE IF NOT EXISTS t0_tasks (...)` 幂等
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_stock_code ON t0_tasks(stock_code)`
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_status_created ON t0_tasks(status, created_at)`
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_user_status ON t0_tasks(user_id, status)`
- **AND** MySQL：`CREATE TABLE IF NOT EXISTS ... ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`
- **AND** SQLite：`CREATE TABLE IF NOT EXISTS ... `（SQLite 兼容模式用 text 类型替代 enum）

#### Scenario: SQLAlchemy ORM 定义

```python
class T0Task(Base):
    __tablename__ = "t0_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    stock_code = Column(String(16), nullable=False)
    base_volume = Column(Integer, nullable=False, default=0)
    target_volume = Column(Integer, nullable=False, default=0)
    coefficient = Column(Float, nullable=False, default=1.0)
    status = Column(Enum("active", "closed", "archived"), nullable=False, default="active")
    note = Column(String(255), nullable=True)
    created_trd_date = Column(String(8), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_t0_tasks_stock_code", "stock_code"),
        Index("ix_t0_tasks_status_created", "status", "created_at"),
        Index("ix_t0_tasks_user_status", "user_id", "status"),
    )
```

### Requirement: 13. `orders.task_id` 列新增（v18 新增）

**业务定位**：委托关联 T0 任务（可空）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `task_id` | Integer | YES | NULL | 关联 `t0_tasks.id`（nullable FK） |

**迁移策略**：
- `ALTER TABLE orders ADD COLUMN task_id INT NULL` 幂等
- `CREATE INDEX IF NOT EXISTS ix_orders_task_id ON orders(task_id)` 幂等
- **不回填**：历史 user_def='T0' 单保持 `task_id = NULL`，继续走 REQ-TRADE-006 聚合路径

**与 user_def 关系**：
- task 下单：`user_def = 'T0'` AND `task_id = <id>`
- 旧 T0 单（无 task）：`user_def = 'T0'` AND `task_id = NULL`
- 普通单（非 T0）：`user_def = ''` AND `task_id = NULL`

#### Scenario: migration 幂等检测列存在

- **WHEN** migration 跑
- **THEN** 先查 `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='orders' AND COLUMN_NAME='task_id'`
- **AND** 已存在则跳过 ALTER；不存在则 ADD
- **AND** SQLite 用 `PRAGMA table_info(orders)` 检测

#### Scenario: task_id NULL 行为

- **WHEN** Order.task_id = NULL
- **THEN** `services/t0/tasks.py::aggregate_task_stats(task_id)` 仍可访问（不报 FK 错）
- **AND** `aggregate_by_stock(..., user_def='T0')` 兼容 NULL（保持现状）