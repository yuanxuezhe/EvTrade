# His-HQ Mock — strategy_exec broker 历史行情离线 mock (2026-08-29)

> 用户拍板 2026-08-29：让回测自己跑通。
> 根因实测：Linux dev 环境无 QMT / xtquant broker，strategy_exec 的 `fetch_his_bars` 等 RabbitMQ 队列 `EvTrade.ReqHisHq` 30s 超时 → 0 rows → run_backtest 抛 BROKER_ERROR 502 → 老 queued 任务永远卡在 queued 状态。

## Why

**实测链路**（2026-08-29）：

```bash
# strategy_exec 直接调 fetch_his_bars
$ uv run python -c "from strategy_exec.market_data.hq_history import fetch_his_bars; ..."
[hq_history] no reply within 30s — broker his_hq 未响应
ERR: HQHistoryError: his_hq reply timeout (30s), received 0 rows

# EvTrade backtest endpoint 转发结果
$ POST /api/script-strategy/strategies/12/backtest
502 {"code":"BROKER_ERROR","msg":"broker his_hq 行情服务未响应: his_hq reply timeout (30s)..."}

# 老 queued 任务永远卡死 (DB 实测)
SELECT id, status, started_at, progress, age FROM strategy_task WHERE status='queued';
# id=3 sid=3 batch=10000002 status=queued started=None progress=None age=24678min
# id=4 sid=3 batch=10000003 status=queued started=None progress=None age=24677min
# id=5 sid=3 batch=10000004 status=queued started=None progress=None age=19298min
# id=6 sid=5 batch=10000001 status=queued started=None progress=None age=11184min
# id=14 sid=12 batch=10000009 status=queued started=None progress=None age=8665min
```

**根因（3 层）**：
1. **broker his_hq 服务没起**：xtquant Windows 端 broker 不在 Linux dev 环境跑，RabbitMQ `EvTrade.ReqHisHq` 队列无人消费
2. **strategy_exec 错误抛出后回测 task 不会标 failed**：`HQHistoryError` 在 `_run_backtest_background` 之前抛出 → `update_task_status('failed')` 没机会执行 → DB 永远 `status='queued'`
3. **前端无失败提示**：用户看到 "排队中"，不知道 broker 挂了

**用户硬规则**：
- 不动 MySQL 任何表/列/行（老 queued 任务只读，不主动改 status / abandon）
- 数据归属 owner/admin 决策
- 但允许新增 `sys_config` 配置项（rpc_test_mode 的对称做法）

## What

### P0 — strategy_exec his_hq mock 数据生成器

1. **新文件** `strategy_exec/strategy_exec/market_data/mock_history.py`
   - `generate_mock_bars(stock_code, start_date, end_date, period, seed=None) -> List[Dict]`
   - 生成**确定性 K 线**（基于 stock_code hash 做 RNG seed，**同标的同区间 = 同数据**，跨重启一致）
   - 数据 schema 与 broker 协议对齐：`{stime, open, close, high, low, volume}` + period 适配
   - 跳过周末/法定节假日（仅返回工作日 K 线）
   - 价格起始基准 + 随机游走（带 trend + volatility），避免全平线
2. **修改** `strategy_exec/strategy_exec/market_data/hq_history.py`
   - 新增 `_is_mock_mode() -> bool`：读 `sys_config.user='0' AND cfg_key='his_hq_test_mode'`（共享 MySQL 同一表）
   - `fetch_bars()` 入口检测：mock 模式 → 调用 `generate_mock_bars` 替代 RabbitMQ 流程
   - **不连接 RabbitMQ**（节省连接池）
3. **`sysconfig` 兼容层**：
   - strategy_exec 端实现一个轻量 `read_sys_config(key, default=0)` helper，直接连 MySQL 读 sys_config 表
   - 缓存 5s（避免每次 fetch 都打 DB）
   - 不依赖 server 端 sysconfig 模块（避免跨服务耦合）

### P1 — 离线开关打通端到端

1. **`init_db` 兜底 seed**（`server/infra/db.py`）：增加 `his_hq_test_mode=0` 默认 seed（与 `rpc_test_mode` 同样套路）
2. **`server/main.py`**：打印启动日志显示 his_hq_test_mode 状态
3. **SystemConfig 页**：可切换（与 rpc_test_mode 一致的 sys_config 表，可改前端加项；先不强制做前端切换 — 后端 DB seed 即可）
4. **admin 启用脚本** `scripts/evctl.py set-his-hq-test-mode 0|1`：手动切换
5. **端到端验收**：
   - 启 test mode → 提交 sid=12 single 回测 → 期望 status='finished' + pnl/trades_count 非空 + backtest_result.best.trades > 0
   - 关 test mode → 仍 502（broker 仍不可用，验证不破坏真实链路）

