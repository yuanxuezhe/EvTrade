# Tasks — RPC 测试模式（固定应答）

## Stage 1 — 配置 + mock 模块

- [ ] **1.1** `server/config.py`：`TEST_MODE: bool = _env_int("EVTRADE_TEST_MODE", 0) == 1`
- [ ] **1.2** 新建 `server/rpc/mock.py`：`maybe_reply(func, **kw) -> dict | None`；`qry_ast` demo / `qry_ord|qry_mch|qry_pos` 空集 / `ord_stk` 动态 order_id / `cxl_ord` 成功
- [ ] **1.3** 单测 `server/tests/test_rpc_mock.py`：mock 开关行为 + 应答结构

## Stage 2 — handler + 启动接线

- [ ] **2.1** `handlers.py` 6 个入口 `maybe_reply` 短路
- [ ] **2.2** `transport.py` `get_rpc_client()` 测试模式不 connect
- [ ] **2.3** `main.py` `on_startup_rpc` 测试模式跳过连接 + 健康同步

## Stage 3 — 验证 + 提交 + 归档

- [ ] **3.1** 验 `import server.main`；pytest mock 单测 + 既有 RPC 测试不回归
- [ ] **3.2** commit：config+mock / handlers+startup / docs 三单元
- [ ] **3.3** KB `RPC通信/RPC客户端.md` 补测试模式段
- [ ] **3.4** 归档 change
