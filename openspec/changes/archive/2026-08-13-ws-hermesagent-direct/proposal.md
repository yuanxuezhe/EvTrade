# 2026-08-13-ws-hermesagent-direct — WS 直连 token=hermesagent 生效

## Why

hermes agent（策略执行环境）用 `wss://…/ws/quote_update?token=hermesagent` 连不上。

根因：`"hermesagent"` 只是 grant 交换密钥，不是 JWT。WS 端点 `_resolve`（endpoint.py:79）
拿 `?token=` 当 JWT 验签 → `decode_token("hermesagent")` 返回 None → `close 4001 "Invalid token"`。

用户确认（2026-08-13）：「我想的就是 token=hermesagent 能生效」——要求 WS 直连时
`token=hermesagent` 直接放行，跳过 grant 换 JWT 的仪式。

## 决策（用户明确选择）

- **无条件接受** `token=hermesagent`：WS 鉴权 decode_token 失败时，若 `token == "hermesagent"`
  直接视为 admin 身份（user_id=6），**不做 env 门控**（区别于 REQ-AUTH-011 grant 端点的
  `EVTRADE_ALLOW_GRANT_TOKEN` 开关）。
- 身份与 grant 一致：`{sub:"6", id:6, role:"admin", username:"admin"}`。
- 影响面：所有非 admin 频道（quote_update 等）无需任何门控即可连；`sync_update` 频道的
  DB admin 校验（endpoint.py:84-93）对 user 6 也会通过 → hermesagent 同样能进 sync_update。

## 安全备注（风险登记，用户已知情）

`hermesagent` 变成 WS 上**无法关闭的硬编码 admin 凭证**（短期 JWT 仍更安全，但本系统为
私有单机 + hermes 白名单集成，用户选择省掉 JWT 仪式）。若未来要回收：改代码或做门控。

## What Changes

### server/auth/security.py

新增单一事实源常量：

```python
# v129: 技能包 hermes agent 固定授信 token (REQ-AUTH-011). WS 直连 / grant 共用.
HERMES_AGENT_TOKEN = "hermesagent"
```

### server/api/auth.py

grant 端点 `token_str != "hermesagent"` → 改用 `HERMES_AGENT_TOKEN`（单一来源，行为不变）。

### server/ws/endpoint.py

提取 `_resolve_ws_user(token) -> dict | None`：

```python
def _resolve_ws_user(token: str):
    user = decode_token(token)
    if user:
        return user
    # v129: hermes agent 直连 —— 无条件接受 token=hermesagent → admin(id=6), 用户决策
    if token == HERMES_AGENT_TOKEN:
        return {"sub": "6", "id": 6, "role": "admin", "username": "admin"}
    return None
```

`websocket_endpoint` 原 `decode_token(token)` 判定改为 `_resolve_ws_user(token)`，
None → close 4001。

### 测试

`server/tests/auth/test_ws_hermes_token.py`：hermesagent→admin；合法 JWT→claims；
垃圾 token→None。

## 时序

```
wss://…/ws/quote_update?token=hermesagent
  → endpoint: _resolve_ws_user("hermesagent")
  → decode_token("hermesagent") = None
  → token == HERMES_AGENT_TOKEN → {id:6, role:admin}
  → 连接接受, 正常订阅 quote_update
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 鉴权 | `server/auth/security.py` | 新增 `HERMES_AGENT_TOKEN` 常量 |
| API | `server/api/auth.py` | grant 改用常量（行为不变） |
| WS | `server/ws/endpoint.py` | `_resolve_ws_user`：decode 失败时接受 hermesagent |
| 测试 | `server/tests/auth/test_ws_hermes_token.py` | 新增 3 case |
| 知识库 | `openspec/specs/auth/spec.md` | 新增 REQ：WS 直连 hermesagent 无条件接受 |

## 关联

- 上游：`REQ-AUTH-011`（grant 永久 token）；`server/ws/endpoint.py`（WS 鉴权）
- 影响面：WS 所有 channel 鉴权入口（quote_update / order_update / trade_update / strategy_update / sync_update）
