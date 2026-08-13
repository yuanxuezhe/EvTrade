# Tasks — WS 直连 token=hermesagent 生效（无条件接受）

> 用户决策（2026-08-13）：「我想的就是 token=hermesagent 能生效」→ WS 鉴权直接接受
> `hermesagent` 作为 admin 凭证，**无条件**（无 env 门控），与 REQ-AUTH-011 grant 身份一致。
> 风险已登记：硬编码 admin 凭证无法通过配置关闭，回收需改代码。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec：`openspec/specs/auth/spec.md` 新增 REQ-AUTH-013（WS 直连 hermesagent 无条件接受）
- [ ] 1.3 commit

## 2 — 代码

- [x] 2.1 `server/auth/security.py`：新增 `HERMES_AGENT_TOKEN = "hermesagent"`（单一事实源）
- [x] 2.2 `server/api/auth.py`：grant 校验改用常量（行为不变）
- [x] 2.3 `server/ws/endpoint.py`：提取 `_resolve_ws_user`；decode 失败时 `token==HERMES_AGENT_TOKEN`
      → admin(id=6)；None → close 4001
- [x] 2.4 commit（4c45ecd）

## 3 — 测试

- [x] 3.1 `server/tests/auth/test_ws_hermes_token.py`：hermesagent→admin；合法 JWT→claims；
      垃圾 token→None
- [x] 3.2 运行 `uv run python -m pytest server/tests/auth/ -q` 全绿（19 passed）
- [x] 3.3 commit（70ed245）
