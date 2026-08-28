# hqserver 行情服务说明

## 对应代码路径

- `e:/EvTrade/hq/hqserverd/`（Rust crate（多模块）：行情消费 + WebSocket 直推路由器）
- `e:/EvTrade/hq/hqsuber.py`（**保留**：按标的订阅的 RabbitMQ 示例客户端，演示如何 bind `quota.broadcast.exchange`）
- `e:/EvTrade/iquant/quota.py`（QMT publisher：tick 批量合并（`_buf` 累计 ≤ `QUOTA_BATCH_MAX`=50 条，',' join 为一帧）后 UDP datagram 直推 hqserverd，不再走 MQ）
- 配置来源：`e:/EvTrade/server/.env`（与 EvTrade 主服务共享）

## 功能概述

hqserverd 是 EvTrade 的**独立行情推送进程**（Rust tokio 单二进制）：
QMT publisher (`iquant/quota.py`) 通过 UDP（默认 `:9001`）直推每条 tick 给 hqserverd，
经内部 tokio mpsc 缓冲与固定 worker 池拆分后，把每条 tick 以 JSON 帧
`{"type":"quote", ...}` 广播给**所有**已连接的 WebSocket 客户端（前端行情页 + strategy_exec 实盘 LiveRunner）。

### 旧架构 vs 新架构

| 维度 | 旧 (`hq/hqserver.py`) | 新 (`hq/hqserverd`) |
|---|---|---|
| 传输 | RabbitMQ `quota.exchange` FANOUT | UDP 单播 (quota.py → hqserverd) |
| 依赖 | aio_pika, websockets (Python) | tokio + tokio-tungstenite (Rust) |
| 并发 | asyncio + N worker coroutine | tokio 多线程 + N worker task |
| 内存 | MQ broker + 本地缓冲 + ack 状态 | 仅本地 mpsc 缓冲（无 ack/重投） |
| 单 tick 延迟 | 1 跳 broker（ms 级） | 直推（µs 级） |
| WS 协议/端口 | `:8765`, `{"type":"quote",...}` | `:8765`, `{"type":"quote",...}` **不变** |
| 前端兼容性 | — | **0 改动** |

架构（hqserverd main.rs 编排）：

```
QMT quota.py (socket sendto)
      ↓ UDP datagram: gbk 编码, 帧内 ',' 分隔多条 tick(≤50), 每条 '|' 分隔, 首字段 stock_code
hqserverd 绑定 :9001 接收
      ↓ tokio mpsc (maxsize=5000, 天然背压)
NUM_WORKERS 个 worker task (CPU 受控)
      ↓ 逐条拆 ',' 批次 → '|' 切字段 → serde_json 序列化为 QuotePayload
WebSocket 服务 :8765 ──→ 前端 + strategy_exec LiveRunner
```

## 文件清单

| 代码文件 | 作用 |
|---|---|
| `hqserverd/Cargo.toml` | Rust 项目元数据 + tokio/tungstenite 依赖 |
| `hqserverd/src/main.rs` | `tokio::main` 入口 + 信号处理 + 编排 |
| `hqserverd/src/config.rs` | 环境变量解析（替代旧 `_env_*` 助手） |
| `hqserverd/src/types.rs` | `QuotePayload` 数据类型 + serde JSON 序列化 |
| `hqserverd/src/udp_receiver.rs` | UDP socket 收包 → 内部 mpsc |
| `hqserverd/src/worker.rs` | N worker 解析 tick（`,` 拆批次 → `|` 切字段、调 WsHub） |
| `hqserverd/src/ws_server.rs` | WS 服务：注册/广播/keepalive |

## 核心实现

### 启动与配置（HQ_* 环境变量）

hqserverd 通过 `Config::from_env()` 读环境变量（无需 .env loader，直接 std::env）。
启动：

```bash
# 1) 编译（首次或 release 优化）
cd hq/hqserverd && cargo build --release

# 2) 运行（推荐）
./target/release/hqserverd[.exe]

# 或开发模式
cargo run --release

# 或通过 evctl
uv run python ./scripts/evctl.py start hqserver
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HQ_UDP_BIND` | `0.0.0.0:9001` | hqserverd UDP 监听地址（接收 quota.py） |
| `QUOTA_UDP_HOST` | `192.168.1.20` | quota.py 推送的目标 IP（hqserverd 仅日志展示用，不主动连） |
| `QUOTA_UDP_PORT` | `9001` | quota.py 推送的目标端口（**仅 quota.py 侧读取**；hqserverd 的 `config.rs` 不解析此变量，实际监听口由 `HQ_UDP_BIND` 决定） |
| `HQ_NUM_WORKERS` | `4` | worker task 数（防吃满单核 CPU） |
| `HQ_MAX_QUEUE_SIZE` | `5000` | 内部 mpsc 缓冲上限（满则背压阻塞） |
| `HQ_WS_HOST` | `0.0.0.0` | WS 监听地址 |
| `HQ_WS_PORT` | `8765` | WS 监听端口（`ws://<host>:8765`） |
| `HQ_DEBUG` | `False` | 每个 tick 在 tracing::debug 打一行（生产必须关；通过 `RUST_LOG=debug` 启用） |

### UDP 接收（udp_receiver.rs）

