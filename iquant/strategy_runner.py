# coding: gbk
"""
strategy_runner.py -- 黄金短线打法 (PDF 优化版)

参考: iquant/指标投资应用四：黄金的短线打法实盘作业.pdf

落地的 PDF 关键规则:
1. 顺势入场: 慢线 EMA(C, slow) 作为大周期趋势代理 (PDF 中 30 分钟级别),
   只在顺势方向开仓 (价站上慢线 -> 多; 踩下慢线 -> 空).
2. 锤子形态 (hammer, 比 TongDaXin 原 F1_1/F2_1 更严):
   - 阳线锤子: C>O 且 下影 >= 1.5*body 且 上影 < body
   - 阴线锤子: C<O 且 上影 >= 1.5*body 且 下影 < body
   - 叠加 TongDaXin 通道突破 (O > UP1 OR C < DW1 等).
   - 实体 / bar 范围 <= 0.40 才算锤子 (PDF "你要 2:3 位置").
3. 严格止损: 入场后每 bar 检查
   - long: low <= stop_price -> STOP 出场 (含 PnL)
   - short: high >= stop_price -> STOP 出场
   阳线上 TF 上曲折价 (高于入场价 1%) -> TP 出场.
   PDF "不要等回本, 走到止损位走".
4. 仓位状态机: idle / long / short.
   持仓期间不开新仓 (简化 PDF "加仓到 2 lot" 步骤).
5. 复盘记录: 每次 ENTRY / STOP / TP 都记录到 events, 末尾一次性打印,
   含 PnL (只在 STOP / TP 里).

TongDaXin 原公式:
  UP1 = EMA(H, tf1=26)
  DW1 = EMA(L, tf1=26)
仍保留, 用于锤子形态中的 "通道突破" 判定.
但入场判定升级为 "锤子 + 顺势" 组合.

事件 schema (与 quota_his_test 集成):
  {
    "event":  "ENTRY"|"STOP"|"TP",
    "stime":  "20260701110000",
    "side":   "BUY"|"SELL",      # 订单方向 (BUY=开多/平空, SELL=开空/平多)
    "price":  float,              # 成交价
    "trend":  "rising"|"falling",
    "stop":   float,              # ENTRY 才有
    "tp":     float,              # ENTRY 才有
    "atr":    float,              # ENTRY 才有
    "slow":   float,              # ENTRY 才有 (慢线 EMA 当时值)
    "pnl":    float,              # STOP/TP 才有 (实现亏损)
    "up1":    float,
    "dw1":    float,
  }
"""

from typing import Callable


class _EMA:
    """增量 EMA: alpha = 2/(N+1), 首条 seed 为其自身."""
    __slots__ = ("alpha", "value", "seeded")

    def __init__(self, period: int) -> None:
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.seeded = False

    def update(self, x: float) -> float:
        if not self.seeded:
            self.value = x
            self.seeded = True
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class _ATR:
    """SMA ATR: 维护最近 N 个 TR, 取均值. 简单稳定, 超参 RMA ATR 不多于 PDF 需求."""
    __slots__ = ("period", "trs", "prev_close", "value")

    def __init__(self, period: int) -> None:
        self.period = period
        self.trs = []
        self.prev_close = None
        self.value = 0.0

    def update(self, h, l, c):
        if self.prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.trs.append(tr)
        if len(self.trs) > self.period:
            self.trs.pop(0)
        if self.trs:
            self.value = sum(self.trs) / len(self.trs)
        self.prev_close = c
        return self.value


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _is_hammer(c, o, h, l, side):
    """锤子形态: 小实体 + 长单边影线."""
    body = abs(c - o)
    bar = h - l
    if bar <= 0 or body / bar > 0.40:
        return False
    lower = min(c, o) - l
    upper = h - max(c, o)
    if side == "bull":
        return (c > o) and (lower >= 1.5 * body) and (upper < body)
    return (c < o) and (upper >= 1.5 * body) and (lower < body)


