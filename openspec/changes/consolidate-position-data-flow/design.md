## Context

持仓 / 资金数据的服务器内部流转当前有 4 条路径,broker 字段名 → DB 列名的 remap 散落在 2 处,pos_cfm / ast_cfm 推送 handler 是死代码 (xtquant broker 不发这两个事件名)。本 change 收口到 2 条路径,统一字段命名收口,删除死代码,新增 trd_cfm → Position 增量更新以解决 day-init 未跑时的日内 stale 问题。

**约束**:

- broker wire 协议侧不动 (xtquant 协议固定 6 字段)
- DB schema 不动 (Position ORM 不加 market_value 列)
- 资金日内 stale 问题归 Change B 解决 (本 change 仅动持仓层)
- 单 commit 粒度建议 ≥ 3 commit (per `feedback_commit_granularity.md`)

**Stakeholders**:

- 后端: `server/rpc/parsers_business.py` / `server/services/reconcile.py` / `server/services/push/*`
- 前端: `client/src/stores/{holdings,holdings_push,ws_dispatch,asset,position}.js`
- 测试: `tests/server/rpc/`, `tests/server/services/{push,test_reconcile}.py`
- spec: `openspec/specs/{push,rpc-protocol,data-model}/spec.md`

## Goals / Non-Goals

**Goals**:

1. parser 输出 dict 字段名与 `Position` ORM 列名完全一致
2. 删除 `pos_cfm` / `ast_cfm` push handler (server + frontend + test 三处)
3. `trd_cfm` 推送时同步增量更新 `Position.vol` (intra-day 不再依赖 day-init reconcile)
4. Position 级 `market_value` 不入 DB,前端现算
5. 与 spec (`push` + `rpc-protocol` + `data-model`) 同步更新

**Non-Goals** (本 change 不做):

- Asset 资金日内更新 (Change B 范畴)
- 新表 `cash_ledger`
- POST /place 冻结 / DELETE /cancel 解冻 / JUNK 解冻
- broker wire 协议变更
- Position ORM 加列 / 减列
- reconcile 算法重构

## Decisions

### DR-1: parser 是 server 全栈唯一重命名边界

**选择**: `_parse_positions` 输出 dict 键名 (`vol` / `avl_vol` / `cost_price`) 与 `Position` ORM 列名一致。broker wire 字段 (`volume` / `avl_amt` / `avg_price`) 仅在 parser 内部读取,输出侧消失。

**理由**:

- 下游 (reconcile / push / API / 前端 store) 单一字段名,阅读一致
- 改动集中 (parser 一处),未来加字段 (`cost_basis` 等) 只改 parser 一处
- 现有反模式 "broker 名 → DB 名 remap 散落在 reconcile / push 两处" 消除

**被拒方案**:

- 保持 parser broker 名透传 + API/Pydantic remap: 反 v10 spec 已拒绝;且 remap 散落 (API 多层 + ORM 反序列化) 难维护。
- parser 重命名 + reconcile 也重命名: 重命名 2 次,无意义。

### DR-2: Position 数据写入收口到 2 路径

**选择**:
- 路径 A — day-init reconcile (`server/services/reconcile.py`): 全表覆盖,负责 `cost_price` / `avl_vol` / `today_buy` / `today_sell` / `last_vol` / `stock_name`。
- 路径 B — intra-day `trd_cfm` push (`server/services/push/trd.py`): 仅 `Position.vol ±= volume`,不动其他字段。

**理由**:

- day-init reconcile 提供权威快照 (broker 视角)
- trd_cfm 增量提供分钟级实时 (持仓数量日内变化)
- 两者无字段冲突 (增量只动 `vol`,权威只动其他字段)

**被拒方案**:

- 全交给 trd_cfm 增量 (cost_price 等不动): 用户看到的是历史成本价,失真。
- 全交给 reconcile 日内多次: 需引入定时调度 (架构债,见风险 R-1)。
- 保留 pos_cfm 推送: broker 不发,死代码。

