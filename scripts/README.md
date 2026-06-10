# 脚本说明

## `dev.{ps1,cmd,sh}` — 一键启停前后端

| 操作 | 命令（PowerShell） | 命令（cmd / git-bash） |
|------|--------------------|------------------------|
| 启动 | `powershell -File scripts\dev.ps1 -Action start` | `scripts\dev.cmd start` |
| 停止 | `powershell -File scripts\dev.ps1 -Action stop`  | `scripts\dev.cmd stop`  |
| 重启 | `powershell -File scripts\dev.ps1 -Action restart`| `scripts\dev.cmd restart`|
| 状态 | `powershell -File scripts\dev.ps1 -Action status` | `scripts\dev.cmd status` |

## 端口约定

| 端口 | 服务 | 备注 |
|------|------|------|
| 8002 | FastAPI (uvicorn) | 8000/8001 被其他用户进程占着且无法 kill，**统一用 8002** |
| 3000 | Vite dev server | Vite 代理自动转发 `/api`、`/ws` → 8002 |

> 改端口：编辑 `scripts\dev.ps1` 顶部的 `$BackendPort` 常量，**同时**修改 `client\vite.config.js` 的 `proxy.target`（两者必须一致）。

## 配置（环境变量）

后端通过 `server\config.py` 加载以下环境变量（也可写到 `server\.env`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `EVTRADE_RABBITMQ_URL` | `amqp://192.168.10.2:5672/` | RabbitMQ 地址 |
| `EVTRADE_EXCHANGE_NAME` | `msgpacket.exchange` | topic exchange |
| `EVTRADE_QUEUE_REQ` | `EvTrade.Test.Req` | 请求队列 |
| `EVTRADE_QUEUE_REPLY` | `EvTrade.Test.Reply` | 应答队列 |
| `EVTRADE_QUEUE_PUSH` | `EvTrade.Test.Push` | 推送队列 |
| `EVTRADE_RPC_TIMEOUT` | `30` | RPC 单次 call 超时（秒） |
| `EVTRADE_API_HOST` | `0.0.0.0` | uvicorn 监听 host |
| `EVTRADE_API_PORT` | `8002` | uvicorn 监听 port |

参考模板：`server\.env.example`。

## 产物

- `scripts\.logs\backend.log` — uvicorn stdout+stderr
- `scripts\.logs\frontend.log` — Vite stdout+stderr
- `scripts\.pids\backend.pid` / `frontend.pid` — 当前进程号

## 行为

- 启动时按端口查占用，已占则跳过；不重复拉起
- 停止时按端口反查 PID 强杀，uvicorn reloader 派生出的 worker 会被二次清理
- 重启 = stop + sleep(2) + start
- 状态 = 端口占用 + `/api/health` 健康检查
