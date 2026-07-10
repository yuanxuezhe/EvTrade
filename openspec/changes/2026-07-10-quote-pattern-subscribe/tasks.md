# Tasks — 2026-07-10 quote-pattern-subscribe

## 1. 服务端 ws/manager.py

- [x] 加 `match_pattern(stock_code, pattern) = pattern in stock_code` 函数
- [x] 注释升级: `subscription_index` 数据结构由 `Dict[code, Set[ws]]` 改为 `Dict[pattern, Set[ws]]`
- [x] `WSManager.subscribe()` 接受 pattern (含空字符串), strip + 幂等
- [x] `WSManager.unsubscribe()` 同步升级
- [x] `WSManager.get_subscribers(code)` 遍历所有 pattern, 子串匹配合并 ws
- [x] 重命名 `get_subscribed_codes` → `get_subscribed_patterns`
- [x] 文件顶部注释更新 + 例子

## 2. 服务端 ws/endpoint.py

- [x] import `match_pattern` (从顶部而非函数内)
- [x] subscribe_ack 区分精确 / 宽泛 pattern:
  - 精确 (含 `.` 且 `len>=6`): 走 `repo_get_latest_multi` 查 DB
  - 宽泛 (`SZ`/`SH`/`数字前缀`/``): 跳过 DB 查
- [x] ack 加 `has_wildcard: bool` + `snapshot_count: int` 字段
- [x] unsubscribe_ack 不变

## 3. OpenSpec specs/quotes/spec.md

- [x] 新增 REQ-QUOTE-006: WS 订阅 pattern 化
- [x] 新增 3 个 Scenario (全市场 pattern / 市场 pattern / subscribe_ack 行为分流)

## 4. OpenSpec change 工单

- [x] `openspec/changes/2026-07-10-quote-pattern-subscribe/proposal.md`
- [x] `openspec/changes/2026-07-10-quote-pattern-subscribe/spec-delta.md`
- [x] `openspec/changes/2026-07-10-quote-pattern-subscribe/tasks.md`

## 5. 测试

- [x] `tests/test_quote_pattern_subscribe.py` 20 个测试
  - 6 个 `match_pattern` 规则
  - 14 个 `WSManager` 行为
- [x] 全部通过

## 6. 实测验证

- [x] backend 重启 (evctl restart backend)
- [x] Node 5-pattern 集成测试 (本地 localhost:8000):
  - 精确 2 codes → 12 ticks for 000001.SZ
  - 'SZ' → 36 ticks for 3 个 SZ code
  - 'SH','SZ' → 84 ticks for SH+SZ
  - '' → 84 ticks for 全市场 (同 SH+SZ)
  - '000001' → 11 ticks for 000001.SZ (子串匹配)
- [x] 单测 + 集成测试全部通过

## 7. 提交

- [x] commit: feat(ws): pattern 化订阅 (子串匹配, ''=全市场)
- [x] commit: docs(spec): REQ-QUOTE-006 pattern 化订阅规范
- [x] commit: docs(openspec): 2026-07-10-quote-pattern-subscribe 工单
- [x] commit: test(ws): 20 个 unit test 覆盖 match_pattern + WSManager
- [x] push origin master