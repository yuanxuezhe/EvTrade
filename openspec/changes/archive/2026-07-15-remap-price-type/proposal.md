# 2026-07-15-remap-price-type — 价格类型协议重对齐

## Why

历史 `price_type` 字段码点（5/11/14/44）源自 xtquant 早期手填约定，**与 xtconstant 柜台常量不对齐**，造成两端需 `price_type_map` 反复映射，且码点语义重叠（11=指定价/限价 vs 14=挂单价/对手价 都是"限价"类），业务上 4 选给 trader 增加认知负担（实际只需要 3 选）。

用户原话 (2026-07-15): "重新设计价格类型方案：
- 限价  0：xtconstant.FIX_PRICE
- 最新价 1：xtconstant.LATEST_PRICE
- 市价  2：xtconstant.MARKET_PEER_PRICE_FIRST"

## What Changes

将价格类型从 **4 选 (5/11/14/44)** 重构为 **3 选 (0/1/2)**, 与 `xtconstant` 柜台常量 1:1 对齐:

| 旧码点 | 新码点 | 语义 | xtconstant 常量 | UI 标签 |
|---|---|---|---|---|
| 11 (指定价) | 0 | 限价 | `FIX_PRICE` | "限价" |
| 14 (挂单价/对手价) | 0 | 限价 | `FIX_PRICE` | "限价" |
| 5 (最新价) | 1 | 最新价 | `LATEST_PRICE` | "最新价" |
| 44 (市价) | 2 | 市价 (对手方最优价, 吃档 1) | `MARKET_PEER_PRICE_FIRST` | "市价" |

### 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 前端枚举 | `client/src/constants/priceType.js` | 重写 `PriceType={FIX_PRICE:0, LATEST_PRICE:1, MARKET_PEER_PRICE_FIRST:2}` + `priceTypeOptions` 3 项 |
| 前端组件 | `client/src/components/OrderForm.vue` | 8 处 `PriceType.OPPONENT` → `PriceType.FIX_PRICE` (输入框禁用/校验/默认/外部应用/提交校验) |
| 后端枚举 | `server/enums/trading.py` | `PriceType` 类重写（`FIX_PRICE=0`, `LATEST_PRICE=1`, `MARKET_PEER_PRICE_FIRST=2`），`_LABEL` 重映射 |
| API schema | `server/api/orders/schemas.py` | `PlaceOrderRequest.price_type default` → `PriceType.FIX_PRICE` |
| ORM | `server/models/orm.py` | `orders.price_type` 列 `default=11` → `default=0` |
| 业务代码 | `server/services/strategy/engine.py` | T0 策略下单两处 `price_type=11` → `PriceType.FIX_PRICE` |
| 测试 | `server/tests/strategy/test_t0_endpoint_migration.py` | `_mk_order` 工厂 `price_type=11` → `PriceType.FIX_PRICE` |
| 迁移脚本 | `server/migrations/2026-07-15-remap-price-type.py` | **新增**：幂等 UPDATE 历史 orders.price_type 11/14→0, 5→1, 44→2 |
| 柜台映射 | `iquant/xtquant_api.py` | `price_type_map` 加 `"2" → MARKET_PEER_PRICE_FIRST` |
| OpenSpec | `openspec/specs/trading/spec.md` | REQ-TRADE-002 码点表 + S-TRADE-001 示例 |
| OpenSpec | `openspec/specs/frontend/spec.md` | REQ-FE-010 + 数据绑定场景 FIX_PRICE |
| OpenSpec | `openspec/specs/data-model/spec.md` | orders 表 price_type 列 default + 注释 |
| REST API 文档 | `docs/server-rest-api.md` | POST /api/orders/place price_type 字段说明 |

### 历史订单数据迁移

迁移脚本 `2026-07-15-remap-price-type.py`:
- `before/after` 双快照 + 完整性校验（不允许 0/1/2 之外的码点）
- 幂等：第 N 次跑只会匹配剩余未迁移的行, 重复运行 = no-op
- 前置校验：检查 `orders` 表 + `price_type` 列存在
- 末尾对账：迁移前/后总行数必须一致

### 不在范围内

- ❌ **不回滚** 上一轮 commit `ca4f645`（"隐藏 LIMIT 按钮"）—— 本次为覆盖性重构, 前端 4→3 按钮在 `b326eb7` 直接落 3 项
- ❌ **不动** xtconstant 常量本身 (柜台侧 Python 枚举, 由 xtquant 维护)
- ❌ **不动** broker 推送 handler / WS payload / 行情 stores
- ❌ **不动** main.css / HoldingsPanel.vue / Trade.vue 等 uncommitted 文件（"范围蔓延禁止"）

## 落地约束

- ✅ 与 OpenSpec 工作流一致：先改 spec.md → 再写代码 → 再写 spec-deltas → 归档
- ✅ 4 commit 按层拆（v6 纪律）
- ✅ 迁移脚本幂等性 + 完整性校验
- ✅ 后端 silent fallback 禁用：未知码点保留原值 + 校验报错（不静默转 0）
- ✅ 浏览器实测 + vision 截图（用户硬性偏好 #7）
- ✅ 不自动 push（用户硬性偏好）

## 关联

- 上游 commit：`ca4f645` (UI "挂单价"→"限价" + 隐藏 LIMIT 按钮 4→3 项)
- 本次覆盖：`b326eb7`, `df0423e`, `7ffc11a`, (本次 commit 4)
- 知识库参考：`openspec/specs/trading/spec.md` §REQ-TRADE-002, `openspec/specs/data-model/spec.md` §13 orders 表