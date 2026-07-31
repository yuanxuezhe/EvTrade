# coding: gbk
"""
strategy_runner.py -- TongDaXin 1m 周期交易策略实现.

通达信原公式 (TF1=26, TF2=89):
  UP1     := EMA(H, TF1)
  DW1     := EMA(L, TF1)
  F1_1    := C > O AND (O > UP1 OR C < DW1)              ; 多头突破
  F2_1    := C < O AND (O < DW1 OR C > UP1)              ; 空头突破
  COND1_1 := UP1 > REF(UP1, 1) AND DW1 > REF(DW1, 1)     ; 双线齐升
  COND1_2 := UP1 < REF(UP1, 1) AND DW1 < REF(DW1, 1)     ; 双线齐降

BUY  条件: F1_1 AND NOT(COND1_2)   ; 多头突破 + 趋势非下行
SELL 条件: F2_1 AND COND1_2        ; 空头突破 + 趋势下行
入场价:  当前 bar close.

实现要点:
  - 增量 EMA (alpha = 2 / (N + 1), 首条 seed 为其自身)
    等价于 pandas.ewm(span=N, adjust=False).mean().
  - 缓存前一 bar UP1/DW1 用于 REF 对比.
  - warmup 等到 bar_count > TF2 才发信号 (默认 TF2=89, 让 EMA 稳定 + 留够 prev).
  - 缺 high/low/open/close 任一字段, 静默跳过.

用法 (与 quota_his_test.send_request_and_consume 配套):
    strat = make_strategy_runner()             # TF1=26, TF2=89
    send_request_and_consume(on_quote=strat)   # 每根 bar 评估 + 入信号列表
    for s in strat.get_signals():
        print(s["stime"], s["side"], s["price"], s["trend"])
"""

from typing import Callable


def make_strategy_runner(tf1: int = 26, tf2: int = 89) -> Callable:
    """返回 on_quote callback, 每根 bar 评估 BUY/SELL 并入栈.

    Args:
        tf1: EMA 周期 (通达信原公式 TF1). 默认 26.
        tf2: warmup bar 数 (bar_count > TF2 才发信号). 默认 89.

    Returns:
        Callable 与 send_request_and_consume 的 on_quote 签名一致.
        附加方法:
          - get_signals() -> list[dict]
                每条: {stime, side, price, trend, up1, dw1}
                side 取值 'BUY' / 'SELL'; trend: rising / falling / mixed
          - get_state() -> dict
                {bar_count, signals_count, tf1, tf2, up1, dw1}
    """
    alpha = 2.0 / (tf1 + 1)
    ema_up = ema_dw = 0.0
    up_seeded = dw_seeded = False
    prev_up = prev_dw = None
    state = {"bar_count": 0, "signals": []}

    def _to_f(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def _on_quote(columns, row):
        nonlocal ema_up, ema_dw, up_seeded, dw_seeded, prev_up, prev_dw
        state["bar_count"] += 1

        h, l, o, c = (_to_f(row.get(k)) for k in ("high", "low", "open", "close"))
        if None in (h, l, o, c):
            return
        stime = row.get("stime", "?")

        # 增量 EMA: 首条 seed = 第一根 bar
        if not up_seeded:
            ema_up = h
            up_seeded = True
        else:
            ema_up = alpha * h + (1.0 - alpha) * ema_up
        if not dw_seeded:
            ema_dw = l
            dw_seeded = True
        else:
            ema_dw = alpha * l + (1.0 - alpha) * ema_dw

        # warmup: bar_count > TF2 + 已有 prev_xxx 用于 REF 对比
        ready = state["bar_count"] > tf2 and prev_up is not None
        if ready:
            f1 = (c > o) and ((o > ema_up) or (c < ema_dw))
            f2 = (c < o) and ((o < ema_dw) or (c > ema_up))
            cond1_1 = (ema_up > prev_up) and (ema_dw > prev_dw)
            cond1_2 = (ema_up < prev_up) and (ema_dw < prev_dw)

            # BUY 优先, SELL 次之 (同 bar 不重复触发)
            if f1 and not cond1_2:
                trend = "rising" if cond1_1 else "mixed"
                state["signals"].append({
                    "stime": stime, "side": "BUY", "price": c,
                    "trend": trend,
                    "up1": round(ema_up, 4), "dw1": round(ema_dw, 4),
                })
            elif f2 and cond1_2:
                state["signals"].append({
                    "stime": stime, "side": "SELL", "price": c,
                    "trend": "falling",
                    "up1": round(ema_up, 4), "dw1": round(ema_dw, 4),
                })

        prev_up, prev_dw = ema_up, ema_dw

    _on_quote.get_signals = lambda: list(state["signals"])
    _on_quote.get_state = lambda: {
        "bar_count": state["bar_count"],
        "signals_count": len(state["signals"]),
        "tf1": tf1, "tf2": tf2,
        "up1": ema_up, "dw1": ema_dw,
    }
    return _on_quote


# ---------------------------------------------------------------------------
# 离线 smoke: 92 bar 序列 (90 阴跌 + 1 强阴线 + 1 跳空阳线), 期望产生 1 SELL + 1 BUY.
# 不依赖 AMQP, 仅用列表驱动 callback.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cols = ["stime", "open", "high", "low", "close"]

    def _bar(stime, o, h, l, c):
        return {"stime": stime, "open": str(o), "high": str(h),
                "low": str(l), "close": str(c)}

    def _stime(idx):
        """idx=0 -> 09:30:00, 之后每 bar 加 1 分钟."""
        total = 30 + idx
        return "20260701" + str(9 + total // 60).zfill(2) \
               + str(total % 60).zfill(2) + "00"

    rows = []
    # 90 根缓慢阴跌: UP1 / DW1 同步下行 (形成 COND1_2 趋势)
    for i in range(90):
        base = 1.200 - i * 0.001
        rows.append(_bar(_stime(i), base, base + 0.005,
                         base - 0.005, base))
    # bar 91: 强阴线 (O=1.115 > DW1, C=1.085 << DW1 跌破下轨)
    rows.append(_bar(_stime(90), 1.115, 1.118, 1.080, 1.085))
    # bar 92: 跳空阳线 (O=1.150 > UP1 跳空, C=1.190 收高)
    rows.append(_bar(_stime(91), 1.150, 1.200, 1.100, 1.190))

    cb = make_strategy_runner()
    for r in rows:
        cb(cols, r)

    state = cb.get_state()
    sigs = cb.get_signals()
    print("[smoke] bars=" + str(state["bar_count"]) +
          "  tf1=" + str(state["tf1"]) +
          "  tf2=" + str(state["tf2"]) +
          "  up1=" + format(state["up1"], ".4f") +
          "  dw1=" + format(state["dw1"], ".4f"))
    print("[smoke] signals=" + str(len(sigs)))
    for s in sigs:
        print("  " + s["stime"] + "  " + s["side"].ljust(4) +
              "  price=" + format(s["price"], ".4f").rjust(8) +
              "  trend=" + s["trend"])
