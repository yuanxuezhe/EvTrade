# spec-deltas/rpc-protocol

## 改动

`openspec/specs/rpc-protocol/spec.md` 新增：

- **REQ-RPC-007 队列拓扑与绑定**：connect() 显式 declare + bind 三条队列到 EXCHANGE_NAME，routing_key = 队列名；connect 幂等
- **REQ-RPC-008 Publisher Confirms**：channel 开 publisher_confirms=True；publish 包 5s 超时；超时抛 RuntimeError 且清理 pending
- **S-RPC-004 队列绑定场景**：启动后 broker 端三条队列均存在且 binding 正确
- **S-RPC-005 Publisher Confirm 超时场景**：broker 不 ack 时 5s 内抛错

## 影响范围

仅 `server/rpc/client.py`：

- `connect()` 增加 declare + bind 三条队列；幂等守卫
- channel 创建时传 `publisher_confirms=True`
- `call()` 内 publish 包超时清理

无业务 API（api/）改动。

## 测试

`server/test_rpc_link.py` 新增 6 用例，mock aio_pika 全链路。