### P2 — 老 queued 任务失败回填（只标 status，不删数据）

1. **新 endpoint** `POST /api/script-strategy/strategies/{id}/stale-queued/cleanup`（admin only）
   - 把 `status='queued' AND started_at IS NULL AND age > 24h` 的 task 全部标 `status='failed'`，error_msg="broker his_hq unavailable (回填 2026-08-29 离线 mock 后) — 建议重测"
   - 返 `{strategy_id, cleaned_count, cleaned_task_ids: [...]}`
2. **`server/services/script_strategy/batches.py`**: `mark_stale_queued_failed(strategy_id, threshold_hours=24) -> int`
3. **测试**：mock 验证 admin OK / 非 admin 403 / 验证 cleanup 后 status 已变 + DB 仍存在（行未删，只改 status）
4. **数据安全**：仅 UPDATE status，不 DELETE；满足用户硬规则

### P3 — 文档同步

1. **spec-delta**: `strategy-exec/spec.md` REQ-SE-013 his_hq mock
2. **知识库** `策略服务/信号推送.md` 或新文件 `策略服务/历史行情.md`：mock 数据生成规则 + 开关流程
3. **README** `strategy_exec/README.md`：补"离线开发模式"段

## 不做什么

- **不动 MySQL schema**（用现有 sys_config 表，不新建表）
- **不动 broker / QMT 真实链路**（mock 关闭时所有路径不变，broker 真起来仍走真 broker）
- **不删老 queued task**（仅标 status='failed'，保留行让 owner/admin 决定重测）
- **不动 signal_consumer / task_progress_consumer**（与本 change 无关）
- **不动 strategy 算法**（run_backtest/sweep 逻辑不变）

## 影响面

| 模块 | 影响 |
|---|---|
| strategy_exec/strategy_exec/market_data/mock_history.py | 新增 ~80 行 |
| strategy_exec/strategy_exec/market_data/hq_history.py | +30 行（mock 分支 + sys_config 读） |
| strategy_exec/strategy_exec/data_access/sys_config.py | 新增 ~25 行（MySQL 直读 + 缓存） |
| server/infra/db.py | +10 行（init_db seed his_hq_test_mode=0） |
| server/main.py | +3 行（启动日志） |
| server/services/script_strategy/batches.py | +25 行（mark_stale_queued_failed helper） |
| server/api/script_strategy/strategies.py | +25 行（cleanup endpoint） |
| server/tests/strategy/test_his_hq_mock.py | 新增 ~60 行 |
| server/tests/strategy/test_stale_queued_cleanup.py | 新增 ~50 行 |
| scripts/evctl.py | +30 行（set-his-hq-test-mode 子命令） |
| openspec/specs/strategy-exec/spec.md | REQ-SE-013 新增段 |
| 知识库/策略服务/信号推送.md + 新文件 历史行情.md | 同步 |
| strategy_exec/README.md | 补离线模式段 |

## Commit 拆解 (v6)

```
1. feat(strategy-exec): mock_history K 线生成器 + hq_history 短路集成
2. feat(strategy-exec): sys_config 读 helper + 缓存
3. feat(server): init_db seed his_hq_test_mode=0
4. test(strategy-exec): mock K 线生成 + 缓存单测
5. test(server): hq mock 端到端 + cleanup endpoint 单测
6. feat(server): cleanup stale-queued endpoint
7. feat(scripts): evctl set-his-hq-test-mode 子命令
8. feat: 端到端验收 (手动 admin token + curl 跑通, commit 留 trace)
9. docs(openspec): strategy-exec REQ-SE-013 spec-delta + merge + 归档
10. docs(knowledge): 策略服务/历史行情.md + README 同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不 drop / truncate / delete from / ALTER AUTO_INCREMENT
- [ ] 不重建 schema
- [ ] P2 cleanup 仅 UPDATE status（行保留），不 DELETE
- [ ] 不动老 queued 任务原始数据（created_at / progress / started_at）

## 验收 (v6 完成自查)

- [ ] pytest strategy_exec/strategy_exec/tests/ + server/tests/strategy/ → 0 fail
- [ ] pytest server/tests/ + tests/strategy_exec/ → 不退化 (基线 117 passed)
- [ ] 端到端：脚本或 admin token 提交回测 → status='finished' + 有 pnl + 有 trades
- [ ] `cd client && npm run build` → 无报错（前端无改动，但保险跑一次）
- [ ] git diff --stat 每 commit 单目的
- [ ] sys_config 表新增 1 行 his_hq_test_mode=0 (init_db seed)
- [ ] cleanup endpoint admin 跑 1 次，老 5 条 queued 变 failed（owner/admin 拍板才跑）