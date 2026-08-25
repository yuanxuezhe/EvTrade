from fastapi import WebSocket
from typing import Dict, Set, Optional, Iterable, List

# WS 广播日志 (server-interaction-logging REQ-LOG-003)
#   顶层 import 走 lazy (在 broadcast 函数内), 避免触发 logflow 的循环链
#   实际上 ws.manager 不在循环链上, 但保持一致风格
#
# 订阅模型:
#   - subscription_index (pattern -> set[ws]) + subscriber_index (ws -> set[pattern])
#   - subscribe() / unsubscribe() / clear_ws() 管理订阅
#   - broadcast() 兼容老 channel-level 推送（legacy 兜底）
#   - broadcast_to_stock(stock_code, message) 只推订阅者；零订阅者时返回 False（兼容策略）
#   - get_subscribers_count(stock_code) 用于 health log / metrics
#
# 订阅条件统一走 "子串匹配": pattern in stock_code
#   - pattern = ''  → 任意代码（空字符串是所有字符串的子串，永远 True）
#   - pattern = 'SZ' → 包含 'SZ' 的代码（000001.SZ / 600000.SZ 全部 SZ 市场）
#   - pattern = 'SH' → 包含 'SH' 的代码
#   - pattern = '000001' → 包含 '000001' 的代码（SH/SZ 双边）
#   - pattern = '000001.SZ' → 完整子串匹配
#   - subscription_index 为 Dict[pattern, Set[ws]]
#     （pattern 不展开为具体 stock_code, 节省内存 + 支持灵活匹配）


def match_pattern(stock_code: str, pattern: str) -> bool:
    """子串匹配规则

    设计原则: 一行规则统一所有 case
      - 空字符串 pattern = '' 永远匹配 (空串是任何字符串的子串)
      - pattern 是 stock_code 的子串即匹配

    例子:
      match_pattern('000001.SZ', '')         → True  (空匹配)
      match_pattern('000001.SZ', 'SZ')       → True  (SZ ⊂ 000001.SZ)
      match_pattern('600000.SH', 'SZ')       → False (SH 不含 SZ)
      match_pattern('000001.SZ', '000001')   → True  (000001 ⊂ 000001.SZ)
      match_pattern('000001.SH', '000001.SZ') → False (完整子串不包含)
    """
    return pattern in stock_code