- `tokio::net::UdpSocket::bind(HQ_UDP_BIND).await`，buf = `Vec<u8>` 64 KiB。
- 每帧 datagram 可含**多条 tick**：quota.py 在 `_buf` 中累计 tick（阈值 `QUOTA_BATCH_MAX`=50 条）后 `b",".join` 成一帧再 `sendto`（旧 MQ 版的 `\n` 分隔已改为 `,`）。
- 字节层不解析、整包入 mpsc；worker 侧做批次拆分与字段切分。
- 通道满 → UDP sendto 由 OS socket buffer 兜底，再满 → quota.py 端 `sendto` 失败丢弃。
- UDP 不做 ACK/重传；行情丢一两条对前端展示无影响。

### worker 池（worker.rs）

N 个 worker task 共享同一个 `Arc<Mutex<mpsc::Receiver<Vec<u8>>>>`，逐条消费：

1. `decode_best_effort(pkt)`：优先严格 gbk（**注**：当前实现为 lossy utf-8，详见"已知限制"）；
2. `body.split(',')` 先拆批次（v1.1 行情合并推送：一帧内 ',' 分隔 N 条 tick，向后兼容无 ',' 的单 tick；空段跳过）；
3. 每条 tick 再 `split('|')` 切字段（首字段 = stock_code）；
4. `QuotePayload::new(stock_code, fields, body)` 构造 payload（含 last_price 解析，取 fields[2]）；
5. `serde_json::to_string(&payload)` 序列化为字符串；
6. `hub.broadcast(text)` → WsHub 复制给所有客户端；
7. `tokio::task::yield_now().await` 让出执行权（等价旧版 `await asyncio.sleep(0)`）。

### WebSocket 服务（ws_server.rs，:8765）

- `tokio::net::TcpListener::bind` 接受 → `tokio_tungstenite::accept_async` 升级握手。
- 每个连接 spawn 2 个 task：出站 task 把 mpsc 进来的帧 `sink.send`；入站 task 仅探测断开（回应 `Pong`）。
- **Ping/Pong keepalive**：旧版 `ping_interval=15 / ping_timeout=60`。tokio-tungstenite 0.24 的 `WebSocketConfig` 不再带这两个字段，改用上层 `tokio::time::interval(15s)` 主动 `Message::Ping`；客户端 60s 内不响应 `Pong` 视为掉线（tungstenite 默认 timeout）。
- 客户端集合 `WsHub`：`Arc<Mutex<HashMap<SocketAddr, WsTx>>>`；`broadcast(text)` 先快照再发送，失败的对端在 `dead` 列表中清掉。
- **无订阅过滤**：服务端把所有 tick 推给所有连接（FANOUT 语义）；按标的过滤由客户端自己做（如 LiveRunner 只处理自己 stock_code 的帧）。订阅消息 `{"type":"subscribe","stock_codes":[...]}` 发送无害但服务端不解析。

### 信号与优雅关闭（main.rs）

- `tokio::sync::Notify` 触发统一停止。
- Unix: 同时监听 `SIGINT/SIGTERM`（`tokio::signal::unix::signal`）；Windows: `tokio::signal::ctrl_c`。
- 收到信号 → `notify_waiters()` → `udp_handle.abort() / ws_handle.abort() / worker_handles.abort()` → 进程退出。

## 已知限制

- **GBK 解码**：`worker.rs` 当前用 `String::from_utf8_lossy` 解码（lossy）；严格 gbk 解码需引入 `encoding_rs` crate（已在下一版 plan 中）。
  - 影响范围：QMT 推送的 body 中含 GBK 中文字段（如股票简称）会变成 `U+FFFD`，但 fields[0..N] 字段名（ASCII）+ 数字字段不受影响；前端展示 last_price 等数字字段无问题。

## 依赖关系

- 上游：QMT publisher `iquant/quota.py`（每条 tick 一帧 UDP datagram）。
- 下游：所有连 `ws://<host>:8765` 的客户端 —— 前端行情页、strategy_exec LiveRunner（实盘 tick）、其他调试工具。
- 同级：与 EvTrade server 共享 `server/.env`；与 strategy_exec 通过 WS 解耦（无代码依赖）。

## 修改指南

- 加按标的订阅/退订：解析客户端首条 subscribe 消息并维护 `peer -> set(stock_code)` 映射，`WsHub::broadcast` 改为按订阅集过滤（注意向后兼容：未订阅的旧客户端保持全推）。
- 改端口/地址：`server/.env` 的 `HQ_UDP_BIND / HQ_WS_HOST / HQ_WS_PORT`；quota.py 侧同步改 `QUOTA_UDP_HOST / QUOTA_UDP_PORT`。
- tick 字段升级：保持 `data.fields`/`data.body` 原始字段不变前提下新增解析字段；消费端（前端 + LiveRunner `_BarAggregator`）需同步。
- 性能调优：`HQ_NUM_WORKERS`（CPU 核数上限内）、`HQ_MAX_QUEUE_SIZE`（内存换延迟）；调试完务必 `HQ_DEBUG=0`。
- 增加新 env：编辑 `hqserverd/src/config.rs` + `.env.example`。

## 回滚方案（紧急）

如需切回 RabbitMQ 旧版：

1. `git revert` 本次 commit（或 checkout 上一个 master）。
2. 旧 `hq/hqserver.py` 自动恢复，evctl `_hqserverd_cmd` 走 release bin 检测会找不到回退——**手动临时**改 evctl hqserver 行恢复 `[sys.executable, '-u', 'hqserver.py']`。
3. 旧 `.env` 的 `HQ_RABBITMQ_URL/...` 仍然在归档 commit 里有 reference。