"""
Default script template — 给前端 ScriptDev.vue 编辑器作为初始内容

用户从模板起步,改写 / 保存到 strategy_script.code
"""
DEFAULT_SCRIPT = '''# === 均线交叉策略 (示例模板) ===
# 框架: 实现以下回调之一即可
#   on_init(ctx)        — 启动时调一次
#   on_bar(ctx, bar)    — 每根 K 线触发
#   on_tick(ctx, tick)  — 每个行情 tick 触发
#   on_finish(ctx)      — 结束时调一次
#
# 可用函数:
#   指标: MA / EMA / RSI / MACD / BOLL / KDJ / ATR / BARSLAST / REF / CROSS
#   交易: doorder(code, side, price, volume)  → 返 order_no
#         docancel(order_no, trd_date)        → 返 bool
#         get_position(code)                  → 返 int
#
# 上下文 ctx 字段:
#   ctx['bars']           — 截至当前的 bar 列表 (含当前 bar)
#   ctx['symbol']         — 标的代码
#   ctx['mode']           — 'backtest' / 'live'
#   ctx['params']         — 用户定义参数 dict
#   ctx['state']          — 自定义状态字典 (自由读写)


def on_init(ctx):
    """启动钩子 (可选)"""
    ctx['state']['position'] = 0      # 当前持仓方向: 0=空仓, 1=持多


def on_bar(ctx, bar):
    """每根 K 线触发"""
    fast = ctx['params']['fast']       # 短周期 (e.g. 5)
    slow = ctx['params']['slow']       # 长周期 (e.g. 20)
    qty  = ctx['params']['qty']        # 下单手数 (e.g. 100)

    ma_fast = MA(ctx['bars'], fast)
    ma_slow = MA(ctx['bars'], slow)
    if ma_fast is None or ma_slow is None:
        return  # warmup 中

    # 昨值 → 用历史 bars (不含当前 bar) 计算上一根周期均线
    prev_bars = ctx['bars'][:-1]
    prev_fast = MA(prev_bars, fast)
    prev_slow = MA(prev_bars, slow)
    if prev_fast is None or prev_slow is None:
        return

    golden_cross = prev_fast <= prev_slow and ma_fast > ma_slow     # 金叉
    death_cross  = prev_fast >= prev_slow and ma_fast < ma_slow     # 死叉

    pos = ctx['state']['position']
    price = bar['close']

    if golden_cross and pos == 0:
        # 金叉 + 空仓 → 买入
        doorder(ctx['symbol'], 'BUY', price, qty)
        ctx['state']['position'] = 1
    elif death_cross and pos == 1:
        # 死叉 + 持仓 → 卖出
        doorder(ctx['symbol'], 'SELL', price, qty)
        ctx['state']['position'] = 0


def on_finish(ctx):
    """结束钩子 (可选)"""
    pass
'''