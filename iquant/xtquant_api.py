#coding:gbk
#本文用一个均线策略演示交易连接断开时怎么处理交易接口重连
# 策略本身不严谨，不能作为实盘策略或者参考策略，本策略仅是演示重连用法
import time
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant
from xtquant import xtdata


strategy_name = "evdata_1.0"

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    # 更多说明见 http://dict.thinktrader.net/nativeApi/xttrader.html?id=I3DJ97#%E5%A7%94%E6%89%98xtorder
    def on_disconnected(self):
        """
        连接断开
        :return:
        """
        print("connection lost, 交易接口断开，即将重连")
        global xt_trader
        xt_trader = None
    
    def on_stock_order(self, order):
        """
        委托回报推送
        :param order: XtOrder对象
        :return:
        """

        # 属性赋值
        account_type = order.account_type  # 账号类型
        account_id = order.account_id  # 资金账号
        stock_code = order.stock_code  # 证券代码，例如"600000.SH"
        order_id = order.order_id  # 订单编号
        order_sysid = order.order_sysid  # 柜台合同编号
        order_time = order.order_time  # 报单时间
        order_type = order.order_type  # 委托类型，参见数据字典
        order_volume = order.order_volume  # 委托数量
        price_type = order.price_type  # 报价类型，该字段在返回时为柜台返回类型，不等价于下单传入的price_type，枚举值不一样功能一样，参见数据字典
        price = order.price  # 委托价格
        traded_volume = order.traded_volume  # 成交数量
        traded_price = order.traded_price  # 成交均价
        order_status = order.order_status  # 委托状态，参见数据字典
        status_msg = order.status_msg  # 委托状态描述，如废单原因
        strategy_name = order.strategy_name  # 策略名称
        order_remark = order.order_remark  # 委托备注

        # 打印输出
        print(f"""
        =============================
                委托信息
        =============================
        账号类型: {order.account_type}, 资金账号: {order.account_id}, 证券代码: {order.stock_code}, 订单编号: {order.order_id}, 
        柜台合同编号: {order.order_sysid}, 报单时间: {order.order_time}, 委托类型: {order.order_type}, 委托数量: {order.order_volume},
        报价类型: {order.price_type}, 委托价格: {order.price}, 成交数量: {order.traded_volume}, 成交均价: {order.traded_price},
        委托状态: {order.order_status}, 委托状态描述: {order.status_msg}, 策略名称: {order.strategy_name}, 委托备注: {order.order_remark}
        """)
        '''
        if order.strategy_name == strategy_name:
            # 该委托是由本策略发出
            ssid = order.order_sysid
            status = order.order_status
            market = order.stock_code.split(".")[1]
            #print(ssid)
            if ssid and status in [50,55]:
                ## 使用cancel_order_stock_sysid_async时，投研端market参数可以填写为0，券商端按实际情况填写
                print(xt_trade.cancel_order_stock_sysid_async(account,0,ssid))
        '''

    def on_stock_trade(self, trade):
        print(f'成交回报: 股票代码:{trade.stock_code} 账号:{trade.account_id}, 订单编号:{trade.order_id} 柜台合同编号:{trade.order_sysid} \
            成交编号:{trade.traded_id} 成交数量:{trade.traded_volume} ')

    def on_order_error(self, order_error):
        print(f"报单失败： 订单编号：{order_error.order_id} 下单失败具体信息:{order_error.error_msg} 委托备注:{order_error.order_remark}")

    def on_cancel_error(self, cancel_error):
        print(f"撤单失败: 订单编号：{cancel_error.order_id} 失败具体信息:{cancel_error.error_msg}, {cancel_error.order_sysid} 市场：{cancel_error.market}")

    def on_order_stock_async_response(self, response):
        print(f"异步下单的请求序号:{response.seq}, 订单编号：{response.order_id} ")

    def on_account_status(self, status):
        print(f"账号状态发生变化， 账号:{status.account_id} 最新状态：{status.status}")

def create_trader(xt_acc,path, session_id):
    trader = XtQuantTrader(path, session_id,callback=MyXtQuantTraderCallback())
    trader.start()
    connect_result = trader.connect()
    trader.subscribe(xt_acc)
    return trader if connect_result == 0 else None


def try_connect(xt_acc,path):
    session_id_range = [i for i in range(100, 120)]

    import random
    random.shuffle(session_id_range)
    
    # 遍历尝试session_id列表尝试连接
    for session_id in session_id_range:
        trader = create_trader(xt_acc,path, session_id)
        if trader:
            print('连接成功，session_id:{}', session_id)
            return trader
        else:
            print('连接失败，session_id:{}，继续尝试下一个id', session_id)
            continue

    print('所有id都尝试后仍失败，放弃连接')
    return None


def get_xttrader(xt_acc,path):
    global xt_trader
    if xt_trader is None:
        xt_trader = try_connect(xt_acc,path)
    return xt_trader


if __name__ == "__main__":

    # 注意实际连接XtQuantTrader时不要写类似while True 这种无限循环的尝试，因为每次连接都会用session_id创建一个对接文件，这样就会占满硬盘导致电脑运行异常
    # 要控制session_id在有限的范围内尝试，这里提供10个session_id供重连尝试
    # 当所有session_id都尝试后，程序会抛出异常。实际使用过程中当session_id用完时，可以增加邮件等通知方式提醒人工处理 

    #指定客户端所在路径
    path = r'D:\software\trade\iQuant\userdata'
    xt_trader = None
    xt_acc = StockAccount('410001265100')
    xt_trader = get_xttrader(xt_acc,path)
    if not xt_trader:
        raise Exception('交易接口连接失败')
    print('交易接口连接成功， 策略开始')

    '''
    account_infos = xt_trader.query_account_infos()
    print("account_infos:", len(account_infos))
    if account_infos:
        for account_info in account_infos:
            print(f"资金账号:       {account_info.account_id}")
            print(f"账号类型:       {account_info.account_type}")
    else:
        print("无委托记录")
    '''
    # 查询证券资产
    print("query asset:")
    asset = xt_trader.query_stock_asset(xt_acc)
    if asset:
        print(f"账号:       {asset.account_id}")
        print(f"可用:     {asset.cash}")
        print(f"冻结金额:     {asset.frozen_cash}")
        print(f"持仓市值:     {asset.market_value}")
        print(f"总资产:     {asset.total_asset}")
    else:
        print("无委托记录")
    '''
    # 查询当日所有的委托
    print("query orders:")
    orders = xt_trader.query_stock_orders(xt_acc)
    print("orders:", len(orders))
    if orders:
        for order in orders:
            print(f"委托号:       {order.order_id}")
            print(f"证券代码:     {order.stock_code}")
            print(f"委托价格:     {order.price}")
            print(f"委托数量:     {order.order_volume}")
            print(f"已成交数量:   {order.traded_volume}")
            print(f"成交均价:     {order.traded_price}")
            print(f"委托状态:     {order.order_status}")
            print(f"委托类型:     {order.order_type}")
            print("-" * 50)
    else:
        print("无委托记录")
    '''
    
    stock = '513050.SH'
    #stock = '000001.SZ'
    xt_trader.order_stock_async(xt_acc, stock, xtconstant.STOCK_BUY,100,xtconstant.LATEST_PRICE,0, strategy_name, 'evdata_test')
    #cancel_result = xt_trader.cancel_order_stock_sysid_async(xt_acc, xtconstant.SZ_MARKET, '916180561')
    #print(f'撤单已发起{cancel_result}')
    # 阻塞主线程退出
    xt_trader.run_forever()




