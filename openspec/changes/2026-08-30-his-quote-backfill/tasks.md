# Tasks: his-quote-backfill (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。整体按 P0→P7 顺序推进。

## P0 — change 骨架 + step-0 KB 补全

- [ ] **commit 0 (骨架 + step-0 KB)**
  - 新建 `openspec/changes/2026-08-30-his-quote-backfill/{proposal.md, tasks.md, spec-deltas/}`
  - step-0 KB 缺口（改代码前必补）:
    - `openspec/specs/data-model/spec.md`：登记 `minute_bars` + `quote_sync_config`（现"20 张表"）
    - `知识库/数据库/Schema说明.md` + `知识库/后端服务/数据层/数据表清单.md`：同上
    - `知识库/脚本工具/数据与环境工具.md`：补 `fetch_minute_bars.py`
  - 验收：`grep minute_bars openspec/specs/data-model/spec.md` 命中

## P1 — 表 + ORM

- [ ] **commit 1 — quote_sync_config 表 + 手写 ORM**
  - `server/schema.yml` 加 `quote_sync_config`（pk stock_code, 列 start_date/end_date/last_loaded_date/auto_sync）
  - `uv run python scripts/sync_schema.py diff`（确认只 ADD quote_sync_config）→ `apply`（建表到生产 evtrade）
  - 手写 `server/tables/quote_sync_config.py` + `server/tables/minute_bars.py`（上次 apply 漏生成）
  - `server/tables/__init__.py` 加两行导出
  - 验收：`SELECT * FROM quote_sync_config` 可查；`from server.tables import QuoteSyncConfig, MinuteBars` 不报错

## P2 — broker 模块（server 自包含，按日）+ VWAP 修正

- [ ] **commit 2 — quote_sync broker + VWAP + 单测 + 修正脚本**
  - 新建 `server/services/quote_sync/broker.py`：自包含 his_hq 单日多字段客户端（msgpacket + durable 应答队列 + idle 超时空日跳过），用 `server.config` HIS_HQ_*（不 import strategy_exec）；`_iter_rows` / `_weekdays_in` 纯函数；`fetch_one_day(stock, d, fields)`；VWAP `avg_price = amount/(volume*100)`
  - `scripts/fix_minute_bars_avg_price.py`：一次性 `UPDATE minute_bars SET avg_price=avg_price/100 WHERE avg_price>0`
  - 单测 `server/tests/services/quote_sync/test_broker.py`：fetch_one_day 空日 / VWAP 公式 / _weekdays_in 边界（mock broker reply）
  - 验收：pytest 新测全过；`avg_price` 抽查 close≈avg_price 同量级

## P3 — API（按日同步 + 配置 CRUD + 启动自动增量同步）

- [ ] **commit 3 — quote_sync API + 启动钩子 + 注册**
  - `server/api/quote_sync.py`（require_admin）：GET list / POST add / DELETE / POST /sync {stock_code,date} 按日同步 / PATCH auto_sync|end_date
  - `server/services/quote_sync/manager.py`：per-stock `asyncio.Lock` 守护（启动自动 + 前端手动共用 `sync_one_day`，不重复拉同一只）
  - `server/main.py`：注册 router（_AUTH 块）+ `on_startup_quote_backfill()`（skip pytest，读 quote_sync_config auto_sync=1 行，对 last_loaded_date<昨天 的证券后台 create_task 从游标逐日增量补到追平昨天）+ `on_shutdown` 取消
  - 单测 `server/tests/test_api_quote_sync.py`：list/add/delete/sync 游标推进 / 假日跳过 + `test_startup_backfill.py`：启动补未追平证券 / 已追平不补 / 并发守护
  - 验收：`pytest` 全过；重启后端 → 未追平证券自动增量补到昨天

## P4 — 前端（数据补全区 + 按日循环 + 转圈 + 失败原因）

- [ ] **commit 4 — 前端路由 + 菜单 + api + 页面**
  - `client/src/router/index.js`：`HistoryQuoteCompletion.vue` 懒加载 + 路由 `/data-completion/history-quote`（requiresAdmin）
  - `client/src/components/Sidebar.vue`：admin 块加 `{divider:'数据补全'}` + 历史行情补全项
  - `client/src/api/quote_sync.js`：`quoteSyncApi = { list, add, remove, syncDay }`
  - `client/src/views/HistoryQuoteCompletion.vue`：DataTableView（证券代码/时间区间/已加载日期/自动同步/状态/操作）+ 按日循环（每行 rowState 转圈/失败原因/完成，从 last_loaded+1 到 min(end||昨天,昨天) 逐日）+ onMounted 自动开跑 auto_sync=1 行（串行）
  - 验收：`cd client && npm run build` 不报 import 错；页面可加配置/看转圈/失败原因

## P5 — 数据修正 + 脚本复用

- [ ] **commit 5 — 跑 avg_price 修正 + fetch_minute_bars 复用 broker**
  - 跑 `scripts/fix_minute_bars_avg_price.py` 修正 17.4w 行
  - `scripts/fetch_minute_bars.py` 重构复用 `server/services/quote_sync/broker.py`（删重复协议代码）
  - 验收：修正后 `SELECT COUNT(*) ... WHERE avg_price>close` 抽查同量级；脚本 `--help` 仍可用

## P6 — 知识库同步

- [ ] **commit 6 — docs(知识库)**
  - `知识库/数据库/Schema说明.md` + `数据层/数据表清单.md`：quote_sync_config
  - `知识库/后端服务/数据补全/行情同步补全.md`（新目录，仿 数据同步/同步管理.md 骨架）
  - `知识库/前端/页面/数据补全页面.md` + `前端/路由与权限.md` + `前端/架构概览.md`
  - `知识库/脚本工具/数据与环境工具.md`：两个脚本
  - `知识库/全局规范.md` §5 映射加 数据补全 行 + `目录索引.md` 条目 + 文档数
  - 验收：grep 新表名/页面路径在知识库命中

## P7 — 归档

- [ ] **commit 7 — docs(openspec) 归档**
  - `openspec/specs/` 相关 spec 合并（data-model 新表段 + 新 capability his-quote-backfill spec）
  - `mv openspec/changes/2026-08-30-his-quote-backfill openspec/changes/archive/`
  - `openspec/AGENTS.md`：capability 表 + 归档行
  - 验收：`openspec/changes/` 只剩 archive

## 验证 (v6 完成自查)

- [ ] `uv run python scripts/sync_schema.py diff` 只 ADD quote_sync_config
- [ ] `pytest server/tests/ tests/strategy_exec/ -q` 守住 149+（新增全过）
- [ ] 端到端：页面加 159992.SZ 配置 → 从 last_loaded+1 逐日补到昨天，转圈 + 失败原因 + 昨天封顶
- [ ] `avg_price` 元/股
- [ ] `git diff --stat` 每 commit 单目的
- [ ] 知识库同步（§八）；不自动 push
