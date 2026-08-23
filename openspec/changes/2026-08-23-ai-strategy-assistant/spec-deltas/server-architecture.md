# Spec Delta — server-architecture (hermes RPC 客户端 + 沙箱)

## REQ-ARCH-007: Hermes RPC 客户端 + LLM 沙箱 (2026-08-23, ai-strategy-assistant change)

### Purpose

EvTrade 后端需要调用外部 Hermes Agent daemon（`hermes serve` 默认 127.0.0.1:9119）来驱动 LLM 生成策略代码。本 spec 约束 RPC 客户端封装 + 沙箱边界，避免 LLM 越权。

### 客户端契约

- **文件**：`server/services/hermes_client.py`（新增，归属 services 层）
- **接口**：
  - `chat(prompt: str, *, model: str = "MiniMax-M3", timeout: float = 60.0) -> str`
  - `is_reachable() -> bool` — health check（GET `/healthz`）
- **协议**：JSON-RPC over HTTP（POST `/v1/chat`），与 hermes serve daemon 兼容
- **配置**：
  - `HERMES_SERVE_URL` 环境变量（默认 `http://127.0.0.1:9119`，hardcoded 兜底）
  - 不依赖 hermes 配置文件（避免 EvTrade 与 hermes 配置耦合）

### 沙箱边界（关键约束）

- LLM 调用必须在 hermes daemon 的 `worktree` 隔离中运行（hermes 默认行为）
- **禁止**让 LLM prompt 注入：
  - EvTrade 任何文件绝对路径
  - 数据库连接串 / API key / JWT secret
  - 用户凭证 / 用户输入以外的上下文
- 后端解析 LLM 输出 → 仅提取 ```python ... ``` 代码块 → 其余文本丢弃
- 提取失败 → 抛 `HermesNoPythonCodeError` → API 层映射 422

### 错误处理

| 异常 | HTTP | 含义 |
|---|---|---|
| `HermesUnreachableError` | 503 | daemon 未起 / 网络不可达 |
| `HermesTimeoutError` | 504 | LLM 调用超时（>60s） |
| `HermesNoPythonCodeError` | 422 | LLM 输出无 ```python 代码块 |
| `HermesInternalError` | 500 | 其他 hermes / 网络异常 |

### 测试

- `server/tests/test_hermes_client.py` 单测：
  - `test_chat_success`（mock HTTP 200 + 合法返回）
  - `test_chat_no_python_code`（mock 返回纯 prose）
  - `test_chat_timeout`（mock sleep > 60s）
  - `test_chat_unreachable`（mock connection refused）
  - `test_extract_python_code_*`（多种 LLM 输出形态）

### Refs

- `openspec/changes/2026-08-23-ai-strategy-assistant/proposal.md`
- `openspec/specs/server-architecture/spec.md` REQ-ARCH-001 ~ REQ-ARCH-006 现有 5 层契约