def make_strategy_runner(
    tf1: int = 26,
    slow: int = 89,
    atr_period: int = 14,
    stop_atr: float = 1.5,
    tp_pct: float = 0.01,
) -> Callable:
    """PDF 黄金短线打法的 on_quote 回调实现.

    Args:
        tf1: 通道 EMA 周期 (H/L). Default 26.
        slow: 慢线 EMA 顺势过滤 (C). Default 89.
        atr_period: ATR 周期. Default 14.
        stop_atr: 止损距 = stop_atr * ATR. Default 1.5.
        tp_pct: 止盈百分比. Default 1% (0.01).

    Returns:
        on_quote callback. 附加方法:
          - get_events() / get_signals() -> list[event dict]
                (get_signals 是 get_events 的别名, 兼容旧 API)
          - get_state() -> dict
    """
    ema_h = _EMA(tf1)
    ema_l = _EMA(tf1)
    ema_slow = _EMA(slow)
    atr = _ATR(atr_period)

    state = {
        "bar_count": 0,
        "events": [],
        "pos": "idle",
        "entry_price": 0.0,
        "stop_price": 0.0,
        "tp_price": 0.0,
        "qty": 0,
        "last_atr": 0.0,
        "last_slow": 0.0,
    }

    def _on_quote(columns, row):
        h, l, o, c = (_f(row.get(k)) for k in ("high", "low", "open", "close"))
        if None in (h, l, o, c):
            return
        stime = row.get("stime", "?")
        state["bar_count"] += 1

        up1 = ema_h.update(h)
        dw1 = ema_l.update(l)
        esl = ema_slow.update(c)
        tr_atr = atr.update(h, l, c)
        state["last_atr"] = tr_atr
        state["last_slow"] = esl

        # warmup: bar_count 超过 slow + atr_period 才发信号
        if state["bar_count"] < slow + atr_period or tr_atr <= 0:
            return

        # === 持仓: 检查 stop / TP ===
        pos = state["pos"]
        if pos == "long":
            if l <= state["stop_price"]:
                _emit_close("STOP", stime, "long", state["stop_price"])
                return
            if h >= state["tp_price"]:
                _emit_close("TP", stime, "long", state["tp_price"])
                return
        elif pos == "short":
            if h >= state["stop_price"]:
                _emit_close("STOP", stime, "short", state["stop_price"])
                return
            if l <= state["tp_price"]:
                _emit_close("TP", stime, "short", state["tp_price"])
                return

        # === 仓位不为 idle 不重开 (简化) ===
        if state["pos"] != "idle":
            return

        # TongDaXin 通道突破 (原 F1_1 / F2_1)
        bull_break = (c > o) and ((o > up1) or (c < dw1))
        bear_break = (c < o) and ((o < dw1) or (c > up1))
        # 锤子形态 + 顺势 (价站上慢线 = 多顺势; 踩下慢线 = 空顺势)
        bull_hammer = bull_break and _is_hammer(c, o, h, l, "bull")
        bear_hammer = bear_break and _is_hammer(c, o, h, l, "bear")
        trend_up = c > esl
        trend_dn = c < esl

        if bull_hammer and trend_up:
            _enter("long", c, stime, tr_atr, up1, dw1, esl)
        elif bear_hammer and trend_dn:
            _enter("short", c, stime, tr_atr, up1, dw1, esl)

    def _enter(side, price, stime, atr_val, up1, dw1, esl):
        state["pos"] = side
        state["entry_price"] = price
        state["qty"] = 1
        if side == "long":
            state["stop_price"] = price - stop_atr * atr_val
            state["tp_price"] = price * (1 + tp_pct)
        else:
            state["stop_price"] = price + stop_atr * atr_val
            state["tp_price"] = price * (1 - tp_pct)
        state["events"].append({
            "event": "ENTRY",
            "stime": stime,
            "side": "BUY" if side == "long" else "SELL",
            "price": price,
            "trend": "rising" if side == "long" else "falling",
            "stop": round(state["stop_price"], 4),
            "tp": round(state["tp_price"], 4),
            "atr": round(atr_val, 4),
            "slow": round(esl, 4),
            "up1": round(up1, 4),
            "dw1": round(dw1, 4),
        })

    def _emit_close(event_kind, stime, side, fill_price):
        if side == "long":
            pnl = (fill_price - state["entry_price"]) * state["qty"]
        else:
            pnl = (state["entry_price"] - fill_price) * state["qty"]
        state["events"].append({
            "event": event_kind,
            "stime": stime,
            "side": "BUY" if side == "short" else "SELL",  # 出场方向与开仓反
            "price": fill_price,
            "trend": "rising" if side == "long" else "falling",
            "pnl": round(pnl, 4),
            "up1": round(ema_h.value, 4),
            "dw1": round(ema_l.value, 4),
        })
        state["pos"] = "idle"
        state["entry_price"] = 0.0
        state["stop_price"] = 0.0
        state["tp_price"] = 0.0
        state["qty"] = 0

    _on_quote.get_events = lambda: list(state["events"])
    _on_quote.get_signals = _on_quote.get_events  # 兼容旧 API
    _on_quote.get_state = lambda: dict(state, tf1=tf1, slow=slow,
                                         atr_period=atr_period,
                                         stop_atr=stop_atr,
                                         tp_pct=tp_pct)
    return _on_quote


