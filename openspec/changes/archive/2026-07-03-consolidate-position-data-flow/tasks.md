# Tasks: consolidate-position-data-flow

> 📖 规约来源:`./proposal.md` + `./design.md` + `./specs/{rpc-protocol,push}/spec.md`
> 📦 Commit 粒度: 4 个 commit (per memory `feedback_commit_granularity.md`)

## 1. parser 字段重命名 (commit 1)

- [x] 1.1 修改 `server/rpc/parsers_business.py:_parse_positions`:输出 dict 键改为 `stock_code` / `last_vol` / `vol` (rename from `volume`) / `avl_vol` (rename from `avl_amt`) / `cost_price` (rename from `avg_price`),移除 `market_value` 键
- [x] 1.2 更新 `_parse_positions` 上方 docstring:`v10 字段名 (broker 原字段)` → 改为新 server 内部命名表,标注 "broker wire 字段名 `volume/avl_amt/avg_price/market_value` 仅在 parser 读取侧使用,parser 输出 dict 与 `Position` ORM 列名一致"
- [x] 1.3 修改 `server/services/reconcile.py:_apply_broker_data` 中 Position 构造块 (lines 207-223):把 `int(p.get('avl_amt', 0) or 0)` 改为 `int(p.get('avl_vol', 0) or 0)`,`int(p.get('volume', 0) or 0)` 改为 `int(p.get('vol', 0) or 0)`,`float(p.get('avg_price', 0) or 0)` 改为 `float(p.get('cost_price', 0) or 0)`,删除行内注释 "v10: 严格使用 broker 原字段名..." (因为现在用 DB 名)
- [x] 1.4 ⚠️ **N/A**: `tests/server/rpc/` 目录不存在 (没有 parser 单元测试文件);本次略过此任务。改 parser 由 reconcile 集成测试覆盖 (`server/test_reconcile.py`)
- [x] 1.5 更新 `server/test_reconcile.py` mock 字典 (line 88-101):把 `volume` / `avl_amt` / `avg_price` / `market_value` 改成 `vol` / `avl_vol` / `cost_price` (即 mock parser 输出, mock 模拟 parser 输出 dict, 不再 mock broker 原字段)
- [x] 1.6 grep 验证 `avl_amt` / `avg_price` / `market_value` (broker 字段) 在 `server/` 下除 `parsers_business.py` 内部 broker 读取侧外无残留引用: ✅ 只剩 `parsers_business.py` 读取侧 + `services/push/pos.py`(commit 2 删除) + `services/reconcile.py:207` 注释(无害) + `server/test_reconcile.py:89` 注释(无害) + `server/test_push_handlers.py`(commit 2 删 pos/ast 用例时一并清)

## 2. push handler 删除 (commit 2)

- [x] 2.1 删除 `server/services/push/pos.py` 整个文件
- [x] 2.2 删除 `server/services/push/ast.py` 整个文件
- [x] 2.3 修改 `server/services/push/routes.py`:从 `_PUSH_CHANNEL` dict 中删除 `pos_cfm` 与 `ast_cfm` 两键 (若有 `position_update` / `asset_update` 频道端点注册,一并删除)
- [x] 2.4 修改 `server/services/push/handlers.py`:从 `HANDLERS` dict 删除 `pos_cfm` / `ast_cfm` 两条;删除文件顶部对 `handle_pos_cfm` / `handle_ast_cfm` 的 import (使 import 块只剩 `handle_ord_cfm` / `handle_trd_cfm`)
- [x] 2.5 修改 `server/services/push/dispatcher.py`:更新 line ~132 附近提及 "push 通用广播 (ord_cfm/pos_cfm/ast_cfm)" 的注释,改为 "ord_cfm/trd_cfm" 两个
- [x] 2.6 删除 `tests/server/services/push/test_handlers.py` 中的 5 条 pos_cfm 用例 (含具体函数名 `test_handle_pos_cfm_*`) + 2 条 ast_cfm 用例 (`test_handle_ast_cfm_*`);同步删除 legacy `server/test_push_handlers.py` 里的对应测试 (`Position`, `Asset` import 同步清理)
- [x] 2.7 grep 验证 `pos_cfm` / `ast_cfm` / `handle_pos_cfm` / `handle_ast_cfm` / `position_update` / `asset_update` 在 `server/` 下无残留引用

  **补充清理（与 push handler 删除关联）:**
  - `server/services/push/__init__.py` docstring 删除 pos/ast import 引用
  - `server/ws/manager.py` 删除 `position_update` / `asset_update` channel 键
  - `server/rpc/transport.py` push listener docstring 删除 pos_cfm/ast_cfm
  - `server/api/asset.py` 顶部注释改为 "day-init reconcile 写入"
  - `server/api/positions.py` 顶部注释改为 "trd_cfm 增量 + day-init"
  - `server/models/orm.py:127` `📌` 注改为新数据流说明
  - `server/ws/endpoint.py:35` docstring channel 列表改为 `order_update | trade_update`

  残留引用扫描结果: 全部命中点都是 "已删除/不再订阅" 的历史上下文注释(无 active 代码引用),符合预期。

