"""
channel_strategy.py — 通道反转策略 (Backtrader 适配版, 策略内自管 15m 桶)

📌 对应原 gxquant 版本:
   - DW1 = EMA(L, tf1)  下轨
   - UP1 = EMA(H, tf1)  上轨
   - 价格偏离下轨超 low1% 后, 回撤到偏离下轨 low2% 以内 → BUY
   - 价格偏离上轨超 high1% 后, 回撤到偏离上轨 high2% 以内 → SELL

📌 策略内自管 N 分钟桶 (跟系统 aggregator 不同):
   - Backtrader 喂的是 1m K 线 (data feed 设 timeframe=Minutes, compression=1)
   - 策略内部维护 _bucket_stime/open/high/low/close, 每根 1m 进来增量更新
   - bucket_stime 切换 → 新桶 OHLCV 重计 (open=新 1m bar.open, high/low 从新 bar 开始)
   - EMA 跨桶连续累积 (不重置)
   - 每根 1m 都做指标计算 + 信号判断 (实时, 不等桶结束)
   - BUY 触发价 = 当前桶 low, SELL 触发价 = 当前桶 high

适配 EvTrade strategy_exec 系统:
- 继承 ProjectStrategy (bt.Strategy 子类)
- 用 buy_signal() / sell_signal() 推送 RabbitMQ → EvTrade 下单
- 通道值/偏离等指标写 audit + signal payload
- 回测/live 统一走 1m 数据, 行为一致

参数 (params):
- tf1:        通道 EMA 周期 (默认 21)
- low1:       下轨超跌触发偏离% (默认 2.0)
- low2:       下轨回撤容忍偏离% (默认 0.5)
- high1:      上轨超涨触发偏离% (默认 2.0)
- high2:      上轨回撤容忍偏离% (默认 0.5)
- qty:        每次下单数量 (默认 100, 整手)
- period_min: 策略内自管周期 (1/5/15/30/60, 默认 15); Backtrader 仍按 1m 喂数据
"""

try:
    import backtrader as bt
except ImportError:
    bt = None  # 离线编辑时 (无 backtrader 环境)

try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    ProjectStrategy = bt.Strategy if bt is not None else object


