# EvTrade

A 股智能交易终端。Vue 3 + FastAPI + msgpacket RPC + XtQuant / QMT 柜台。

- 后端业务数据本地 SQLite 优先（v4），下单 / 撤单 / 对账走 QMT 柜台 RPC。
- 行情通过独立 `hqserver` WebSocket（:8765）FANOUT 推送。
- 鉴权：JWT + RBAC（admin / trader / viewer）。
- 开发流程：spec-driven（详见 [`openspec/AGENTS.md`](openspec/AGENTS.md)）。

## 启动

```bash
# 一键启动 backend / frontend / hqserver
python scripts/evctl.py start

# 查看状态
python scripts/evctl.py status

# 停止
python scripts/evctl.py stop
```

端口：backend `:8000`、frontend `:50998`、hqserver `:8765`。

## 默认账号

| 字段 | 值 |
|------|----|
| 用户名 | `admin` |
| 密码 | `admin123` |
| 角色 | `admin` |

首次启动且 `users` 表为空时由 `server/lifecycle/seed.py` 自动 seed。

## 目录速览

| 路径 | 作用 |
|------|------|
| [`server/`](server/) | FastAPI 后端（phase-2 拆分） |
| [`client/`](client/) | Vue 3 前端（Element Plus + ECharts） |
| [`hq/`](hq/) | 独立行情 WebSocket 服务 |
| [`iquant/`](iquant/) | XtQuant / msgpacket 参考实现（仅参考） |
| [`openspec/`](openspec/) | 规范驱动开发：specs + changes + archive |
| [`docs/`](docs/) | 设计稿、归档分析、协议文档 |
| [`kb/`](kb/) | **已弃用** — 内容已并入 [`openspec/specs/`](openspec/specs/) |
| [`scripts/`](scripts/) | 启停脚本 + 一次性迁移 |

## 进一步阅读

- 改代码前必读：[`openspec/AGENTS.md`](openspec/AGENTS.md)（步骤 0：检索知识库）
- 当前活跃变更：[`openspec/changes/active/`](openspec/changes/active/)
- 数据模型：[`openspec/specs/data-model/spec.md`](openspec/specs/data-model/spec.md)
- 交易流程：[`openspec/specs/trading/spec.md`](openspec/specs/trading/spec.md)
- 协议文档：[`docs/msgpacket-python-api.md`](docs/msgpacket-python-api.md)