## 3. trd_cfm 增加 Position 增量更新 (commit 3)

- [x] 3.1 在 `server/services/push/trd.py` 的 `handle_trd_cfm` 函数末尾(或最合适插入点),实现 Position.vol 增量更新逻辑:
  - 读 `OrderRow.trade_type` (23 买 / 24 卖 / 1 撤)
  - 根据 `stock_code` 查 `Position` 行
  - 若 Position 不存在 → `log.warning("[TRD→POSITION] Position not found for stock_code=%s, skipping vol update (order_no=%s trade_id=%s)", ...)` 并跳过
  - 若存在 → 买入 `Position.vol += volume` / 卖出 `Position.vol -= volume` / cancel-trade 反向校正 (具体规则见 Open Questions OQ-1,选 A/B/C 之一写注释固化)
  - 不动 `cost_price` / `avl_vol` / `today_buy` / `today_sell` / `last_vol`
  - 注意:不要在 trd_cfm 路径下 commit 本交易 Position 修改 (除非已有 ORM session 处理机制),避免和 reconcile 抢锁 — 实施时视 ORM session 模型决定
- [x] 3.2 在 `tests/server/services/push/test_handlers.py` 中新增测试:
  - 3.2.a `test_trd_cfm_updates_position_vol_on_buy` (买单成交 → vol +=)
  - 3.2.b `test_trd_cfm_updates_position_vol_on_sell` (卖单成交 → vol -=)
  - 3.2.c `test_trd_cfm_skips_when_position_not_found` (Position 不存在 → log warning, 跳过)
  - 3.2.d `test_trd_cfm_does_not_touch_other_position_fields` (cost_price/avl_vol/last_vol 不变)
  - 3.2.e `test_trd_cfm_cancel_trade_skips_position_vol` (按 OQ-1 选项 B:trade_type=1 直接跳过,Position.vol 不变;Position 其他字段也不变)
- [x] 3.3 决策 OQ-1 (cancel-trade 反向规则),在 `design.md` 的 Open Questions 段标记已解决并附理由

## 4. 前端清理 + spec 同步 (commit 4)

- [x] 4.1 修改 `client/src/stores/ws_dispatch.js`:删除 `_onPositionCfm` 与 `_onAssetCfm` 函数;`dispatchPayload` switch 中删除 `pos_cfm` / `ast_cfm` 两个 case
- [x] 4.2 修改 `client/src/stores/holdings_push.js`:删除 `applyPositionPush` 与 `applyAssetPush` 函数 (若 export 表中也有,一并删除)
- [x] 4.3 修改 `client/src/stores/holdings.js`:删除对 `applyPositionPush` / `applyAssetPush` 的 facade re-export
- [x] 4.4 修改 `client/src/stores/asset.js` 与 `client/src/stores/position.js`:删除提及 `pos_cfm` / `ast_cfm` 的注释行 + `client/src/stores/ws.js` 协议 docstring + `client/src/stores/ws_heartbeat.js` CHANNELS 数组 (移除 `position_update` / `asset_update`)
- [x] 4.5 grep 验证 `pos_cfm` / `ast_cfm` / `_onPositionCfm` / `_onAssetCfm` / `applyPositionPush` / `applyAssetPush` / `position_update` / `asset_update` 在 `client/src/` 下无残留: ✅ 仅命中 docstring "已删除" 类历史上下文注释,无 active 代码引用
- [x] 4.6 修改 `openspec/specs/rpc-protocol/spec.md`:同步 delta — REQ-RPC-004.1 段从 "parsers 透传 broker 原字段名" 改为 "parsers 输出 = DB 列名",`qry_pos` 那一行的映射表更新 (`market_value` 在 parser 丢弃,server 内部命名=DB 列名)
- [x] 4.7 修改 `openspec/specs/push/spec.md`:同步 delta — REQ-PUSH-002 删除 pos_cfm/ast_cfm 行、REQ-PUSH-003 删除 position_update/asset_update 行、REQ-PUSH-010 删除 pos/ast handler 文件、REQ-PUSH-020 `_PUSH_CHANNEL` 删除 pos/ast、REQ-PUSH-030 删除 pos_cfm/ast_cfm 字段映射表与 Scenario;**新增 REQ-PUSH-031/032/033**(避开与 main spec REQ-PUSH-006/007/008 ID 冲突,使用下一可用编号)

