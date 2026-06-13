# EvTrade — OpenSpec Entry Point

> 改代码前先看这里。OpenSpec 工作流：proposal → spec delta → 实施 → 归档。

## 项目一句话

Vue3 + FastAPI 量化交易 Web 平台。**唯一数据源**是 QMT 柜台（msgpacket RPC over RabbitMQ）。
后端是薄薄一层包装 + 鉴权 + WebSocket 推送；前端 = 12 个页面；行情走独立 hqserver。

## 架构

```
┌─────────────────┐    /api/*     ┌──────────────────┐
│  Vue3 (:50998)  │──────────────▶│  FastAPI (:8000) │
│  12 views       │◀─── /ws/...──│  + JWT + RBAC    │
└─────────────────┘               └────────┬─────────┘
       │  ws://:8765 (直连)                 │ msgpacket RPC
       ▼                                    ▼
┌─────────────────┐               ┌──────────────────┐
│  hqserver       │               │  RabbitMQ        │
│  (FANOUT→WS)    │◀─── FANOUT ───│  EvTrade.Test.*  │
└─────────────────┘               └────────┬─────────┘
                                           │ YSWY 协议
                                           ▼
                                  ┌──────────────────┐
                                  │  QMT 柜台        │
                                  │  (Windows 部署)  │
                                  └──────────────────┘
```

## 8 个 capability（specs/ 目录一一对应）

| Cap | 范围 | 关键文件 |
|---|---|---|
| `auth` | 登录/JWT/RBAC | `server/auth/`, `server/api/auth.py`, `client/src/stores/auth.js` |
| `trading` | 下单/撤单/委托/成交/资金 | `server/api/{orders,trades,asset}.py`, `client/src/views/{Trade,Orders,Trades,Asset}.vue` |
| `positioning` | 持仓查询 | `server/api/positions.py`, `client/src/views/Position.vue` |
| `quotes` | 行情推送 | `hq/hqserver.py`, `client/src/stores/quote.js`, `client/src/stores/ws.js` |
| `push` | 柜台 push → WebSocket 路由 | `server/rpc/client.py:121-180` |
| `frontend` | Vue 路由/角色守卫/WS | `client/src/router/`, `client/src/api/` |
| `configuration` | .env / 配置分层 | `server/config.py`, `hq/hqserver.py:26-62` |
| `rpc-protocol` | msgpacket 客户端契约 | `server/rpc/client.py` |

## 改东西的流程

```bash
# 1. 创建变更（用 AI 助手）
/openspec:proposal <name>

# 2. 检查产出
ls openspec/changes/<name>/
#   proposal.md    ← 为什么改
#   tasks.md       ← checklist
#   spec-deltas/   ← 涉及 cap 的 spec 增量

# 3. 改代码，按 tasks.md 走

# 4. 归档（spec 已合并到 specs/<cap>/spec.md 后）
/openspec:archive <name>
```

## 约定

- **单一数据源**：后端不维护内存委托/成交/持仓副本，所有展示走柜台 RPC + push
- **WS 频道命名**：`order_update` / `trade_update` / `position_update` / `asset_update` / `quote_update`
- **RPC 响应统一**：`{code, msg, list}`（code=0 成功，前端 axios 拦截器自动展平）
- **配置分层**：`server/.env`（FastAPI）+ `HQ_*`（hqserver，与 server 共享 .env）
- **测试**：`pytest hq/` 18/18 通过；`test_rpc.py` 是手测脚本

## 当前活跃 change

| Change | 状态 | 解决什么 |
|---|---|---|
| `current-issues` | draft | 列出本轮分析发现的 13 项问题及修复分工 |
| `add-config-validation` | draft | .env 启动校验 + 配置分层文档化 |
| `consolidate-rpc-parsers` | draft | 8 个 _parse_* 解析器合并为统一 schema |

详见 `openspec/changes/<name>/proposal.md`。
