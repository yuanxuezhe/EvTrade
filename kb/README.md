# EvTrade 知识库（KB）索引

> ⚠️ **DEPRECATED（2026-06-28）** — 本目录已弃用。
>
> 内容已逐步并入 OpenSpec 工作流的 [`openspec/specs/`](openspec/specs/) 单一真源（SSOT）。
> 各 capability 对应：
>
> | KB 旧文档 | OpenSpec 现行 spec |
> |---|---|
> | `server/01_api.md` / `server/02_auth.md` | [`openspec/specs/trading/spec.md`](openspec/specs/trading/spec.md) + [`openspec/specs/auth/spec.md`](openspec/specs/auth/spec.md) |
> | `server/03_db_models.md` | [`openspec/specs/data-model/spec.md`](openspec/specs/data-model/spec.md) |
> | `server/04_services.md` / `server/05_rpc_client.md` / `server/06_xtquant.md` | [`openspec/specs/rpc-protocol/spec.md`](openspec/specs/rpc-protocol/spec.md) |
> | `server/07_websocket.md` | [`openspec/specs/ws-protocol/spec.md`](openspec/specs/ws-protocol/spec.md) |
> | `cross/01_data_models.md` | [`openspec/specs/data-model/spec.md`](openspec/specs/data-model/spec.md) |
> | `cross/02_order_status.md` | [`openspec/specs/trading/spec.md`](openspec/specs/trading/spec.md) 内 REQ-TRADE-* 段 |
> | `cross/03_role_matrix.md` | [`openspec/specs/auth/spec.md`](openspec/specs/auth/spec.md) 内 REQ-AUTH-* 段 |
> | `cross/04_iquant.md` | [`openspec/specs/rpc-protocol/spec.md`](openspec/specs/rpc-protocol/spec.md) |
> | `client/01_router.md` ~ `06_views.md` | [`openspec/specs/frontend/spec.md`](openspec/specs/frontend/spec.md) |
>
> 本目录保留仅作历史快照，**改文档请直接改 OpenSpec**。

> 本知识库基于代码逐行梳理，记录 EvTrade 智能交易终端的完整功能、接口、数据结构与实现细节。
> 可作为后续代码维护、扩展、重构的参考依据；所有结论均来自 `client/`、`server/`、`iquant/` 当前代码。

## 项目定位

**EvTrade** = 现代化 A 股智能交易终端
- 前端：Vue 3 + Vite + Element Plus + ECharts（管理面板型 SPA）
- 后端：FastAPI + SQLAlchemy + JWT（基于 RabbitMQ + MsgPacket 协议桥接交易柜台）
- 交易接入：支持 xtquant（迅投 QMT）等可插拔适配器

## 文档目录

| 文档 | 内容 | 适用范围 |
|------|------|----------|
| [00_overview.md](00_overview.md) | 项目概览、技术栈、目录结构、运行方式 | 入门 |
| [01_architecture.md](01_architecture.md) | 整体架构、模块依赖、数据流 | 架构 |
| [server/01_api.md](server/01_api.md) | 所有 FastAPI HTTP 接口清单 | 后端 |
| [server/02_auth.md](server/02_auth.md) | JWT/角色权限（`get_current_user` / `require_admin` / `require_trader`） | 后端 |
| [server/03_db_models.md](server/03_db_models.md) | SQLite + SQLAlchemy ORM（`User`） | 后端 |
| [server/04_services.md](server/04_services.md) | 内存级领域服务（`trading.py`） | 后端 |
| [server/05_rpc_client.md](server/05_rpc_client.md) | RabbitMQ + MsgPacket 异步 RPC 客户端 | 后端 |
| [server/06_xtquant.md](server/06_xtquant.md) | 迅投 QMT 交易柜台适配 | 后端 |
| [server/07_websocket.md](server/07_websocket.md) | WS 推送通道 | 后端 |
| [client/01_router.md](client/01_router.md) | 路由表、守卫、权限元数据 | 前端 |
| [client/02_stores.md](client/02_stores.md) | Pinia stores（auth/asset/order/position/ui） | 前端 |
| [client/03_api_layer.md](client/03_api_layer.md) | axios 封装、token、API 聚合 | 前端 |
| [client/04_utils.md](client/04_utils.md) | 格式化与状态映射工具 | 前端 |
| [client/05_components.md](client/05_components.md) | 通用组件清单 | 前端 |
| [client/06_views.md](client/06_views.md) | 9 个页面级视图清单 | 前端 |
| [cross/01_data_models.md](cross/01_data_models.md) | 跨端数据契约（`Position` / `Order` / `Trade` / `Asset`） | 跨端 |
| [cross/02_order_status.md](cross/02_order_status.md) | 11 档订单状态映射（XtQuant 码 ↔ 前端 key） | 跨端 |
| [cross/03_role_matrix.md](cross/03_role_matrix.md) | 角色 × 路由 × API 权限矩阵 | 跨端 |
| [cross/04_iquant.md](cross/04_iquant.md) | iQuant 目录的辅助脚本与协议 | 跨端 |

## 默认账号

| 字段 | 值 |
|------|----|
| 用户名 | `admin` |
| 密码 | `admin123` |
| 角色 | `admin` |

> 首次启动时若 `users` 表为空，由 `server/main.py:on_startup` 自动 seed。

## 关键约定

- 所有路由以 `/api` 为前缀，前端通过 Vite 代理到 `http://localhost:8000`。
- 鉴权使用 `Authorization: Bearer <jwt>`，token 存于 `localStorage` 的 `evtrade-token`。
- 订单状态使用前端 12 种 key（11 档 XtQuant 状态 + 兼容旧的 `pending`），详见 `cross/02_order_status.md`。
- 角色三档：`admin` / `trader` / `viewer`，权限矩阵见 `cross/03_role_matrix.md`。
- 真实交易柜台的接入由 `server/services/xtquant.py` 包装，RPC 调用走 RabbitMQ + MsgPacket 协议。

## 如何用本知识库更新代码

1. 找到目标功能所在的 KB 文档（按目录或索引表）。
2. 阅读其"接口签名 / 数据结构 / 业务规则"小节，确认与设计意图一致。
3. 在修改代码时遵循 KB 中标注的约束（如状态枚举、角色权限、数据契约）。
4. 修改完成后回写 KB 相应章节，保持文档与代码同步。
