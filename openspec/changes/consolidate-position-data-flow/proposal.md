# Proposal: consolidate-position-data-flow

## Why

持仓/资金数据流入路径**分裂**且**易漂移**:

1. **三入口并存**: `pos_cfm` 推送 (intra-day 增量) + `ast_cfm` 推送 + `reconcile` (day-init 全量)。三条路径都写 `Position`/`Asset` 表,broker 字段名 (`volume`/`avl_amt`/`avg_price`/`market_value`) 在 reconcile.py 内手动 remap 到 DB 列名 (`vol`/`avl_vol`/`cost_price`)。
2. **broker 字段名→DB 列名**的 remap 散落在 `reconcile.py` 与 `push/pos.py` 两处,漂移是单点失败。
3. **broker 不发 pos_cfm/ast_cfm** (xtquant 协议层没有这两个推送事件名) — 这两个 handler 是**死代码**,反而成为误导新读者的复杂度。
4. **持仓日内 stale**: 若 day-init reconcile 未跑, trd_cfm 来了也只在 Order 上累计,Position 表不动 → 用户看 /api/holdings 永远是 0。

## What Changes

- **服务器字段命名收敛**: `_parse_positions` 输出 dict 键名与 `Position` ORM 列名完全一致 (`volume→vol`,`avl_amt→avl_vol`,`avg_price→cost_price`);broker wire 字段名不变;reconcile.py 删掉 broker→DB remap 手工块。
- **`pos_cfm` / `ast_cfm` 删除**: 删除 `server/services/push/pos.py`、`server/services/push/ast.py`;从 `routes.py::_PUSH_CHANNEL` 与 `handlers.py::HANDLERS` 移除;前端 `ws_dispatch.js` / `holdings_push.js` / `holdings.js` 同步清理对应入口。**BREAKING**: 若外部有依赖 `position_update` / `asset_update` 频道的代码会被破坏。
- **`trd_cfm` 增加 Position 增量更新** (新行为): 每笔成交在落库 Order/Trade 时,同步 `Position.vol ±= volume` (买 +,卖 -,cancel-trade 反向)。其余持仓字段 (`cost_price` / `avl_vol` / `today_buy` / `today_sell` / `last_vol`) 不动,继续由 day-init reconcile 兜底。
- **Position 级 `market_value` 不入库**: parser 丢弃该字段,前端持仓页用 `last_vol × last_price` 现算,DB 不再需要存储。
- **测试/前端/文档同步**: parser / reconcile / push handler 测试更新;删除 5+2 = 7 条 pos/ast push 用例;新增 trd_cfm→Position 增量更新用例;前端 4 文件清理;`push` 与 `rpc-protocol` spec 同步。

## Capabilities

### New Capabilities

(无 — 全部为现有 capability 的需求变更)

### Modified Capabilities

- `rpc-protocol`: REQ-RPC-004.1 业务字段映射表 — `qry_pos` 那行的 "server 内部命名 (DB/API)" 列更新为"server 内部命名 = DB 列名 (= parser 输出)";"parsers 层职责"从"broker 原字段名透传"改为"在 parser 输出边界做 broker→DB 重命名 (一次性)";`qry_ast` 行 `market_value` 不变 (Asset 级 market_value 仍由 reconcile 写入 DB)。
- `push`: REQ-PUSH-002 事件路由表删 `pos_cfm`/`ast_cfm` 两行;REQ-PUSH-003 WS 频道→前端 store 表删 `position_update`/`asset_update` 两行;新增 REQ-PUSH-006 trd_cfm 触发 Position.vol 增量更新的语义与边界 (Position 不存在时跳过 + 警告;cancel-trade 反向规则;不动 last_vol/cost_price/avl_vol/today_buy/today_sell)。
- `data-model`: §3 `positions` 表的 `Position` 字段定义已经按 DB 列名书写,本次不改 schema,只需在表头注明"`market_value` 不入此表 (前端自算)",与本 change 的 DR-3 对齐。

## Impact

**受影响的代码**:

```
server/rpc/parsers_business.py:_parse_positions   (改 dict 输出键名)
server/services/reconcile.py:_apply_broker_data   (删 broker→DB remap 块)
server/services/push/pos.py                       (删除)
server/services/push/ast.py                       (删除)
server/services/push/routes.py                    (删 _PUSH_CHANNEL 两条)
server/services/push/handlers.py                  (删 HANDLERS 两条 + import)
server/services/push/dispatcher.py                (更新注释)
server/services/push/trd.py                       (新增 Position.vol 增量)
tests/server/rpc/test_parsers_business.py         (断言新键名)
tests/server/services/test_reconcile.py           (删 remap 相关断言)
tests/server/services/push/test_handlers.py       (删 7 用例 + 新增 trd→Position 用例)
client/src/stores/ws_dispatch.js                  (删 _onPositionCfm/_onAssetCfm)
client/src/stores/holdings_push.js                (删 applyPositionPush/applyAssetPush)
client/src/stores/holdings.js                     (删 facade re-export)
client/src/stores/asset.js + position.js          (删注释)
openspec/specs/{push,rpc-protocol,data-model}/spec.md
```

**API 契约变更**:

- GET `/api/holdings` 响应字段不变 (本来就是 DB 列名序列化),行为变更: 数据从"三种路径写入" 改成 "reconcile + trd_cfm 两条路径"。
- WebSocket 频道 `position_update` / `asset_update` **不再有消息**。**BREAKING**: 任何依赖该频道的下游需迁移至定时调 `/api/holdings` 与 `/api/asset`。
- RPC `qry_pos` 响应字段名变更: `volume` → `vol`,`avl_amt` → `avl_vol`,`avg_price` → `cost_price`,`market_value` 字段消失。**BREAKING**: 任何直接读 parser 输出的代码 (`reconcile.py`) 需迁移。
- RPC `qry_ast` 响应字段名不变 (Asset 级 broker 名 = DB 名,无漂移)。

**依赖关系**:

```
parser 字段重命名 (T1)
   ↓
reconcile 删 remap (T2)
   ↓
   └── trd_cfm 增加 Position 增量 (T4) — 独立可做,但推荐先 T2 让 DB 状态稳定

push handler 删除 (T3) — 完全独立,任意顺序
       ↓
       ├── 测试更新 (T5)
       └── 前端清理 (T6) + 文档 (T7)
```

**留待 Change B 处理** (本次 out of scope):

- Asset 日内 stale (cash/frozen_cash 不在 trd_cfm 中更新)
- 新表 `cash_ledger` 流水
- POST /place 冻结资金
- DELETE /cancel 解冻资金
- broker JUNK 解冻
