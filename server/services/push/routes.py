"""
push/routes.py — push 类型 → WS channel 路由表

唯一的 push 路由权威位置，被 push/dispatcher.py 引用。

仅保留 ord_cfm/trd_cfm 两个推送
(xtquant broker 协议不发送 pos_cfm / ast_cfm)。

pos_push 路由 → channel 'position_update'
  - broker 端 position_callback 推送 pos_push 事件
  - 持仓变化直接覆盖本地 positions 表 + 推前端
  - 不依赖 trd_cfm 累加, 不依赖 reconcile 兜底
  - 系统初始化时 qry_positions RPC 一次性同步
"""
# 推送类型 → WS channel
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
    "pos_push": "position_update",
}

__all__ = ["_PUSH_CHANNEL"]
