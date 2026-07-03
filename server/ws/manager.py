from fastapi import WebSocket
from typing import Dict, Set, Optional
import json

from server.auth.security import decode_token
# v10 增: WS 广播日志 (server-interaction-logging REQ-LOG-003)
#   顶层 import 走 lazy (在 broadcast 函数内), 避免触发 logflow 的循环链
#   实际上 ws.manager 不在循环链上, 但保持一致风格

class WSManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "order_update": set(),
            "trade_update": set(),
            # change consolidate-position-data-flow: position_update / asset_update 频道已删除
            # (xtquant broker 不发 pos_cfm / ast_cfm, 改由 trd_cfm 增量 + day-init reconcile 兜底)
            "quote_update": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str, token: Optional[str] = None):
        await websocket.accept()
        self.active_connections.setdefault(channel, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict, trace_id: Optional[str] = None):
        if channel not in self.active_connections:
            return
        # v10 增: 记 [front<-svc] ws broadcast 日志
        #   trace_id: 上游 push / RPC reply 传下来, 让 [svc<-rpc] push + [front<-svc] ws 配对
        from server.utils.logflow import DIR_SVC_TO_FRONT, log_interaction
        clients = len(self.active_connections[channel])
        log_interaction(
            DIR_SVC_TO_FRONT,
            "ws broadcast channel={} clients={}".format(channel, clients),
            data={"channel": channel, "clients": clients, "payload": message},
            level="info",
            trace_id=trace_id,
        )
        dead_connections = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception as e:
                # 客户端断连: 记 WARN
                log_interaction(
                    DIR_SVC_TO_FRONT,
                    "ws broadcast channel={} 1 client disconnected".format(channel),
                    data={"err": "{}: {}".format(type(e).__name__, e)},
                    level="warning",
                    trace_id=trace_id,
                )
                dead_connections.add(connection)
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)

ws_manager = WSManager()
