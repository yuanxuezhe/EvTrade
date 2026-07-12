# stocks — 股票基础信息管理 capability spec

> 单一事实源(Single Source of Truth)。本文件改 → 同步到 `server/models/orm.py` + `server/repo/stocks.py`。

## Purpose

EvTrade 当前缺股票基础信息(行业/市值/PE/PB/公司简介)。本 capability 定义:
1. `stocks` 表结构(REQ-STOCK-001)
2. 增量 upsert 语义(REQ-STOCK-002)
3. 同步任务生命周期(REQ-STOCK-003)
4. 同步进度推送协议(REQ-STOCK-004)
5. 东方财富数据源适配契约(REQ-STOCK-005)

数据流:Admin 点击 "开始同步" → 后台爬虫 → 增量 upsert MySQL → WS 推送前端更新缓存。

## REQ-STOCK-001: 股票基础信息表（v23 slim-stocks-table）

**Given** EvTrade 需要股票基础信息  
**When** 设计 stocks 表  
**Then** 必须满足:

- 表名 `stocks`,PK `stock_code VARCHAR(16)`(带 `.SH/.SZ` 后缀)
- 字段定义详见 `data-model/spec.md` §13(v23 6 业务字段 + 2 审计字段)
- 0 个字段索引(v23 移除 ix_stocks_industry / ix_stocks_market,数据量小走全表扫)
- DDL 幂等(`CREATE TABLE IF NOT EXISTS`)
- 历史 14 字段完整数据保留在 `stocks_legacy` 表

**And** ORM `server/models/orm.py:Stock` 必须与 spec 同构

## REQ-STOCK-002: 增量 upsert

**Given** stocks 表存全市场股票基础信息  
**When** 同步任务 upsert 单只股票  
**Then** 必须满足:

- **7 天内不重复更新**:`updated_at > NOW() - 7 DAY` → 跳过(返 `skipped`)
- **7 天外覆盖**:`updated_at <= NOW() - 7 DAY` → UPDATE crawler 入仓字段(返 `updated`)
- **新行插入**:不存在 → INSERT(返 `inserted`)
- 应用层走 `repo.stocks.upsert(db, stock_code, data)` 单一入口
- **v23 重要约束**:crawler 入仓仅写 `stock_name` + `sector`,不会覆盖 `is_t0_able` / `min_buy_qty` / `trade_unit`(admin 专属字段)

**Rationale**:减少不必要的写库,降低东方财富 API 调用频率;admin 手动配置的 3 个交易粒度字段不会被爬虫循环覆盖。

## REQ-STOCK-003: admin 编辑 stocks 字段（v23 字段同步）

**Given** admin 用户需要修改单只股票字段  
**When** 调用 `PATCH /api/stocks/{stock_code}`  
**Then** 必须满足:

- 鉴权:`require_admin` 守卫(role=admin)
- 白名单字段(5 字段):`stock_name` / `sector` / `is_t0_able` / `min_buy_qty` / `trade_unit`
- 任何非白名单字段(如 `industry`)返 422
- 空 body(无字段需要更新)返 400
- `stock_code` 不存在返 404
- 成功返回更新后的完整 stock 对象(6 字段)
- 应用层走 `repo.stocks.update_by_admin(db, stock_code, data)` 单一入口
- 不发 WS push(v22 范围最小化原则)

## REQ-STOCK-004: 同步任务生命周期（v24 全市场范围扩到沪深京 A 股）

**Given** admin 用户触发股票同步  
**When** 调用 `POST /api/sync/stocks`  
**Then** 必须满足:

- 鉴权:`_AUTH_ADMIN` 守卫(role=admin)
- 重复 start → 返 409 conflict(已有任务在跑)
- 启动后立即返 202 Accepted + `{job_id, total: ~5529}`
- **`total ~5529`(沪深京 A 股全市场,v24 sina_list.fetch_all_a_codes 拉取)
- 后台 task 异步执行,不影响 API 响应时间
- 同步期间每 1 秒推 WS `stock_sync_progress` 消息
- 每只股票 upsert 成功后推 WS `stock_synced` 消息(v23 仅 3 字段,见 REQ-STOCK-005)
- `DELETE /api/sync/stocks` 发送停止信号,task 优雅退出(完成当前只后停)
- `GET /api/sync/stocks/status` 返当前 task 状态(state/counters/elapsed)
- 首次同步预计耗时 ~60-90min(NFR-STOCK-001 v21 + 实测 ~0.83s/只)

**Task 单例**:`server.services.sync.manager` 维护 `current_task: SyncTask`,后启动覆盖前一个(警告)。

