# 2026-07-12-full-a-share-sync — 同步范围扩到沪深京 A 股全市场 (~5560 只)

## Why

v21 stock-info-crawler 起步时,为避免初次就爬全 5400+ 只耗时,sync 入口 `_get_all_stock_codes` 仅返回:
- 从 `positions` 表读已持仓代码(实际 0 只)
- 内置 `builtin` 硬编码 20 只大盘股
- 总计 ~20 只

后果:
- `/admin/sync` 触发后只同步 ~20 只(不是用户期望的全市场)
- `stocks` 表长期停留在 23 行(builtin 20 + positions 3 演示数据)
- 前端 `/admin/stock-config` 只能看到 ~20 只能展示+编辑的股票,**其他 ~5540 只完全没入库**,admin 无法编辑任何一只非大盘股的元数据(sector/is_t0_able/min_buy_qty/trade_unit)

## What Changes

1. **新增数据源** `crawler/sources/sina_list.py`:
   - 端点: `https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?node=hs_a&page={P}&num=100&sort=symbol&asc=1`
   - 返回沪深京 A 股全市场 ~5560 只(分页 100/页 × ~56 页)
   - 单次拉取 ~17s(56 次 HTTP,每次 ~0.3s)
   - **代码格式转换**: `bj920169` → `920169.BJ`, `sh600519` → `600519.SH`, `sz000001` → `000001.SZ`
2. **改 `_get_all_stock_codes`**:
   - **优先**用 `sina_list.fetch_all_a_codes()` 拉全市场
   - **合并** `positions` 表代码(交易过的小盘股可能不在线,需要保留)
   - **缓存**: 全市场列表存 `data/all_a_codes.json`(TTL 24h),后续 sync 命中缓存(避免每次重启都拉 17s)
3. **缓存策略**:
   - 首次启动 / 缓存过期 / 缓存文件不存在 → 重新拉
   - 缓存命中 → 直接读 JSON 跳过 HTTP
   - 缓存损坏 / JSON parse 失败 → 重新拉(不静默回退到 builtin)
4. **`POST /api/sync/stocks` 语义**:
   - 现有契约不变(无需 body)
   - 行为变化: 从"~20 只"扩到"~5560 只"
   - 同步耗时从 ~10s 涨到 ~60min(NFR-STOCK-001)
5. **前端 `/admin/stock-config` 行为**:
   - 表格在首次访问时只显示已入仓的股票
   - 启动一次 `/admin/sync` 同步后,刷新页面会看到 ~5560 只全市场股票
   - 搜索框按代码/名称模糊匹配,板块筛选按 sector 分组

## 候选 + 决策

**Q1 数据源** → 已定: **新浪 vip 接口** (D 决策,实测 56 页返回 ~5560 只,含北交所 920xxx)
- 东方财富 push2 404 (2026-07-12 实测)
- 东方财富 datacenter RPT_* 报表 9501 "报表配置不存在"
- 网易 quotes.money.163.com 502 Bad Gateway
- TX qt.gtimg.cn 是单只行情接口,无列表 API

**Q2 拉取时机** → 已定: **每次 sync 启动时实时拉,带 24h 缓存**
- 单次 17s,首次启动慢一次可接受
- 缓存命中跳过 HTTP,后续 sync 启动 0ms
- 不在服务启动时拉(避免服务启动慢)

**Q3 端点** → 已定: **复用现有 `POST /api/sync/stocks`**
- 不增端点(范围蔓延禁止)
- 行为从"小范围同步"变"全市场同步",契约不变

**Q4 旧数据处理** → 已定: **增量合并,不删**
- builtin 20 只 → 会被 sina 列表覆盖(都是大盘股,sina 必有)
- positions 表 → 继续作为补充(交易过的小盘股兜底)
- 旧的 23 行保留,新 5537 只首次入仓

## Impact

- **Affected specs**: `data-model/spec.md` §13 stocks 表语义不变;`stocks/spec.md` REQ-STOCK-004 同步任务范围扩到全市场
- **Affected code**: `api/sync.py` (1 file), 新增 `crawler/sources/sina_list.py` (1 file), `runner.py` 不动(已支持任意 code list)
- **Affected frontend**: `views/AdminStockConfig.vue` 不动(store 自动加载全表)
- **首次 sync 耗时**: ~60min(NFR-STOCK-001 v21 已写,无变化)
- **DB 增长**: 23 行 → ~5560 行,stocks 表索引 0 个,扫表代价可忽略

## Out of Scope

- 不实现增量 cron 刷新(每次手动 `/admin/sync` 触发)
- 不实现多数据源容错(只用 sina 一个,挂了即 500)
- 不缓存单只股票的基础信息(每次 sync 还是按代码逐只爬 emweb)
- 不实现 sector 自动分类(申万二级只有 emweb 详情页才返回,已有 REQ-STOCK-005 流程)
- 不修改 quotes/positions/orders 等其他表的 sync 行为

## Risk

| Risk | Severity | Mitigation |
|---|---|---|
| 新浪接口变更 / 限流 | M | 缓存 24h + 失败返 500 不静默 fallback |
| sync 跑到一半服务挂 | L | runner 单任务单例 + state 持久化在 WS push (NFR-STOCK-003) |
| DB 写并发 | L | 5400 只串行 upsert(0.5s/只 = ~45min),无并发压力 |
| 前端表格 5560 行渲染卡 | L | `limit=100` 默认 + 搜索框 + 板块筛选,不全量展示 |
| admin 误触同步 | L | PATCH 已有 `_AUTH_ADMIN` 守卫,DELETE 可停止 |

## Validation

- [x] 新浪接口实测: page=1~56 返回有效 JSON, page=57+ 返回空数组 → 真实全市场 ~5560 只
- [ ] 新建 `crawler/sources/sina_list.py` 跑 `python3 -m server.crawler.sources.sina_list` 验证
- [ ] `_get_all_stock_codes` 在 sync 启动时返 ~5560 只
- [ ] 缓存文件 `data/all_a_codes.json` 写入并 24h 内复用
- [ ] 跑一次 `/api/sync/stocks` 看 stocks 表从 23 → ~5560 行
- [ ] 前端 `/admin/stock-config` 刷新看到全市场股票
- [ ] git log -1 看 commit 真实落地, push 后 GitHub origin 双 hash 一致