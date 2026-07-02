## Why

委托 `status` 字段当前有 3 套互相冲突的字典:
1. `server/services/order_status.py:Status._LABEL` (broker 原始码残留, 死代码)
2. `server/services/order_status.py:ORDER_STATUS` (legacy 模块级, 实际被 `_status_msg` 使用)
3. `client/src/utils/format.js:STATUS_LABEL` (前端, 与 #2 一致)

业务写入点 (place.py / cancel.py / ord.py) 用的是第 2 套"本地推断"码 (53=已撤 / 55=废单 / 56=部成部撤), 而 broker (xtquant/xtconstant) 的标准字典是 (54=已撤 / 57=废单 / 53=部成部撤) — 数字空间相互错位, 跟 broker 协议对不齐。

`_infer_order_status` 函数也产出一套本地码 (49/50/51/53/56), 跟 broker 字典不一一对应, 但 spec/注释没有把"broker 码 → 本地码"的重映射关系写出来, 读者看到 51 不知道是 broker "已报待撤" 还是本地 "已成"。

本次 change 把**全栈 status 字典统一到 broker xtconstant 权威字典**:

| 码 | xtconstant 常量 | 中文 |
|---|---|---|
| 48 | ORDER_UNREPORTED | 未报 |
| 49 | ORDER_WAIT_REPORTING | 待报 |
| 50 | ORDER_REPORTED | 已报 |
| 51 | ORDER_REPORTED_CANCEL | 已报待撤 |
| 52 | ORDER_PARTSUCC_CANCEL | 部成待撤 |
| 53 | ORDER_PART_CANCEL | 部成部撤 |
| 54 | ORDER_CANCELED | 已撤 |
| 55 | ORDER_PART_SUCC | 部成 |
| 56 | ORDER_SUCCEEDED | 已成 |
| 57 | ORDER_JUNK | 废单 |
| 255 | ORDER_UNKNOWN | 未知 |

业务写入点与 `_infer_order_status` 输出码全部改为 broker 码, 前端 5 张展示字典同步, 测试 140 处断言改码, 历史 DB 数据一次性 backfill。

**码值一一对应** (无本地扩展):
- 本地 49 (已报) → broker 50
- 本地 50 (部成) → broker 55
- 本地 51 (已成) → broker 56
- 本地 53 (已撤) → broker 54
- 本地 56 (部成部撤) → broker 53 (注意: 不是 broker 56, broker 56 已是"已成")

## What Changes

- **后端核心模块 `server/services/order_status.py` 重构**:
  - 删 `Status._LABEL` 死代码 (整个项目 0 处 `Status.label()` 调用)
  - 删 `Status` 类的英文常量 (`PARTIAL_CANCEL` / `FILLED` / `REJECTED` / `CANCELLED` / `PARTIAL_CANCEL2`) — 0 处引用
  - `ORDER_STATUS` 改为 broker xtconstant 字典 (11 条: 48-57, 255)
  - `TERMINAL_STATUSES` 从 `('51','52','53','54','55','56')` 改为 `('52','53','54','55','56','57')` (broker 终态: 52=部成待撤 过渡, 53=部成部撤, 54=已撤, 55=部成, 56=已成, 57=废单; 51=已报待撤 也算过渡, 决策点 #2)
  - `_infer_order_status` 输出码改: 49→50 / 50→55 / 51→56 / 53→54 / 56→53, 新 5 码全集 {50, 53, 54, 55, 56}
  - `Status.is_cancellable` 触发码从 `("48","49")` 改为 `("48","49","50")` (含 broker 50=已报 也可撤)
- **业务写入点改固定码** (**BREAKING** for downstream):
  - `server/api/orders/place.py:90` 拒单 status `"55"` → `"57"`
  - `server/api/orders/place.py:110` RPC 成功 status `"49"` → `"50"`
  - `server/api/orders/place.py:113` RPC 拒单 status `"55"` → `"57"`
  - `server/api/orders/cancel.py:74` cancel-row 起手 status `"48"` → `"48"` (保留 sentinel, 见决策点 #1)
  - `server/api/orders/cancel.py:115` DELETE 成功 status `"53"` → `"54"`
  - `server/api/orders/cancel.py:144` DELETE 失败 status `"55"` → `"57"`
  - `server/api/orders/cancel.py:61` pre-check `if order.status not in ("48","49")` → `("48","49","50")` (含 broker 50=已报)
  - `server/services/push/ord.py:75` R2b 触发条件 `broker_status in ('53','55')` → `('52','53','54','55','56','57')` (broker 全部终态)
  - `server/services/push/ord.py:85` rule 3 触发 `broker_status in ('52','53','54')` → `('51','52','53','54')` (broker 撤单类: 51=已报待撤, 52=部成待撤, 53=部成部撤, 54=已撤)
- **前端 `client/src/utils/format.js` 5 张字典同步** (**BREAKING** for UI):
  - `STATUS_LABEL` 改 broker 字典 (11 条)
  - `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 按 broker 义重映射
  - `STATUS_OPTIONS` (下拉) 按 broker 字典顺序
  - `inferOrderStatus` 输出码改: 49→50 / 50→55 / 51→56 / 53→54 / 56→53 (与后端镜像一致)
  - 删历史 fall-back 兼容 key (`unreported` / `pending_report` / `reported` / `filled` / `cancelled` 等) — 0 处外部引用
- **测试断言改码** (140 处, 不影响契约, 仅数值):
  - `tests/server/services/push/test_handlers.py` 11 个 `_infer_order_status` 矩阵用例
  - `tests/server/api/orders/test_cancel.py` / `test_place.py` / `test_query.py` / `test_t0_aggregate.py` (~50 处)
  - `client/tests/utils/orderCalc.test.js` 32 个 status 断言
  - `client/tests/stores/holdings.test.js` 5 个 status 断言
- **DB 历史 backfill** (新 tracking issue 记录, 不在线执行):
  - `UPDATE orders SET status = '54' WHERE status = '53' AND order_flag = 1` (cancel-row 已撤)
  - `UPDATE orders SET status = '57' WHERE status = '55'`
  - `UPDATE orders SET status = '56' WHERE status = '51'`
  - `UPDATE orders SET status = '55' WHERE status = '50'`
  - `UPDATE orders SET status = '50' WHERE status = '49'`
  - `UPDATE orders SET status = '53' WHERE status = '56'` (本地 部成部撤 → broker 部成部撤)
  - 48 (sentinel) 不动
- **spec 同步**:
  - `openspec/specs/data-model/spec.md` §1 业务规则段 + 列注释
  - `openspec/specs/push/spec.md` REQ-PUSH-005 + REQ-PUSH-030 + Scenario 例子
  - `openspec/specs/frontend/spec.md` REQ-FE-009.9 推断规则段
  - 删 `openspec/specs/frontend/spec.md` 中 fall-back 兼容 key 的描述

## Capabilities

### New Capabilities

无 (字典对齐属于修改既有 capability, 不引入新 capability)

### Modified Capabilities

- `data-model`: `orders.status` 字段业务规则改, 字典从"本地推断语义"换成"broker xtconstant 权威字典"
- `push`: REQ-PUSH-005 (本地推断输出码) 改 broker 码; REQ-PUSH-030 (broker 字段名对齐) 加 "broker 原始码语义" 文档段
- `frontend`: REQ-FE-009.9 (前端独立计算) 的 status 推断规则改 broker 码
- `rpc-protocol`: §1 broker status 字段映射表加 "xtconstant 码→中文" 重映射段
- `trading`: REQ-TRADE-003 (DELETE 端点 5 步流程) 撤单 status 写入点改 broker 码

## Impact

**代码影响 (5 类写入路径 + 共享模块 + 5 张前端字典)**:
- 后端: `server/services/order_status.py` (核心) / `server/api/orders/place.py` / `server/api/orders/cancel.py` / `server/services/push/ord.py` / `server/models/orm.py:78` (列注释)
- 前端: `client/src/utils/format.js` (5 张字典 + inferOrderStatus) / `client/src/utils/orderCalc.js` (间接, 调 inferOrderStatus) / `client/src/stores/*.js` (间接)
- 测试: 88 处 Python + 52 处 JS = **140 处 status 断言改码值**

**数据影响 (历史 DB backfill)**:
- dry-run: 当前 dev DB 仅 1 行需改 (status=53 cancel-row → 54)
- 生产规模未知, backfill SQL 6 条, 一次写完
- backfill 单独开 tracking issue (`openspec/tracking/2026-XX-XX-status-backfill/`), 不在线执行

**下游影响 (BREAKING)**:
- DB 中 `orders.status` 数字含义变化, 下游报表/分析需跟着调整
- WS `order_update` 推的 `status` 字段值变化, 前端 v0.x.x 兼容旧版有风险
- 跨系统对账 (broker 推回的 order_status 与本地存的 status) 现在可以直接用同一字典, 不再需要翻译

**与刚归档的 `system-delegation-price-fill-calc` 关系**:
- 那个 change 的 3 处固定 status 码 (`place.py:113` / `cancel.py:115` / `cancel.py:144`) 在本 change 同步改 broker 码
- `_infer_order_status` 输出码变化不影响 cancelled_volume 抹平逻辑 (那个逻辑只读 `cancelled_volume` 数值, 不看 status)
- `cancelled_volume = volume` 抹平触发条件仍由 `cancelled_volume` 数值驱动, 不依赖 status
- 5 类 cancelled_volume 写入路径 (R1/R2a/R2b/R4) 路径不变, 只是出口 status 码值变

## 决策点 (review 时需确认)

1. **cancel-row 起手 status (cancel.py:74)**: 保留 `"48"` (sentinel=未报) 还是改成 `"49"` (待报)? — sentinel 语义本地私有, broker 字典里 48/49 都行
2. **TERMINAL_STATUSES 是否含 52 (部成待撤)**: 严格按 broker, 52 是"过渡态"非终态, 应排除; 但本项目里 52 不在推断输出码 (推断只产 50/53/54/55/56), 留着只是为兼容 broker 推 52 进来时不被锁死; 建议保留 (与 broker 一致)
3. **fall-back 兼容 key (`unreported` / `filled` 等英文 key)**: 删 (0 处引用) 还是保留 (前端用了 1-2 年, 第三方可能引用)
4. **历史 backfill 时机**: 跟 trades.amount backfill 一起组"维护窗口" 一次执行, 还是分两次
5. **commit 粒度**: 建议 5 commit (spec → 后端核心 → 业务写入点 → 前端 → 测试 + backfill) — 跟 `feedback_commit_granularity` memory 一致