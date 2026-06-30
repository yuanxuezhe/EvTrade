"""
push/routes.py — push 类型 → WS channel 路由表

唯一的 push 路由权威位置，被 push/dispatcher.py 引用。
"""
# 推送类型 → WS channel
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
    "pos_cfm": "position_update",
    "ast_cfm": "asset_update",
}

__all__ = ["_PUSH_CHANNEL"]