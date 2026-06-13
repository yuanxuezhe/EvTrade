# Tasks — consolidate-rpc-parsers

## 阶段 1：定义 schema（不动解析逻辑）

- [ ] 读 `server/models/types.py` 当前实现
- [ ] 读 `server/api/{orders,trades,asset,positions}.py` 4 个文件
- [ ] 读 `server/rpc/client.py` 全部 `_parse_*` 函数
- [ ] 列字段映射表：每个 RPC 字段 → 哪个 Pydantic 字段

## 阶段 2：实现 Pydantic 模型

- [ ] `server/models/types.py` 新增：
  - [ ] `AssetResponse`
  - [ ] `OrderResponse`
  - [ ] `TradeResponse`
  - [ ] `PositionResponse`
  - [ ] `OrderAckResponse`
  - [ ] `OrderPushEvent`（push 专用）
- [ ] `RpcResponse[T]` 泛型容器

## 阶段 3：重写解析层

- [ ] 写 `_parse_rpc_response(pkt, rs1_model, rs2_model)` 统一入口
- [ ] 替换 6 个业务解析器
- [ ] 替换 push 路径的 `ord_cfm` / `trd_cfm` 解析器

## 阶段 4：业务层联调

- [ ] 4 个 api 文件改为传 BaseModel
- [ ] 检查 WS push listener 用新 model
- [ ] 检查 Pydantic v1/v2 兼容（项目用 v1 还是 v2？）

## 阶段 5：测试

- [ ] 写 `server/test_rpc_parsers.py`：
  - [ ] 正常 RS1 + RS2
  - [ ] code≠0
  - [ ] RS2 字段缺失
  - [ ] 字段类型不匹配
- [ ] pytest 全绿
- [ ] 端到端：手动 `test_rpc.py` 验真实柜台（可选）

## 阶段 6：文档与提交

- [ ] 更新 `openspec/specs/rpc-protocol/spec.md`
- [ ] commit: `refactor(rpc): 8 个 _parse_* 统一为 Pydantic BaseModel`
- [ ] push

## 验证

- [ ] `pytest hq/ server/` 全绿
- [ ] api 响应字段名/类型与前端期望一致（用 `grep` 对比 client/src/stores/*.js）
- [ ] git log 显示新 commit
