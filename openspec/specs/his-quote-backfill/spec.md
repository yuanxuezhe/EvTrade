# his-quote-backfill — 历史行情补全

> 能力：数据补全区 → 历史行情补全。管理"要跟踪并自动补全的证券"配置（`quote_sync_config`），从 broker his_hq 拉 1m K 线落地 `minute_bars`，前端驱动按日补全 + 后端启动自动增量补平。

## Context

- `159992.SZ` 等标的的分钟 K 线需从 broker 历史落地到 `minute_bars`（回测/分析数据源）
- 需要可管理、可续传、失败可见的补全机制：加一行配置 = 声明跟踪该证券；启动/开页面自动增量补平；从"已加载到的最后一天"一天一天往前拉
- **当前同步到的日期** 必须按 `minute_bars` 实际数据统计（`MAX(stime 日期)`），不是盲目 +1
- **统一入口 (change 2026-09-03 unify-his-hq-broker-client)**: 所有历史行情拉取/解析/VWAP 计算
  走 `strategy_exec.market_data.his_hq_client` 公共 client (server 端 + scripts + strategy_exec 三处共用).
  server 的 `services/quote_sync/broker.py` 改为薄壳 (继承公共 client + 注入 server settings).

## 驱动模型

- **后端按日接口**：`POST /api/quote-sync/sync {stock_code, date}` → 调公共 client 拉当日 1m (7 字段: stime/open/high/low/close/volume/amount) → upsert `minute_bars` → 写操作记录（成功/失败）
- **前端一天天调用**：从 `last_loaded_date+1` 到 `min(end_date||昨天, 昨天)` 逐日调；成功进下一天，失败停止
- **启动自动补全**：`on_startup` 读 `auto_sync=1` 且未追平的证券，后台从游标逐日增量补平（不阻塞启动）
- **昨天封顶**：今天 1m 数据不全不进
- **CLI 补全（`scripts/fetch_minute_bars.py`）**：按日 chunk 调公共 client, 默认 10 天/段

## Requirements

### REQ-QSB-001: 后端按日同步接口

`POST /api/quote-sync/sync` body `{stock_code, date}`（require_admin）：
- 调 `HisHqClient.fetch_bars(stock, day, day, fields=DEFAULT_FIELDS)` (period 写死 1m)
- DEFAULT_FIELDS = `[open, high, low, close, volume, amount]` (broker 端 col_header 自动加 stime)
- upsert `minute_bars`（`ON DUPLICATE KEY UPDATE` 幂等）
- 成功（含假日 0 根）→ `record_success`：重算 `last_loaded_date`（= minute_bars 实际最大日期）+ status=success + 清 error_msg
- 失败（broker 连不上/异常）→ `record_failure`（status=failed + error_msg，游标不动）+ re-raise
- 返回：成功 `{code:0, bars, last_loaded_date}` / 失败 `{code:1, msg:原因}`

#### Scenario: 交易日
- **WHEN** sync {159992.SZ, 20260828}（周五）
- **THEN** broker 返 240 根 → upsert → last_loaded_date=20260828, status=success

#### Scenario: 周末（走 broker, END marker / idle 超时秒返）
- **WHEN** sync {159992.SZ, 20260829}（周六）
- **THEN** 仍调 broker (方案 B: 不本地提前跳过) → broker 循环结束发 `#END_OF_HIS_HQ#` 或 idle 超时 → 客户端返 [] → record_success（bars=0，~0.9s）

#### Scenario: 假日（落工作日，broker 结束标记）
- **WHEN** sync {159992.SZ, 20260901}（中秋周二）
- **THEN** 拉 broker → broker 循环结束发 `#END_OF_HIS_HQ#` → 客户端秒回 0 根 → record_success（bars=0，~0.9s）

#### Scenario: broker 连不上
- **WHEN** sync 但 broker 不可达
- **THEN** BrokerError 上抛 → record_failure（status=failed + 原因）→ 返 code:1 + msg，游标不动

#### Scenario: broker 返 OHLCV 字段不全（xtquant 实盘只返 close）
- **WHEN** broker 返 0 占位的 open/high/low/volume/amount (xtquant 实盘只返 close)
- **THEN** `to_record()` 兜底: open/high/low = close (单 1m bar 内 H=L=O=C); volume=0 → avg_price=0.0
- **WHY** xtquant 实盘 1m close 是唯一真实数据 (2026-08-30 实测确认)

### REQ-QSB-002: 配置表 CRUD

- `GET /api/quote-sync` → 列配置（任务表）
- `POST /api/quote-sync` {stock_code,start_date,end_date,auto_sync} → 加配置；`last_loaded_date` 按已有 minute_bars 数据初始化（有数据=最大日期，无数据=start_date 前一天使 next 不漏首日）
- `DELETE /api/quote-sync/{stock_code}` → 删配置（不删 minute_bars 数据）
- `PATCH /api/quote-sync/{stock_code}` {auto_sync?|end_date?} → 改开关/终点

### REQ-QSB-003: 均价口径 VWAP

`avg_price = amount/(volume*100)`（元/股）。A股/ETF volume 单位是手（1 手=100 股），直接 amount/volume 是"元/手"，必须 /100。volume=0 → 0.0。

### REQ-QSB-004: 前端按日循环（数据补全区 → 历史行情补全页）

路由 `/data-completion/history-quote`（requiresAdmin）；Sidebar "数据补全" 分隔 + 菜单项。

- 主表 `DataTableView`：证券代码 / 时间区间 / 当前已加载到的日期 / 自动同步 / 状态（成功·失败·同步中·未开始）/ 操作（补全·删除）
- 新增任务弹窗：证券代码 + 开始日期 + 结束日期（默认昨天）+ 自动同步开关
- 按日循环（串行队列，同一时刻只补一只）：从 `last_loaded_date+1` 逐日调 `/sync`，成功进下一天，失败停止
- 状态列：纯 tag（成功/失败/同步中/未开始），无转圈动画、无失败原因展示（2026-08-30 用户要求简化）

### REQ-QSB-005: 昨天封顶

补全末天一律 ≤ 昨天（今天 1m 数据不全不进）。

### REQ-QSB-006: 启动自动增量同步

`@app.on_event("startup") on_startup_quote_backfill()`（skip `PYTEST_CURRENT_TEST`）：
- 读 `quote_sync_config` auto_sync=1 且 `last_loaded_date < 昨天` 的证券
- 后台 `asyncio.create_task` 从 `last_loaded_date+1` 逐日补平（per-stock `asyncio.Lock` 守护，与前端手动共用 `sync_one_day`，不重复拉同一只）
- 不阻塞启动；`on_shutdown` 取消未完成任务

### REQ-QSB-007: broker 结束标记（change B）

- broker `iquant/quota_his.py` 每天循环结束后 put `#END_OF_HIS_HQ#` 到应答队列
- 客户端 `quote_sync/broker.py` 收到即 break → 无数据日秒回（实测 ~0.9s）；旧 broker 无标记回退到 idle 超时（兼容）
- 标记常量 `END_OF_HIS_HQ_MARKER` 两端一致
- strategy_exec 共享 broker：其 `_iter_rows` 对标记 = 0 行，行为零变化（不计数/不早停）

## Cross References

- 数据表 schema：`data-model/spec.md` REQ `minute_bars` / `quote_sync_config`
- 知识库：`后端服务/数据补全/行情同步补全.md`、`前端/页面/数据补全页面.md`
- broker 端：`iquant/quota_his.py`（结束标记，需 QMT 机器重启 broker 生效）
- 均价修正：`scripts/fix_minute_bars_avg_price.py`（一次性 元/手→元/股）
