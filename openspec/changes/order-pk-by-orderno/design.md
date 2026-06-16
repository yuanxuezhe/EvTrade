## Context

`orders` 表当前复合主键 `(trd_date, order_id)`,broker 真实 `order_id` 下单时不可知,代码用 `PENDING-{order_no}` 占位 (`server/api/orders.py:144`) + 删-插交换 (L191-213) 强行绕过,产生 PENDING 漏更新 / trd_cfm 找不到 Order 等 bug(commit 8414425 即是修这类问题)。

`Order.status` 字段直接抄 broker ord_cfm 推的 status,客户端边界态(部成 / 部成部撤)展示完全依赖 broker 推得准,broker 漏推 / 推错会污染前端。

`trd_cfm` 推送按 broker `order_id` 查本地 Order,需要 ord_cfm 先到把 `order_id` 填好,否则永远找不到,只能靠 PENDING- 占位糊过去。

## Goals / Non-Goals

**Goals:**
- 委托主表主键改为 `(trd_date, order_no)`,`order_id` 改可空,broker 推送到达再写入
- 彻底删除 PENDING- 占位 + 删-插交换,DB 不再出现 `PENDING-*` 字符串
- `trd_cfm` 用 broker 透传的 `remark` (= `order_no`) 匹配 Order,不再依赖 broker `order_id`
- `Order.status` 改为本地推断(累计成交 + 撤单信号),不再直接抄 broker
- 撤单 endpoint 改用 `order_no`,broker `order_id` 不可用时返回 409

**Non-Goals:**
- 不引入新的 schema 字段(如 `broker_status` 等"内部信号"字段)— 用现有 `status` 字段的"本地推断"语义覆盖所有场景
- 不做生产数据迁移脚本(无 Alembic),dev 期 `rm evtrade.db` 重建,生产由用户自行处理
- 不改 `Trade.order_id` 字段含义(仍存 broker 推的 order_id,便于以后做 trade→broker 反查)
- 不重构 `t0_stats` / `holdings` / `reconcile` 等下游消费逻辑(它们不查 Order.order_id)

## Decisions

### Decision 1: PK 选 `(trd_date, order_no)` 而不是 `(trd_date, order_id)`

**理由:**
- `order_no` 是本地原子 8 位序列,`server/services/order_no.py` 自主生成,稳定可预测
- `order_id` 是 broker 系统生成的外部 ID,broker 协议变更或号段冲突都会影响
- `order_no` 下单即知,`order_id` 必须等 broker 回报才有
- `client_order_id` 是幂等键,用户可指定,不适合做主键

**替代方案考虑:** 用 `client_order_id` 做 PK — 拒绝,幂等键应可复用,PK 应稳定。

### Decision 2: `status` 字段单义化为"本地推断的委托状态",不新增内部信号字段

**理由:**
- 简化 schema:不引入 `broker_status` / `last_broker_status` 等冗余字段
- `status` 字段含义由 "broker 推的数字码" 升级为 "本系统判定的委托状态"
- 推断函数 `_infer_order_status(order, broker_status=None)` 在 ord_cfm 到达时把 broker 推的 status 作为**临时参数**传入,不持久化

**替代方案考虑:** 新增 `broker_status` 列做"内部信号保留" — 拒绝,用户明确表示"不加字段,复用 status"。

### Decision 3: 推断函数的"终态保护"机制

**理由:**
- broker 撤单后理论上不再推 trd_cfm,但实际偶有"已撤单后又成交一笔"的乱序
- 终态(51/52/53/54/55/56)被 ord_cfm 写入后,后续 trd_cfm 累计不应再覆盖
- 实现:`_infer_order_status` 第一步检查 `order.status` 若是终态直接 return 当前值

**反例:** 不加保护,broker 推 ord_cfm status=53 → 本地 status=53;然后 trd_cfm 累计一笔 → status 被覆盖成 50(部成),前端误以为还没撤。

### Decision 4: 撤单路由从 `/{order_id}` 改为 `/{order_no}`

**理由:**
- `order_no` 下单即知,broker 没回报前也能查到 Order
- 内部用查到的 `order.order_id` 调 RPC,broker 协议层契约不变
- `order_id` 尚未到达时返回 409 `BROKER_NOT_READY`(理论上不应触发,因为 broker 没回报=broker 不知道此单,无法撤)

**替代方案考虑:** 保持 `/{order_id}` 路由 + 等 broker 回报后才能撤 — 不行,下单后立刻撤(高频场景)会被阻塞。

### Decision 5: `trd_cfm` 用 `remark` 匹配 Order,不用 `order_id`

