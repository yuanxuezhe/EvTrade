# His-Quote Backfill — 历史行情补全（数据补全页面 + 前端驱动按日补全）(2026-08-30)

> 用户拍板 2026-08-30：加"数据补全"前端区 → "历史行情补全"页面，主表 = **行情同步任务表**（证券代码/时间区间/当前已加载到的日期/启用自动同步标志）。**后端接口按日获取**（拉当日 1m → 插入 `minute_bars` → 返回成功/失败），**前端按日期一天天调用**（`last_loaded_date+1` → 昨天，正在执行的行转圈，成功进下一天，失败显示原因）。

## Why

- 已把 `159992.SZ` 最近 3 年（20230830~20260828）分钟 K 线落地 `minute_bars`（174,240 行），但靠手动脚本 `scripts/fetch_minute_bars.py`，无进度记录、无续传、无多标的管理。
- 需要一个可管理的补全机制：往配置表加一行 = 声明"跟踪并自动补全这只证券"；页面展示每只证券补到哪；支持续传（从 `last_loaded_date+1`）与失败原因可见。
- 附带修正：已落地 `avg_price` 存成"元/手"（比"元/股"大 100 倍，A股 volume 单位是手）。VWAP 应为 `amount/(volume*100)`。

## What

### 驱动模型（前端驱动按日，非后端 background task）

- **后端接口按日**：`POST /api/quote-sync/sync {stock_code, date}` → 拉当日 1m K 线（broker his_hq，server 进程自包含客户端）→ upsert `minute_bars` → 成功则 `last_loaded_date = max(现, date)` → 返 `{code:0, msg, bars, last_loaded_date}`；失败返 `{code:非0, msg:原因}`（HTTP 200 + code 区分，前端据 code 显示）。
- **前端一天天调用**：从 `last_loaded_date+1` 到 `min(end_date||昨天, 昨天)`（今天数据不全，封顶昨天）逐日调；正在执行的那一行显示转圈；成功进下一天，失败停止 + 显示原因。
- **启动自动补全**：页面加载时，`auto_sync=1` 且未完成的行自动开始按日循环（串行，避免同时压 broker）。
- **后端启动自动增量同步**：`@app.on_event("startup")` 钩子读 `quote_sync_config` 全部 `auto_sync=1` 行，对 `last_loaded_date < 昨天`（未补完）的证券后台 `asyncio.create_task` 从游标 `last_loaded_date+1` 逐日增量补到追平昨天（不阻塞启动，shutdown 取消）。与前端手动共用同一 `sync_one_day` 核心，per-stock `asyncio.Lock` 守护避免重复拉。

### 表 `quote_sync_config`（主键 stock_code）

| 列 | 类型 | 说明 |
|---|---|---|
| `stock_code` | String(16) | 证券代码（主键） |
| `start_date` | String(8) | 时间区间起点 YYYYMMDD |
| `end_date` | String(8) | 时间区间终点（空串=开放，补到昨天） |
| `last_loaded_date` | String(8) | 当前已加载到的日期（游标）；新增配置时自动 = `MIN(昨天, COALESCE(MAX(minute_bars 该标日期), start_date))` |
| `auto_sync` | Integer(1) | 启用自动同步标志（1/0，默认 1） |

（运行态 spinner/失败原因/当前进行日 → 存前端，不落库。严格只存 4 项 + 主键。）

### 落库

复用 `minute_bars`（已存在，主键 stock_code+stime，`ON DUPLICATE KEY UPDATE` 幂等）。**不新增落库表**，只新增配置表 `quote_sync_config`。

## 不做什么

- 不做 WS 进度推送（进度由后端成功时持久化 `last_loaded_date`，前端读游标 + 手动刷新）。
- 不 import strategy_exec（server 进程自包含 broker 客户端，用 `server.config` 现有 `HIS_HQ_*`）。
- 不做复杂后台调度框架：启动自动补全只是 `on_startup` 里一个 `asyncio.create_task`（仿 `on_startup_auth_sweep`），per-stock 串行、不并发多标的同时拉。
- 不动 broker 端（iquant/quota_his.py 单源真相）。
- 不 drop/rebuild 任何表（只 ADD）。
- 不修 tables-codegen gbk bug（本 change 手动补 ORM，bug 记 followup）。

## 影响面

| 模块 | 影响 |
|---|---|
| `server/schema.yml` | +1 表 `quote_sync_config`（`minute_bars` 已在上个 commit 加） |
| `server/tables/quote_sync_config.py` + `minute_bars.py` + `__init__.py` | 手写 ORM（codegen gbk bug 绕过） |
| `server/services/quote_sync/broker.py` | 自包含 his_hq 单日多字段客户端 + VWAP 修正 |
| `server/api/quote_sync.py` | 配置 CRUD + 按日同步 endpoint（require_admin） |
| `server/main.py` | 注册 router |
| `scripts/fix_minute_bars_avg_price.py` | 一次性 `avg_price/=100` 修正 17.4w 行 |
| `scripts/fetch_minute_bars.py` | 重构复用 `broker.py`（保 CLI backdoor） |
| `client/src/{router,Sidebar,api/quote_sync,views/HistoryQuoteCompletion}` | 数据补全区 + 按日循环 UI |
| 知识库 | data-model/Schema说明/数据表清单/脚本工具 + 新 后端服务/数据补全/ + 前端 3 处 |

## 数据安全 checklist

- [ ] 只 ADD `quote_sync_config` 表，不动现有表
- [ ] `minute_bars` 写入走 upsert（幂等，可重跑）
- [ ] avg_price 修正脚本只改 `avg_price` 列，WHERE 限 `avg_price>0`，可重跑
- [ ] 不删生产数据；测试不碰 minute_bars/quote_sync_config 生产行
- [ ] 目标库 = 生产 `evtrade`（用户拍板）

## 验收 checklist

- [ ] `sync_schema.py diff` 只 ADD `quote_sync_config`
- [ ] `pytest server/tests/ tests/strategy_exec/ -q` 守住 149+（新增 broker/api 单测全过）
- [ ] 页面加 159992.SZ 配置（start=20260824, end 空）→ 从 last_loaded+1 逐日补到昨天，行内转圈，末天完成
- [ ] 某天 broker 失败 → 停 + 显示原因
- [ ] 昨天封顶生效（今天数据不进）
- [ ] `avg_price` 元/股（抽查 close≈avg_price 同量级）
- [ ] 每 commit 单目的；知识库同步；不自动 push
