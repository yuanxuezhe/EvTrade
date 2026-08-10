# docs/ 目录索引

> `docs/` 是 OpenSpec 接管前的**静态沉淀**。本目录的边界约定参见 [openspec/specs/dev-process-control/spec.md §"文档目录双体系约定"](../openspec/specs/dev-process-control/spec.md)。

## API 契约（2026-06-29 新增）

| 文档 | 范围 | 何时查阅 |
|---|---|---|
| [xtquant-rpc.md](xtquant-rpc.md) | QMT 柜台的 6 个 RPC 接口（4 查询 + 2 写）+ 8 类 broker push | 排查 broker ↔ server 通信、对账字段映射 |
| [server-rest-api.md](server-rest-api.md) | FastAPI 全部 REST 端点（auth/users/orders/admin/positions/...） | 前端联调、新人 onboarding |
| [ws-push.md](ws-push.md) | 4 个 WS 频道 + payload 字段 + 心跳协议 | 前端订阅推送、调试推送状态机 |
| [msgpacket-python-api.md](msgpacket-python-api.md) | msgpacket 库的 Python API 速查（外部依赖） | 排查 msgpacket 协议层 |

## 策略指南

| 文档 | 范围 | 何时查阅 |
|---|---|---|
| [strategy_trading_guide.md](strategy_trading_guide.md) | 网格策略 / T0 策略的创建、风控、实盘使用 | 用户配置策略、排查触发/下单 |
| [strategy-migration-v90-to-bt.md](strategy-migration-v90-to-bt.md) | v90 用户脚本 → Backtrader（strategy_exec）迁移指南 + 3 个例子 | 迁移旧脚本、写新 Backtrader 策略 |

## 历史与设计

| 目录 | 内容 | 何时查阅 |
|---|---|---|
| [specs-history/](specs-history/) | OpenSpec 立项前沉淀的 spec 演进（4 份：P0 sprint + T0 v1/v2/v3）。OpenSpec **未接管**这些文件 | 追溯某能力的"早期决策"或"被覆盖前版本" |
| [designs/plans/](designs/plans/) | 阶段性大型实施的实施计划（2 份：Vue 交易系统 / holdings 查询） | 回顾大块功能的实施路径 |
| [designs/specs/](designs/specs/) | 与 plans 配对的设计文档 | 同上 |

## 与 OpenSpec 的关系

- 本目录承载**已沉淀的细节**：接口字段、阶段设计、历史 spec
- [../openspec/](../openspec/) 承载**活工作流**：当前 spec 真相源 + 变更追踪
- 改代码前先看 [../openspec/AGENTS.md](../openspec/AGENTS.md) §步骤 0

## 维护规则

1. **新增 API 文档**：使用本文档的"API 契约"段；字段名直接抄代码（v10 broker 原字段名），不发明
2. **新增阶段性设计**：放入 [designs/](designs/)，文件名带 `YYYY-MM-DD-` 前缀
3. **被覆盖的 spec**：保留在 [specs-history/](specs-history/)，**不删除**——spec 演进史是"为什么这样决策"的证据
4. **代码引用**：每节末尾用 `// 权威源: file:line` 标注，方便 review 时核对
