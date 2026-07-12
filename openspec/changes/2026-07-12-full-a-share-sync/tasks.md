# Tasks — full-a-share-sync

## Commit 拆分（按层 v6 纪律）

| # | 范围 | 触动文件 | 验证 |
|---|---|---|---|
| 1 | OpenSpec 4 件套 | `openspec/changes/2026-07-12-full-a-share-sync/{proposal,tasks,spec-deltas/*}.md` | `git log -1 --stat` |
| 2 | 新数据源 `sina_list.py` | `server/crawler/sources/sina_list.py` (新) | `python3 -m server.crawler.sources.sina_list` 拉 ~5560 只 |
| 3 | api/sync 集成 | `server/api/sync.py` (改 `_get_all_stock_codes`) | `curl POST /api/sync/stocks` 触发,total ~5560 |
| 4 | docs 同步 | `openspec/specs/stocks/spec.md` (改 REQ-STOCK-004) | `git diff` 校验 |

## 详细步骤

### Commit 2: sina_list.py

```bash
mkdir -p server/crawler/sources
# 新文件: 公开 fetch_all_a_codes() -> List[str], 56 次分页 HTTP + 代码转换
# 公共 API:
#   fetch_all_a_codes(use_cache=True, cache_ttl_hours=24, cache_dir='data') -> List[str]
#   clear_cache(cache_dir='data') -> None  # 测试用
# 私有:
#   _fetch_one_page(page, num=100) -> List[dict]
#   _symbol_to_evtrade(sina_symbol) -> str  # sh600519 -> 600519.SH
```

### Commit 3: api/sync.py 集成

```bash
# 改 _get_all_stock_codes:
#   1. 调 sina_list.fetch_all_a_codes() (优先缓存)
#   2. 合并 positions 表代码 (兜底小盘股,已交易过)
#   3. 返去重排序的 List[str]
# 失败 → 抛 HTTPException 500 + 详细原因 (禁止 silent fallback)
```

### Commit 4: docs

```bash
# 改 stocks/spec.md REQ-STOCK-004:
#   - "范围: 沪深京 A 股全市场 (~5560 只)"
#   - "首次 sync 耗时 ~60min,数据源: 新浪 vip 接口 24h 缓存"
```

## 顺序约束

Commit 2 必须先 commit 并验证（sina_list.py 独立可跑）→ Commit 3 集成 → Commit 4 docs。**不合并**：
- sina_list 是新文件 + 独立单元
- api/sync 是 1 文件改动 + 集成验证
- docs 是字符串改动,无运行时风险

## 验证清单

- [ ] sina_list 独立跑: `python3 -m server.crawler.sources.sina_list` 输出 `total=5560` (期望 ±50)
- [ ] api/sync 启动任务: `curl -X POST /api/sync/stocks -H "Authorization: Bearer ..."` 返 `total ~5560`
- [ ] 缓存命中: 第一次跑后删 cache 文件 → 第二次跑速度 <1s (复用)
- [ ] sync 跑完后 `SELECT COUNT(*) FROM stocks` ≈ 5560
- [ ] 前端 `/admin/stock-config` 刷新看到 ~5560 只
- [ ] git log 4 commit 落地
- [ ] git push origin master 推送成功