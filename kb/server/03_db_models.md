# Server · 03 · 数据库与 ORM（DB & Models）

> 文件：`server/db.py` · `server/models/user.py` · `server/models/types.py`

## 1. 数据库连接

### 1.1 引擎配置
- 类型：SQLite（文件 `server/evtrade.db`）
- URL：`sqlite:///{BASE_DIR}/evtrade.db`
- `connect_args={"check_same_thread": False}`（FastAPI 多线程访问需要）
- `echo=False`

### 1.2 Session
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`
- `Base = declarative_base()`

### 1.3 依赖注入 `get_db()`
```python
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
```
用于 FastAPI `Depends(get_db)`。

### 1.4 初始化 `init_db()`
- 导入 `models.user` 让 Base 注册元数据
- 调用 `Base.metadata.create_all(bind=engine)` 建表
- 在 `main.py on_startup` 钩子里调用

### 1.5 默认种子 `admin / admin123`
- `on_startup` 中检查 `count==0` 时插入
- role=admin / full_name=系统管理员 / is_active=true
- 控制台打印提示请修改密码

## 2. ORM 模型 `models/user.py`

### 2.1 表名
`__tablename__ = "users"`

### 2.2 字段
| 字段 | 类型 | 约束 | 默认 |
|------|------|------|------|
| `id` | Integer | PK, index | autoincrement |
| `username` | String(64) | unique, not null, index | — |
| `password_hash` | String(255) | not null | — |
| `email` | String(128) | nullable | None |
| `full_name` | String(64) | nullable | None |
| `role` | String(16) | not null | `"trader"` |
| `is_active` | Boolean | not null | True |
| `created_at` | DateTime | not null | `utcnow` |
| `updated_at` | DateTime | not null, onupdate=utcnow | `utcnow` |
| `last_login_at` | DateTime | nullable | None |

### 2.3 方法 `to_dict()`
- 序列化为可 JSON 化的 dict
- 时间字段 → ISO 格式字符串
- 字段顺序：`id, username, email, full_name, role, is_active, created_at, updated_at, last_login_at`

## 3. 领域 dataclass `models/types.py`

> 这些是**纯 Python dataclass**，不入库，做内存中的领域对象。

### 3.1 `Position`
| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_code` | str | 必填 |
| `stock_name` | str | 默认 `""` |
| `initial_position` | int | 期初持仓 |
| `today_buy` | int | 今日买入 |
| `today_sell` | int | 今日卖出 |
| `available` | property | `initial - today_sell + today_buy` |
| `total` | property | `initial + today_buy - today_sell` |

### 3.2 `Order`
| 字段 | 类型 | 说明 |
|------|------|------|
| `order_id` | str | 必填 |
| `stock_code` | str | — |
| `direction` | str | `BUY` / `SELL` |
| `volume` | int | — |
| `price` | float | — |
| `price_type` | str | 默认 `LIMIT` |
| `status` | str | 默认 `pending` |
| `traded_volume` | int | 默认 0 |
| `traded_price` | float | 默认 0.0 |
| `order_time` | str | 默认 `""` |

### 3.3 `Trade`
| 字段 | 类型 | 说明 |
|------|------|------|
| `trade_id` | str | 必填 |
| `order_id` | str | — |
| `stock_code` | str | — |
| `direction` | str | — |
| `volume` | int | — |
| `price` | float | — |
| `trade_time` | str | 默认 `""` |

### 3.4 `Asset`
| 字段 | 类型 | 默认 |
|------|------|------|
| `cash` | float | 0.0 |
| `frozen_cash` | float | 0.0 |
| `market_value` | float | 0.0 |
| `total_asset` | float | 0.0 |

## 4. 仓储语义（`services/trading.py`）

> 见 `server/04_services.md`

- `positions_store: Dict[str, Position]`：按 `stock_code` 索引
- `orders_store: List[Order]` / `trades_store: List[Trade]`：列表追加
- 这些 store 是**进程级单例**，进程重启会丢失

## 5. 表结构示意（创建后）

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(128),
  full_name VARCHAR(64),
  role VARCHAR(16) NOT NULL DEFAULT 'trader',
  is_active BOOLEAN NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  last_login_at DATETIME
);
CREATE INDEX ix_users_id ON users(id);
CREATE INDEX ix_users_username ON users(username);
```

## 6. 迁移与升级

当前**无 Alembic** 迁移。`create_all` 不会修改已存在表的列。如需新增字段：
1. 修改 `models/user.py`
2. 手动 `ALTER TABLE`，或删除 `evtrade.db` 重建（开发期可接受）

## 7. 与 RPC 协议字段的对应

| ORM 字段 | MsgPacket / RPC 字段 | 说明 |
|----------|---------------------|------|
| `id` | `user_id` | 自增整数 |
| `username` | `username` | 唯一 |
| `password_hash` | — | 内部用，不外发 |
| `email` | `email` | 可选 |
| `full_name` | `full_name` | 可选 |
| `role` | `role` | 字符串 |
| `is_active` | `is_active` | boolean |
| `created_at` | `created_at` | ISO 字符串 |
| `last_login_at` | `last_login_at` | ISO 字符串 |