CHANNEL_STRATEGY_CODE = '''import backtrader as bt

try:
    from strategy_exec.engines.backtrader.adapter import ProjectStrategy
except ImportError:
    # 离线编辑时 — 退化为标准 bt.Strategy
    ProjectStrategy = bt.Strategy


class ChannelStrategy(ProjectStrategy):
    """通道反转策略 — EMA(H/L, tf1) 双轨 + 偏离阈值

    核心思想:
      DW1 = EMA(L, tf1)  下轨
      UP1 = EMA(H, tf1)  上轨
      当 L 偏离 DW1 超过 low1% → 标记 low_hit
      当 H 偏离 UP1 超过 high1% → 标记 high_hit
      下一根 L 回升到偏离 DW1 < low2% → BUY (回撤入场)
      下一根 H 回落到偏离 UP1 < high2% → SELL (回撤入场)

    信号方向:
      BUY  = 价格从下方极端偏离回到通道内 (超跌反弹)
      SELL = 价格从上方极端偏离回到通道内 (超涨回落)

    持仓语义:
      - 默认与 gxquant 原版一致: BUY/SELL 信号触发即推送
      - 若要"持仓中不再开同向单", 在 next() 加 self.position 判断
        (本模板按 gxquant 行为: 不校验持仓, 跟原版信号流一致)
    """

    params = (
        ("tf1",       21),   # 通道 EMA 周期
        ("low1",      2.0),  # 下轨超跌触发偏离%
        ("low2",      0.5),  # 下轨回撤容忍偏离%
        ("high1",     2.0),  # 上轨超涨触发偏离%
        ("high2",     0.5),  # 上轨回撤容忍偏离%
        ("qty",       100),  # 每次下单数量 (整手)
        ("period_min", 15),  # 周期 (1/5/15/30/60) — 策略内部按 1m 喂数据, 自管 N 分钟桶
    )

    def __init__(self):
        # EMA 状态 (跨桶连续累积, 不重置)
        self._alpha = 2.0 / (self.p.tf1 + 1)
        self._ema_high = None
        self._ema_low  = None
        # 信号触发状态机 (新桶/首根无历史数据 → 默认 False, 强制累积偏离)
        self._low_hit  = False
        self._high_hit = False

        # ====== 周期桶状态 (自管 N 分钟 K 线合并) ======
        # 每根 1m bar 进来都增量更新当前桶的 OHLCV; 桶满切新桶, 新桶 OHLCV 重计
        self._bucket_stime = None   # 当前桶起点 14位 stime (YYYYMMDDHHMMSS)
        self._bucket_open  = None   # 当前桶首根 1m 的 open
        self._bucket_high  = None   # 当前桶内 max(1m.high), 实时"长高"
        self._bucket_low   = None   # 当前桶内 min(1m.low),  实时"长低"
        self._bucket_close = None   # 当前桶内最新 1m 的 close

    @staticmethod
    def _align_bucket(stime_14: str, period_min: int) -> str:
        """1m bar 的 stime → 对齐到 N 分钟桶起点 stime.

        例如 period_min=15, stime=20240902093100 → 20240902093000 (09:30 桶)
            period_min=15, stime=20240902094500 → 20240902094500 (09:45 桶, 边界)
            period_min=15, stime=20240902094600 → 20240902094500 (09:45 桶)
        """
        from datetime import datetime
        dt = datetime.strptime(stime_14, "%Y%m%d%H%M%S")
        aligned_min = (dt.minute // period_min) * period_min
        return dt.replace(minute=aligned_min, second=0).strftime("%Y%m%d%H%M%S")

    def _bucket_ohlcv(self):
        """返当前桶完整 OHLCV (跟原版策略的 self.data.* 接口对齐)"""
        return (
            self._bucket_open,
            self._bucket_high,
            self._bucket_low,
            self._bucket_close,
        )

    def next(self):
        """每根 1m bar 调一次 — 自管 15m 桶 + 实时指标/信号

        数据流 (Backtrader 喂 1m bar, 周期由 period_min 决定):
          1. 读当前 1m bar OHLCV + 算桶起点 stime
          2. 若新桶 (stime != self._bucket_stime) → 切桶: 新桶 OHLCV 重计 (open=新bar.open)
          3. 否则同桶 → 增量更新 bucket_high/low/close (高/低"长高"/"长低", close 取最新)
          4. 用当前桶 OHLCV (实时合并中的 15m) 做 EMA + 信号判断
             - EMA 每根 1m 都平滑一次 (跨桶连续)
             - BUY 触发价 = 桶 low, SELL 触发价 = 桶 high (用本周期极值成交)
        """
        # ====== 1. 读 1m bar ======
        low  = self.data.low[0]
        high = self.data.high[0]
        if low is None or high is None:
            return

        stime_14 = self.data.datetime.datetime(0).strftime("%Y%m%d%H%M%S")
        bucket_stime = self._align_bucket(stime_14, self.p.period_min)

        # ====== 2. 桶切换判断 ======
        if self._bucket_stime is None:
            # 首根 1m bar — 直接开新桶, 无老桶可触发
            self._bucket_stime = bucket_stime
            self._bucket_open  = self.data.open[0]
            self._bucket_high  = high
            self._bucket_low   = low
            self._bucket_close = self.data.close[0]
        elif bucket_stime != self._bucket_stime:
            # 新桶 → 重计 OHLCV (EMA 跨桶连续保留)
            self._bucket_stime = bucket_stime
            self._bucket_open  = self.data.open[0]
            self._bucket_high  = high
            self._bucket_low   = low
            self._bucket_close = self.data.close[0]
            # 重置信号状态机 (新桶独立判断; 首根无历史数据 → high_hit/low_hit 都 False,
            # 强制从下一根 bar 开始累积偏离, 避免"开盘首根就发 SELL"误触发)
            self._low_hit  = False
            self._high_hit = False
        else:
            # 同桶 → 增量更新 (高低实时"长高/长低", close 取最新)
            self._bucket_high  = max(self._bucket_high, high)
            self._bucket_low   = min(self._bucket_low,  low)
            self._bucket_close = self.data.close[0]

        # 当前桶 OHLCV (即"实时合并的 15m")
        b_open, b_high, b_low, b_close = self._bucket_ohlcv()

        # ====== 3. 增量更新 EMA (跨桶连续, 每根 1m 都做一次平滑) ======
        if self._ema_high is None:
            self._ema_high = b_high
            self._ema_low  = b_low
        else:
            a = self._alpha
            self._ema_high = b_high * a + self._ema_high * (1 - a)
            self._ema_low  = b_low  * a + self._ema_low  * (1 - a)

        up1 = self._ema_high
        dw1 = self._ema_low

        # 偏离% (基于当前桶极值, 跟原版一致)
        up_dev_pct = (b_high - up1) / up1 * 100.0 if up1 else 0.0
        dw_dev_pct = (b_low  - dw1) / dw1 * 100.0 if dw1 else 0.0

        # ====== 4. 信号判断 (用桶 H/L 极值 + 阈值) ======
        # 第 1 步: 高点扫一遍 (极端超涨检测)
        if b_high >= up1 * (1 + self.p.high1 / 100.0):
            self._high_hit = True

        # 第 2 步: 低点扫一遍 (极端超跌检测)
        if b_low  <= dw1 * (1 - self.p.low1  / 100.0):
            self._low_hit = True

        # 第 3 步: SELL 触发 (高轨回落) — 用桶 high 价成交
        if self._high_hit and b_high <= up1 * (1 + self.p.high2 / 100.0):
            self.sell_signal(
                price=b_high,           # 桶内极值价成交 (当前 15m 桶的 high)
                volume=self.p.qty,
                price_type="limit",
                indicators={
                    "UP1": up1,
                    "DW1": dw1,
                    "up_dev_pct": up_dev_pct,
                    "dw_dev_pct": dw_dev_pct,
                    "tf1": self.p.tf1,
                    "high1": self.p.high1,
                    "high2": self.p.high2,
                    "bucket_stime": self._bucket_stime,
                    "period_min": self.p.period_min,
                    "trigger_price": b_high,
                    "trigger_kind": "bucket_high",
                },
                msg=(
                    f"通道回撤 SELL: bucket[{self._bucket_stime}] high={b_high:.4f} "
                    f"回落到 UP1*(1+{self.p.high2:.2f}%)={up1 * (1 + self.p.high2 / 100.0):.4f} 内, "
                    f"up_dev_pct={up_dev_pct:+.2f}%"
                ),
            )
            self._high_hit = False

        # 第 4 步: BUY 触发 (低轨回升) — 用桶 low 价成交
        if self._low_hit and b_low >= dw1 * (1 - self.p.low2 / 100.0):
            self.buy_signal(
                price=b_low,            # 桶内极值价成交 (当前 15m 桶的 low)
                volume=self.p.qty,
                price_type="limit",
                indicators={
                    "UP1": up1,
                    "DW1": dw1,
                    "up_dev_pct": up_dev_pct,
                    "dw_dev_pct": dw_dev_pct,
                    "tf1": self.p.tf1,
                    "low1": self.p.low1,
                    "low2": self.p.low2,
                    "bucket_stime": self._bucket_stime,
                    "period_min": self.p.period_min,
                    "trigger_price": b_low,
                    "trigger_kind": "bucket_low",
                },
                msg=(
                    f"通道回撤 BUY: bucket[{self._bucket_stime}] low={b_low:.4f} "
                    f"回升到 DW1*(1-{self.p.low2:.2f}%)={dw1 * (1 - self.p.low2 / 100.0):.4f} 内, "
                    f"dw_dev_pct={dw_dev_pct:+.2f}%"
                ),
            )
            self._low_hit = False

    def notify_signal_published(self, signal_id: str, ok: bool) -> None:
        """可选回调: signal 推送成功/失败"""
        if not ok:
            self.log.warning(f"signal {signal_id} 推送失败, 请检查 RabbitMQ")
'''