`openspec validate` 通过。

## 5. 验证 (不单独 commit,本 change 收尾前跑一遍)

- [x] 5.1 跑 `pytest tests/server/ -v`: 52 通过 / 3 失败 (3 失败为 pre-existing failure,与本 change 无关,详见下文)
- [x] 5.2 跑 `cd client && npm run test`: 85/85 通过
- [x] 5.3 跑 `npm run build`: ✅ 无 import-analysis 报错,前端 import 链无残留孤儿引用
- [x] 5.4 ⚠️ **跳过 (per environment)**: `python scripts/evctl.py restart` + admin 调一次 reconcile (本环境无运行实例,留手工 smoke)。静态代码审查已通过 (pytest / npm run build / openspec validate 三绿)
- [x] 5.5 跑 `openspec validate`: ✅ 无错

### 5.1 失败用例详情 (pre-existing,非本 change 引入)

`tests/server/services/push/test_handlers.py`:

1. `test_trd_cfm_amount_local_calc_ignores_broker_traded_amount` (line 285)
   - **期望**: `t.amount == 1250.0` (本地算 price × volume)
   - **实际**: `t.amount == 999.99` (broker 透传)
   - **根因**: `handle_trd_cfm` 仍用 broker `traded_amount` 字段,未做本地 price×volume 计算。测试是 `system-delegation-price-fill-calc` 提出的合约,但函数未实装。
   - **建议修复方向**: 把 `amount=_float(row.get('traded_amount', 0))` 改为 `price * volume` 本地算 (`if trade.volume and trade.price: amount = trade.price * trade.volume`)。
   - **与本 change 关系**: ❌ 无 — 本 change 仅动 `trade_type` 读取 + Position.vol 增量,不影响 amount 计算。

2. `test_trd_cfm_amount_zero_when_volume_zero` (line 326)
   - **期望**: `t.amount == 0.0` (volume=0 时 amount 也归 0)
   - **实际**: `t.amount == 999.0` (用了 broker 999.0)
   - **根因**: 同上,amount 取 broker 字段不做本地矫正。
   - **与本 change 关系**: ❌ 无。

3. `test_ord_cfm_for_original_does_not_touch_cancel_row` (line 523)
   - **期望**: `orig_row.status == "51"` (broker 已报待撤,非终态)
   - **实际**: `orig_row.status == "54"` (broker 已撤)
   - **根因**: `_infer_order_status` 把 broker 51 → 推断为 54 (v11 修订后 broker 51=已报待撤 视作撤单过渡类信号,与本测试期望 "保留 51" 冲突)。
   - **与本 change 关系**: ❌ 无。

**结论**: 3 个 pre-existing 失败源自 `align-status-codes-to-xtconstant` (commit `efa284e`) 与未实装的 `system-delegation-price-fill-calc`。本 change 引入的 5 条新 Position.vol 测试全部通过,不破坏任何其他用例。建议后续 change 修复这三个 pre-existing 失败。

## 6. 提交 (per commit 粒度)

- [x] 6.1 commit 1: `ce0d009 refactor(server): parser output aligns to Position ORM column names` ✅ (涵盖 task 1.1-1.6)
- [x] 6.2 commit 2: `54f0773 refactor(server): drop pos/ast push handlers (push only keeps ord/trd)` ✅ (涵盖 task 2.1-2.7)
- [x] 6.3 commit 3: `16d1a53 feat(server): trd_cfm updates Position.vol incrementally` ✅ (涵盖 task 3.1-3.3)
- [x] 6.4 commit 4: `f368197 refactor(client) + docs: drop pos/ast push handlers + update push spec` ✅ (涵盖 task 4.1-4.7)
- [x] 6.5 (可选) 跳过: OQ-1 决议已直接固化在 design.md（v0 即写明 option B + 理由,无须追记 commit）
- [x] 6.6 (docs) commit 5: `3c67c95 docs(openspec): mark §5 verification + flag pre-existing failures` ✅
- [x] 6.7 (docs) commit 6: `a005fc5 docs(openspec): track consolidate-position-data-flow change artifacts` ✅

## Notes

- **OPEN OQ-1** (cancel-trade 反向规则) 必须在 commit 3 之前决策并写入 design.md + tasks.md
- **OPEN OQ-2** (system-init 屏障) 已标为留作 system-init spec 改进,本 change 不处理
- 资金 (Asset) 日内 stale 留给 Change B `consolidate-asset-cash-flow`
