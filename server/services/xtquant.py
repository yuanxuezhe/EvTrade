import sys
import os

# 添加iQuant路径
sys.path.insert(0, r'D:\software\trade\iQuant')
sys.path.insert(0, r'D:\software\trade\iQuant\Lib\site-packages')

from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant
from services.trading import set_trader

# 配置
TRADE_PATH = r'D:\software\trade\iQuant\userdata'
ACCOUNT_ID = '410001265100'
SESSION_ID = 100

_trader = None


class MyXtQuantTraderCallback:
    """XtQuant回调"""
    def on_disconnected(self):
        print("连接断开")
        global _trader
        _trader = None

    def on_stock_order(self, order):
        print(f"委托回报: {order.stock_code} {order.direction} {order.volume}@{order.price} status={order.order_status}")

    def on_stock_trade(self, trade):
        print(f"成交回报: {trade.stock_code} {trade.direction} {trade.volume}@{trade.price}")

    def on_order_error(self, order_error):
        print(f"委托失败: {order_error.order_id} {order_error.error_msg}")

    def on_cancel_error(self, cancel_error):
        print(f"撤单失败: {cancel_error.order_id} {cancel_error.error_msg}")

    def on_order_stock_async_response(self, response):
        print(f"异步下单响应: seq={response.seq} order_id={response.order_id}")

    def on_account_status(self, status):
        print(f"账户状态变化: {status.account_id} status={status.status}")


def init_trader():
    """初始化XtQuant交易器"""
    global _trader

    if _trader is not None:
        return _trader

    xt_acc = StockAccount(ACCOUNT_ID)
    callback = MyXtQuantTraderCallback()
    _trader = XtQuantTrader(TRADE_PATH, SESSION_ID, callback=callback)

    connect_result = _trader.connect()
    if connect_result != 0:
        print(f"连接失败: {connect_result}")
        _trader = None
        return None

    subscribe_result = _trader.subscribe(xt_acc)
    if subscribe_result != 0:
        print(f"订阅失败: {subscribe_result}")

    set_trader(_trader, xt_acc)
    print("XtQuant交易器初始化成功")
    return _trader


def get_trader():
    global _trader
    if _trader is None:
        init_trader()
    return _trader