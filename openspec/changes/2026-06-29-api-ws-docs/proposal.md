# docs/ API 文档补全

> 创建日期：2026-06-29
> 状态：draft
> 范围：[docs/](../../docs/) 顶层新增 4 份 API 参考

## Why

代码层接口（QMT RPC、FastAPI REST、WebSocket 推送）已稳定，但**契约面没有专门文档**：
- 新人 onboarding 只能从代码里"反查"出入参
- 跨服务（broker / server / frontend）调试时缺乏权威来源
- 之前 `docs/msgpacket-python-api.md` 写了 msgpacket 库的 Python API，但**没写 EvTrade 自己在 broker / server / ws 三层的实际接口**

## What

在 [docs/](../../docs/) 顶层新增 4 份 Markdown，**纯静态参考，不替代 OpenSpec specs 的真相源**：

| 文档 | 覆盖范围 | 权威源 |
|---|---|---|
| [docs/xtquant-rpc.md](../../docs/xtquant-rpc.md) | 6 个 QMT RPC 接口（4 查询 + 2 写）+ 6 类 push | [iquant/xtquant_api.py](../../iquant/xtquant_api.py) |
| [docs/server-rest-api.md](../../docs/server-rest-api.md) | 全部 FastAPI 端点（auth/users/orders/admin/positions/...） | [server/api/](../../server/api/) + [server/rpc/handlers.py](../../server/rpc/handlers.py) |
| [docs/ws-push.md](../../docs/ws-push.md) | 4 个 WS 频道 + payload 字段 + 心跳协议 | [server/ws/](../../server/ws/) + [server/rpc/transport.py](../../server/rpc/transport.py) |
| [docs/index.md](../../docs/index.md) | docs/ 目录索引（已含 designs/ / specs-history/ / 4 份 API 文档） | 新增 |

## 文档编写原则

1. **真实字段**：所有字段名直接抄代码（v10 broker 原字段名：order_status / order_volume / traded_id / avl_amt / avg_price / frozen_cash），不发明、不简写
2. **真实路由**：所有 URL 路径抄 [server/main.py](../../server/main.py) 的 include_router，HTTP 方法 + 路径 + 鉴权要求
3. **真实响应**：所有响应字段抄 Pydantic schema
4. **真实 WS payload**：抄 [server/rpc/transport.py:251-274](../../server/rpc/transport.py) 的 `payload = {type, channel, ts, data}` + enriched_row 字段
5. **代码引用**：每节末尾用 `// 权威源: file:line` 形式标注
6. **不写"应做"**：不写"未来要 X 字段"——只反映已实现的接口
7. **不重复 OpenSpec**：spec 描述的是"能力"（"system SHALL ..."），本文档描述的是"已实现接口的契约"

## 不做什么

- 不动 `docs/msgpacket-python-api.md`（msgpacket 库 API 速查，独立专题）
- 不动 `docs/designs/` / `docs/specs-history/`
- 不重排 `docs/` 子目录
- 不写 OpenAPI/Swagger 配置文件（FastAPI `/docs` 已有）

## 验证

- [docs/index.md](../../docs/index.md) 包含全部 4 份新文档的链接
- 4 份文档中所有"权威源"代码路径均存在（`grep` 验证）
- 文档中所有字段名与代码里的 Pydantic model / msgpacket row 字段一致
- [openspec/AGENTS.md](../../openspec/AGENTS.md) 步骤 0 引用 docs/index.md

## 影响的 capability

- `dev-process-control` — 文档目录边界（"静态沉淀"）继续生效
- `rpc-protocol` — 文档是 rpc-protocol spec 的**实现细节快照**，与 spec 并行
- `frontend` / `push` / `trading` / `positioning` / `auth` — 这些 capability 的 spec 描述"系统 SHALL"，本文档描述"具体字段名"