# params_schema (前端 ScriptDev.vue 表单初始化用)
CHANNEL_STRATEGY_PARAMS_SCHEMA = [
    {"key": "tf1",       "type": "int",   "min": 5,    "max": 120,   "step": 1,   "default": 21,
     "desc": "通道 EMA 周期 (H/L 各一根)"},
    {"key": "low1",      "type": "float", "min": 0.5,  "max": 10.0,  "step": 0.1, "default": 2.0,
     "desc": "下轨超跌触发偏离% (L 相对 DW1)"},
    {"key": "low2",      "type": "float", "min": 0.1,  "max": 5.0,   "step": 0.1, "default": 0.5,
     "desc": "下轨回撤容忍偏离% (L 回到 DW1*附近)"},
    {"key": "high1",     "type": "float", "min": 0.5,  "max": 10.0,  "step": 0.1, "default": 2.0,
     "desc": "上轨超涨触发偏离% (H 相对 UP1)"},
    {"key": "high2",     "type": "float", "min": 0.1,  "max": 5.0,   "step": 0.1, "default": 0.5,
     "desc": "上轨回撤容忍偏离% (H 回到 UP1*附近)"},
    {"key": "qty",       "type": "int",   "min": 100,  "max": 10000, "step": 100, "default": 100,
     "desc": "每次下单数量 (整手)"},
    {"key": "period_min","type": "int",   "min": 1,    "max": 60,    "step": 1,   "default": 15,
     "desc": "策略内部自管周期 (1/5/15/30/60 分钟); Backtrader 仍按 1m 喂数据"},
]


__all__ = [
    "CHANNEL_STRATEGY_CODE",
    "CHANNEL_STRATEGY_PARAMS_SCHEMA",
]