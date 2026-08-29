# his-quote-backfill — Spec Delta (2026-08-30)

## 修改类型
ADDED — 新 capability：历史行情补全（数据补全页面 + 前端驱动按日补全）

## 变更内容

### REQ-QSB-001: 后端按日同步接口

`POST /api/quote-sync/sync` body `{stock_code, date}`（`require_admin`）：

- 拉 `date` 当日 1m K 线（broker his_hq，server 进程自包含客户端，用 `server.config` `HIS_HQ_*`，**不 import strategy_exec**）
- upsert 进 `minute_bars`（`ON DUPLICATE KEY UPDATE` 幂等）
- 成功 → `quote_sync_config.last_loaded_date = max(现, date)`，返 `{code:0, msg, bars, last_loaded_date}`
- 失败 → 返 `{code:非0, msg:失败原因}`（HTTP 200 + code 区分；前端据 code 显示原因）
- 周末/假日（broker 返 0 行）→ 视为**成功空**（`code:0, bars:0`），游标照常推进（不停在假日）

#### Scenario: 交易日同步
- **WHEN** sync {159992.SZ, 20260825}（交易日）
- **THEN** broker 返 240 根 1m → upsert minute_bars → last_loaded_date=20260825 → code:0

#### Scenario: 假日同步
- **WHEN** sync {159992.SZ, 20261001}（国庆假日）
- **THEN** broker 返 0 行 → code:0, bars:0 → last_loaded_date 推进到 20261001（跳过，不算失败）

#### Scenario: broker 失败
- **WHEN** sync {159992.SZ, 20260825} 但 broker 超时/异常
- **THEN** code:非0, msg:"his_hq reply timeout ..." → last_loaded_date 不变

### REQ-QSB-002: 配置表 CRUD

- `GET /api/quote-sync` → `{code:0, msg, list:[{stock_code,start_date,end_date,last_loaded_date,auto_sync}]}`
- `POST /api/quote-sync` body {stock_code,start_date,end_date,auto_sync} → 加配置行；last_loaded_date 自动 = `MIN(昨天, COALESCE(MAX(minute_bars 该标日期), start_date))`
- `DELETE /api/quote-sync/{stock_code}` → 删配置（不删 minute_bars 数据）
- `PATCH /api/quote-sync/{stock_code}` body {auto_sync?|end_date?} → 改开关/终点

### REQ-QSB-003: 均价口径 VWAP

`avg_price = amount/(volume*100)`（元/股）。A股/ETF volume 单位是**手**（1 手=100 股），amount 单位元 → 直接 amount/volume 是"元/手"，必须 /100 才是"元/股"。volume=0 → 0.0。

### REQ-QSB-004: 前端按日循环（数据补全区 → 历史行情补全页）

路由 `/data-completion/history-quote`（`requiresAdmin`）；Sidebar admin 块 "数据补全" 分隔 + 菜单项。

页面主表 `DataTableView`（列：证券代码/时间区间/当前已加载到的日期/自动同步/状态/操作），**前端驱动按日循环**：

- 每行独立运行态 `{day, running, failReason, done}`（存前端，不落库）
- 补全区间：`last_loaded_date+1` → `min(end_date||昨天, 昨天)`（今天数据不全，封顶昨天）
- 逐日调 `syncDay(stock, date)`：期间该行显示**转圈动画**；成功 → last_loaded 前进进下一天；失败 → 停止 + 该行显示失败原因
- **启动自动补全**：`onMounted` 后对 `auto_sync=1` 且未完成的行自动开跑（**串行**，避免同时压 broker）
- 达到末天 → 该行"已同步到 X"

### REQ-QSB-005: 昨天封顶

补全末天一律 ≤ 昨天（当前日期 - 1 天）。今天的 1m 数据交易未结束、不完整，不进 minute_bars。

### REQ-QSB-006: 启动自动增量同步

`@app.on_event("startup") on_startup_quote_backfill()`（skip `PYTEST_CURRENT_TEST`，仿 `on_startup_auth_sweep`）：

- 启动时读 `quote_sync_config` 全部 `auto_sync=1` 的行
- 对每只 `last_loaded_date < 昨天`（未补完）的证券，后台 `asyncio.create_task` **增量补全**：从 `last_loaded_date+1` 逐日调 `sync_one_day`，每成功一天持久化游标，直到追平昨天
- **增量**：从游标续跑，已补过的天不重复拉（upsert 幂等兜底）
- **并发守护**：per-stock `asyncio.Lock`（`manager` 内），启动自动补全 与 前端手动 syncDay 不会同时补同一只证券（避免重复压 broker）；同一只串行
- **不阻塞启动**：后台任务跑，启动钩子立即返回；`on_shutdown` 取消未完成任务
- 前端交互（REQ-QSB-004）与启动自动（本条）共用同一 `sync_one_day` 核心

#### Scenario: 启动续传
- **WHEN** 应用启动，`quote_sync_config` 有 159992.SZ last_loaded_date=20260824（昨天=20260829）
- **THEN** 后台自动从 20260825 逐日补到 20260829，游标逐日推进
- **AND** 重启再启 → 从新的 last_loaded_date 续跑（已追平则不动）

#### Scenario: 已追平不补
- **WHEN** 启动，某证券 last_loaded_date == 昨天
- **THEN** 不触发补全

#### Scenario: 与手动并发守护
- **WHEN** 启动自动正在补 159992.SZ，前端又对该证券点"补全"
- **THEN** per-stock lock 串行化，不重复拉同一天（幂等兜底）

## 影响面

| 模块 | 影响 |
|---|---|
| `server/services/quote_sync/broker.py` | 自包含 his_hq 单日多字段客户端 + VWAP |
| `server/api/quote_sync.py` | 配置 CRUD + 按日同步（require_admin） |
| `server/main.py` | 注册 router |
| `client/src/{router,Sidebar,api/quote_sync,views/HistoryQuoteCompletion}` | 数据补全区 UI |
| `scripts/fix_minute_bars_avg_price.py` | 一次性 avg_price 修正 |
| `scripts/fetch_minute_bars.py` | 重构复用 broker.py |

## 不修改
- broker 端（iquant/quota_his.py）
- strategy_exec（不 import，server 自包含）
- 现有 20 张表
- minute_bars 表结构（已存在）

## 测试覆盖
- `server/tests/services/quote_sync/test_broker.py`：fetch_one_day 空日 / VWAP / _weekdays_in
- `server/tests/test_api_quote_sync.py`：list/add/delete/sync 游标推进 / 假日跳过
