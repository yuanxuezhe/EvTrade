# stock-info-crawler — Capability Spec

> 本 spec 合并到 `openspec/specs/stocks/spec.md`(archive 时合并)

## REQ-STOCK-001: 股票基础信息表

**Given** EvTrade 需要股票基础信息(行业/市值/PE 等)
**When** 设计 stocks 表
**Then** 必须满足:
- 表名 `stocks`,主键 `stock_code VARCHAR(16)`
- 14 个业务字段:stock_name, industry, sector, market, list_date, total_share, float_share, market_cap, pe_ratio, pb_ratio, intro, created_at, updated_at
- 2 个索引:industry(行业筛选),market(市场筛选)
- `updated_at` 自动 ON UPDATE CURRENT_TIMESTAMP
- DDL 幂等(CREATE TABLE IF NOT EXISTS)

## REQ-STOCK-002: 增量 upsert

**Given** stocks 表存全市场股票基础信息
**When** 同步任务跑完一只股票
**Then** 必须满足:
- 已存在(按 stock_code)→ UPDATE 所有业务字段 + updated_at 自动刷新
- 不存在 → INSERT 新行
- 应用层用 SQLAlchemy `merge()` 或 `INSERT...ON DUPLICATE KEY UPDATE`(MySQL 原生)
- **7 天内不重复更新**(updated_at < NOW() - 7 DAY → skip,除非强制刷新)

## REQ-STOCK-003: 同步任务生命周期

**Given** admin 用户触发股票同步
**When** 调用 `POST /api/sync/stocks`
**Then** 必须满足:
- 鉴权:admin role(走 `_AUTH_ADMIN` 守卫)
- 重复 start → 返 409 conflict(已有任务在跑)
- 启动后立即返 202 Accepted + task_id
- 后台 task 异步执行,不影响 API 响应
- 同步期间每 1 秒推 WS `stock_sync_progress` 消息
- 每只股票 upsert 成功后推 WS `stock_synced` 消息(含完整数据)
- `DELETE /api/sync/stocks` 发送停止信号,task 优雅退出(完成当前只后停)
- `GET /api/sync/stocks/status` 返当前 task 状态(state/counters/elapsed)

## REQ-STOCK-004: 同步进度推送协议(WS /ws/sync_update)

**Channel**: `/ws/sync_update` (admin only,独立于 /ws/quote_update)
**Auth**: query param `?token=JWT`,要求 `role=admin`(否则 close 4003)

**Server → Client 消息**:

```json
// 进度消息(1Hz 节流)
{
  "type": "stock_sync_progress",
  "job_id": "uuid-v4",
  "state": "running",          // running / done / stopped / failed
  "total": 5400,
  "processed": 1234,
  "inserted": 800,
  "updated": 420,
  "skipped": 12,               // 7 天内跳过
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
    "list_date": "1991-04-03",
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

## REQ-STOCK-005: 东方财富数据源适配

**Given** 同步任务从东方财富抓股票信息
**When** crawler 拉取数据
**Then** 必须满足:
- 数据源 URL:
  - 基本信息:`https://push2.eastmoney.com/api/qt/stock/get?secid={market_id}.{code}&fields=...`
  - 公司简介:`https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={code}`
- market_id 映射:SZ=0 / SH=1 / BJ=0(简化处理)
- User-Agent:`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
- sleep 0.5s/只(防反爬)
- 单只失败 → 跳过 + 计入 failed 计数 + 日志记录,不影响后续

## Non-Functional Requirements

- **NFR-STOCK-001**:首次 backfill 全市场 ~5400 只耗时 ≤ 60 min
- **NFR-STOCK-002**:WS 推送延迟 ≤ 1s(从 upsert 成功到前端收到)
- **NFR-STOCK-003**:内存 task dict 单例,服务重启不持久化(接受丢失)
- **NFR-STOCK-004**:前端页面 admin role 守卫,viewer/trader 看不到
## 实施实测结果 (v21 实际跑通)

> 2026-07-10 真实同步结果

| 指标 | 值 |
|---|---|
| 同步任务大小 | 25 只(仓位置 5 + builtin 20) |
| 耗时 | 22.8s(单线程 0.5s/只) |
| inserted | 18 |
| skipped (7 天内) | 5 |
| failed (网络) | 2 |
| DB 累计 | 23 行 |
| API 实测 | `GET /api/stocks` 返 23 条 / `GET /api/sync/stocks/status` 实时 progress |
| REST 鉴权 | admin ✓ / non-admin → 403 |
| WS 鉴权 | admin token → connect OK / 无 token → close 4001 / non-admin → close 4003 |

**数据源修正**: 实际采用 `https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={SZ|SH}{code}`,而非 push2 端点。后者 Python requests 拒连,只有 curl 可达。PageAjax 端点静态字段(公司基础信息)够用,Python reqs 可访问。

**Bug 修复记录**:
- `repo/stocks.upsert`:`data` 含 `stock_code` 时 `Stock(stock_code=..., **data)` 双值冲突 → 剔除 dict 里的 stock_code
- `crawler/eastmoney._format_code`:`'000001.SZ'.split('.', 1)` 切成 `('000001', '.SZ')` 拼回去 → 改用 `rsplit` 切到正确 `SZ000001`
