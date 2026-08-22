# Tasks — RPC 测试模式（固定应答）

## Stage 1 — mock 模块 + sys_config 开关

- [x] **1.1** `server/rpc/mock.py`：`maybe_reply(func, **kw) -> dict | None`；`qry_ast` demo / `qry_ord|qry_mch|qry_pos` 空集 / `ord_stk` 动态 order_id / `cxl_ord` 成功；判定读 `sysconfig.get("rpc_test_mode", 0)`（每次调用 → 切换即时生效）
- [x] **1.2** `server/infra/db.py` init_db 兜底 seed `rpc_test_mode=0`
- [x] **1.3** 单测 `server/tests/test_rpc_mock.py`：开关行为/固定应答/order_id 递增/切换即时生效/短路不连

## Stage 2 — handler + 启动接线

- [x] **2.1** `handlers.py` 6 个入口 `maybe_reply` 短路
- [x] **2.2** `main.py` `on_startup_rpc` 启动时 `rpc_test_mode=1` 跳过连接 + 健康同步
- [x] **2.3** `transport.py` `get_rpc_client()` 恢复始终 connect（运行时切换只影响 mock 判定，连接保持）

## Stage 3 — 验证 + 提交 + 归档

- [ ] **3.1** 验 `import server.main`；pytest mock 单测 + 既有 RPC 测试不回归
- [ ] **3.2** commit：config+mock / handlers+startup / docs 三单元
- [ ] **3.3** KB `RPC通信/RPC客户端.md` 补测试模式段
- [ ] **3.4** 归档 change
