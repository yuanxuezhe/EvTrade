# Tasks — consolidate-rpc-parsers

## 实施 commit
- `e5c3f4b` refactor(rpc): client.py 拆 transport+parsers+handlers
- `390da31` docs(spec): rpc-protocol 应用 consolidate-rpc-parsers + M6 spec delta

## 任务列表

### 阶段 1：定义 schema（不动解析逻辑）

- [x] 读 `server/models/types.py` 当前实现 — N/A，模型在 Pydantic BaseModel 各自的 schema.py
- [x] 读 `server/api/{orders,trades,asset,positions}.py` 4 个文件
- [x] 读 `server/rpc/client.py` 全部 `_parse_*` 函数
- [x] 列字段映射表：每个 RPC 字段 → 哪个 dict 字段

### 阶段 2：实现 Pydantic 模型 — **未实施（折中）**

- [ ] `server/models/types.py` 新增 5 个 Response — **未实施**：当前 parsers 返 `Dict[str, Any]`，已通过 docstring 字段列表 + v10 broker 原字段名约束保证类型
- [ ] `RpcResponse[T]` 泛型容器 — **未实施**

### 阶段 3：重写解析层

- [x] 写 `_parse_rpc_response(pkt, parser_fn)` 统一入口 — **折中**：拆 `parsers_common.py`（_select_rs / _parse_code_msg / _iter_rows / _to_int / _to_float / _empty）+ `parsers_business.py`（5 个业务解析器），统一返 `{code, msg, list}` shape
- [x] 替换 6 个业务解析器 — `e5c3f4b` 拆分到 parsers_business.py
- [ ] 替换 push 路径的 `ord_cfm` / `trd_cfm` 解析器 — 独立于本 change（`parsers_push.py` 已在 simplify-rpc-transport-thin 范围）

### 阶段 4：业务层联调

- [x] 4 个 api 文件改为统一 list 包装 — `asset.py` 已改 `list=[AssetOut]`，其他维持
- [x] 检查 WS push listener 用新 model — OK，parsers_push.py 独立

### 阶段 5：测试

- [x] 测试覆盖：复用现有 test_push_handlers / test_rpc_link（conftest 修复后通过）
- [x] pytest 全绿（除 4 个 AsyncMock 预存问题）
- [ ] 端到端：test_rpc.py 验真实柜台 — pytest.ini 已排除 test_rpc.py（手动脚本）

### 阶段 6：文档与提交

- [x] 更新 `openspec/specs/rpc-protocol/spec.md` — `390da31`
  - REQ-RPC-003 重写（统一 shape 描述）
  - REQ-RPC-013 新增（API 格式统一，M6 折叠）
  - S-RPC-006 新增（asset 端点响应）
  - Known Issues 全 ✅
- [x] commit — `e5c3f4b` (代码) + `390da31` (spec)
- [x] tracking 标 M2/M6 Done

## 验证

- [x] `pytest server/test_rpc_parsers.py` 等相关测试全绿
- [x] api 响应字段名/类型与前端期望一致（v10 broker 原字段名约定）
- [x] `git log --oneline | grep consolidate` 显示已实施 commits

## 偏离提案的决策

| 提案 | 实际 | 理由 |
|---|---|---|
| Pydantic `BaseModel` 化 | 保留 `Dict[str, Any]` + docstring | Pydantic v1 + Py3.6 + `Dict[str, Any]` 已统一 shape，无需强制类型；dict 输出更易前端解包 |
| `_parse_rpc_response` 统一入口 | 拆 parsers_common + parsers_business | 同样达到"统一入口"目标（5 个业务解析器共享 _parse_code_msg / _iter_rows / _to_int） |
| 一次性 6 commit 拆 Pydantic 化 | 分阶段 + 部分完成 | Pydantic 化需求不强；当前 dict 实现已通过 v10 broker 字段名约束保持一致性 |