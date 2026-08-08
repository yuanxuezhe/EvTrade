"""
default_bt_strategy.py — 默认 Backtrader 用户脚本模板

📌 这是 EvTrade strategy_exec 服务的默认脚本模板, 供 ScriptDev.vue 编辑器初始化使用

策略逻辑 (双均线交叉):
- 5日均线上穿20日均线 → 金叉 → 推送 BUY signal
- 5日均线下穿20日均线 → 死叉 → 推送 SELL signal
- 持仓中再次出现金叉不重复买, 死叉平仓

特点:
- 继承 ProjectStrategy (strategy_exec.engines.backtrader.adapter.ProjectStrategy)
- 通过 self.buy_signal() / self.sell_signal() 推送信号 (不走 Backtrader 本地 broker)
- 指标 (ma5 / ma20 / rsi) 自动写入 audit + signal payload

参数 (params):
- fast: 快线周期 (默认 5)
- slow: 慢线周期 (默认 20)
- qty: 每次下单数量 (默认 100, 整手)
- rsi_period: RSI 周期 (默认 14)

用法:
1. ScriptDev.vue 编辑器加载本模板作为初始内容
2. 用户可修改 params / 策略逻辑 / 添加新指标
3. 保存到 strategy_script 表 (user_id, id, code, params_schema)
4. ScriptTask.vue 启动回测/实盘 → strategy_exec 服务加载并运行
"""

try:
    import backtrader as bt
except ImportError:
    bt = None  # backtrader 未装时 (e.g. migration 脚本), 默认模板字符串仍可用


# 项目适配层 (Phase 2 实施) — 提供 buy_signal/sell_signal 方法
# 当前 Phase 1 阶段, 此 import 暂时未启用, 用户脚本可在 Phase 2 启用
try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    # Phase 1: 适配层未实现, 临时继承 bt.Strategy (脚本可独立测试 next() 逻辑)
    ProjectStrategy = bt.Strategy if bt is not None else object


DEFAULT_BT_STRATEGY_CODE = '''import backtrader as bt

try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    # 离线编辑时 (无 strategy_exec 环境) — 退化为标准 bt.Strategy
    # 部署到 strategy_exec 服务后会自动用 ProjectStrategy 基类
    ProjectStrategy = bt.Strategy


class MAStrategy(ProjectStrategy):
    """双均线交叉策略 (默认模板)

    5日上穿20日 → 金叉 → BUY signal (推送 RabbitMQ → EvTrade 下单)
    5日下穿20日 → 死叉 → SELL signal
    """

    params = (
        ("fast", 5),       # 快线周期
        ("slow", 20),      # 慢线周期
        ("qty", 100),      # 每次下单数量
        ("rsi_period", 14),# RSI 周期 (可选过滤)
    )

    def __init__(self):
        # 指标初始化 (Backtrader 自动增量计算)
        self.sma_fast = bt.indicators.SMA(period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(period=self.p.slow)
        self.rsi = bt.indicators.RSI(period=self.p.rsi_period)
        # 金叉死叉信号
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

    def next(self):
        """每根 bar (1d / 1m 等) 调一次"""
        # 数据不足时跳过 (Backtrader 会从第 N 根 bar 开始有指标值)
        if len(self) < self.p.slow + 1:
            return

        price = self.data.close[0]
        ma5 = self.sma_fast[0]
        ma20 = self.sma_slow[0]
        rsi_v = self.rsi[0]

        # 金叉: 快线上穿慢线 + 没持仓 → BUY
        if self.crossover[0] > 0 and not self.position:
            self.buy_signal(
                price=price,
                volume=self.p.qty,
                price_type="limit",
                indicators={"ma5": ma5, "ma20": ma20, "rsi": rsi_v},
                msg=f"金叉: ma5={ma5:.2f} 上穿 ma20={ma20:.2f}, RSI={rsi_v:.1f}",
            )

        # 死叉: 快线下穿慢线 + 有持仓 → SELL
        elif self.crossover[0] < 0 and self.position:
            self.sell_signal(
                price=price,
                volume=self.position.size,  # 全仓平仓
                price_type="limit",
                indicators={"ma5": ma5, "ma20": ma20, "rsi": rsi_v},
                msg=f"死叉: ma5={ma5:.2f} 下穿 ma20={ma20:.2f}, RSI={rsi_v:.1f}",
            )

    def notify_signal_published(self, signal_id: str, ok: bool) -> None:
        """可选回调: signal 推送成功/失败"""
        if not ok:
            self.log.warning(f"signal {signal_id} 推送失败, 请检查 RabbitMQ")
'''


# 默认 params_schema (前端 ScriptDev.vue 表单初始化用)
DEFAULT_BT_STRATEGY_PARAMS_SCHEMA = [
    {"key": "fast", "type": "int", "min": 3, "max": 30, "step": 1, "default": 5,
     "desc": "快线周期"},
    {"key": "slow", "type": "int", "min": 10, "max": 120, "step": 1, "default": 20,
     "desc": "慢线周期"},
    {"key": "qty", "type": "int", "min": 100, "max": 10000, "step": 100, "default": 100,
     "desc": "下单数量 (整手)"},
    {"key": "rsi_period", "type": "int", "min": 6, "max": 30, "step": 1, "default": 14,
     "desc": "RSI 周期"},
]


__all__ = [
    "DEFAULT_BT_STRATEGY_CODE",
    "DEFAULT_BT_STRATEGY_PARAMS_SCHEMA",
]