# 1. Why

本轮深度分析（2026-06-14）发现 EvTrade 项目 13 项问题，分级如下：

| 级别 | 数量 | 状态 |
|---|---|---|
| 🔴 高（bug/数据不一致） | 3 | **2 已修，1 待修** |
| 🟡 中（设计缺陷/契约不清） | 5 | 待修 |
| 🟢 低（代码风格/可优化） | 5 | 视情况 |

本 change 是**问题盘点 + 修复追踪表**，不直接实施任何改动。
修复具体某项时，新建独立 change（如 `add-config-validation`）。

## 2. What

### 2.1 🔴 高（已修）

| # | 问题 | 根因 | 修复 | 提交 |
|---|---|---|---|---|
| H1 | `DELETE /api/orders/{id}` 假撤单（前端刷新就回到原状态） | `update_order_status` 只写内存，无 RPC | `client.cancel_order` 走真 RPC，DELETE 调它 | `1b8e785` |
| H2 | `services/trading.py` 118 行内存仓，永不被消费 | 早版本遗物 | 整文件删除 | `1b8e785` |
| H3 | `services/xtquant.py` 硬编码 Windows 路径，Linux 必崩 | 同上 | 整文件删除 | `1b8e785` |

### 2.2 🟡 中（待修，本 change 追踪）

| # | 问题 | 范围 | 建议 change |
|---|---|---|---|
| M1 | `JWT_SECRET` 缺失时静默通过用 `dev-secret-please-change` | `configuration` | `add-config-validation` |
| M2 | 8 个 `_parse_*` 解析器无统一 schema，部分返回 dict 部分 TypedDict | `rpc-protocol` | `consolidate-rpc-parsers` |
| M3 | `position_update` / `asset_update` WS 频道无数据源（push listener 不识别） | `push` | `route-position-asset-push` |
| M4 | 行情 vs 业务 WS 在前端是**两个不同 host**（:8765 vs :8000），但 `ws.js` 单 store 管理 | `frontend` | `split-quote-and-bus-ws` |
| M5 | `TStrategy.vue` / `AlgoStrategy.vue` 各 43 行未实现 | `frontend` | `implement-strategies` 或**删** |

### 2.3 🟢 低（视情况）

| # | 问题 | 备注 |
|---|---|---|
| L1 | `server/main.py` 有 2 个 `@app.on_event("startup")`，FastAPI 推荐用 `lifespan` | 不影响功能 |
| L2 | `POST /api/auth/logout` 是空 stub | JWT 无状态，可删 |
| L3 | `client.py:567` 之前 `cancel_order` 注释写了"占位" → 本轮已修 | ✅ |
| L4 | `kb/` 18 份文档索引校对 | 文档问题 |
| L5 | `server/test_rpc.py` 是手测脚本，被 pytest 自动发现超时 | 已通过 `pytest.ini testpaths = hq` 规避 |

## 3. 影响面

- 修复 M1-M5 不影响线上，仅改本地代码
- M4（拆 WS）需要前端 8 个视图 + 3 个 store 协同改动，**有 UI 风险**
- M5（策略页面）需要确认是真未实现还是占位

## 4. 不在本 change 范围

- 真实环境部署（网络/CORS/Windows 部署） — 留给运维
- msgpacket 协议本身 — 独立项目
- QMT 柜台行为 — 不可控

## 5. Tasks

- [x] H1-H3 修复（见 commit `1b8e785`）
- [x] 18/18 测试通过（commit `3188316`）
- [ ] M1 启动校验（提案：`add-config-validation`）
- [ ] M2 RPC 解析器统一（提案：`consolidate-rpc-parsers`）
- [ ] M3 push 路由 position/asset（提案：`route-position-asset-push`）
- [ ] M4 WS 拆分（提案：`split-quote-and-bus-ws`）
- [ ] M5 策略页面（提案：`implement-strategies` 或 `remove-placeholder-strategies`）

## 6. 归档条件

本 change 性质特殊：**它不是要被实施的 change，而是问题追踪表**。
建议实施路径：
- 每完成 M1-M5 一项时，从本文件移出对应行到独立 change 的 tasks.md
- 全部 M 项完成后，把本文件归档，change 名保留作历史快照
