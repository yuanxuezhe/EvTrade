# frontend delta — status 字典统一到 broker xtconstant

## MODIFIED Requirements

### Requirement: REQ-FE-006 委托 status 本地推断（v11 broker 字典对齐）

`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数 MUST 与 `server/services/order_status.py:_infer_order_status` **逐行一致**，输出码全集 {50, 53, 54, 55, 56}（全是 broker xtconstant 码，无本地扩展）。

#### Scenario: 推断输出码全集是 broker 码

- **WHEN** order.volume=100, traded_volume=50, cancelled_volume=0, status='50'
- **THEN** inferOrderStatus 输出 '55'（broker 部成），不是本地推断码 50

#### Scenario: 终态保持（含 broker 52）

- **WHEN** order.status='52'（broker 部成待撤）
- **THEN** inferOrderStatus 保持 '52'

#### Scenario: 视图层按 broker 字典分组

- **WHEN** Trade.vue 显示今日委托表
- **THEN** `_PENDING_NUMERIC` 包含 {48, 49, 50}（broker 未报/待报/已报）
- **AND** `_FILLED_NUMERIC` 包含 {55, 56, 54}（broker 部成/已成/已撤）
- **AND** `_PARTIAL_CANCEL_NUMERIC` 包含 {53}（broker 部成部撤）

### Requirement: REQ-FE-009.9 前端独立计算委托 / 成交缓存（v11 broker 码）

ws 推送的 trd_cfm payload 仅含当前笔 trade 字段；前端 holdings store 缓存层 MUST 独立维护 `orders.status`（调 `inferOrderStatus(order, null)` 本地推断），与后端 `_infer_order_status` 镜像，输出 broker 码。

#### Scenario: 增量累计 status 输出 broker 码

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='50'（broker 已报）
- **AND** applyTradePush 收到 volume=30 的新成交
- **THEN** recomputeOrderFromTrade 累计后 order.status='55'（broker 部成）

#### Scenario: cancel-row 反向抹平后 status 输出 broker 码

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='55'（broker 部成）
- **AND** applyOrderPush 收到 cancel-row (order_flag=1) 反向抹平 cancelled_volume=100
- **THEN** 反向抹平后 order.status='53'（broker 部成部撤），不是本地推断码 56

### Requirement: REQ-FE-009.5 撤单审计行（cancel-row）短路（v11 修订 status 码）

`holdings.applyOrderPush(row, action)` MUST 在 `row.order_flag === 1` 时直接 merge + return, 不走 `_recomputeStatus`。cancel-row 的 `status` MUST 由 DELETE 端点全权管理（broker 54=已撤 / broker 57=废单, v11 修订）。

#### Scenario: cancel-row status 短路（v11 修订）

- **WHEN** applyOrderPush 收到 order_flag=1 的 cancel-row，row.status='54'（broker 已撤）
- **THEN** 直接 merge 到 orders.value，不调 inferOrderStatus
- **AND** 视图层 Trade.vue / Orders.vue 显示「类型=撤单」标签（cancel-row 守卫）

### Requirement: REQ-FE-009.9.1 前端 helper 工具函数（v11 输出码全集 broker 码）

`client/src/utils/orderCalc.js` MUST 提供的 helper 函数输出 broker 码:
- `normalizeTrade(trade)`：返回 `{...trade, amount: price × volume}`
- `recomputeOrderFromTrade(order, trade)`：返回基于单笔 trade 增量累计的新 order 对象（含 status 推断, 输出 broker 码）
- `metaMerge(row, ref)`：返回仅覆盖 PK + 元数据、保留 ref 计算字段的合并结果
- `flattenCancelledByRow(row, orders)`：cancel-row 触发的反向抹平逻辑

#### Scenario: recomputeOrderFromTrade 输出 broker 码

- **WHEN** order.volume=100, traded_volume=0, trade.volume=30
- **THEN** 返回新 order 的 status='55'（broker 部成），不是本地推断码 50

#### Scenario: flattenCancelledByRow 触发 broker 53

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='55'（broker 部成）
- **AND** cancel-row 反向抹平 cancelled_volume=100
- **THEN** 返回新 order 的 status='53'（broker 部成部撤），不是本地推断码 56

## REMOVED Requirements

### Requirement: 前端 fall-back 兼容 key（unreported / filled / cancelled 等英文 key）

**Reason**:
- 14 个英文 fall-back key（`unreported` / `pending_report` / `reported` / `reported_cancel` / `partial_pending_cancel` / `partial_cancelled` / `cancelled` / `partial` / `filled` / `rejected` / `unknown` / `pending` 等）是历史 in-memory 状态遗留
- `grep -rE "STATUS_LABEL\['(unreported|pending_report|reported|...)\]'\]" client/src/` 0 处外部引用
- 与 broker xtconstant 字典对齐后无业务价值（broker 字典只有数字字符串 key）
- 1-2 年前遗留，无第三方引用，删 0 风险

**Migration**:
- 删除 `client/src/utils/format.js` 的 `STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 5 张字典中所有英文 fall-back key 段
- 仅保留 broker xtconstant 字典 11 条（48-57 + 255）
- 视图层（Trade.vue / Orders.vue / TradeStatusBadge.vue）只读 5 张字典的 broker 码 key，不读英文 fall-back key

