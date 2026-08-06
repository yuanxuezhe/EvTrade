# 2026-07-10 quote-pattern-subscribe

## Why

2026-07-09 quote-snapshot-subscribe 工单实现了"按 stock_code 订阅",但只能精确订阅。
实际使用场景需要更灵活的订阅方式:
- 行情 app: 一波订阅整个深圳市场 (SZ),不用列举 ~2500 个代码
- 监控大盘: 订阅沪深两市所有 tick, 空字符串 = 全市场
- 持仓 + 候选: 订阅 `['000001', '002736', ...]` (6 位数字前缀, 双市场都覆盖)

需求(用户原话):"订阅的时候,订阅条件支持送入数组,多个 `'000001.SZ', '000002.SZ'`
标识订阅这两个证券代码。`'SZ'` 标识订阅深圳市场。数组一个元素 `''` 传空则能跟所有
代码匹配上,表示订阅全市场。"

补充:"空字符串是 `[]`, 这样能和前面的规则一致" → 设计成所有 pattern 都走统一规则,
不要为 `''` 写特殊分支。

## What Changes

### 服务端
- 新增 `match_pattern(stock_code, pattern) = pattern in stock_code` 函数
  (一行规则, 空字符串 = 任何字符串的子串 = 永远 True)
- `WSManager.subscription_index` 数据结构 `Dict[stock_code, Set[ws]]` 升级为
  `Dict[pattern, Set[ws]]` (pattern 即用户传入的订阅条件, 不再展开为 stock_code)
- `WSManager.subscribe()` / `unsubscribe()` 接受任意字符串 pattern (含空字符串),
  strip 处理 + 幂等
- `WSManager.get_subscribers(stock_code)` 遍历所有 pattern, 对每个 pattern 跑
  `match_pattern()`, 命中合并 ws 集合
- `ws/endpoint.py` subscribe_ack 区分"精确 pattern"和"宽泛 pattern":
  - 精确 (含 `.` 且 `len>=6`): 查 DB 拿 snapshot 立即返回
  - 宽泛 (`'SZ'`/`'SH'`/`'000001'`/`''`): `snapshots={}`, `has_wildcard=true`,
    后续 tick 自动推
- 重命名 `get_subscribed_codes` → `get_subscribed_patterns` (语义更准)

### 前端
- 无 breaking change — `ws_dispatch.subscribe(codes)` 仍发 `{type:"subscribe",
  stock_codes:[...]}`, 字段名复用
- 新增 `subscribe_ack.has_wildcard` / `subscribe_ack.snapshot_count` 字段供前端诊断

### 数据
- 不变 — snapshot 数据仍由 QuoteSnapshot 表 + 22 字段 schema 提供

### 文档
- 增 REQ-QUOTE-006 (quote-pattern-subscribe)
- 增 3 个 Scenario (全市场 pattern / 市场 pattern / subscribe_ack 行为分流)

## Impact

- 性能:
  - `get_subscribers(code)` 时间复杂度从 O(1) 升为 O(P) (P = pattern 总数)
  - 实际 pattern 总数极少 (一个 ws 通常 < 20 pattern), 性能影响可忽略
- 内存:
  - `subscription_index` key 减少 (5 codes → 1 pattern 'SZ'), 节省
- 向后兼容:
  - 精确 stock_code pattern (`'000001.SZ'`) 仍按 REQ-QUOTE-005 行为
  - 前端字段名 `stock_codes` 不变 (subscribe/unsubscribe ack 都保留)
- 测试覆盖:
  - `tests/test_quote_pattern_subscribe.py` 20 个测试覆盖 match_pattern + WSManager

## Risk

- **低风险**: 数据结构升级, 但客户端接口不变
- **回滚容易**: `git revert` 即可 (但 `subscription_index` 数据结构是 hot-path,
  revert 需重启 backend)

## Out of Scope

- WS 反压 / 限速 / 单 ws 200 上限收紧 (后续可靠性工单)
- pattern → 具体 stock_code 展开缓存 (目前 O(P) 已足够)
- 前端 UI 改: demo 已支持所有 pattern 模式, 正式 UI 后续独立工单