**数据源 (v24 新增)**:
- 主源: `server.crawler.sources.sina_list.fetch_all_a_codes()` 拉沪深京 A 股全市场
- 端点: 新浪 `vip.stock.finance.sina.com.cn` Market_Center.getHQNodeData?node=hs_a
- 缓存: `data/all_a_codes.json` (TTL 24h),命中 <100ms / 失效 ~19s 重拉
- 备援: `positions.stock_code` 表持仓代码(交易过的小盘股,可能不在 sina 当前列表)
- 代码转换: `sh600519` → `600519.SH`, `bj920169` → `920169.BJ`
- **失败 = 500**(禁止 silent fallback 到 builtin 20 只子集,违反用户硬性偏好 #6)

## REQ-STOCK-005: 同步进度推送协议 + 数据源契约（v23 字段同步）

**Channel**: `/ws/sync_update`(admin only,独立于 `/ws/quote_update`)  
**Auth**: query param `?token=JWT`,要求 `role=admin`(否则 close 4003)

**数据源契约**:

- 端点: `https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={market}{code}`(如 `SZ000001`)
- 字段映射(v23 精简):
  - `SECURITY_NAME_ABBR` → `stock_name`
  - `INDUSTRYCSRC2` → `sector`(申万二级,完整保留如 `银行-国有大型银行`)
  - `SECUCODE` → `stock_code`(由 caller 传入)
- **v23 不再爬**:`INDUSTRYCSRC1` / `TRADE_MARKET` / `ORG_PROFILE` / `REG_CAPITAL` 等 9 字段
- User-Agent:`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
- 单线程 + sleep 0.5s/只(防反爬)
- 单只失败 → 跳过 + 计入 failed 计数 + 日志记录,不影响后续
- 超时:单只 HTTP 请求 10s(防卡死)

**Server → Client 消息**:

```json
// 进度消息(1Hz 节流)
{
  "type": "stock_sync_progress",
  "job_id": "uuid-v4",
  "state": "running",
  "total": 5400,
  "processed": 1234,
  "inserted": 800,
  "updated": 420,
  "skipped": 12,
  "failed": 2,
  "current_code": "000123.SZ",
  "current_name": "平安银行",
  "elapsed_s": 750,
  "eta_s": 2520,
  "ts": 1720611893.123
}

// 单只股票同步完成(v23 仅 3 字段,精简前 6 字段)
{
  "type": "stock_synced",
  "stock_code": "000123.SZ",
  "data": {
    "stock_code": "000123.SZ",
    "stock_name": "平安银行",
    "sector": "银行-国有大型银行"
  },
  "ts": 1720611893.456
}
```

#### Scenario: 前端订阅 sync_update 频道

- **GIVEN** admin 用户已登录,持有 JWT
- **WHEN** 前端建立 WS 连接 `ws://host/ws/sync_update?token={JWT}`
- **THEN** 服务端鉴权通过(role=admin)→ accept
- **AND** 若 role≠admin → close 4003

#### Scenario: 同步期间进度推送

- **GIVEN** 同步任务 running,已处理 1234 只
- **WHEN** 进度回调被触发
- **THEN** 服务端向 `/ws/sync_update` 所有连接广播 `stock_sync_progress` 消息
- **AND** 消息内 counters 字段反映当前真实状态

#### Scenario: v23 stock_synced payload 字段裁剪

- **GIVEN** 同步任务 upsert 单只股票成功
- **WHEN** runner 推 `stock_synced` 消息
- **THEN** `data` 字段仅含 `stock_code` / `stock_name` / `sector`(3 字段)
- **AND** 不含 `industry` / `market` / `intro` 等 v21 字段(已删除)

## Non-Functional Requirements

- **NFR-STOCK-001**:首次 backfill 全市场 ~5400 只耗时 ≤ 60 min
- **NFR-STOCK-002**:WS 推送延迟 ≤ 1s(从 upsert 成功到前端收到)
- **NFR-STOCK-003**:内存 task dict 单例,服务重启不持久化(接受丢失)
- **NFR-STOCK-004**:前端页面 admin role 守卫,viewer/trader 看不到
- **NFR-STOCK-005 (v23)**:单只 HTTP 请求 10s 超时,失败计入 failed 不阻塞后续

## Out of Scope (Future)

- 多数据源(新浪/同花顺/雪球)
- 财务三表(资产负债表/利润表/现金流量表)
- 概念板块 / 题材概念
- 资讯新闻爬取
- cron daily 增量刷新
- ~~行业(industry)/市场(market)/上市日期/估值/简介 等展示性字段~~ (v23 已下线)
