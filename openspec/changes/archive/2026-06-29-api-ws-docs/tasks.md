# Tasks: docs/ API 文档补全

> 与 [proposal.md](proposal.md) 配套

- [x] **T1** 写 [docs/xtquant-rpc.md](../../docs/xtquant-rpc.md)：6 RPC + 8 push（含 ord_err / cxl_err / ord_ack / acc_sts）
- [x] **T2** 写 [docs/server-rest-api.md](../../docs/server-rest-api.md)：全部 FastAPI 端点
- [x] **T3** 写 [docs/ws-push.md](../../docs/ws-push.md)：4 频道 + payload + 心跳 + quote_update 旁路
- [x] **T4** 写 [docs/index.md](../../docs/index.md)：docs/ 目录导航
- [x] **T5** 在 [openspec/AGENTS.md](../../openspec/AGENTS.md) 步骤 0 引用 [docs/index.md](../../docs/index.md)
- [x] **T6** 验证：4 文档 11+18+10+5+1 处"权威源"引用全部命中
- [ ] **T7** git commit：`docs(api): 补全 QMT RPC / server REST / WS 三层接口文档`（按 [feedback_commit_granularity](../../.claude/memory/feedback_commit_granularity.md) 单 commit）
- [ ] **T8** 归档此 change 到 [openspec/changes/archive/2026-06-29-api-ws-docs/](../archive/2026-06-29-api-ws-docs/)
