# Spec Delta: stocks — REQ-STOCK-004 全市场范围同步 (v24 2026-07-12)

## MODIFIED Requirements

### Requirement: REQ-STOCK-004 同步任务生命周期（v24 范围扩到全市场）

**Given** admin 用户触发股票同步  
**When** 调用 `POST /api/sync/stocks`  
**Then** 必须满足:

- 鉴权:`_AUTH_ADMIN` 守卫(role=admin)
- 重复 start → 返 409 conflict(已有任务在跑)
- 启动后立即返 202 Accepted + `{job_id, total}`
- **`total ~5560`(沪深京 A 股全市场,2026-07-12 实测 56 页 × 100/页)**
- 后台 task 异步执行,不影响 API 响应时间
- 同步期间每 1 秒推 WS `stock_sync_progress` 消息
- 每只股票 upsert 成功后推 WS `stock_synced` 消息(v23 仅 3 字段,见 REQ-STOCK-005)
- `DELETE /api/sync/stocks` 发送停止信号,task 优雅退出(完成当前只后停)
- `GET /api/sync/stocks/status` 返当前 task 状态(state/counters/elapsed)
- 首次同步预计耗时 ~60min(NFR-STOCK-001 v21)

**Task 单例**:`server.services.sync.manager` 维护 `current_task: SyncTask`,后启动覆盖前一个(警告)。

**数据源**(v24 新增 REQ-STOCK-006):
- 主源: 新浪 `vip.stock.finance.sina.com.cn` 的 `Market_Center.getHQNodeData?node=hs_a`(分页 100/页,sort=symbol&asc=1)
- 备援: `positions` 表持仓代码(交易过的小盘股兜底,可能不在 sina 当前列表)
- 代码转换: `sh600519` → `600519.SH`, `sz000001` → `000001.SZ`, `bj920169` → `920169.BJ`
- 缓存: `data/all_a_codes.json`(TTL 24h),复用前次结果避免每次启动都拉 17s
- **失败 = 500**(禁止 silent fallback 到 builtin 20 只子集,违反用户硬性偏好 #6)

#### Scenario: 同步任务范围扩到全市场 (v24)

- **GIVEN** admin 调用 `POST /api/sync/stocks`(无 body)
- **WHEN** `_get_all_stock_codes()` 执行
- **THEN** 调 `sina_list.fetch_all_a_codes()`(优先缓存)
- **AND** 合并 `positions.stock_code` 去重
- **AND** 返回 ~5560 只沪深京 A 股代码
- **AND** sync_manager.start(all_codes) 启动 task,`task.counters['total'] = ~5560`

#### Scenario: 缓存命中跳过 HTTP

- **GIVEN** `data/all_a_codes.json` 存在且 TTL 未过期(<24h)
- **WHEN** `_get_all_stock_codes()` 执行
- **THEN** 直接读 JSON 返 List[str],**不**发起任何 HTTP 请求
- **AND** 日志记录 "sina_list cache hit, codes=N"

#### Scenario: 缓存失效重新拉

- **GIVEN** `data/all_a_codes.json` 不存在 OR TTL 已过 OR 文件损坏
- **WHEN** `_get_all_stock_codes()` 执行
- **THEN** 56 次分页拉 sina 接口,~17s 完成
- **AND** 写入 `data/all_a_codes.json`(含 fetched_at timestamp)
- **AND** 日志记录 "sina_list cache miss, fetched=N"

#### Scenario: sina 接口失败不静默 fallback

- **GIVEN** sina 接口 5xx / 网络 timeout / JSON 解析失败
- **WHEN** `_get_all_stock_codes()` 执行
- **THEN** 抛 HTTPException 500 `{detail: "sina list source failed: <reason>"}`
- **AND** **不**回退到 builtin 20 只(用户硬性偏好 #6 禁止 silent fallback)
- **AND** sync 任务不启动