# hqserverd (Rust)

EvTrade 行情消费 + WebSocket 直推服务。2026-08-18 起取代旧 `hq/hqserver.py`。

## 链路

```
QMT iquant/quota.py  ──UDP datagram──▶  hqserverd  ──WS frame──▶  前端 / strategy_exec
                                        (Rust tokio)
```

## 构建

```bash
cd hq/hqserverd
cargo build --release
```

产物：`target/release/hqserverd[.exe]` (~2 MB)

## 运行

```bash
./target/release/hqserverd[.exe]      # Linux/macOS / Windows
```

或通过 `scripts/evctl.py`：

```bash
uv run python scripts/evctl.py start hqserver
```

## 环境变量（与 `server/.env` 共享）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HQ_UDP_BIND` | `0.0.0.0:9001` | 监听 UDP 端口（接收 quota.py） |
| `QUOTA_UDP_HOST` | `192.168.1.20` | quota.py 推送目标 IP（信息展示） |
| `QUOTA_UDP_PORT` | `9001` | quota.py 推送目标端口（信息展示） |
| `HQ_NUM_WORKERS` | `4` | worker task 数 |
| `HQ_MAX_QUEUE_SIZE` | `5000` | 内部 mpsc 缓冲上限 |
| `HQ_WS_HOST` | `0.0.0.0` | WS 监听地址 |
| `HQ_WS_PORT` | `8765` | WS 监听端口 |
| `HQ_DEBUG` | `False` | 启用 tracing::debug 日志（生产关） |
| `RUST_LOG` | — | tracing 过滤（如 `RUST_LOG=debug` 启用 HQ_DEBUG） |

## 模块布局

- `src/main.rs`：入口、信号、编排
- `src/config.rs`：env 解析
- `src/types.rs`：`QuotePayload` 数据类型
- `src/udp_receiver.rs`：UDP 收包 → mpsc
- `src/worker.rs`：N worker 解析 tick
- `src/ws_server.rs`：WS 服务

## 协议

### 输入（quota.py → hqserverd）

- UDP datagram，每条 tick 一帧
- GBK 编码（lossy UTF-8 兜底，详见 `worker.rs:decode_best_effort`）
- `|` 分隔，首字段 = stock_code，共 32 字段

### 输出（hqserverd → 前端 WS）

- 端口 `:8765`，与旧版完全一致
- 每条 tick 一帧 JSON：
  ```json
  {"type":"quote","channel":"quote_update","data":{"stock_code":"600519.SH","last_price":1700.5,"fields":["..."],"body":"..."}}
  ```
- `ping_interval=15s`（每 15s 主动 Ping），客户端 60s 内不响应 Pong 视为掉线