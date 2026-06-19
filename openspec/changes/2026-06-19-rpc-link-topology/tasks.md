# Tasks

- [x] 写 proposal.md + spec-deltas/rpc-protocol.md（引用 REQ-RPC-007/008 + S-RPC-004/005）
- [x] spec.md 增 REQ-RPC-007（队列拓扑与绑定）+ REQ-RPC-008（publisher confirms）+ S-RPC-004/005
- [ ] server/rpc/client.py：connect 显式 bind 三条队列
- [ ] server/rpc/client.py：channel 开启 publisher_confirms
- [ ] server/rpc/client.py：publish 包 5s 超时 + pending 清理
- [ ] server/rpc/client.py：connect 幂等守卫（已连接则直接返回）
- [ ] server/test_rpc_link.py：6 用例（mock aio_pika 全链路）
- [ ] pytest server/test_rpc_link.py 全绿

## Out-of-scope

- push 同步 DB 操作改 async（涉及 push_handlers.py，独立 change）
- qry_* 解析器统一 schema（独立 change）
- listener 启动顺序优化（无实际故障）