### DR-3: Position-level market_value 不入库

**选择**: parser 丢弃 `market_value` 字段,前端 `holdings` 页用 `last_vol × last_price` 现算。

**理由**:

- `Position` ORM 本就不存储 market_value (不要因为删除而破坏现状)
- 行情 latest price 由 quote API 单独提供,与持仓快照解耦
- 避免 broker 推的 market_value 与前端行情价格版本不一致

**被拒方案**:

- parser 仍透传 market_value,前端读 DB: 增加无意义字段。
- 在 reconcile 时算并存: 加列 + 加计算 + 加版本同步,代价高。

### DR-4: trd_cfm 增量时 Position 不存在如何处理

**选择**: log warning + 跳过。admin 必须先 day-init reconcile 才能开市交易。

**理由**:

- trd_cfm 是 "patch" (相对当前持仓做 ±),不能凭空创建持仓
- 创建持仓需要 broker 确认的初始快照 (cost_price / avl_vol 等),只有 reconcile 给得出
- 跳过比 upsert 安全 (upsert 会用零值污染 stock_name 等)

**被拒方案**:

- upsert 创建空 Position: 字段不完整,污染表。
- 抛 4xx 中断 push: broker 不重试机制,push 队列会被卡。

### DR-5: pos_cfm / ast_cfm 整体删除而不是 only-disable

**选择**: 不只是 channel 注册处 disable,而是删除整个 handler 文件 + 注册 + 前端入口 + 测试用例。

**理由**:

- broker 不发这两个事件名,handler 是 dead code
- 注释 "重拉 (push 当前未路由)" 已与新行为对齐
- 留着会让未来读者误以为有推送路径

**被拒方案**:

- 只 disable channel + 留 handler: 死代码误导。
- 把 pos_cfm 升级为定时 reconcile 触发器: scope 蔓延,应独立 change。

### DR-6: trd_cfm 增量更新时的字段集

**选择**: 只动 `Position.vol`,`last_vol` 不动。

**理由**:

- `last_vol` 在 v5 schema 语义是 "持仓余额" = 期初持仓;日内不变化。
- reconcile 会每天早上重置 last_vol 为 broker 实际值。
- 若 trd_cfm 也动 last_vol,会让日内 last_vol 偏离 broker 真实持仓余额。

**被拒方案**:

- `vol` + `last_vol` 都动: 与 day-init reconcile 产生冲突。
- `vol` + `avl_vol` 都动: 但 avl_vol 涉及 T+1 规则,单笔成交算不出最终 avl_vol。

### DR-7: commit 粒度 ≥ 3 commit

**选择**:
1. `refactor(server): parser output aligns to Position ORM column names` (parser + reconcile + 测试)
2. `refactor(server): drop pos/ast push handlers` (push handler + frontend + dispatch.py 注释)
3. `feat(server): trd_cfm updates Position.vol incrementally` (trd.py + 测试)
4. `refactor(client) + docs:` (前端清理 + spec 同步,合并 commit 也可单独)

**理由**: per `feedback_commit_granularity.md` 内存指引,批量改动按维度拆 commit,便于 review 和局部回滚。

## Risks / Trade-offs

- R-1: Asset 日内 stale (cash/frozen_cash 在 trd_cfm 中不动) → 用户看 `/api/asset` 拿到的是 day-init reconcile 的快照。Mitigation: 文档化;Change B 引入 cash_ledger 后解决。
- R-2: trd_cfm 在 day-init reconcile 之前到达 → Position row 不存在 → log warning 跳过。Mitigation: admin 必须先 day-init 才能开市 (既有流程)。
- R-3: trd_cfm 增量与下一次 reconcile 时序冲突 (trd_cfm 后于 reconcile 到达会"找回"持仓) → 若 broker 的 trd_cfm 推回顺序异常,会出现 Position.vol 与 broker 真实持仓短期不一致。Mitigation: 出现此情况时下一次 reconcile 自动覆盖;前端 UI 显示"对账中"角标 (待 Change B 增加 recon_status 字段后再做)。
- R-4: **BREAKING** 删除 `position_update` / `asset_update` WS 频道 → 任何外部系统依赖此频道会断流。Mitigation: 文档 announcement + spec 同步。
- R-5: **BREAKING** parser 输出字段名变更 (`volume` → `vol` 等) → `reconcile.py` 必须同步改;若有第三方代码直接消费 parser 输出也会断。Mitigation: 实施时一处 parsers + 一处 reconcile 一同改,grep 验证无第三方。
- R-6: trade_type=1 (cancel-trade) 反向规则设计未定 → 见 Open Questions OQ-1。

