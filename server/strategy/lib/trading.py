"""
server/strategy/lib/trading.py — 下单 / 撤单 wrapper

📌 设计：
- doorder / docancel / get_position 是用户脚本调用的 facade
- 行为由 ctx.mode 决定:
    * 'backtest': 仅记录到 ctx.audit_log + 维护 ctx.sim_position, 不调 RPC
    * 'live':    调 server.api.orders.ord_stk / cancel_order (走真实 broker RPC)
- ctx 由 runtime 注入 (sandbox 加载时构造)

📌 用户脚本调用约定:
    lib.doorder('600519.SH', 'BUY', 1680.5, 100)   # 限价单
    lib.doorder('600519.SH', 'BUY', 1680.5, 100, price_type='market')
    lib.docancel(order_no, trd_date)
    pos = lib.get_position('600519.SH')

📌 实盘模式额外校验:
- 价格 / 数量必须在合理范围 (防止策略脚本 bug 把账户砸穿)
- 单笔成交量 ≤ 10000 股 / ETF 10000 份 (硬上限, 超出抛 ValueError)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


# ─────────────── 异常 ───────────────


class OrderError(Exception):
    """下单 / 撤单错误 (回测和实盘共用)"""
    pass


class SignalRecorder:
    """信号记录器 — 由 runtime 在构造 ctx 时注入

    用法 (用户脚本):
        ctx.lib.signal('金叉 MA5 > MA20', type='INFO')   # 纯信号, 不下单
        doorder(...)                                       # 自动产生 type=BUY/SELL 的信号
    """

    def __init__(self):
        self.log: List[Dict[str, Any]] = []
        self.indicator_snapshot_keys: Tuple[str, ...] = ()  # 由 runtime 注入

    def record(
        self,
        type_: str,
        msg: str = "",
        price: Optional[float] = None,
        indicators: Optional[Dict[str, Any]] = None,
        state: Optional[Dict[str, Any]] = None,
        pnl: Optional[float] = None,
        order_no: Optional[str] = None,
    ) -> None:
        """记录一条信号 (用户脚本可调, 也可由 doorder 自动调)"""
        entry: Dict[str, Any] = {
            "type": type_,
            "msg": msg,
        }
        if price is not None:
            entry["price"] = round(price, 4) if isinstance(price, float) else price
        if indicators is not None:
            entry["indicators"] = indicators
        if state is not None:
            entry["state"] = state
        if pnl is not None:
            entry["pnl"] = round(pnl, 4) if isinstance(pnl, float) else pnl
        if order_no is not None:
            entry["order_no"] = order_no
        self.log.append(entry)


# ─────────────── 通用校验 ───────────────


MAX_VOLUME = 10000       # 单笔硬上限
MIN_PRICE = 0.001        # 最低价
MAX_PRICE = 10000.0      # 最高价 (够 A 股 / ETF / 期货)


def _validate_order(stock_code: str, side: str, price: float, volume: int) -> None:
    """参数校验 (回测 / 实盘都跑)"""
    if not stock_code or not isinstance(stock_code, str):
        raise OrderError(f"stock_code 必须是非空字符串, 收到 {stock_code!r}")
    if side not in ("BUY", "SELL"):
        raise OrderError(f"side 必须是 'BUY' / 'SELL', 收到 {side!r}")
    if not isinstance(price, (int, float)) or price < MIN_PRICE or price > MAX_PRICE:
        raise OrderError(f"price {price} 超出范围 [{MIN_PRICE}, {MAX_PRICE}]")
    if not isinstance(volume, int) or volume <= 0 or volume > MAX_VOLUME:
        raise OrderError(f"volume {volume} 超出范围 (1, {MAX_VOLUME}]")


# ─────────────── backtest 模式 ───────────────


class _BacktestTradingFacade:
    """回测模式 trading facade (用 ctx 维护模拟持仓 + 审计日志)

    📌 ctx 字段约定:
        - mode = 'backtest'
        - sim_positions: dict[stock_code, int] 持仓量
        - sim_cash: float                        模拟现金
        - sim_initial_cash: float                初始现金
        - audit_log: list[dict]                  模拟下单日志
        - signals: SignalRecorder                信号流 (用户脚本 + doorder 自动记录)
        - current_trd_date: str                  模拟交易日
        - bar: dict                              当前 bar
        - bar_idx: int                           当前 bar 在 bars 列表里的索引
    """

    def signal(self, msg: str, type_: str = "INFO", **kw) -> None:
        """用户脚本主动记录一条信号 (不影响交易)

        Args:
            msg: 简短描述, e.g. '金叉 MA5 > MA20'
            type_: 'INFO' / 'WARN' / 'BUY' / 'SELL' (用户也可自己用 'EXIT' 等)
            **kw: 透传给 SignalRecorder.record (price/indicators/state/pnl/order_no)
        """
        signals = self._ctx.get("signals")
        if signals is not None:
            signals.record(type_=type_, msg=msg, **kw)

    def doorder(
        self,
        stock_code: str,
        side: str,
        price: float,
        volume: int,
        *,
        price_type: str = "limit",
    ) -> str:
        ctx = self._ctx
        _validate_order(stock_code, side, price, volume)

        # v10+ 风控检查 (risk_checker 放在 ctx 上, 由 BacktestEngine 注入)
        risk = ctx.get("_risk_checker")
        if risk is not None:
            current_pos = ctx["sim_positions"].get(stock_code, 0)
            current_cash = ctx["sim_cash"]
            # 持仓市值 (回测模式: 用当前 bar 的 close 或下单价)
            mark_price = price if price > 0 else 0
            pos_value = current_pos * mark_price
            trd_date = ctx.get("current_trd_date", "")
            ok, reason = risk.check_before_order(
                side=side, price=price, qty=volume,
                current_position=current_pos, current_cash=current_cash,
                current_position_value=pos_value, trd_date=trd_date,
            )
            if not ok:
                # 风控拒绝: 写 signal WARN, 不抛异常 (脚本继续跑)
                signals = ctx.get("signals")
                if signals is not None:
                    signals.record(type_="WARN", msg=f"风控拒单: {reason}")
                ctx.setdefault("risk_rejected", []).append({"reason": reason, "side": side, "price": price, "volume": volume})
                log.warning("[risk] 拒单: %s", reason)
                return ""  # 返空 order_no (脚本可判断)
            risk.record_trade(trd_date)

        # 计算成交 (T+1 简化: 立即成交, 立即持仓变化)
        positions = ctx["sim_positions"]
        cash = ctx["sim_cash"]
        cost = price * volume

        if side == "BUY":
            if cash < cost:
                raise OrderError(
                    f"BUY 资金不足: 需 {cost:.2f}, 现金 {cash:.2f}"
                )
            positions[stock_code] = positions.get(stock_code, 0) + volume
            ctx["sim_cash"] = cash - cost
        else:  # SELL
            pos = positions.get(stock_code, 0)
            if pos < volume:
                raise OrderError(
                    f"SELL 持仓不足: 需 {volume}, 持仓 {pos}"
                )
            positions[stock_code] = pos - volume
            ctx["sim_cash"] = cash + cost

        # 生成模拟 order_no (8 位数字, 时间戳后 6 位 + 2 位序号)
        order_no = self._next_order_no()
        log_entry = {
            "order_no": order_no,
            "stime": ctx.get("bar", {}).get("stime", ""),
            "stock_code": stock_code,
            "side": side,
            "price": price,
            "volume": volume,
            "price_type": price_type,
            "status": "filled",      # 回测假设立即成交
            "filled_price": price,
            "filled_volume": volume,
        }
        ctx.setdefault("audit_log", []).append(log_entry)

        # 自动记录一条信号 (type=BUY/SELL)
        signals = ctx.get("signals")
        if signals is not None:
            signals.record(
                type_=side,
                msg=f"{side} {stock_code} {volume}股 @ {price}",
                price=price,
                state={
                    "position": positions.get(stock_code, 0),
                    "cash": round(ctx["sim_cash"], 2),
                },
                order_no=order_no,
            )
        return order_no

    def docancel(self, order_no: str, trd_date: str) -> bool:
        ctx = self._ctx
        for entry in ctx.get("audit_log", []):
            if entry["order_no"] == order_no:
                entry["status"] = "cancelled"
                return True
        return False

    def get_position(self, stock_code: str) -> int:
        return self._ctx.get("sim_positions", {}).get(stock_code, 0)

    def get_cash(self) -> float:
        return self._ctx.get("sim_cash", 0.0)

    def _next_order_no(self) -> str:
        # 简化: 用 ctx.counter (从 1 开始)
        ctx = self._ctx
        ctx["counter"] = ctx.get("counter", 0) + 1
        # 8 位数字, 前 6 位是交易日 (YYYYMMDD 简化用 '900001'), 后 2 位计数
        # 真实场景由 next_order_no(DB) 生成; 回测这里简化即可
        return f"9{ctx.get('current_trd_date', '000000')[-6:]}{ctx['counter']:02d}"[-8:].zfill(8)


# ─────────────── live 模式 ───────────────


class _LiveTradingFacade:
    """实盘模式 trading facade — 调 server.api.orders.ord_stk

    📌 ord_stk / cancel_order 是 async 函数, 但用户脚本是 sync def。
       用 asyncio.run_coroutine_threadsafe 把 coroutine 投到主事件循环执行。
       这是 FastAPI 进程内嵌的标准做法。
    """

    def signal(self, msg: str, type_: str = "INFO", **kw) -> None:
        """实盘模式信号记录 — 写入 ctx['signals'] (SignalRecorder)"""
        signals = self._ctx.get("signals")
        if signals is not None:
            signals.record(type_=type_, msg=msg, **kw)

    def doorder(
        self,
        stock_code: str,
        side: str,
        price: float,
        volume: int,
        *,
        price_type: str = "limit",
    ) -> str:
        _validate_order(stock_code, side, price, volume)

        ctx = self._ctx
        loop = ctx.get("event_loop")
        if loop is None:
            raise OrderError("live mode: ctx.event_loop 未设置")

        from server.api.orders import ord_stk
        from server.enums.trading import PriceType, OrderType

        order_type_int = "23" if side == "BUY" else "24"
        price_type_int = PriceType.MKT_PRICE if price_type == "market" else PriceType.FIX_PRICE

        # 异步调用投到主事件循环 (阻塞当前线程等结果)
        async def _call():
            return await ord_stk(
                stock_code=stock_code,
                order_type=order_type_int,
                price_type=price_type_int,
                price=price,
                volume=volume,
            )

        future = asyncio.run_coroutine_threadsafe(_call(), loop)
        try:
            ack = future.result(timeout=10)
        except Exception as e:
            raise OrderError(f"ord_stk RPC 失败: {e}") from e

        # v84: broker ord_cfm push 异步处理真实 broker_order_id; 这里只回 order_no
        order_no = ack.get("order_no", "") if isinstance(ack, dict) else ""

        # 记录信号
        signals = self._ctx.get("signals")
        if signals is not None:
            pos = self.get_position(stock_code)
            signals.record(
                type_=side,
                msg=f"{side} {stock_code} {volume}股 @ {price}",
                price=price,
                state={"position": pos},
                order_no=order_no,
            )
        return order_no

    def docancel(self, order_no: str, trd_date: str) -> bool:
        ctx = self._ctx
        loop = ctx.get("event_loop")
        if loop is None:
            raise OrderError("live mode: ctx.event_loop 未设置")

        from server.rpc.client import cancel_order

        async def _call():
            return await cancel_order(order_no=order_no, trd_date=trd_date)

        future = asyncio.run_coroutine_threadsafe(_call(), loop)
        try:
            ack = future.result(timeout=10)
        except Exception as e:
            raise OrderError(f"cancel_order RPC 失败: {e}") from e

        code = ack.get("code", -1) if isinstance(ack, dict) else -1
        return code == 0

    def get_position(self, stock_code: str) -> int:
        """实盘模式查持仓走 Positions 表"""
        from server.tables import Positions
        row = Positions.query_by_fields({"stock_code": stock_code})
        if not row:
            return 0
        return int(row[0].get("volume", 0) or 0)


# ─────────────── facade 工厂 ───────────────


def make_trading_facade(ctx: Dict[str, Any]):
    """根据 ctx.mode 返 trading facade

    Args:
        ctx: 由 runtime 构造, 含 mode / event_loop / sim_cash 等
    Returns:
        BacktestTradingFacade 或 LiveTradingFacade 实例
    """
    mode = ctx.get("mode", "backtest")
    if mode == "backtest":
        facade = _BacktestTradingFacade()
    elif mode == "live":
        facade = _LiveTradingFacade()
    else:
        raise OrderError(f"未知 mode: {mode!r}")
    facade._ctx = ctx  # type: ignore[attr-defined]
    return facade


# ─────────────── 用户脚本便捷别名 ───────────────
# 用户脚本: `from server.strategy.lib import doorder, docancel, get_position`
# 实际由 sandbox 在加载时把 facade 函数注入 globals

def doorder(stock_code: str, side: str, price: float, volume: int, *, price_type: str = "limit") -> str:
    """用户脚本直接调 doorder(ctx, ...) 走 facade 注入; 此处为 stub 由 sandbox 替换"""
    raise OrderError("doorder 必须由 sandbox 注入调用")


def docancel(order_no: str, trd_date: str) -> bool:
    raise OrderError("docancel 必须由 sandbox 注入调用")


def get_position(stock_code: str) -> int:
    raise OrderError("get_position 必须由 sandbox 注入调用")


def signal(msg: str, type_: str = "INFO", **kw) -> None:
    """用户脚本主动记录一条信号 (不交易, 仅供回测/实盘日志分析)

    用法:
        signal('金叉 MA5>MA20', type_='INFO')
        signal('跌破止损', type_='WARN', price=bar['close'], indicators={'MA5': ma5})

    注意: 跟 stdlib signal 同名, 但本 stub 仅作占位; sandbox 注入时
    会覆盖, 用户脚本调 signal() 实际走 facade.signal()
    """
    raise OrderError("signal 必须由 sandbox 注入调用")


__all__ = [
    "OrderError",
    "make_trading_facade",
    "doorder", "docancel", "get_position",
    "MAX_VOLUME",
]