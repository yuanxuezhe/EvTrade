"""
ws/__init__.py — WebSocket 子系统

暴露：
- ws_manager: 全局单例（被业务推送 / 端点共用）
- WSManager: 类（测试时用）
- register_ws_endpoint(app): 在 FastAPI app 上注册 /ws/{channel} 端点
"""
from server.ws.manager import ws_manager, WSManager
from server.ws.endpoint import register_ws_endpoint

__all__ = ["ws_manager", "WSManager", "register_ws_endpoint"]
