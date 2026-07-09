from fastapi import WebSocket
from typing import Dict, Set, Optional, Iterable

# v10 增: WS 广播日志 (server-interaction-logging REQ-LOG-003)
#   顶层 import 走 lazy (在 broadcast 函数内), 避免触发 logflow 的循环链
#   实际上 ws.manager 不在循环链上, 但保持一致风格
#
# 2026-07-09 quote-snapshot-subscribe:
#   - 加 subscription_index (stock_code -> set[ws]) + subscriber_index (ws -> set[stock_code])
#   - subscribe() / unsubscribe() / clear_ws() 管理订阅
#   - broadcast() 兼容老 channel-level 推送（legacy 兜底）
#   - broadcast_to_stock(stock_code, message) 只推订阅者；零订阅者时返回 False（兼容策略）
#   - get_subscribers_count(stock_code) 用于 health log / metrics


class WSManager:
    # 单 ws 连接允许的最大订阅数（防止恶意前端发超大 stock_codes 数组）
    MAX_SUBSCRIPTIONS_PER_WS = 200

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "order_update": set(),
            "trade_update": set(),
            # change consolidate-position-data-flow: position_update / asset_update 频道已删除
            # (xtquant broker 不发 pos_cfm / ast_cfm, 改由 trd_cfm 增量 + day-init reconcile 兜底)
            "quote_update": set(),
            # change strategy_trade: 策略引擎事件频道（regime_changed / grid_triggered / regime_cooldown）
            "strategy_update": set(),
        }
        # 2026-07-09 quote-snapshot-subscribe:
        #   stock_code -> Set[WebSocket]：倒排索引（订阅了此 code 的 ws 集合）
        self.subscription_index: Dict[str, Set[WebSocket]] = {}
        #   WebSocket -> Set[stock_code]：正向索引（此 ws 订阅的所有 code，clear 时用）
        self.subscriber_index: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket, channel: str, token: Optional[str] = None):
        await websocket.accept()
        self.active_connections.setdefault(channel, set()).add(websocket)
        # 2026-07-09: 新 ws 默认无订阅（按 Q2A：默认不收，等用户触发订阅）
        self.subscriber_index.setdefault(websocket, set())

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
        # 2026-07-09: 同步清理订阅索引（避免 ws 关闭后成为"幽灵订阅者"）
        self.clear_ws(websocket)

    # ─────────────── 订阅管理（2026-07-09 新增） ───────────────

    def subscribe(self, websocket: WebSocket, stock_codes: Iterable[str]) -> Set[str]:
        """订阅一组 stock_codes，返回成功订阅的集合（去重 + 上限检查）

        - 超过 MAX_SUBSCRIPTIONS_PER_WS → 抛 ValueError（前端应分批）
        - 已订阅 code → 静默忽略（幂等）
        """
        codes = set()
        for c in stock_codes:
            if isinstance(c, str) and c.strip():
                codes.add(c.strip())
        if not codes:
            return set()
        # 上限检查
        existing = self.subscriber_index.get(websocket, set())
        new_total = len(existing) + len(codes - existing)
        if new_total > self.MAX_SUBSCRIPTIONS_PER_WS:
            raise ValueError(
                f"max subscriptions per ws = {self.MAX_SUBSCRIPTIONS_PER_WS}, "
                f"existing={len(existing)}, new={len(codes)}"
            )
        # 双向索引
        self.subscriber_index.setdefault(websocket, set()).update(codes)
        for c in codes:
            self.subscription_index.setdefault(c, set()).add(websocket)
        return codes

    def unsubscribe(self, websocket: WebSocket, stock_codes: Iterable[str]) -> Set[str]:
        """取消订阅一组 stock_codes，返回成功取消的集合"""
        codes = set()
        for c in stock_codes:
            if isinstance(c, str) and c.strip():
                codes.add(c.strip())
        if not codes:
            return set()
        removed = set()
        sub = self.subscriber_index.get(websocket)
        if sub:
            for c in codes & sub:
                sub.discard(c)
                removed.add(c)
                # 倒排索引清理
                sock_set = self.subscription_index.get(c)
                if sock_set is not None:
                    sock_set.discard(websocket)
                    if not sock_set:
                        del self.subscription_index[c]
        return removed

    def clear_ws(self, websocket: WebSocket) -> None:
        """ws 断开时调用：清理该 ws 所有订阅"""
        codes = self.subscriber_index.pop(websocket, None)
        if not codes:
            return
        for c in codes:
            sock_set = self.subscription_index.get(c)
            if sock_set is not None:
                sock_set.discard(websocket)
                if not sock_set:
                    del self.subscription_index[c]

    def get_subscribers(self, stock_code: str) -> Set[WebSocket]:
        """查 stock_code 的当前订阅者集合"""
        return self.subscription_index.get(stock_code, set())

    def get_subscribed_codes(self, websocket: WebSocket) -> Set[str]:
        """查 ws 的当前订阅集合"""
        return set(self.subscriber_index.get(websocket, set()))

    # ─────────────── 广播（兼容老路径 + 新路径） ───────────────

    async def broadcast(self, channel: str, message: dict, trace_id: Optional[str] = None):
        """全 channel 广播（老路径，向所有 ws conn 推）

        📌 2026-07-09 兼容性：
           - 仍保留供 quote_consumer 老 fallback 调用
           - 新前端订阅模式应走 broadcast_to_stock
        """
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

    async def broadcast_to_stock(
        self,
        stock_code: str,
        message: dict,
        channel: str = "quote_update",
        trace_id: Optional[str] = None,
    ) -> int:
        """按 stock_code 推给订阅者；返回实际推送成功的连接数

        📌 2026-07-09 quote-snapshot-subscribe:
           - 倒排索引查 stock_code 的 ws 子集
           - 失败 ws 自动清理订阅索引（防止幽灵订阅）
           - 与 broadcast() 共享同一组 active_connections（同一 ws conn）
        """
        subs = self.get_subscribers(stock_code)
        if not subs:
            return 0  # 零订阅者 → 不推（避免广播风暴）
        from server.utils.logflow import DIR_SVC_TO_FRONT, log_interaction

        delivered = 0
        dead = set()
        for ws in subs:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception as e:
                log_interaction(
                    DIR_SVC_TO_FRONT,
                    "ws broadcast_to_stock stock={} 1 client disconnected".format(stock_code),
                    data={"err": "{}: {}".format(type(e).__name__, e)},
                    level="warning",
                    trace_id=trace_id,
                )
                dead.add(ws)
        for ws in dead:
            # 清理失效订阅
            self.clear_ws(ws)
            if channel in self.active_connections:
                self.active_connections[channel].discard(ws)
        return delivered


ws_manager = WSManager()