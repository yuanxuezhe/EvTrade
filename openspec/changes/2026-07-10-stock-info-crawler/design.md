# Design: stock-info-crawler

## 数据流图

```
                    ┌─────────────────┐
                    │ Admin 浏览器     │
                    │ /admin/sync     │
                    └────────┬────────┘
                             │ (1) POST /api/sync/stocks
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI :8000                                                │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  api/sync.py                                          │    │
│  │  POST /api/sync/stocks → sync_manager.start()         │    │
│  └──────────────────────────────────────────────────────┘    │
│                             │                                 │
│                             ▼                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  services/sync/manager.py                             │    │
│  │  - 单例 task dict (job_id → SyncTask)                 │    │
│  │  - start(): 拒绝重复 + 创建后台 asyncio.Task          │    │
│  │  - stop(): 设 stop_event,task 优雅退出               │    │
│  │  - status(): 返当前 SyncTask 状态                     │    │
│  └──────────────────────────────────────────────────────┘    │
│                             │                                 │
│                             ▼                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  services/sync/task.py                                │    │
│  │  SyncTask.run():                                      │    │
│  │    while not stop_event:                              │    │
│  │      code = next(all_codes)                           │    │
│  │      data = eastmoney.fetch(code)                     │    │
│  │      if data:                                         │    │
│  │        repo.upsert(stocks, data)                      │    │
│  │        ws.broadcast("sync_update", stock_synced)      │    │
│  │      progress = {processed, inserted, ...}            │    │
│  │      ws.broadcast("sync_update", stock_sync_progress) │    │
│  │      sleep 0.5s                                       │    │
│  └──────────────────────────────────────────────────────┘    │
│                             │                                 │
│                             ▼                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  crawler/sources/eastmoney.py                         │    │
│  │  - fetch_base_info(code) → dict                       │    │
│  │  - fetch_intro(code) → str                            │    │
│  │  - User-Agent + 随机 UA                               │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────┬───────────────────────────────┘
                               │ (2) WS /ws/sync_update
                               ▼
                    ┌─────────────────┐
                    │ Admin 浏览器     │
                    │ 进度条 + 表格    │
                    └─────────────────┘
```

## 表结构

```sql
CREATE TABLE stocks (
    stock_code VARCHAR(16) PRIMARY KEY,
    stock_name VARCHAR(64) NOT NULL,
    industry VARCHAR(64),
    sector VARCHAR(64),
    market VARCHAR(8),
    list_date DATE,
    total_share BIGINT,
    float_share BIGINT,
    market_cap DECIMAL(18,2),
    pe_ratio DECIMAL(10,4),
    pb_ratio DECIMAL(10,4),
    intro TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_industry (industry),
    INDEX idx_market (market)
);
```

## WS 频道架构

```
                    ┌──────────────────────────────┐
                    │  ws_manager active_connections│
                    ├──────────────────────────────┤
                    │  order_update: set()          │
                    │  trade_update: set()          │
                    │  quote_update: set()          │
                    │  strategy_update: set()       │
                    │  sync_update: set()           │  ← NEW
                    └──────────────────────────────┘
```

- `/ws/{channel}` endpoint 接受任意 channel 名,加白名单:`order_update | trade_update | quote_update | strategy_update | sync_update`
- sync_update 频道鉴权加严:`role=admin` 否则 close 4003

## 增量 upsert 策略

```python
# repo/stocks.py
def upsert(db: Session, stock_code: str, data: dict) -> str:
    """返 'inserted' | 'updated' | 'skipped'"""
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing:
        if existing.updated_at and existing.updated_at > (datetime.utcnow() - timedelta(days=7)):
            return 'skipped'  # 7 天内不重复更新
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        return 'updated'
    else:
        stock = Stock(stock_code=stock_code, **data)
        db.add(stock)
        db.commit()
        return 'inserted'
```

## 前端集成

```
client/src/views/Sync.vue:
  onMounted → connect WS /ws/sync_update
  onBeforeUnmount → disconnect
  监听 store.sync:
    - state (idle / running / done / stopped / failed)
    - counters (processed / total / inserted / updated / skipped / failed)
    - current_code / current_name
    - elapsed_s / eta_s
  监听 store.stocks:
    - 缓存股票信息 Map<stock_code, StockData>
    - WS 收到 stock_synced → 立即更新缓存
```

## 目录结构

```
server/
├── api/
│   ├── stocks.py                 # NEW
│   └── sync.py                   # NEW
├── crawler/                       # NEW directory
│   ├── __init__.py
│   ├── sources/
│   │   └── eastmoney.py          # NEW
│   └── runner.py                 # NEW
├── migrations/
│   └── 2026-07-10-create-stocks-table.py  # NEW
├── models/
│   └── orm.py                    # + Stock class
├── repo/
│   └── stocks.py                 # NEW
├── services/
│   └── sync/                     # NEW directory
│       ├── __init__.py
│       ├── manager.py            # NEW
│       └── task.py               # NEW
├── ws/
│   └── endpoint.py               # + sync_update 频道处理
└── main.py                       # + 2 router

client/src/
├── api/
│   ├── stocks.js                 # NEW (或 inline 在 Sync.vue)
│   └── sync.js                   # NEW
├── stores/
│   ├── stocks.js                 # NEW (Pinia cache)
│   └── sync.js                   # NEW (Pinia sync state)
├── views/
│   └── Sync.vue                  # NEW
└── router/
    └── index.js                  # + /admin/sync 路由

tests/
├── test_crawler_eastmoney.py     # NEW
└── test_sync_manager.py          # NEW

openspec/
├── changes/2026-07-10-stock-info-crawler/
│   ├── proposal.md
│   ├── tasks.md
│   ├── spec.md
│   └── design.md
└── specs/
    ├── data-model/spec.md         # + §12 stocks
    └── stocks/spec.md             # NEW
```

## 风险与权衡

| 决策 | 选择 | 权衡 |
|---|---|---|
| 数据源 | 东方财富单源 | 简单 vs 多源冗余 |
| 同步范围 | 全市场 backfill | 数据全 vs 慢(45min) |
| 进度持久化 | 内存 task dict | 简单 vs 重启丢失 |
| 鉴权位置 | REST `_AUTH_ADMIN` + WS `role=admin` 双重 | 安全 vs 实现复杂度 |
| WS 频道 | 新建 `/ws/sync_update` | 解耦 vs 多 ws 连接 |
| 速率策略 | 单线程 sleep 0.5s | 稳 vs 慢 |
## 实施实测补充 (v21)

- **真实数据源**: 实际只走 `emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax`,push2 端点未用(Python 拒连)
- **PageAjax 返回字段**: `jbzl[].SECUCODE/SECURITY_NAME_ABBR/INDUSTRYCSRC1/INDUSTRYCSRC2/TRADE_MARKET/ORG_PROFILE/REG_CAPITAL`
- **行业处理**: `INDUSTRYCSRC1` 形如 "金融业-货币金融服务",split('-')[0] 取一级作为 industry
- **公司简介清洗**: `<[^>]+>` 去标签 + `\s+` 折叠空白
- **实测同步 25 只**: 22.8s 完成,18 inserted + 5 skipped(7天阈值触发) + 2 failed(网络瞬断)
- **REST 鉴权**: 复用 `server.auth.deps.require_admin`
- **WS 鉴权**: `/ws/sync_update` 频道在 endpoint.py 单独查 users.role
