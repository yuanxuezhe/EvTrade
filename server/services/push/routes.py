"""
push/routes.py — push 类型 → WS channel 路由表

唯一的 push 路由权威位置，被 push/dispatcher.py 引用。

change consolidate-position-data-flow: 仅保留 ord_cfm/trd_cfm 两个推送
(xtquant broker 协议不发送 pos_cfm / ast_cfm)。
"""
# 推送类型 → WS channel
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
}

__all__ = ["_PUSH_CHANNEL"]