**理由:**
- `remark` 字段是 broker 必然透传的(下单时送 `remark=order_no`,broker 在 ord_cfm 原样返回)
- broker 协议里 trd_cfm 也应同样透传 `remark`(**前提条件**,需 broker 端确认)
- 用 `remark`(= `order_no`)查 Order 完全不依赖 broker `order_id`,ord_cfm / trd_cfm 谁先到都行

**兜底:** 如果 broker trd_cfm 实际没送 `remark`,退化到用 `order_id` 查(`push_handlers.py` L169 旧逻辑),找不到打 WARN。这是次优路径,主路径是 `remark`。

**替代方案考虑:** trd_cfm 也用 `order_id` 查,要求 ord_cfm 必须先到 — 拒绝,这就是现状的痛点。

### Decision 6: 无 Alembic,dev 期 `rm evtrade.db` 重建

**理由:**
- 项目无 Alembic / 迁移框架(`kb/server/03_db_models.md:137`)
- dev 期惯例:删 DB 重建可接受
- 生产需手工 `ALTER TABLE` 或新装,本次不提供迁移脚本

**风险:** 生产数据丢失。用户已确认 dev 期操作。

## Risks / Trade-offs

- **[R1] broker trd_cfm 实际不送 `remark` 字段** → 退化到 `order_id` 查找,需要 ord_cfm 先到(回到当前痛点)
  - **Mitigation:** 上线前与 broker 方确认协议;在 push_handlers.py 加 `[trd_cfm] WARN: no remark, fallback to order_id` 日志,监控出现频率

- **[R2] 旧的 `PENDING-*` 占位数据残留** → 删 DB 重建会丢失所有未完成委托
  - **Mitigation:** dev 期可接受,生产期 `rm evtrade.db` 前需 dump 关键状态机

- **[R3] 前端需要同步改** → 撤单 URL 参数从 `order_id` 改为 `order_no`;`order_id` 字段空串语义
  - **Mitigation:** 修改后立即通知前端;`OrderOut.order_id` 默认 `""` 在 Pydantic schema 显式声明,前端 TypeScript 类型同步

- **[R4] status 推断的边界场景** — broker 推 ord_cfm status=49(已报)时本地累计=0,推断也是 49;若 broker 推 48(待报)且累计=0,推断本地 = 49(已报)。如果 broker 业务上"48 → 49"中间有真实状态(比如"待确认"),会被本地吞掉
  - **Mitigation:** 接受,本地"已报" 涵盖 broker 48/49 两种语义。如需细分,把推断函数加 case

- **[R5] ord_cfm handler 不再累计 traded_volume,完全依赖 trd_cfm** — 如果 broker 只推 ord_cfm 不推 trd_cfm(全成单,某些 broker 行为),traded_volume 不会更新
  - **Mitigation:** 在 ord_cfm handler 里读 broker 推的 `traded_volume` 字段,如果 > 0 也累计(防御性);trd_cfm 仍是主路径

- **[R6] 终态保护可能让"已部成"误显示** — 假设 broker 推 ord_cfm status=53(已撤)时本地累计=0,推断 53(已撤);若 broker 后续又推一笔 trd_cfm,本地累计=100,status 应是 56(部成部撤)但被终态保护卡在 53
  - **Mitigation:** 这是用户接受的简化;实际场景 broker 撤单后极少再推 trd_cfm

## Migration Plan

dev 期:
1. `rm server/evtrade.db` — 删旧 DB
2. `python scripts/evctl.py restart backend` — 重建 schema
3. 实施代码改动(`/opsx:apply` 流程)
4. `python -m pytest server/test_models.py server/test_orders_api.py server/test_push_handlers.py -v`
5. 手动 e2e 验证(见 proposal)
6. `git commit` + `git push`

生产期(用户自行处理,不提供脚本):
- 备份 `evtrade.db`
- 手工 `ALTER TABLE orders DROP PRIMARY KEY, ADD PRIMARY KEY (trd_date, order_no)`
- 手工 `ALTER TABLE orders MODIFY order_id VARCHAR(64) NULL`
- 手工 `ALTER TABLE orders DROP INDEX uq_orders_order_no, ADD UNIQUE KEY uq_orders_broker_id (order_id, trd_date)`
- 手工 `ALTER TABLE orders ADD INDEX ix_orders_order_id (order_id)`
- 应用代码切换

回滚策略: dev 期 `git revert` + 删 DB 重建。生产期代码回滚 + DB 还原备份。

## Open Questions

- 实施时是否真的需要 broker 端确认 `trd_cfm.remark` 字段?若 broker 实际不送,需要 broker 方协调改协议
- 前端 `OrderOut.order_id` 空串语义的对接,需要同步前端 PR
- 测试 `test_push_handlers.py` 中 PENDING- 相关的几条测试需要重写,具体重写策略实施时确定
