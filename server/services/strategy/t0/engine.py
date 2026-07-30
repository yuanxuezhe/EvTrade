"""
strategy/t0/engine.py — T0 策略主评估引擎

📌 Pipeline: tick → buffer → bar → VWAP → signal → risk → order/audit → WS
📌 test_mode=True: 仅信号展示 + audit，不 ord_stk
📌 test_mode=False: 完整下单链路（INSERT Order → ord_stk RPC）
📌 信号冷却: 两次信号间隔 ≥ signal_cooldown 秒
📌 与 StrategyEngine 并行，独立评估逻辑
"""
import asyncio
import logging
import time
from collections import deque
from typing import Dict, List, Optional

from server.services.strategy.t0.models import (
    T0StrategyParams, T0Position, T0Signal, T0EvaluateResult,
)
from server.services.strategy.t0.bar_aggregator import (
    BarAggregator, MORNING_START, MORNING_END, AFTERNOON_START, AFTERNOON_END,
)
from server.services.strategy.t0.t0_indicators import (
    compute_vwap, compute_vwap_deviation, compute_bollinger_bands,
    classify_volume_trend,
)
from server.services.strategy.t0.signals import detect_all_signals
from server.services.strategy.t0.position_tracker import T0PositionTracker
from server.services.strategy.t0.risk_control import T0RiskController, LOT_SIZE
from server.services.strategy import repository as repo
from server.services.strategy.audit import write_audit
from server.services.strategy.indicators import IndicatorParams
from server.db import db_session
from server.enums.trading import PriceType
from server.models.orm import Order
from server.repo.orders import next_order_no
from server.utils.time import format_ts
from server.services.guards import resolve_default_trd_date
from server.ws.manager import ws_manager

log = logging.getLogger(__name__)

T0_WS_CHANNEL = "t0_strategy_update"


