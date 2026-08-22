# Proposal — RPC 测试模式（固定应答，不发送真实请求）

## Why

开发/演示环境没有 QMT 柜台 + RabbitMQ 时，EvTrade 无法启动完整下单链路。需要一个系统参数"测试模式"：开启后所有业务 RPC 调用**不发真实请求**，直接返回固定应答结果集，让下单/查询/撤单端到端可走通。

## Design

- **系统参数**：`EVTRADE_TEST_MODE=1`（env，`server/config.py` `settings.TEST_MODE`，默认关）——启动时在 `.env` 开启，与现有 config 分层一致。
- **拦截点**：`server/rpc/handlers.py`（唯一业务 RPC 入口，KB 已约定"勿绕过 handlers 直接用 client.call"）。每个 handler 先 `maybe_reply(func, **kw)`，测试模式下直接返回已解析 dict `{code,msg,list}`。
- **为何不在 `transport.RPClient.call()` 单点拦截**：需构造 MsgPacket 应答包，实测 msgpacket DLL 构造多结果集包（code/msg + 业务数据）会 segfault（build→encode→decode 往返单结果集可读、2 结果集崩溃）。handler 层 mock 返回解析后 dict，绕开 DLL 脆弱点。
- **`server/rpc/mock.py`**（新，单一职责）：
  - `maybe_reply(func, **kw) -> dict | None`：`TEST_MODE` 关 → None（走真实链路）；开 → 固定应答
  - `qry_ast` → 固定资产 demo；`qry_ord/qry_mch/qry_pos` → 空集（不污染 DB）
  - `ord_stk` → 动态 `order_id`（`TEST-<seq>` 进程内递增），使下单 status 48→50 端到端走通
  - `cxl_ord` → 成功空集
- **启动**：`main.py on_startup_rpc` 测试模式跳过 RabbitMQ 连接 + 健康同步；`transport.get_rpc_client()` 测试模式不 connect（完全离线可用）。

## What Changes

| 文件 | 改动 |
|---|---|
| `server/config.py` | `TEST_MODE` from `EVTRADE_TEST_MODE` |
| `server/rpc/mock.py` | 新增：`maybe_reply` + 固定应答 + order_id 计数器 |
| `server/rpc/handlers.py` | 6 个入口加 `maybe_reply` 短路 |
| `server/rpc/transport.py` | `get_rpc_client()` 测试模式不 connect |
| `server/main.py` | `on_startup_rpc` 测试模式跳过连接 + 健康同步 |
| `server/tests/test_rpc_mock.py` | 新增 mock 单测 |
| KB `RPC通信/RPC客户端.md` | 补测试模式段 |

## Backward Compatibility

- `TEST_MODE` 默认关，行为零变化；开启时仅影响 RPC 应答来源。
- 查询 mock 空集 → reconcile 对账无新数据（与真实空柜台一致）；下单 mock 返回真实格式 order_id。
- push（ord_cfm/trd_cfm）测试模式不模拟——下单后不会有成交推送，属预期（只 mock RPC 请求应答）。

## Risks

- **只 mock 请求应答，不 mock push**：用户如果期望成交也会被模拟，需要后续扩展（不在本 change）。
- **order_id 进程内递增**：重启会从 TEST-00001 重新开始，重复 order_id 可能出现在不同 trd_date 的 orders 行（无唯一约束，不影响正确性）。

## Decisions

| # | 决策点 | 结果 |
|---|---|---|
| Q1 | 参数放 env 还是 sys_config | env `EVTRADE_TEST_MODE`（启动时定死，防运行中误切导致单子静默不发） |
| Q2 | 拦截点 | handlers.py（handler 层 mock dict），非 transport.call() |
| Q3 | 查询类应答 | 固定资产 demo / 空集，不造幻影数据 |

## Reference

- `知识库/后端服务/RPC通信/RPC客户端.md`（handlers 唯一入口约定）
- `server/config.py`（Settings env 模式）