class WSManager:
    # 单 ws 连接允许的最大订阅数（防止恶意前端发超大 stock_codes 数组）
    MAX_SUBSCRIPTIONS_PER_WS = 200

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "order_update": set(),
            "trade_update": set(),
            # position_update channel — broker pos_push 推送
            #   (consolidate-position-data-flow 已废弃; pos_push 是持仓唯一数据源)
            "position_update": set(),
            "quote_update": set(),
            # change 2026-07-15-system-init-broadcast: 系统级事件频道
            #   - 日初成功 → system_status_change
            #   - (后续) 对账失败 / 切日失败等扩展位
            #   - 与 push 事件频道并列，但触发源是 init_trading_day 业务接口而非 broker push
            "system_update": set(),
            # 回测 / live task 进度推送 (ScriptTask.vue 详情实时刷新)
            "task_progress_update": set(),
        }
        #   pattern -> Set[WebSocket]：倒排索引（订阅了此 pattern 的 ws 集合）
        #   pattern 可以是: 具体 stock_code ('000001.SZ') / 市场 ('SZ') / 片段 ('000001') / '' (全市场)
        self.subscription_index: Dict[str, Set[WebSocket]] = {}
        #   WebSocket -> Set[stock_code]：正向索引（此 ws 订阅的所有 pattern，clear 时用）
        self.subscriber_index: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket, channel: str, token: Optional[str] = None):
        await websocket.accept()
        self.active_connections.setdefault(channel, set()).add(websocket)
        # 新 ws 默认无订阅（按 Q2A：默认不收，等用户触发订阅）
        self.subscriber_index.setdefault(websocket, set())

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
        # 同步清理订阅索引（避免 ws 关闭后成为"幽灵订阅者"）
        self.clear_ws(websocket)

    # ─────────────── 订阅管理 ───────────────

    def subscribe(self, websocket: WebSocket, patterns: Iterable[str]) -> Set[str]:
        """订阅一组 patterns，返回成功订阅的集合

        pattern 规则（统一走子串匹配）:
          - ''     → 全市场（空字符串是任何字符串的子串）
          - 'SZ'   → 所有 SZ 市场代码
          - 'SH'   → 所有 SH 市场代码
          - '000001' → 包含 000001 的代码（SH/SZ 双边）
          - '000001.SZ' → 完整子串匹配

        边界:
          - 超过 MAX_SUBSCRIPTIONS_PER_WS → 抛 ValueError（前端应分批）
          - 已订阅 pattern → 静默忽略（幂等）
          - None / 非字符串元素 → 跳过
        """
        pats = set()
        for p in patterns:
            if isinstance(p, str):
                # 允许空字符串（=全市场）；只 strip 保留 pattern 原样
                pats.add(p.strip() if p else "")
        if not pats:
            return set()
        # 上限检查（注意: 全市场 pattern '' 也算 1 个订阅位）
        existing = self.subscriber_index.get(websocket, set())
        new_total = len(existing) + len(pats - existing)
        if new_total > self.MAX_SUBSCRIPTIONS_PER_WS:
            raise ValueError(
                f"max subscriptions per ws = {self.MAX_SUBSCRIPTIONS_PER_WS}, "
                f"existing={len(existing)}, new={len(pats)}"
            )
        # 双向索引 (key 现在是 pattern, 不再是 stock_code)
        self.subscriber_index.setdefault(websocket, set()).update(pats)
        for p in pats:
            self.subscription_index.setdefault(p, set()).add(websocket)
        return pats

    def unsubscribe(self, websocket: WebSocket, patterns: Iterable[str]) -> Set[str]:
        """取消订阅一组 patterns，返回成功取消的集合"""
        pats = set()
        for p in patterns:
            if isinstance(p, str):
                pats.add(p.strip() if p else "")
        if not pats:
            return set()
        removed = set()
        sub = self.subscriber_index.get(websocket)
        if sub:
            for p in pats & sub:
                sub.discard(p)
                removed.add(p)
                # 倒排索引清理
                sock_set = self.subscription_index.get(p)
                if sock_set is not None:
                    sock_set.discard(websocket)
                    if not sock_set:
                        del self.subscription_index[p]
        return removed

    def clear_ws(self, websocket: WebSocket) -> None:
        """ws 断开时调用：清理该 ws 所有 pattern 订阅"""
        pats = self.subscriber_index.pop(websocket, None)
        if not pats:
            return
        for p in pats:
            sock_set = self.subscription_index.get(p)
            if sock_set is not None:
                sock_set.discard(websocket)
                if not sock_set:
                    del self.subscription_index[p]

    def get_subscribers(self, stock_code: str) -> Set[WebSocket]:
        """查 stock_code 的当前订阅者集合（遍历 pattern 匹配）

        遍历所有 pattern, 对每个 pattern 跑 match_pattern(code, pattern),
        命中则合并该 pattern 对应的 ws 集合
        """
        result: Set[WebSocket] = set()
        for pattern, ws_set in self.subscription_index.items():
            if match_pattern(stock_code, pattern):
                result.update(ws_set)
        return result

    def get_subscribed_patterns(self, websocket: WebSocket) -> Set[str]:
        """查 ws 的当前订阅 pattern 集合"""
        return set(self.subscriber_index.get(websocket, set()))

    # ─────────────── 广播（兼容老路径 + 新路径） ───────────────

    async def broadcast(self, channel: str, message: dict, trace_id: Optional[str] = None):
        """全 channel 广播（老路径，向所有 ws conn 推）

        📌 兼容性：
           - 仍保留供 quote_consumer 老 fallback 调用
           - 新前端订阅模式应走 broadcast_to_stock
        """
        if channel not in self.active_connections:
            return
        # 记 [front<-svc] ws broadcast 日志
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

        📌 按订阅推送:
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

    async def broadcast_batch(
        self,
        ticks: List[dict],
        channel: str = "quote_update",
        trace_id: Optional[str] = None,
    ) -> int:
        """批量推送: 1 个 ws frame 装 N 个 tick (按订阅过滤)

        - 输入: ticks = [{stock_code, last_price, snapshot, fields, body}, ...]
        - 输出: 1 个 payload = {type:quote_batch, channel:quote_update, ticks:[...]}
        - 推给所有 ws 客户端, 每个客户端只收到它订阅的 stock_code 对应 tick
        - 返回: 实际推送成功的连接数

        与 broadcast_to_stock 的对比:
        - broadcast_to_stock: N tick = N ws frame (现状低效)
        - broadcast_batch:    N tick (去重后) = 1 ws frame (新方案)
        """
        if not ticks:
            return 0
        # 索引 by stock_code, O(1) 查
        tick_by_code = {t.get("stock_code"): t for t in ticks if t.get("stock_code")}
        if not tick_by_code:
            return 0

        from server.utils.logflow import DIR_SVC_TO_FRONT, log_interaction

        # 找出所有活跃 ws 客户端 (避免对无订阅 ws 推空 batch)
        active_ws = list(self.active_connections.get(channel, set()))
        if not active_ws:
            return 0

        delivered = 0
        dead = set()
        for ws in active_ws:
            sub_patterns = self.subscriber_index.get(ws)
            if not sub_patterns:
                continue
            # 过滤本 ws 订阅的 tick (按 pattern 子串匹配)
            matched = []
            for pattern in sub_patterns:
                for stock_code, tick in tick_by_code.items():
                    if match_pattern(stock_code, pattern) and tick not in matched:
                        matched.append(tick)
            if not matched:
                continue
            payload = {
                "type": "quote_batch",
                "channel": channel,
                "data": {"ticks": matched},
            }
            try:
                await ws.send_json(payload)
                delivered += 1
            except Exception as e:
                log_interaction(
                    DIR_SVC_TO_FRONT,
                    "ws broadcast_batch 1 client disconnected",
                    data={"err": "{}: {}".format(type(e).__name__, e), "tick_count": len(matched)},
                    level="warning",
                    trace_id=trace_id,
                )
                dead.add(ws)

        for ws in dead:
            self.clear_ws(ws)
            self.active_connections.get(channel, set()).discard(ws)

        log_interaction(
            DIR_SVC_TO_FRONT,
            "ws broadcast_batch ticks={} subs={}".format(len(tick_by_code), delivered),
            data={"channel": channel, "ticks": len(tick_by_code), "clients": delivered},
            level="info",
            trace_id=trace_id,
        )
        return delivered


ws_manager = WSManager()