class T0StrategyEngine:
    """T0 日内做T评估引擎（每个活跃 t0 strategy 一个实例）

    📌 tick 缓冲: deque(maxlen=500)，覆盖全天 VWAP 计算
    📌 bar 聚合: BarAggregator（5 分钟 K 线）
    📌 持仓跟踪: T0PositionTracker（entry/exit 配对）
    📌 风控: T0RiskController（止损/截断/频次）
    """

    def __init__(
        self,
        strategy_id: int,
        stock_code: str,
        initial_params: T0StrategyParams = None,
    ):
        self.strategy_id = strategy_id
        self.stock_code = stock_code
        self._tick_buffer: deque = deque(maxlen=500)
        self._bar_agg = BarAggregator(bar_minutes=5)
        self._position_tracker = T0PositionTracker(strategy_id, stock_code)
        self._params = initial_params or T0StrategyParams()
        self._risk = T0RiskController(self._params.risk)
        self._prev_close: Optional[float] = None
        self._open_price: Optional[float] = None
        self._trd_date: Optional[str] = None
        self._last_signal_ts: float = 0.0
        # 增量 VWAP 状态
        self._vwap_cumulative_pv: float = 0.0
        self._vwap_cumulative_v: int = 0
        self._current_vwap: Optional[float] = None

    def set_prev_close(self, prev_close: float) -> None:
        self._prev_close = prev_close

    def set_params(self, params: T0StrategyParams) -> None:
        """热更新参数（API PUT 时调）"""
        self._params = params
        self._risk = T0RiskController(params.risk)

    @property
    def prev_close(self) -> Optional[float]:
        return self._prev_close

    @property
    def last_regime(self):
        """兼容 quote_consumer 的 last_regime 属性（T0 无 regime，返 None）"""
        return None

    # ─────────────── 主入口 ───────────────

    async def evaluate_tick(
        self,
        tick: dict,
        position_vol: int,
        base_volume: int,
        prev_close: Optional[float] = None,
        now_ts: Optional[float] = None,
        trd_date: Optional[str] = None,
    ) -> T0EvaluateResult:
        """单次 tick 评估（与 StrategyEngine.evaluate_tick 签名一致）"""
        if now_ts is None:
            now_ts = time.time()
        if prev_close is None:
            prev_close = self._prev_close

        current_price = tick.get("last_price")
        if current_price is None:
            return T0EvaluateResult(strategy_id=self.strategy_id)

        result = T0EvaluateResult(strategy_id=self.strategy_id)

        # 1. 初始化当日
        if trd_date is None:
            trd_date = self._resolve_trd_date()
        self._init_day(trd_date, tick, now_ts)

        # 2. tick 入库
        self._tick_buffer.append(tick)

        # 3. bar 聚合
        completed_bar = self._bar_agg.add_tick(tick)

        # 4. 获取当前时间
        current_time_minutes = self._extract_minutes(tick)
        if current_time_minutes is None:
            current_time_minutes = self._minutes_from_ts(now_ts)

        # 5. 强制平仓检查（14:30 截断）
        if self._risk.should_force_close_all(current_time_minutes):
            await self._force_close_all(result, current_price, trd_date, now_ts)

        # 6. 计算指标
        vwap = self._compute_vwap(tick)
        result.vwap = vwap

        bb = None
        all_closes = self._bar_agg.get_all_closes()
        if len(all_closes) >= self._params.bollinger.period:
            bb = compute_bollinger_bands(
                all_closes,
                self._params.bollinger.period,
                self._params.bollinger.std_mult,
            )
            if bb:
                result.bb_upper, result.bb_middle, result.bb_lower = bb

        if vwap and vwap > 0:
            result.current_deviation = compute_vwap_deviation(current_price, vwap)

        # 7. 止损检查：遍历 open positions
        open_positions = self._position_tracker.get_open_positions()
        for pos in open_positions:
            if self._risk.should_stop_loss(pos, current_price):
                await self._close_position_by_stop_loss(
                    result, pos, current_price, trd_date, now_ts,
                )

        # 8. 信号检测
        current_bar = self._bar_agg.get_current_bar()
        prev_bars = self._bar_agg.get_bars(10)
        open_price = self._open_price or current_price

        volume_trend = "normal"
        if current_bar and prev_bars:
            volume_trend = classify_volume_trend(current_bar, prev_bars)

        signals = detect_all_signals(
            current_price=current_price,
            vwap=vwap or 0.0,
            current_bar=current_bar,
            prev_bars=prev_bars,
            all_closes=all_closes,
            open_price=open_price,
            prev_close=prev_close or open_price,
            current_time_minutes=current_time_minutes,
            volume_trend=volume_trend,
            params=self._params,
            now_ts=now_ts,
        )

        # 9. 信号冷却过滤 + 执行
        for signal in signals:
            await self._process_signal(
                signal=signal,
                result=result,
                current_price=current_price,
                position_vol=position_vol,
                base_volume=base_volume,
                trd_date=trd_date,
                now_ts=now_ts,
            )

        # 10. 更新敞口快照
        result.open_positions = self._position_tracker.to_dicts()

        # 11. WS broadcast（有信号或有 action 时）
        if signals or result.actions_taken:
            await self._broadcast("t0_signal", result, current_price, signals)

        return result

    # ─────────────── 信号处理 ───────────────

    async def _process_signal(
        self,
        signal: T0Signal,
        result: T0EvaluateResult,
        current_price: float,
        position_vol: int,
        base_volume: int,
        trd_date: str,
        now_ts: float,
    ) -> None:
        """处理单条信号: 冷却 → 风控 → 执行"""
        # 冷却检查
        if (signal.signal_type != "close_position" and
                (now_ts - self._last_signal_ts) < self._params.signal_cooldown):
            return

        result.signals.append(signal)

        # 平仓信号
        if signal.signal_type == "close_position":
            if self._position_tracker.has_any_open():
                await self._execute_close(result, current_price, trd_date, now_ts)
            return

        # 新开仓信号
        if not self._risk.can_open_position(self._position_tracker.operations_today):
            return  # 日限已达

        if self._risk.is_past_cutoff(self._extract_minutes_for_cutoff(now_ts)):
            return  # 时间截断

        # 同 model 已有 open position → 跳过
        if self._position_tracker.has_open_position(signal.model):
            return

        # 计算交易数量
        vol = self._risk.calculate_trade_volume(
            position_vol, base_volume, self._params.signal_volume,
        )
        if vol <= 0:
            return  # 无可做T 数量

        signal.volume = vol

        # 执行信号
        await self._execute_signal(
            signal=signal,
            result=result,
            current_price=current_price,
            volume=vol,
            trd_date=trd_date,
            now_ts=now_ts,
        )

    async def _execute_signal(
        self,
        signal: T0Signal,
        result: T0EvaluateResult,
        current_price: float,
        volume: int,
        trd_date: str,
        now_ts: float,
    ) -> None:
        """执行信号: audit + (test_mode 跳过下单 / live_mode ord_stk)"""
        self._last_signal_ts = now_ts

        action_info = {
            "signal_type": signal.signal_type,
            "model": signal.model,
            "direction": signal.direction,
            "price": current_price,
            "volume": volume,
            "reason": signal.reason,
            "strength": signal.strength,
        }

        # 测试模式：仅记录，不下单
        if self._params.test_mode:
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, f"t0_{signal.signal_type}",
                    current_price=current_price,
                    action_payload=action_info,
                    reject_reason="test_mode",
                    trd_date=trd_date,
                )
            result.actions_taken.append(action_info)
            log.info(
                "[T0 test] strategy=%s signal=%s price=%.2f vol=%d reason=%s",
                self.strategy_id, signal.signal_type, current_price, volume, signal.reason,
            )
            return

        # 实盘模式：下单
        order_no = await self._place_order(signal, current_price, volume, trd_date)

        if order_no:
            action_info["order_no"] = order_no
            # 记录 position
            self._position_tracker.add_position(T0Position(
                direction=signal.direction,
                entry_price=current_price,
                entry_volume=volume,
                entry_time=now_ts,
                signal_model=signal.model,
                strategy_id=self.strategy_id,
                stock_code=self.stock_code,
                trd_date=trd_date,
            ))
        else:
            action_info["reject_reason"] = "order_failed"

        result.actions_taken.append(action_info)

    async def _execute_close(
        self,
        result: T0EvaluateResult,
        current_price: float,
        trd_date: str,
        now_ts: float,
    ) -> None:
        """平仓所有 open positions（VWAP 回归时）"""
        positions = self._position_tracker.get_open_positions()
        for pos in positions:
            # 平仓方向与 entry 方向相反
            close_direction = "sell" if pos.direction == "buy" else "buy"
            action_info = {
                "signal_type": "close_position",
                "model": pos.signal_model,
                "direction": close_direction,
                "price": current_price,
                "volume": pos.entry_volume,
                "reason": f"平仓 {pos.signal_model} ({pos.direction}→{close_direction})",
            }

            if self._params.test_mode:
                with db_session() as db:
                    write_audit(
                        db, self.strategy_id, "t0_close_position",
                        current_price=current_price,
                        action_payload=action_info,
                        reject_reason="test_mode",
                        trd_date=trd_date,
                    )
            else:
                close_signal = T0Signal(
                    signal_type="close_position",
                    model=pos.signal_model,
                    direction=close_direction,
                    price=current_price,
                    volume=pos.entry_volume,
                    reason=action_info["reason"],
                    strength=0.5,
                    timestamp=now_ts,
                )
                order_no = await self._place_order(
                    close_signal, current_price, pos.entry_volume, trd_date,
                )
                if order_no:
                    action_info["order_no"] = order_no

            result.actions_taken.append(action_info)
            self._position_tracker.close_position(pos.signal_model)

            log.info(
                "[T0 close] strategy=%s model=%s dir=%s price=%.2f vol=%d",
                self.strategy_id, pos.signal_model, close_direction,
                current_price, pos.entry_volume,
            )

    async def _force_close_all(
        self,
        result: T0EvaluateResult,
        current_price: float,
        trd_date: str,
        now_ts: float,
    ) -> None:
        """14:30 强制全部平仓"""
        if not self._position_tracker.has_any_open():
            return
        await self._execute_close(result, current_price, trd_date, now_ts)

    async def _close_position_by_stop_loss(
        self,
        result: T0EvaluateResult,
        pos: T0Position,
        current_price: float,
        trd_date: str,
        now_ts: float,
    ) -> None:
        """止损平仓"""
        close_direction = "sell" if pos.direction == "buy" else "buy"
        action_info = {
            "signal_type": "risk_stop_loss",
            "model": pos.signal_model,
            "direction": close_direction,
            "price": current_price,
            "volume": pos.entry_volume,
            "reason": f"止损 {pos.signal_model}，浮亏超限",
        }

        if self._params.test_mode:
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, "t0_risk_stop_loss",
                    current_price=current_price,
                    action_payload=action_info,
                    reject_reason="test_mode",
                    trd_date=trd_date,
                )
        else:
            close_signal = T0Signal(
                signal_type="risk_stop_loss",
                model=pos.signal_model,
                direction=close_direction,
                price=current_price,
                volume=pos.entry_volume,
                reason=action_info["reason"],
                strength=1.0,
                timestamp=now_ts,
            )
            order_no = await self._place_order(
                close_signal, current_price, pos.entry_volume, trd_date,
            )
            if order_no:
                action_info["order_no"] = order_no

        result.actions_taken.append(action_info)
        self._position_tracker.close_position(pos.signal_model)
        log.warning(
            "[T0 STOP LOSS] strategy=%s model=%s price=%.2f",
            self.strategy_id, pos.signal_model, current_price,
        )

    # ─────────────── 下单 ───────────────

    async def _place_order(
        self,
        signal: T0Signal,
        price: float,
        volume: int,
        trd_date: str,
    ) -> Optional[str]:
        """INSERT Order(status=48) → ord_stk RPC"""
        try:
            from server.api.orders import ord_stk
            with db_session() as db:
                order_no = next_order_no(db)
                order = Order(
                    trd_date=trd_date,
                    order_no=order_no,
                    user_def=f"T0_{self.strategy_id}",
                    stock_code=self.stock_code,
                    order_type="23" if signal.direction == "buy" else "24",
                    price_type=PriceType.FIX_PRICE,
                    price=price,
                    volume=volume,
                    traded_volume=0, traded_amount=0.0, avg_price=0.0,
                    status="48", status_msg="未报",
                    order_time=format_ts(tz='local'),
                )
                db.add(order)
                db.commit()
                db.refresh(order)

            msgid_meta = {
                "order_no": order_no,
                "trd_date": trd_date,
                "stock_code": self.stock_code,
            }
            try:
                ack = await ord_stk(
                    stock_code=self.stock_code,
                    volume=volume,
                    price_type=PriceType.FIX_PRICE,
                    price=price,
                    order_type="23" if signal.direction == "buy" else "24",
                    remark=order_no,
                    msgid_meta=msgid_meta,
                )
                log.info(
                    "[T0 order] strategy=%s order_no=%s dir=%s price=%.2f vol=%d",
                    self.strategy_id, order_no, signal.direction, price, volume,
                )
            except Exception as e:
                log.exception("[T0 order] ord_stk failed: %s", e)
                with db_session() as db:
                    o = db.query(Order).filter_by(order_no=order_no).first()
                    if o:
                        o.status = "57"
                        o.status_msg = f"RPC 失败: {e}"
                        db.commit()
                return None

            return order_no
        except Exception as e:
            log.exception("[T0 order] _place_order failed: %s", e)
            return None

    # ─────────────── 辅助方法 ───────────────

    def _init_day(self, trd_date: str, tick: dict, now_ts: float) -> None:
        """每日初始化：检测日期变更，重置状态"""
        if self._trd_date != trd_date:
            self._bar_agg.reset()
            self._position_tracker.reset_day(trd_date)
            self._tick_buffer.clear()
            self._vwap_cumulative_pv = 0.0
            self._vwap_cumulative_v = 0
            self._current_vwap = None
            self._trd_date = trd_date

        # 记录开盘价（第一个 tick）
        if self._open_price is None and len(self._tick_buffer) <= 2:
            p = tick.get("last_price")
            if p:
                self._open_price = float(p)

    def _compute_vwap(self, tick: dict) -> Optional[float]:
        """增量 VWAP 计算"""
        price = tick.get("last_price")
        volume = tick.get("volume")
        if price is None or not volume or volume <= 0:
            return self._current_vwap

        v = int(volume)
        # 判断 volume 是累计值还是增量：如果比上次大很多则是累计值
        # QMT tick 的 volume 字段是当日累计成交量，需要算差值
        prev_total_vol = self._vwap_cumulative_v
        total_vol = v
        if total_vol > prev_total_vol and prev_total_vol > 0:
            # 累计值模式：取差值作为增量
            delta_vol = total_vol - prev_total_vol
            # 增量成交额 ≈ price × delta_vol（简化）
            delta_pv = float(price) * delta_vol
            self._vwap_cumulative_pv += delta_pv
            self._vwap_cumulative_v = total_vol
        elif prev_total_vol == 0:
            # 首个 tick
            self._vwap_cumulative_pv = float(price) * total_vol
            self._vwap_cumulative_v = total_vol
        # else: volume 没变，不更新

        if self._vwap_cumulative_v <= 0:
            return None
        self._current_vwap = self._vwap_cumulative_pv / self._vwap_cumulative_v
        return self._current_vwap

    def _extract_minutes(self, tick: dict) -> Optional[int]:
        """从 tick 提取分钟数"""
        fields = tick.get("fields") or []
        if len(fields) > 1 and fields[1]:
            dt_str = str(fields[1])
            if len(dt_str) >= 12:
                try:
                    return int(dt_str[8:10]) * 60 + int(dt_str[10:12])
                except (ValueError, IndexError):
                    pass
        return None

    @staticmethod
    def _minutes_from_ts(epoch_ts: float) -> int:
        """epoch 秒 → 本地时区分钟数"""
        from datetime import datetime
        dt = datetime.fromtimestamp(epoch_ts)
        return dt.hour * 60 + dt.minute

    def _extract_minutes_for_cutoff(self, epoch_ts: float) -> int:
        return self._minutes_from_ts(epoch_ts)

    @staticmethod
    def _resolve_trd_date() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d")

    # ─────────────── WS broadcast ───────────────

    async def _broadcast(
        self,
        event_type: str,
        result: T0EvaluateResult,
        current_price: float,
        signals: List[T0Signal],
    ) -> None:
        try:
            payload = {
                "type": event_type,
                "strategy_id": self.strategy_id,
                "stock_code": self.stock_code,
                "current_price": current_price,
                "vwap": result.vwap,
                "bb_upper": result.bb_upper,
                "bb_middle": result.bb_middle,
                "bb_lower": result.bb_lower,
                "current_deviation": result.current_deviation,
                "signals": [
                    {
                        "signal_type": s.signal_type,
                        "model": s.model,
                        "direction": s.direction,
                        "price": s.price,
                        "volume": s.volume,
                        "reason": s.reason,
                        "strength": s.strength,
                    }
                    for s in signals
                ],
                "actions": result.actions_taken,
                "open_positions": result.open_positions,
                "order_nos": result.order_nos,
                "ts": time.time(),
            }
            await ws_manager.broadcast(T0_WS_CHANNEL, payload)
        except Exception as e:
            log.warning("T0 WS broadcast failed: %s", e)


__all__ = ["T0StrategyEngine", "T0EvaluateResult", "T0_WS_CHANNEL"]
