# Tasks: his-hq-mock (2026-08-29)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进。

## P0 — strategy_exec his_hq mock (核心修复)

- [ ] **commit 1 — mock_history K 线生成器 + hq_history 短路集成**
  - 新文件 `strategy_exec/strategy_exec/market_data/mock_history.py`:
    - `generate_mock_bars(stock_code, start_date, end_date, period, seed=None) -> List[Dict[str, Any]]`
    - 数据 schema: `[{"stime": "20250102", "open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0, "volume": 1000000}]`
    - 起始价基于 `int(hash(stock_code)) % 100 + 50` (50~150 区间)
    - 随机游走 `random.Random(seed).gauss(0, 0.02)` 涨跌幅 → 算 OHLC
    - 跳过周末 (Sat/Sun)
    - period=1d → 日期序列；period=1m → 按 240 分钟/天填充 (暂只支持 1d, 其他返回空)
    - 确定性: 同 stock_code + 同区间 = 同数据 (seed 默认从 stock_code 派生)
  - 改 `strategy_exec/strategy_exec/market_data/hq_history.py`:
    - 入口加 mock 分支：`if _is_mock_mode(): return await generate_mock_bars(...)`
    - `_is_mock_mode()` 实现：读 sys_config（用 db 直连 + 5s 缓存）
    - 不连 RabbitMQ（mock 时直接返）
  - 编译/语法 sanity: `uv run python -c "from strategy_exec.market_data.mock_history import generate_mock_bars; print(len(generate_mock_bars('600519.SH', '20250101', '20250110', '1d')))"`
  - 验收: 返 8 个工作日 K 线 (2025-01-01~2025-01-10 跳过周末)

- [ ] **commit 2 — sys_config 读 helper**
  - 新文件 `strategy_exec/strategy_exec/data_access/sys_config.py`:
    - `read(key: str, default: Any = 0) -> Any` 读 user='0' 的 sys_config 行
    - 内存缓存 5s（避免每次 fetch 打 DB）
    - 用 SQLAlchemy text + DB engine (复用 data_access/db.py 的 engine)
    - 错误/缺失 → 返回 default
  - 验收: 调 `read('rpc_test_mode', 0)` 返当前 DB 值
  - 测试: `tests/strategy_exec/test_sys_config_cache.py` (4 cases: cache hit, expiry, missing key, db error)

## P1 — 端到端打通

- [ ] **commit 3 — server init_db seed his_hq_test_mode=0**
  - 改 `server/infra/db.py` 第 459 行附近:
    - `SELECT cfg_val FROM sys_config WHERE user='0' AND cfg_key='his_hq_test_mode'`
    - 缺失则 `INSERT ('0', 'his_hq_test_mode', '0', 'strategy_exec 历史行情 mock 模式...', NOW(), 'system')`
  - 改 `server/main.py` 启动日志：打印 his_hq_test_mode 状态
  - 测试: 手动 init_db 后 sys_config 应含 his_hq_test_mode=0

- [ ] **commit 4 — evctl set-his-hq-test-mode 子命令**
  - 改 `scripts/evctl.py`: 新增 `set-his-hq-test-mode 0|1` 子命令
  - 直连 DB UPDATE sys_config
  - 输出确认消息
  - 验收: 跑 `set-his-hq-test-mode 1` 后 sys_config.his_hq_test_mode='1'

- [ ] **commit 5 — 端到端验收脚本**
  - 新文件 `tests/strategy_exec/test_his_hq_e2e.py` (or scripts 下的):
    - 启 mock mode → 调 strategy_exec fetch_his_bars → 期望返 K 线（非 502）
    - 关 mock mode → 期望 raise HQHistoryError (与 broker 实际状态一致)
  - pytest 包含此用例
  - 验收: 8 working day K 线 + 高低开收 volume 都齐全

## P2 — 单测 + 老 queued cleanup

- [ ] **commit 6 — mock K 线生成单测**
  - 新文件 `tests/strategy_exec/test_mock_history.py`:
    - 5 day 区间返 5 行 (跳过 Sat/Sun)
    - 跨月/跨年区间正确
    - 同 stock_code + 同区间 = 同数据 (确定性)
    - 不同 stock_code = 不同数据
    - volume > 0
    - OHLC 关系: high >= max(open, close), low <= min(open, close)

- [ ] **commit 7 — server cleanup endpoint + 单测**
  - 改 `server/services/script_strategy/batches.py`:
    - 新 `mark_stale_queued_failed(strategy_id, threshold_hours=24) -> int`
    - 单 SQL: `UPDATE strategy_task SET status='failed', error_msg=... WHERE strategy_id=:sid AND status='queued' AND started_at IS NULL AND created_at < NOW() - INTERVAL :h HOUR`
    - 不删行！只 UPDATE status
  - 改 `server/api/script_strategy/strategies.py`:
    - 新 endpoint `POST /strategies/{id}/stale-queued/cleanup` (admin only)
    - 返 `{strategy_id, cleaned_count}`
  - 新文件 `server/tests/strategy/test_stale_queued_cleanup.py`:
    - admin OK + 非 admin 403 + cleanup 真改了 status (mock DB)

## P3 — 文档同步 + 归档

- [ ] **commit 8 — spec-delta merge + 归档**
  - 改 `openspec/specs/strategy-exec/spec.md`: 加 REQ-SE-013 his_hq mock
  - 归档: `mv openspec/changes/2026-08-29-his-hq-mock openspec/changes/archive/`

- [ ] **commit 9 — 知识库同步**
  - 新文件 `知识库/策略服务/历史行情.md`: mock 数据生成规则 + 开关流程
  - 改 `知识库/策略服务/信号推送.md`: 引用 broker his_hq 测试模式
  - 改 `strategy_exec/README.md`: 补"离线开发模式"段

## 验证（v6 完成自查）

- [ ] pytest strategy_exec/strategy_exec/tests/test_mock_history.py → 0 fail
- [ ] pytest strategy_exec/strategy_exec/tests/test_sys_config_cache.py → 0 fail
- [ ] pytest server/tests/strategy/test_stale_queued_cleanup.py → 0 fail
- [ ] pytest server/tests/ + tests/strategy_exec/ → 117+ 不退化
- [ ] 端到端实测 (commit 5 留 trace): mock on → fetch 8 bars；mock off → raise HQHistoryError
- [ ] cleanup admin 跑 1 次 → 老 queued 变 failed, 行未删
- [ ] cd client && npm run build → 无报错 (前端未改)
- [ ] git diff --stat 每 commit 单目的
- [ ] 不动 MySQL schema / 行（仅 UPDATE status, 不 DELETE）