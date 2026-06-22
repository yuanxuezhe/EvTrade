from fastapi import WebSocket
from typing import Dict, Set, Optional
import json

from server.auth.security import decode_token

class WSManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "order_update": set(),
            "trade_update": set(),
            "position_update": set(),
            "asset_update": set(),
            "quote_update": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str, token: Optional[str] = None):
        await websocket.accept()
        self.active_connections.setdefault(channel, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict):
        if channel not in self.active_connections:
            return
        dead_connections = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)

ws_manager = WSManager()