#### Scenario: 删除 fall-back 兼容 key

- **WHEN** 静态扫 `client/src/utils/format.js`
- **THEN** `STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 5 张字典只含 11 条 broker xtconstant 码 (48-57 + 255)
- **AND** 14 个英文 fall-back key (unreported / pending_report / reported / ...) 全部删除

## ADDED Requirements

### Requirement: 前端 5 张字典按 broker 义重映射（v11）

`STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` / `STATUS_OPTIONS` MUST 按 broker xtconstant 字典义重映射。

#### Scenario: STATUS_LABEL 按 broker 义（v11 新增）

- **WHEN** 视图层渲染订单状态
- **THEN** `STATUS_LABEL['54']` = '已撤'（broker CANCELED）
- **AND** `STATUS_LABEL['57']` = '废单'（broker JUNK）
- **AND** `STATUS_LABEL['53']` = '部成部撤'（broker PART_CANCEL）
- **AND** `STATUS_LABEL['55']` = '部成'（broker PART_SUCC）
- **AND** `STATUS_LABEL['56']` = '已成'（broker SUCCEEDED）

#### Scenario: STATUS_OPTIONS 按 broker 字典顺序（v11 新增）

- **WHEN** Trade.vue / Orders.vue 渲染状态过滤下拉
- **THEN** STATUS_OPTIONS 按 broker 字典顺序：48→待报 / 49→待报 / 50→已报 / 51→已报待撤 / 52→部成待撤 / 53→部成部撤 / 54→已撤 / 55→部成 / 56→已成 / 57→废单 / 255→未知

#### Scenario: STATUS_PULSE 中间态脉冲（v11 新增）

- **WHEN** 视图层渲染订单状态
- **THEN** 48/49/50/51/52/55 等中间态 MUST 有脉冲动画（true）
- **AND** 53/54/56/57/255 等终态 MUST 无脉冲动画（false）

## 备注

- 前端 commit 4 与后端 commit 2/3 必须同次部署（同 release tag），否则前端字典 broker 码 vs 后端本地码不一致 → 视图层显示错位
- 部署前 grep 自检：`grep -rE "status.*===.*'(49|50|51|53|56)'" client/src/views/` 应只命中 `archive/` 目录
- 测试覆盖：`vitest client/tests/utils/orderCalc.test.js` 32 个 status 用例 + `client/tests/stores/holdings.test.js` 5 个 status 集成用例, 共 52 处 JS 断言改 broker 码

## 勘误历史

- 2026-07-02 v11: status 字典统一到 broker xtconstant (align-status-codes-to-xtconstant)
  - `inferOrderStatus` 输出码全集 {50, 53, 54, 55, 56} 改 broker 码
  - `recomputeOrderFromTrade` / `flattenCancelledByRow` / `metaMerge` 输出码全集 broker 码
  - 5 张字典 + `STATUS_OPTIONS` 按 broker 义重映射
  - 14 个英文 fall-back 兼容 key 全部删除
  - cancel-row 短路 status 改 broker 码 (54/57)