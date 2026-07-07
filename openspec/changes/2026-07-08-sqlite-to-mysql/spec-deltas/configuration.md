## ADDED Requirements

### REQ-CFG-009: 数据库连接 (`EVTRADE_DB_URL`)

| Key | 默认 | 说明 |
|---|---|---|
| `EVTRADE_DB_URL` | `mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4` | SQLAlchemy URL；driver= pymysql；参数符号编码（`@` → `%40`） |
| `EVTRADE_DB_POOL_SIZE` | `5` | 连接池大小 |
| `EVTRADE_DB_MAX_OVERFLOW` | `10` | 高峰额外溢出连接数 |
| `EVTRADE_DB_POOL_RECYCLE` | `1800` | 连接回收秒数（避免 MySQL wait_timeout） |
| `EVTRADE_DB_POOL_PRE_PING` | `true` | 用前 ping，防 stale connection |

#### Scenario: 默认配置本地起动

- **GIVEN** 开发者新拉代码 + MySQL 容器已 ready
- **WHEN** 启动 backend
- **THEN** MUST 连 `mysql+pymysql://EvTrade:...@127.0.0.1:33066/evtrade?charset=utf8mb4`
- **THEN** 连接池 `pool_size=5` `max_overflow=10` `pool_recycle=1800` `pool_pre_ping=True`

#### Scenario: fallback 到 SQLite（开发分支）

- **GIVEN** `EVTRADE_DB_URL=sqlite:///./evtrade.db` 显式写入 .env
- **WHEN** 启动
- **THEN** MUST 回退 SQLite（保留开发体验零依赖）

### REQ-CFG-010: 数据库用户与角色

- MySQL **root** 用户 `p@ssw0rd`：仅容器内用，**不**外部暴露
- MySQL **EvTrade** 用户 `p@ssw0rd`：业务库 `evtrade` 的 **DML only**（SELECT/INSERT/UPDATE/DELETE）；无 DDL（不给 CREATE/DROP/ALTER）
- `0.0.0.0:33066` 端口映射（外部用 MySQL 客户端连时），仅在容器内 `bind-address=127.0.0.1` 时不开（docker-compose 必须 bind 127.0.0.1）

#### Scenario: EvTrade 用户没 DDL 权限

- **GIVEN** EvTrade 用户登录
- **WHEN** 执行 `CREATE INDEX ix_X ON y`
- **THEN** MUST 失败 (`1142 CREATE command denied`)

#### Scenario: MySQL bind 仅 127.0.0.1

- **GIVEN** docker-compose 起 mysql
- **WHEN** 从外部公网 `14.153.197.79:33066` nc 测试
- **THEN** MUST 拒绝连接（拒绝原因：端口映射仅暴露到 docker host）