# ---------------------------------------------------------------------------
# 离线 smoke: 验证 hammer + trend + stop + TP 主路径
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cols = ["stime", "open", "high", "low", "close"]

    def _bar(t, o, h, l, c):
        return {"stime": t, "open": str(o), "high": str(h),
                "low": str(l), "close": str(c)}

    def _stime(idx):
        t = 30 + idx
        return "20260701" + str(9 + t // 60).zfill(2) + str(t % 60).zfill(2) + "00"

    rows = []
    # warmup need: slow=89 + atr_period=14 = 103 bars. 留 150 bar 充分稳化 EMA.
    for i in range(150):
        base = 1.20 + i * 0.0001
        rows.append(_bar(_stime(i), base, base + 0.005, base - 0.005, base))
    # bar 151: bullish hammer + gap-up over UP1
    # 150 bar 后 up1 ≈ EMA(H,26) ≈ 1.215, esl ≈ EMA(C,89) ≈ 1.213
    # O=1.2210 > up1=1.215 (gap up), H=1.2240, L=1.2070, C=1.2235
    #   body=0.0025, bar=0.0170, body/bar=14.7% < 40% ok
    #   lower=min(O,C)-L=1.2210-1.2070=0.0140, 1.5*body=0.00375, lower >> body ok
    #   upper=H-max(O,C)=1.2240-1.2235=0.0005, upper < body ok
    #   bull_break: c>o YES; o>up1 YES (1.221 > 1.215)
    #   trend_up: c=1.2235 > esl  ok
    rows.append(_bar(_stime(150), 1.2210, 1.2240, 1.2070, 1.2235))
    # bar 152: 顺势上拉, 不到 TP (entry=1.2235, tp=1.2235*1.01=1.2358)
    rows.append(_bar(_stime(151), 1.2240, 1.2330, 1.2220, 1.2310))
    # bar 153: 到达 TP. H=1.2380 >= 1.2358  -> TP 触发
    rows.append(_bar(_stime(152), 1.2315, 1.2380, 1.2310, 1.2360))

    cb = make_strategy_runner()
    for r in rows:
        cb(cols, r)

    print("[smoke] " + str(cb.get_state()["bar_count"]) + " bars, " +
          str(len(cb.get_events())) + " events, pos=" + cb.get_state()["pos"])
    for e in cb.get_events():
        print("  " + str(e))