## Migration Plan

**部署步骤**:

1. commit 1 (parser + reconcile): 灰度,reconcile 跑一次验证 Position 表 row 数与字段值与改前一致。
2. commit 2 (push handler 删除): 与 commit 1 合并部署即可,无破坏 (handler 本就是死代码)。
3. commit 3 (trd_cfm 增量): 灰度,先观察 `Position.vol` 日内是否随成交变化;与 day-init reconcile 后第一笔成交比对。
4. spec 同步: 部署后任何 spec 漂移用 `openspec validate` + 后续 review 检查。

**回滚策略**:

- commit 3 (trd_cfm 增量) 是最易回滚的: revert 单 commit 即可恢复 (trd_cfm 回到仅动 Order/Trade)。
- commit 1 (parser) 回滚 = 字段名回到 broker 名,但 reconcile 不一定能直接兼容 (需同步回滚 reconcile.py)。Mitigation: 1+2 同步回滚。
- commit 2 (push 删除) 回滚 = 恢复 pos.py/ast.py,无运行时破坏。

## Open Questions

- OQ-1: ✅ **RESOLVED → option B**
  - **选择**: `trade_type=1` (cancel-trade) 的 trd_cfm MUST 跳过 Position.vol 更新。
  - **理由**:
    1. DELETE 端点 (server/api/orders/cancel.py) 已在 broker ack.code == 0 时执行 R1 抹平语义:`orig.cancelled_volume = orig.volume`,即原委托已经视作 "全撤"。
    2. cancel-trade (trade_type=1) 在 broker 视角是一次反向成交,但在业务语义里是对原委托剩余量的"撤销"声明 — 而不是真实的新增/减少持仓。
    3. DELETE 端点同步 INSERT 一条 trade_type=1 行到 trades 表,该行的 Order / Trade 落库由 DELETE 端点负责,不依赖 trd_cfm 重复处理。
    4. 若 trd_cfm 对 trade_type=1 也做 vol 反向校正,会与 R1 抹平语义产生不一致 (e.g., DELETE 抹平后 Position.vol 被 trd_cfm "找回")。
  - **被拒**:
    - A (反向校正):与 R1 抹平冲突,且违反"cancel 是状态变更而非新增交易"的语义。
    - C (user_def 反查):增加复杂度而语义不变,无收益。
- OQ-2: ⏳ 仍开放。day-init reconcile 是 admin 手动触发,若管理员忘记 reconcile 就开市,Position 为空,trd_cfm 全部 log warning 跳过 → 持仓页面日内不变化。Mitigation 备选: 加个 system-init 屏障 (SysStatus.status != 'active' 拒绝 place 订单),此架构改动出 Change 范畴外,留作 system-init spec 改进。

## References

- `openspec/specs/data-model/spec.md` §3 `positions` 表
- `openspec/specs/push/spec.md` REQ-PUSH-002 / REQ-PUSH-003 / REQ-PUSH-005
- `openspec/specs/rpc-protocol/spec.md` REQ-RPC-004.1
- archive: `openspec/changes/archive/2026-06-25-rpc-field-alignment-ts-unify/` — 历史 broker 字段对齐变更 (v10)
- 内存: `feedback_commit_granularity.md`, `feedback_workflow.md`
