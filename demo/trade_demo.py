#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo/trade_demo.py

极简 demo —— 组合 quote_base.QuoteBase + trade_base.TradeBase。
"""
from quote_base import QuoteBase
from trade_base import TradeBase

CODES = ["159992.SZ"]


def on_tick(d):
    """每条 tick 打印。"""
    print(f"[{d.get('stock_code')}] last={d.get('last_price')}  high={d['snapshot']['high_price']}  low={d['snapshot']['low_price']}  open={d['snapshot']['open_price']}")


def on_order(o):
    """委托状态变更(status=48/50/54/55/57 等)。"""
    print(f"📋 order {o.get('order_no')} → {o.get('status')} {o.get('status_msg')}")


def on_trade(t):
    """成交回报。"""
    print(f"💰 trade {t.get('stock_code')} {t.get('volume')}@{t.get('price')}")


class Client(TradeBase, QuoteBase):
    """
    组合两个基类:
      - TradeBase 提供 token / buy / sell / cancel / positions / asset / orders
      - QuoteBase 提供 subscribe / run / stop (token 从 TradeBase 拿)
    """

    def __init__(self, base_url, username, password, codes,
                 on_quote=None, on_order=None, on_trade=None,
                 on_stop=None, on_error=None):
        TradeBase.__init__(self, base_url, username, password)
        QuoteBase.__init__(
            self, base_url=base_url, token=self.token, codes=codes,
            on_quote=on_quote, on_order=on_order, on_trade=on_trade,
            on_stop=on_stop, on_error=on_error,
        )


if __name__ == "__main__":
    # 生产服务器用 quota/quota (viewer 角色,只能订阅不能下单);
    # 本地 dev 用 admin/admin123 (trader 角色,下单/撤单/查持仓 全通)。
    USE_PROD = True
    BASE_URL = "https://evtrade.ngx.evdata.top:50443/"
    USER, PASS = ("admin", "123456")

    cli = Client(BASE_URL, USER, PASS, CODES,
                 on_quote=on_tick, on_order=on_order, on_trade=on_trade)

    # 工作线程跑 WS 主循环(否则主线程会被阻塞)
    import threading
    threading.Thread(target=cli.run, daemon=True).start()

    import time; time.sleep(3)   # 等 WS 起来
    #print("💼 账户:", cli.asset())
    #print("📦 持仓:", cli.positions())

    '''
    # 下单/撤单 需要 trader 角色 (admin);viewer (quota) 会 403。
    if USER == "admin":
        ret = cli.buy("600519.SH", price=1.0, volume=100)
        print("🛒 买 →", ret.get("code"), ret.get("msg"))
        order_no = (ret.get("order") or {}).get("order_no")
        if order_no:
            time.sleep(1)
            print("❌ 撤 →", cli.cancel(order_no))
    else:
        print("⚠️  viewer 角色不能下单,跳过 buy/cancel 演示")
    '''
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("👋 bye")
