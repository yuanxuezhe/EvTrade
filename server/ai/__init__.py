"""
server/ai/ — EvTrade AI 助手 (claudedemo 模式)

架构 (2026-08-24 重做, 取代 self-built Hermes API server 链路):
    Vue AgentPanel (前端按钮, 不动)
        ↓ WS /ws/agent_channel?token=<user JWT> (鉴权)
    server/ws/endpoint.py (WS handler)
        ↓ agent_spawner.send(user_text) + recv(event) 双向
    server/ai/agent_spawner.py — spawn `claude -p` 子进程
        ↓ --mcp-config http://127.0.0.1:{RAND}/mcp 注入
    server/ai/mcp_server.py — HTTP MCP server (127.0.0.1 随机端口)
        ↓ tools/list + tools/call JSON-RPC
    server/ai/tools.py — EvTrade 业务调用 (进程内, 不走 HTTP, 不用 user JWT)

参考: /root/workspcae/codespace/claudedemo/src/{agent,mcp,ui}/*

约束:
    - claude CLI 必须在 EvTrade backend 同机 PATH 中可调用 (本机或容器内)
    - claude 自管 auth (OS keychain), spawn 时不传 ANTHROPIC_API_KEY env
    - MCP server 仅绑 127.0.0.1 (loopback), 不暴露外网
    - spawner 与 WS endpoint 是 FastAPI 进程内通信, 同步接口 + 异步包装
"""