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

## REQ-STOCK-001: 股票基础信息表

**Given** EvTrade 需要股票基础信息  
**When** 设计 stocks 表  
**Then** 必须满足:

- 表名 `stocks`,PK `stock_code VARCHAR(16)`(带 `.SH/.SZ` 后缀)
- 字段定义详见 `data-model/spec.md` §13
- 2 个索引:ix_stocks_industry / ix_stocks_market
- DDL 幂等(`CREATE TABLE IF NOT EXISTS`)

**And** ORM `server/models/orm.py:Stock` 必须与 spec 同构

## REQ-STOCK-002: 增量 upsert

**Given** stocks 表存全市场股票基础信息  
**When** 同步任务 upsert 单只股票  
**Then** 必须满足:

- **7 天内不重复更新**:`updated_at > NOW() - 7 DAY` → 跳过(返 `skipped`)
- **7 天外覆盖**:`updated_at <= NOW() - 7 DAY` → UPDATE 所有业务字段(返 `updated`)
- **新行插入**:不存在 → INSERT(返 `inserted`)
- 应用层走 `repo.stocks.upsert(db, stock_code, data)` 单一入口

**Rationale**:减少不必要的写库,降低东方财富 API 调用频率。

## REQ-STOCK-003: 同步任务生命周期

**Given** admin 用户触发股票同步  
**When** 调用 `POST /api/sync/stocks`  
**Then** 必须满足:

- 鉴权:`_AUTH_ADMIN` 守卫(role=admin)
- 重复 start → 返 409 conflict(已有任务在跑)
- 启动后立即返 202 Accepted + `{job_id}`
- 后台 task 异步执行,不影响 API 响应时间
- 同步期间每 1 秒推 WS `stock_sync_progress` 消息
- 每只股票 upsert 成功后推 WS `stock_synced` 消息(含完整数据)
- `DELETE /api/sync/stocks` 发送停止信号,task 优雅退出(完成当前只后停)
- `GET /api/sync/stocks/status` 返当前 task 状态(state/counters/elapsed)

**Task 单例**:`server.services.sync.manager` 维护 `current_task: SyncTask`,后启动覆盖前一个(警告)。

## REQ-STOCK-004: 同步进度推送协议(WS /ws/sync_update)

**Channel**: `/ws/sync_update`(admin only,独立于 `/ws/quote_update`)  
**Auth**: query param `?token=JWT`,要求 `role=admin`(否则 close 4003)

**Server → Client 消息**:

```json
// 进度消息(1Hz 节流)
{
  "type": "stock_sync_progress",
  "job_id": "uuid-v4",
  "state": "running",          // running | done | stopped | failed
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

// 单只股票同步完成(upsert 成功后立即推)
{
  "type": "stock_synced",
  "stock_code": "000123.SZ",
  "data": {
    "stock_name": "平安银行",
    "industry": "银行",
    "sector": "金融",
    "market": "SZ",
    "list_date": "1991-04-03T00:00:00",
    "total_share": 19405918198,
    "float_share": 19405751065,
    "market_cap": 102345678901.0,
    "pe_ratio": 5.23,
    "pb_ratio": 0.56,
    "intro": "平安银行股份有限公司..."
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

## REQ-STOCK-005: 东方财富数据源适配

**Given** 同步任务从东方财富抓股票信息  
**When** crawler 拉取数据  
**Then** 必须满足:

- 数据源 URL:
  - 基本信息:`https://push2.eastmoney.com/api/qt/stock/get?secid={market_id}.{code}&fields=...`
  - 公司简介:`https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={code}`
- market_id 映射:SZ=0 / SH=1(简化处理,BJ 暂不支持)
- User-Agent:`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
- 单线程 + sleep 0.5s/只(防反爬)
- 单只失败 → 跳过 + 计入 failed 计数 + 日志记录,不影响后续
- 超时:单只 HTTP 请求 10s(防卡死)

**Adapter 入口**:`server/crawler/sources/eastmoney.py::fetch_base_info(stock_code) -> dict`

## Non-Functional Requirements

- **NFR-STOCK-001**:首次 backfill 全市场 ~5400 只耗时 ≤ 60 min
- **NFR-STOCK-002**:WS 推送延迟 ≤ 1s(从 upsert 成功到前端收到)
- **NFR-STOCK-003**:内存 task dict 单例,服务重启不持久化(接受丢失)
- **NFR-STOCK-004**:前端页面 admin role 守卫,viewer/trader 看不到

## Out of Scope (Future)

- 多数据源(新浪/同花顺/雪球)
- 财务三表(资产负债表/利润表/现金流量表)
- 概念板块 / 题材概念
- 资讯新闻爬取
- cron daily 增量刷新