"""
strategy — 主评估引擎（change strategy_trade task 6）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-006 + 009
📌 8 步流水线：tick → buffer → flags → regime → cooldown → grids → ord_stk → audit + WS
📌 evaluate_tick 是 async（await ord_stk + await ws_manager.broadcast）
📌 DB 走 server.db.db_session() sync context manager（DI 不可用场景）
📌 状态：TickBuffer + last_regime + last_switch_ts + IndicatorParams
📌 每个活跃 strategy 一个 StrategyEngine 实例
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any

from sqlalchemy.orm import Session

from server.services.strategy.models import (
    Strategy, StrategyRegime, StrategyAudit,
)
from server.services.strategy.indicators import TickBuffer, IndicatorParams
from server.services.strategy.flags import detect_flags
from server.services.strategy.regime import match_regime, apply_cooldown
from server.services.strategy.grid import GridAction, evaluate_grids
from server.services.strategy import repository as repo
from server.services.strategy.audit import write_audit

# Late import 拿 patched symbol（test_engine.py monkeypatch 路径）
from server.api.orders import ord_stk
from server.db import db_session
from server.models.orm import Order
from server.repo.orders import next_order_no
from server.utils.time import format_ts
from server.services.guards import resolve_default_trd_date
from server.ws.manager import ws_manager


log = logging.getLogger(__name__)


# ─────────────── 常量 ───────────────

STRATEGY_WS_CHANNEL = "strategy_update"   # WS 频道名（注册到 ws_manager.active_connections）


# ─────────────── 数据结构 ───────────────


@dataclass
class EvaluateResult:
    """evaluate_tick 一次调用的输出（单测断言 + WS payload 来源）"""
    strategy_id: int
    active_flags: Set[str] = field(default_factory=set)
    matched_regime_id: Optional[int] = None
    regime_switched: bool = False
    regime_cooldown_blocked: bool = False
    actions: List[GridAction] = field(default_factory=list)
    audit_ids: List[int] = field(default_factory=list)
    order_nos: List[str] = field(default_factory=list)


# ─────────────── StrategyEngine ───────────────


class StrategyEngine:
    """单一策略的评估引擎（每个活跃 strategy 一个实例）

    📌 状态字段：
       - buffer: 滚动 tick 缓冲
       - params: IndicatorParams（v1 固定；后续市场状态识别模块可 set_params 整体替换）
       - last_regime: 上一次激活的 Regime（cooldown 用）
       - last_switch_ts: 上次 regime 切换的 epoch 秒
       - prev_close: 昨收（price_change_* flag 用，由 quote_consumer 灌入）

    📌 evaluate_tick 是唯一对外入口（quote_consumer 每 tick 调一次）
    """

    def __init__(
        self,
        strategy_id: int,
        stock_code: str,
        initial_params: IndicatorParams = None,
        cooldown_seconds: int = 300,
    ):
        self.strategy_id = strategy_id
        self.stock_code = stock_code
        self.buffer = TickBuffer()
        self.params = initial_params or IndicatorParams.standard()
        self.last_regime: Optional[StrategyRegime] = None
        self.last_switch_ts: Optional[float] = None
        self.prev_close: Optional[float] = None
        self.cooldown_seconds = cooldown_seconds

    def set_params(self, params: IndicatorParams) -> None:
        """整体替换指标参数（市场状态识别模块切换 preset 时调）"""
        self.params = params

    def set_prev_close(self, prev_close: float) -> None:
        """灌入昨收价（每个交易日开盘时 quote_consumer 调一次）"""
        self.prev_close = prev_close

    # ──── 主入口 ────

    async def evaluate_tick(
        self,
        tick: dict,
        position_vol: int,
        base_volume: int,
        prev_close: Optional[float] = None,
        now_ts: Optional[float] = None,
        trd_date: Optional[str] = None,
    ) -> EvaluateResult:
        """单 tick 评估（spec REQ-STRAT-006 8 步流水线）

        📌 参数：
           - tick: hqserver 原始 tick dict（至少含 last_price，可选 volume）
           - position_vol / base_volume: 当前持仓 / 底仓（外部从 broker / DB 取）
           - prev_close / now_ts / trd_date: 可选覆盖（单测友好）

        📌 副作用：写 audit、INSERT Order、调 RPC、广播 WS（均不抛错给 caller）
        """
        if now_ts is None:
            now_ts = time.time()
        if prev_close is None:
            prev_close = self.prev_close
        result = EvaluateResult(strategy_id=self.strategy_id)

        # 1. buffer.append
        self.buffer.append(tick)
        current_price = tick.get("last_price")

        # 2. detect_flags
        result.active_flags = detect_flags(self.buffer, self.params, prev_close)
        flags_list = sorted(result.active_flags)

        # 3. 读 strategy + regimes（DB；eager load grids 防 lazy load 后 session 关闭）
        from sqlalchemy.orm import joinedload
        with db_session() as db:
            strategy = (
                db.query(Strategy)
                .options(joinedload(Strategy.regimes).joinedload(StrategyRegime.grids))
                .filter(Strategy.id == self.strategy_id)
                .first()
            )
            if strategy is None or strategy.status != "active":
                # 策略已删除或停用 → 不评估
                return result
            # override base_volume 用 strategy 自己的（如未传）
            if base_volume is None:
                base_volume = strategy.base_volume or 0
            regimes = list(strategy.regimes)
            # 进入候选匹配的 regime 也需要保留 identity（确保 last_regime 比较 id 时 OK）
            for r in regimes:
                db.expunge(r)

        # 4. match_regime
        candidate = match_regime(regimes, result.active_flags)
        candidate_id = candidate.id if candidate else None

        # 5. cooldown 检查
        can_switch = apply_cooldown(
            self.last_regime, candidate,
            self.last_switch_ts, now_ts,
            cooldown=self.cooldown_seconds,
        )

        if not can_switch and candidate_id != (self.last_regime.id if self.last_regime else None):
            # 冷却中且候选 ≠ 当前 → 维持 prev_regime，audit 记 cooldown
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, "regime_cooldown",
                    regime_id=self.last_regime.id if self.last_regime else None,
                    flags_active=flags_list, current_price=current_price,
                    position_vol=position_vol, base_volume=base_volume,
                    trd_date=trd_date,
                )
            result.audit_ids = []
            result.regime_cooldown_blocked = True
            await self._broadcast("regime_cooldown", result, current_price, flags_list)
            return result

        # 切换判定
        regime_switched = (
            candidate is not None
            and (self.last_regime is None or candidate.id != self.last_regime.id)
        )
        if regime_switched:
            self.last_regime = candidate
            self.last_switch_ts = now_ts
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, "regime_switch",
                    regime_id=candidate.id,
                    flags_active=flags_list, current_price=current_price,
                    position_vol=position_vol, base_volume=base_volume,
                    trd_date=trd_date,
                )
            await self._broadcast("regime_changed", result, current_price, flags_list)
        result.regime_switched = regime_switched
        result.matched_regime_id = candidate.id if candidate else None

        # 6. 无 regime 命中 → audit no_match
        if candidate is None:
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, "no_match",
                    flags_active=flags_list, current_price=current_price,
                    position_vol=position_vol, base_volume=base_volume,
                    trd_date=trd_date,
                )
            return result

        # 7. evaluate_grids
        actions = evaluate_grids(
            grids=candidate.grids,
            current_price=current_price,
            position_vol=position_vol,
            base_volume=base_volume,
            clear_position=candidate.clear_position,
        )
        result.actions = actions

        # 8. 遍历 actions：每个单独 audit + 触发则 INSERT Order + RPC
        if not actions:
            with db_session() as db:
                write_audit(
                    db, self.strategy_id, "no_action",
                    regime_id=candidate.id,
                    flags_active=flags_list, current_price=current_price,
                    position_vol=position_vol, base_volume=base_volume,
                    trd_date=trd_date,
                )
            return result

        for action in actions:
            order_no = await self._execute_action(action, current_price, flags_list, candidate, trd_date)
            if order_no:
                result.order_nos.append(order_no)

        # 9. 触发广播（grid_triggered）
        if any(a.reject_reason is None for a in actions):
            await self._broadcast("grid_triggered", result, current_price, flags_list)

        return result

    # ──── 单 action 执行 ────

    async def _execute_action(
        self,
        action: GridAction,
        current_price: float,
        flags_list: list,
        regime: StrategyRegime,
        trd_date: Optional[str],
    ) -> Optional[str]:
        """单 GridAction：写 audit → INSERT Order → ord_stk → UPDATE status → 二次 audit

        📌 拒触发（reject_reason 非空）：只写一次 audit，不下单
        📌 触发（reject_reason=None）：写 audit + 下单 + 成功更新 fired_count + 写二次 audit
        📌 返回 order_no（成功）或 None（拒触发 / 失败）
        """
        trigger_type = "grid_buy" if action.direction == "buy" else "grid_sell"
        if regime.clear_position and action.grid_id == -1:
            trigger_type = "clear"

        # audit 1：动作记录（拒触发也写）
        with db_session() as db:
            write_audit(
                db, self.strategy_id, trigger_type,
                regime_id=regime.id,
                flags_active=flags_list, current_price=current_price,
                position_vol=None,  # 上下文中不直接用
                base_volume=None,
                action_payload={
                    "direction": action.direction,
                    "volume": action.volume,
                    "trigger_price": action.trigger_price,
                    "grid_id": action.grid_id,
                    "reject_reason": action.reject_reason,
                },
                reject_reason=action.reject_reason,
                trd_date=trd_date,
            )

        # 拒触发 → 不下单
        if action.reject_reason is not None or action.volume <= 0:
            return None

        # 触发 → 下单流程（INSERT Order → ord_stk → UPDATE）
        order_no = await self._place_order(action, current_price, trd_date)
        if order_no:
            # 成功 → increment_fired_count（grid_id != -1 即普通 grid）
            if action.grid_id != -1:
                with db_session() as db:
                    g = repo.get_grid(db, action.grid_id)
                    if g is not None:
                        repo.increment_fired_count(db, g)
                        db.commit()
        return order_no

    async def _place_order(
        self,
        action: GridAction,
        current_price: float,
        trd_date: Optional[str],
    ) -> Optional[str]:
        """INSERT Order (status='48') → ord_stk → UPDATE status

        📌 仿 place.py 范式：user_def = str(strategy.id)
        📌 ord_stk 失败 → status='57'（不抛错给 caller）
        """
        order_no = None
        try:
            with db_session() as db:
                # 取 trd_date
                if trd_date is None:
                    trd_date = resolve_default_trd_date(db)
                order_no = next_order_no(db)
                order = Order(
                    trd_date=trd_date,
                    order_no=order_no,
                    user_def=str(self.strategy_id),  # spec REQ-STRAT-006 step 7
                    stock_code=self.stock_code,
                    order_type="23" if action.direction == "buy" else "24",
                    price_type=11,  # 限价（spec 默认对手价；v1 简化为限价 = current_price）
                    price=current_price,
                    volume=action.volume,
                    traded_volume=0, traded_amount=0.0, avg_price=0.0,
                    status="48", status_msg="待报",
                    order_time=format_ts(tz='local'),
                )
                db.add(order)
                db.commit()
                db.refresh(order)

            # 调 RPC（broker 同步返回 ack）
            try:
                ack = await ord_stk(
                    stock_code=self.stock_code,
                    volume=action.volume,
                    price_type=11,
                    price=current_price,
                    order_type="23" if action.direction == "buy" else "24",
                    remark=order_no,
                )
            except Exception as e:
                log.exception("strategy ord_stk failed: strategy=%s order_no=%s err=%s",
                              self.strategy_id, order_no, e)
                with db_session() as db:
                    o = db.query(Order).filter_by(order_no=order_no).first()
                    if o:
                        o.status = "57"
                        o.status_msg = "RPC 失败: {}".format(e)
                        db.commit()
                return None

            # 解析 ack → UPDATE
            ack_code = int(ack.get("code", -1))
            ack_list = ack.get("list", [])
            with db_session() as db:
                o = db.query(Order).filter_by(order_no=order_no).first()
                if o:
                    if ack_code == 0 and ack_list:
                        broker_order_id = str(ack_list[0].get("order_id", "")) if isinstance(ack_list[0], dict) else ""
                        if broker_order_id:
                            o.order_id = broker_order_id
                        o.status = "50"
                        o.status_msg = "已报"
                    else:
                        o.status = "57"
                        o.status_msg = ack.get("msg", "柜台拒单")
                        o.cancelled_volume = o.volume
                    db.commit()
            return order_no
        except Exception as e:
            log.exception("strategy _place_order failed: %s", e)
            return None

    # ──── WS broadcast ────

    async def _broadcast(
        self,
        event_type: str,
        result: EvaluateResult,
        current_price: Optional[float],
        flags_list: list,
    ) -> None:
        """广播 strategy_update 事件（失败不抛错）"""
        try:
            payload = {
                "type": event_type,
                "strategy_id": self.strategy_id,
                "stock_code": self.stock_code,
                "regime_id": result.matched_regime_id,
                "active_flags": flags_list,
                "current_price": current_price,
                "actions": [
                    {
                        "direction": a.direction,
                        "volume": a.volume,
                        "trigger_price": a.trigger_price,
                        "grid_id": a.grid_id,
                        "reject_reason": a.reject_reason,
                    } for a in result.actions
                ],
                "order_nos": result.order_nos,
                "ts": time.time(),
            }
            await ws_manager.broadcast(STRATEGY_WS_CHANNEL, payload)
        except Exception as e:
            log.warning("strategy WS broadcast failed: %s", e)


__all__ = ["StrategyEngine", "EvaluateResult", "STRATEGY_WS_CHANNEL"]